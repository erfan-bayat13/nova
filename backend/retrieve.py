"""Per-round memory retrieval for a small context window. See docs/MEMORY.md.

The core card (memory.py) holds the ~25 hottest facts. Everything else is "cold": older facts that did not fit
the card, and the user's own past lines. This module pulls the few cold items that matter for THIS round and
formats them as one tiny note (<= ~110 tokens) that goes into the session right before the user speaks.

Design, from the research (see docs/MEMORY.md):
  * Small units, small K, hard token cap. For a 2B model a few distractors hurt more than a missed memory helps,
    so the default answer is "nothing": a quality gate drops weak matches, and most rounds inject no note.
  * Hybrid score: BM25 (SQLite FTS5, porter stemming) x query-term coverage, plus a small recency term, a
    pinned boost and a prior for curated facts over raw lines. No embedding model: the 8 GB machine has none to
    spare, and for short personal facts keyword + stemming + coverage is close (see test_retrieval.py).
  * Dedupe: skip anything already in the card, already shown in the last few rounds, still inside the live
    session, or that says what a chosen fact already says (a raw line that produced a fact).
  * Only the user's own words (facts and user lines) are retrieved. Assistant lines never are: they hold the
    model's own inventions, and retrieving them lets mistakes feed on themselves.
  * Dates, so "June 3rd" can be told apart from last year's: each item carries its age ("2 weeks ago").
"""
from __future__ import annotations

import math, re, time
from dataclasses import dataclass

from memory import Store, est_tokens, norm

NOTE_TOKENS = 110        # hard cap for one round's note
MAX_HITS = 3
MIN_SCORE = 0.50         # quality gate, keywords only; tuned on test_retrieval.py
MIN_SCORE_HYBRID = 0.36  # ... with embeddings (grid-searched on the train set only, then checked on held-out)
DENSE_FLOOR, DENSE_SPAN = 0.15, 0.30   # cosine 0.15 -> 0, 0.45 -> 1 (MiniLM: unrelated pairs sit at 0.1-0.3)
W_DENSE, W_REL, W_COV = 0.60, 0.15, 0.20
REPEAT_ROUNDS = 6        # an item shown this recently is not shown again
HALF_LIFE_DAYS = 45.0
TURN_CHARS = 150         # a past line is cut to this

STOP = set("""a an the and or but if then so of to in on at for from with by about as into over after before up down out off
is are was were be been being am do does did done have has had having will would can could should shall may might must
i me my mine we us our you your he him his she her it its they them their this that these those there here what which who
whom whose when where why how not no yes yeah okay ok just really very too also still even only some any all more most
much many few other such own same than now today again ever never always please thanks thank hey nova hi hello well like
get got go going gone know knew think thought tell told said say ask asked want need let lets make made see look looking
thing things stuff something anything one ones way lot bit kind sure right good great nice""".split())


def stem(w: str) -> str:
    w = w.lower().replace("'s", "").strip("'")
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: len(w) - len(suf)] + rep
            break
    return w


def terms(text: str) -> list[str]:
    """Content stems of a text, in order, without repeats."""
    seen, out = set(), []
    for w in re.findall(r"[A-Za-z0-9']+", text):
        if w.lower() in STOP or len(w) < 2:
            continue
        s = stem(w)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# Everyday words people use for the same thing. Query-side only: "who's my boss" must find "manager". A hand-made
# map is the cheap stand-in for an embedding model we cannot afford on this machine; the background pass adds
# per-fact keywords on top of it (memory.py `kw`, consolidate.py).
SYNONYMS = [
    "mom mother mum mama parent parents", "dad father papa", "sibling sister brother", "kid kids child children son daughter",
    "wife husband spouse partner girlfriend boyfriend married", "boss manager supervisor lead", "coworker colleague teammate",
    "job work works occupation career profession employer office", "study studying learn learning course class language",
    "car vehicle drive drives driving honda toyota ford tesla", "bike bicycle cycling", "dog dogs puppy", "cat cats kitten",
    "nut nuts peanut peanuts allergy allergic allergies", "vegetarian vegan diet eat eating food meal",
    "coffee tea drink drinks drinking", "music band song songs singer album artist", "movie film show series",
    "book books read reading novel", "run running marathon jog jogging race training workout exercise gym",
    "money save saving saved budget afford buy buying purchase cost", "house home apartment flat live lives living rent",
    "trip travel vacation holiday flight flying fly visit abroad", "spring march april may", "summer june july august",
    "autumn fall september october november", "winter december january february", "birthday birth born anniversary",
    "doctor dentist hospital clinic appointment medical health", "phone laptop computer tablet device",
    "wifi password internet network", "plant plants garden gardening tomato tomatoes flowers", "instrument cello guitar piano violin play plays",
    "hobby hobbies weekend free", "name named called", "old age years",
]
_SYN: dict[str, set[str]] = {}
for _g in SYNONYMS:
    _stems = {stem(w) for w in _g.split()}
    for _s in _stems:
        _SYN.setdefault(_s, set()).update(_stems)


def expand(q: list[str]) -> list[set[str]]:
    """Each query stem with its everyday alternates."""
    return [{t} | _SYN.get(t, set()) for t in q]


@dataclass
class Hit:
    kind: str            # "fact" | "turn"
    ref: int
    text: str
    ts: float
    score: float
    matched: int = 0
    cos: float | None = None
    pinned: bool = False
    extra: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref}"


def age(ts: float, now: float | None = None) -> str:
    d = ((now or time.time()) - ts) / 86400
    if d < 1:
        return "today"
    if d < 2:
        return "yesterday"
    if d < 14:
        return f"{int(d)} days ago"
    if d < 60:
        return f"{int(d // 7)} weeks ago"
    return f"{int(d // 30)} months ago"


def _fts_query(groups: list[set[str]]) -> str:
    words = sorted({w for g in groups[:10] for w in g})
    return " OR ".join('"' + w.replace('"', "") + '"' for w in words)


def _bm25_norm(rows: list, col: str = "s") -> dict[int, float]:
    """FTS5 bm25() is negative (more negative = better). Map the set to (0, 1], best = 1."""
    if not rows:
        return {}
    raw = {r["id"]: -r[col] for r in rows}
    top = max(raw.values()) or 1.0
    return {k: max(v, 0.0) / top for k, v in raw.items()}


class Retriever:
    def __init__(self, store: Store, embedder=None):
        self.store = store
        self.embedder = embedder          # embed.Embedder or None (then keywords only)
        self.shown: dict[str, int] = {}   # item key -> round it was last shown in (per connection)
        self.round = 0

    # ------------------------------------------------------------ candidates
    def _live_turn_ids(self, conn: str | None) -> set[int]:
        if not conn:  # lines of this run are still in the live session (or carried over by rotation)
            return set()
        return {r["id"] for r in self.store.db.execute("SELECT id FROM turns WHERE conn=? ORDER BY id DESC LIMIT 12", (conn,))}

    def _lexical(self, q: list[set[str]], skip_facts: set[int], live: set[int]) -> dict[str, tuple[str, int, float]]:
        """BM25 candidates: key -> (kind, id, relevance in (0, 1])."""
        db, out = self.store.db, {}
        fq = _fts_query(q)
        rows = db.execute("SELECT f.id AS id, bm25(facts_fts, 1.0, 0.6) AS s FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid "
                          "WHERE facts_fts MATCH ? AND f.superseded_by IS NULL LIMIT 20", (fq,)).fetchall()
        for i, r in _bm25_norm(rows).items():
            if i not in skip_facts:
                out[f"fact:{i}"] = ("fact", i, r)
        rows = db.execute("SELECT t.id AS id, bm25(turns_fts) AS s FROM turns_fts JOIN turns t ON t.id = turns_fts.rowid "
                          "WHERE turns_fts MATCH ? AND t.role='user' AND t.text NOT LIKE '%?%' ORDER BY s LIMIT 20", (fq,)).fetchall()
        for i, r in _bm25_norm([r for r in rows if r["id"] not in live]).items():
            out[f"turn:{i}"] = ("turn", i, r)
        return out

    def _dense(self, query: str, skip_facts: set[int], live: set[int], top: int = 8) -> dict[str, float]:
        """Cosine to every stored fact / user line (a few thousand vectors: a numpy dot, ~1 ms). key -> cosine."""
        if not self.embedder or not self.embedder.available:
            return {}
        qv = self.embedder.encode([query])
        if qv is None:
            return {}
        import numpy as np
        from embed import from_blob
        db, tag, keys, vecs = self.store.db, self.embedder.name, [], []
        for r in db.execute("SELECT id, emb FROM facts WHERE superseded_by IS NULL AND emb IS NOT NULL AND emb_model=?", (tag,)):
            if r["id"] not in skip_facts:
                keys.append(f"fact:{r['id']}"); vecs.append(from_blob(r["emb"]))
        for r in db.execute("SELECT id, emb FROM turns WHERE role='user' AND text NOT LIKE '%?%' AND emb IS NOT NULL AND emb_model=?", (tag,)):
            if r["id"] not in live:
                keys.append(f"turn:{r['id']}"); vecs.append(from_blob(r["emb"]))
        if not keys:
            return {}
        sims = np.stack(vecs) @ qv[0]
        order = np.argsort(-sims)[:top]
        return {keys[i]: float(sims[i]) for i in order}

    def _load(self, key: str) -> Hit | None:
        kind, i = key.split(":")
        db = self.store.db
        row = db.execute("SELECT text, kw, ts, pinned FROM facts WHERE id=?", (i,)).fetchone() if kind == "fact" else \
            db.execute("SELECT text, '' AS kw, ts, 0 AS pinned FROM turns WHERE id=?", (i,)).fetchone()
        if row is None:
            return None
        h = Hit(kind, int(i), row["text"], row["ts"], 0)
        h.pinned, h.extra = bool(row["pinned"]), row["kw"] or ""
        return h

    @staticmethod
    def _score(h: Hit, q: list[set[str]], rel: float, cos: float | None, now: float) -> Hit:
        have = set(terms(h.text + " " + h.extra))
        h.matched = sum(1 for g in q if g & have)
        coverage = min(1.0, h.matched / min(len(q), 3))      # the query's first terms carry the topic
        recency = 0.5 ** (max(now - h.ts, 0) / 86400 / HALF_LIFE_DAYS)
        prior = (0.08 if h.kind == "fact" else 0.0) + (0.05 if h.pinned else 0.0)
        h.cos = cos
        if cos is None:   # keywords only
            h.score = 0.40 * rel + 0.40 * coverage + 0.07 * recency + prior
        else:             # hybrid: meaning decides, keywords confirm
            dsc = min(1.0, max(0.0, (cos - DENSE_FLOOR) / DENSE_SPAN))
            h.score = W_DENSE * dsc + W_REL * rel + W_COV * coverage + 0.05 * recency + prior
        return h

    # ------------------------------------------------------------ public
    def retrieve(self, query: str, *, conn: str | None = None, card_texts: list[str] | None = None,
                 now: float | None = None, max_hits: int = MAX_HITS) -> list[Hit]:
        """The cold items worth showing this round, best first. Usually an empty list."""
        now = now or time.time()
        base = terms(query)
        if not base:
            return []
        q = expand(base)
        card = {norm(t) for t in (card_texts or [])}
        skip = {r["id"] for r in self.store.active_facts() if norm(r["text"]) in card}
        live = self._live_turn_ids(conn)
        if live:  # a fact learned from a line that is still inside the live session needs no reminder
            marks = ",".join(str(i) for i in live)
            skip |= {r["id"] for r in self.store.db.execute(f"SELECT id FROM facts WHERE source_turn IN ({marks})")}
        lex = self._lexical(q, skip, live)
        dense = self._dense(query, skip, live)
        hybrid = bool(dense)
        cands = []
        for key in set(lex) | set(dense):
            h = self._load(key)
            if h is None:
                continue
            rel = lex[key][2] if key in lex else 0.0
            self._score(h, q, rel, dense.get(key, 0.0) if hybrid else None, now)
            if (hybrid or h.matched >= 1) and h.score >= (MIN_SCORE_HYBRID if hybrid else MIN_SCORE) \
                    and self.round - self.shown.get(h.key, -99) > REPEAT_ROUNDS:
                cands.append(h)
        cands.sort(key=lambda c: -c.score)
        chosen: list[Hit] = []
        for c in cands:  # greedy, near-duplicates of an already chosen item are dropped (MMR with lambda -> 1)
            ct = set(terms(c.text))
            if any(len(ct & set(terms(o.text))) / max(len(ct | set(terms(o.text))), 1) > 0.5 for o in chosen):
                continue
            chosen.append(c)
            if len(chosen) == max_hits:
                break
        return chosen

    def note(self, hits: list[Hit], now: float | None = None, budget: int = NOTE_TOKENS) -> str:
        """One compact note, within the token budget (lowest-ranked items are dropped first)."""
        head = "(Remembered from before, for reference only, never read this out and only use it if it helps: "
        parts = []
        for h in hits:
            # no brackets or parentheses inside: the voice model sometimes echoes notes, and orchestrator.strip_context_echo
            # removes a note by its outer parentheses
            text = h.text.rstrip(".") if h.kind == "fact" else \
                'the user said "' + (h.text if len(h.text) <= TURN_CHARS else h.text[:TURN_CHARS - 1] + "…") + '"'
            parts.append(f"{text}, {age(h.ts, now)}")
        while parts and est_tokens(head + "; ".join(parts) + ")") > budget:
            parts.pop()
        return head + "; ".join(parts) + ")" if parts else ""

    def commit(self, hits: list[Hit]):
        """Call when a note was really sent: those items rest for a few rounds."""
        for h in hits:
            self.shown[h.key] = self.round

    def tick(self):
        """Call once per round, before retrieve()."""
        self.round += 1
