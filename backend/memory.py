"""Long-term memory for the voice loop. See docs/MEMORY.md.

The local 2B model never decides what to remember. This module sits around it:

  turns   every user/assistant line, verbatim (SQLite + FTS5 for keyword search)
  facts   short dated statements about the user, each with a key, a source turn and
          `superseded_by`, so a newer fact replaces an older one deterministically (newest wins)
  card    the "core card": the newest/pinned active facts that fit a small token budget. It goes into
          the system prompt at session start, so it is a stable prefix (the KV cache is reused).

Nothing here touches the model or the network, so it is safe on the voice path (a few ms).
`consolidate.py` is the optional background pass that cleans the fact list with a bigger model.
"""
from __future__ import annotations

import functools, os, re, sqlite3, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("MEMORY_DB", os.path.join(HERE, "data", "memory.db"))
CARD_TOKENS = 400          # core card budget; ~3.5 chars per token
CHARS_PER_TOKEN = 3.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS turns(
  id INTEGER PRIMARY KEY, ts REAL, conn TEXT, role TEXT, text TEXT, emb BLOB, emb_model TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(text, content='turns', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
  INSERT INTO turns_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
  INSERT INTO turns_fts(turns_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY, ts REAL, text TEXT NOT NULL, key TEXT, pinned INTEGER DEFAULT 0,
  source_turn INTEGER, superseded_by INTEGER, origin TEXT DEFAULT 'local', kw TEXT DEFAULT '', emb BLOB, emb_model TEXT);
CREATE INDEX IF NOT EXISTS facts_key ON facts(key);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, kw, tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts WHEN new.superseded_by IS NULL BEGIN
  INSERT INTO facts_fts(rowid, text, kw) VALUES (new.id, new.text, new.kw); END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE OF superseded_by ON facts WHEN new.superseded_by IS NOT NULL BEGIN
  DELETE FROM facts_fts WHERE rowid = old.id; END;
CREATE TRIGGER IF NOT EXISTS facts_ku AFTER UPDATE OF kw ON facts WHEN new.superseded_by IS NULL BEGIN
  DELETE FROM facts_fts WHERE rowid = old.id; INSERT INTO facts_fts(rowid, text, kw) VALUES (new.id, new.text, new.kw); END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
  DELETE FROM facts_fts WHERE rowid = old.id; END;
"""

_NORM = re.compile(r"[^a-z0-9 ]+")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", _NORM.sub(" ", s.lower())).strip()


# "The user's cat is named Luna." -> "cat"; "The user lives in Berlin." -> "lives in"
_POSSESSIVE = re.compile(r"^the user'?s? (.+?) (?:is|are|was|were) (\S+)", re.I)
_CANON = {"lives in": "residence", "moved to": "residence", "is from": "origin", "born in": "origin",
          "works at": "employer", "works for": "employer", "works as": "role", "studies": "study",
          "is learning": "study", "learning": "study", "name is": "name", "is called": "name", "is named": "name"}
_VERB = re.compile(r"^the user (?:is |has |was )?((?:lives in|moved to|works (?:at|as|for)|studies|is learning|learning|"
                   r"likes|loves|prefers|hates|dislikes|plays|speaks|drives|owns|wants to|plans to|is allergic to|"
                   r"allergic to|is vegetarian|is vegan|is from|born in|name is|is called|is named)\b)", re.I)


def fact_key(text: str) -> str:
    """A subject key so a newer fact about the same thing supersedes the older one. Heuristic on purpose:
    wrong keys just mean two facts coexist, and the background pass (consolidate.py) cleans those up."""
    t = text.strip().rstrip(".")
    m = _POSSESSIVE.match(t)
    if m:  # "cat is named X" and "cat is 3 years old" are different facts; "named X" vs "named Y" are the same one
        head = "#" if m.group(2)[0].isdigit() else norm(m.group(2))
        return f"of:{norm(m.group(1))}:{head}"
    m = _VERB.match(t)
    if m:
        v = norm(m.group(1))
        return "do:" + _CANON.get(v, v)
    return ""


def est_tokens(s: str) -> int:
    return int(len(s) / CHARS_PER_TOKEN) + 1


# ---------------------------------------------------------------- voice commands (deterministic)
REMEMBER_RE = re.compile(r"^\W*(?:hey nova,?\s*|nova,?\s*|please\s*)?(?:remember|don'?t forget|keep in mind|note)(?: that| this)?[:,]?\s+(.+)", re.I)
FORGET_RE = re.compile(r"^\W*(?:hey nova,?\s*|nova,?\s*|please\s*)?(?:forget|delete|erase)(?: that| about| everything about)?\s+(.+)", re.I)
FORGET_ALL_RE = re.compile(r"\b(forget everything|forget all of (?:it|that)|wipe (?:your|my) memory|reset (?:your )?memory)\b", re.I)
OFF_RECORD_RE = re.compile(r"\b(off the record|stop remembering|don'?t remember (?:this|anything))\b", re.I)
ON_RECORD_RE = re.compile(r"\b(back on the record|on the record|start remembering again|you can remember again)\b", re.I)


def parse_command(text: str) -> tuple[str, str] | None:
    """('remember'|'forget'|'forget_all'|'off_record'|'on_record', argument) or None."""
    text = (text or "").strip()
    if not text or len(text) > 300:
        return None
    if ON_RECORD_RE.search(text) and not OFF_RECORD_RE.search(text):
        return ("on_record", "")
    if OFF_RECORD_RE.search(text):
        return ("off_record", "")
    if FORGET_ALL_RE.search(text):
        return ("forget_all", "")
    m = REMEMBER_RE.match(text)
    if m:
        return ("remember", m.group(1).strip(" .!"))
    m = FORGET_RE.match(text)
    if m:
        return ("forget", m.group(1).strip(" .!"))
    return None


def to_third_person(s: str) -> str:
    """'I live in Berlin' -> 'The user lives in Berlin.' (cheap rewrite; the background pass polishes it)."""
    s = s.strip().rstrip(".!?")
    if s.lower().startswith("the user"):
        return s[0].upper() + s[1:] + "."
    swaps = [(r"^i am\b", "The user is"), (r"^i'm\b", "The user is"), (r"^i have\b", "The user has"),
             (r"^i'?ve\b", "The user has"), (r"^my\b", "The user's"), (r"^i\b", "The user")]
    for pat, rep in swaps:
        if re.match(pat, s, re.I):
            s = re.sub(pat, rep, s, count=1, flags=re.I)
            break
    else:
        s = "The user said: " + s
    s = re.sub(r"^The user (live|work|like|love|prefer|hate|want|need|play|speak|drive|own|study|go|eat|drink)\b",
               lambda m: f"The user {m.group(1)}{'es' if m.group(1) in ('go',) else 's'}", s)
    return s[0].upper() + s[1:] + "."


def locked(fn):
    @functools.wraps(fn)
    def wrap(self, *a, **kw):
        with self.lock:
            return fn(self, *a, **kw)
    return wrap


# ---------------------------------------------------------------- cheap, high-precision fact rules
# The 2B extractor misses statements (the live test dropped "I live in Lisbon and my dog is called Biscuit").
# These rules only fire on clear first-person sentences, and a miss costs nothing: the raw line is still searchable.
_NAME = r"([A-Z][\w'-]*(?: [A-Z][\w'-]*){0,2})"
_RULES = [
    (re.compile(r"\bI(?:'m| am)? (?:currently )?living in " + _NAME), "The user lives in {0}."),
    (re.compile(r"\bI live in " + _NAME), "The user lives in {0}."),
    (re.compile(r"\bI(?:'ve| have)? (?:just )?moved to " + _NAME), "The user moved to {0}."),
    (re.compile(r"\bmy name is " + _NAME, re.I), "The user's name is {0}."),
    (re.compile(r"\bmy (\w+(?: \w+)?) (?:is|are) (?:called|named) " + _NAME), "The user's {0} is named {1}."),
    (re.compile(r"\bmy (\w+(?: \w+)?)(?: is|'s) (?:called|named) " + _NAME), "The user's {0} is named {1}."),
    (re.compile(r"\bI(?:'m| am) allergic to ([a-z]+(?: [a-z]+)?)", re.I), "The user is allergic to {0}."),
    (re.compile(r"\bI work (?:at|for) " + _NAME), "The user works at {0}."),
    (re.compile(r"\bI work as (?:a |an )?([a-z]+(?: [a-z]+)?)", re.I), "The user works as a {0}."),
    (re.compile(r"\bmy (\w+)'s birthday is ([A-Z][a-z]+ \d+\w*)"), "The user's {0}'s birthday is {1}."),
    (re.compile(r"\bI(?:'m| am) (vegetarian|vegan|pescatarian)\b", re.I), "The user is {0}."),
]


def rule_facts(text: str) -> list[str]:
    out = []
    for rx, tpl in _RULES:
        for m in rx.finditer(text or ""):
            g = [x.strip(" .,") for x in m.groups()]
            if all(g):
                out.append(tpl.format(*g))
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- store
class Store:
    def __init__(self, path: str = DEFAULT_DB):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.lock = threading.RLock()  # the background pass runs in a worker thread
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- turns
    @locked
    def add_turn(self, conn: str, role: str, text: str) -> int:
        cur = self.db.execute("INSERT INTO turns(ts, conn, role, text) VALUES (?,?,?,?)",
                              (time.time(), conn, role, text))
        self.db.commit()
        return cur.lastrowid

    def recent_turns(self, conn: str, n: int = 12) -> list[tuple[str, str]]:
        rows = self.db.execute("SELECT role, text FROM turns WHERE conn=? ORDER BY id DESC LIMIT ?", (conn, n))
        return [(r["role"], r["text"]) for r in rows]

    def search(self, query: str, limit: int = 4) -> list[dict]:
        """Keyword search over past turns (BM25). Returns [{ts, role, text}] best first."""
        words = [w for w in re.findall(r"[a-z0-9']{3,}", query.lower())][:8]
        if not words:
            return []
        q = " OR ".join('"' + w.replace('"', "") + '"' for w in words)
        try:
            rows = self.db.execute(
                "SELECT t.ts, t.role, t.text FROM turns_fts f JOIN turns t ON t.id=f.rowid "
                "WHERE turns_fts MATCH ? ORDER BY bm25(turns_fts) LIMIT ?", (q, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(r) for r in rows]

    # ---- facts
    def active_facts(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM facts WHERE superseded_by IS NULL ORDER BY pinned DESC, id DESC").fetchall()

    @locked
    def add_fact(self, text: str, *, pinned: bool = False, source_turn: int | None = None,
                 origin: str = "local", kw: str = "") -> int | None:
        """Add a fact. Same text as an active fact: refresh it (and keep it pinned if either is). Same key as an
        active fact: the new one supersedes the old one (newest wins). Returns the fact id, or None if empty."""
        text = text.strip()
        if not text:
            return None
        n = norm(text)
        for row in self.active_facts():
            if norm(row["text"]) == n:
                if pinned and not row["pinned"]:
                    self.db.execute("UPDATE facts SET pinned=1 WHERE id=?", (row["id"],))
                    self.db.commit()
                return row["id"]
        key = fact_key(text)
        cur = self.db.execute("INSERT INTO facts(ts, text, key, pinned, source_turn, origin, kw) VALUES (?,?,?,?,?,?,?)",
                              (time.time(), text, key, int(pinned), source_turn, origin, kw))
        new_id = cur.lastrowid
        if key:
            self.db.execute("UPDATE facts SET superseded_by=? WHERE key=? AND id<>? AND superseded_by IS NULL",
                            (new_id, key, new_id))
        self.db.commit()
        return new_id

    @locked
    def forget(self, what: str) -> list[str]:
        """Delete active facts that mention `what` (every word of it), and return their text. The turns that
        produced them go too, so the derived memory cannot be re-extracted from the log."""
        from retrieve import terms  # content words only: "forget about the dog" must match "my dog is Biscuit"
        words = [w for w in terms(what)] or norm(what).split()
        if not words:
            return []
        gone = []
        for row in self.db.execute("SELECT * FROM facts").fetchall():
            if all(w in norm(row["text"]) for w in words):
                gone.append(row["text"])
                if row["source_turn"]:
                    self.db.execute("DELETE FROM turns WHERE id=?", (row["source_turn"],))
                self.db.execute("DELETE FROM facts WHERE id=?", (row["id"],))
        for row in self.db.execute("SELECT id, text FROM turns").fetchall():
            if all(w in norm(row["text"]) for w in words):
                self.db.execute("DELETE FROM turns WHERE id=?", (row["id"],))
        self.db.commit()
        return gone

    @locked
    def forget_all(self) -> int:
        n = self.db.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        self.db.executescript("DELETE FROM facts; DELETE FROM turns;")
        self.db.execute("INSERT INTO turns_fts(turns_fts) VALUES ('rebuild')")
        self.db.commit()
        return n

    @locked
    def replace_facts(self, facts: list[dict]):
        """Used by the background pass: swap the active (non-pinned) facts for a cleaned list. Pinned facts the
        user asked for are kept untouched unless the new list restates them."""
        for row in self.active_facts():
            if not row["pinned"]:
                self.db.execute("UPDATE facts SET superseded_by=0 WHERE id=?", (row["id"],))
        self.db.commit()
        for f in facts:
            self.add_fact(f["text"], pinned=bool(f.get("pinned")), origin="consolidated", kw=f.get("kw", ""))

    # ---- the core card
    def core_facts(self, budget: int = CARD_TOKENS) -> list[str]:
        out, used = [], 0
        for row in self.active_facts():  # pinned first, then newest
            cost = est_tokens(row["text"]) + 2
            if used + cost > budget:
                continue
            out.append(row["text"])
            used += cost
        return out

    def core_card(self, budget: int = CARD_TOKENS) -> str:
        facts = self.core_facts(budget)
        if not facts:
            return ""
        return ("What you already know about the user (from earlier days; use it quietly, never recite the list, "
                "and never mention these notes):\n" + "\n".join(f"- {f}" for f in facts))

    @locked
    def embed_missing(self, embedder, limit: int = 64) -> int:
        """Embed facts and user lines that have no vector for this embedder yet. Off the voice path (~20 ms a batch)."""
        from embed import to_blob
        n = 0
        for table, where in (("facts", "superseded_by IS NULL"), ("turns", "role='user'")):
            rows = self.db.execute(f"SELECT id, text, kw FROM {table} WHERE {where} AND (emb IS NULL OR emb_model IS NOT ?) "
                                   f"ORDER BY id DESC LIMIT ?", (embedder.name, limit)).fetchall() \
                if table == "facts" else \
                self.db.execute(f"SELECT id, text, '' AS kw FROM {table} WHERE {where} AND (emb IS NULL OR emb_model IS NOT ?) "
                                f"ORDER BY id DESC LIMIT ?", (embedder.name, limit)).fetchall()
            if not rows:
                continue
            vecs = embedder.encode([(r["text"] + " " + (r["kw"] or "")).strip() for r in rows])
            if vecs is None:
                return n
            for r, v in zip(rows, vecs):
                self.db.execute(f"UPDATE {table} SET emb=?, emb_model=? WHERE id=?", (to_blob(v), embedder.name, r["id"]))
                n += 1
        self.db.commit()
        return n

    def stats(self) -> dict:
        q = lambda s: self.db.execute(s).fetchone()[0]  # noqa: E731
        return {"turns": q("SELECT COUNT(*) FROM turns"), "facts": q("SELECT COUNT(*) FROM facts WHERE superseded_by IS NULL"),
                "superseded": q("SELECT COUNT(*) FROM facts WHERE superseded_by IS NOT NULL")}


# ---------------------------------------------------------------- per connection bridge
class ConnectionMemory:
    """Glue between one orchestrator connection and the Store. Reads what the SessionManager already collects
    (`sm.history`, `sm.facts`) after each turn, so session_manager.py needs no changes."""

    def __init__(self, store: Store, conn_id: str, embedder=None):
        from retrieve import Retriever
        self.store, self.conn, self.embedder = store, conn_id, embedder
        self.retriever = Retriever(store, embedder)
        self.card_facts: list[str] = []      # what the core card held when this session opened
        self.next_note = ""                  # prefetched for the next round (voice: built from the last exchange)
        self.next_hits: list = []
        self.off_record = False
        self._seen_facts: set[str] = set()   # sm.facts entries already handled (so they are not re-added)
        self._last_user_turn: int | None = None

    def card(self) -> str:
        self.card_facts = self.store.core_facts()
        return self.store.core_card()

    # ---- per-round retrieval (retrieve.py)
    def note_for(self, query: str) -> tuple[str, list]:
        """A memory note for this round, built from `query` (the user's words, or the last exchange). Usually ""."""
        if self.off_record or not query.strip():
            return "", []
        hits = self.retriever.retrieve(query, conn=self.conn, card_texts=self.card_facts)
        return (self.retriever.note(hits), hits) if hits else ("", [])

    def plan_next(self, sm):
        """After a turn (transcript known): prefetch the note for the NEXT round from the last exchange.
        Voice turns have no transcript before the reply, and follow-ups mostly stay on topic."""
        done = [h for h in sm._done_history() if h["role"] in ("user", "assistant") and not h["text"].startswith("(called ")]
        users = [h["text"] for h in done if h["role"] == "user"][-2:]
        last_assistant = next((h["text"] for h in reversed(done) if h["role"] == "assistant"), "")
        self.next_note, self.next_hits = self.note_for(" ".join(users[-1:] + [last_assistant[:200]] + users[:-1]))

    def take_note(self, query: str | None = None) -> str:
        """The note to send now: from `query` if the words are known (typed turns), else the prefetched one."""
        self.retriever.tick()
        if query:
            note, hits = self.note_for(query)
        else:
            note, hits, self.next_note, self.next_hits = self.next_note, self.next_hits, "", []
        if note:
            self.retriever.commit(hits)
        return note

    def sync(self, sm) -> list[tuple[str, str]]:
        """Persist new turns and facts from the session. Returns the command(s) found in new user lines,
        already applied: [(command, detail)]. While off the record nothing is stored."""
        events: list[tuple[str, str]] = []
        recent = set(self.store.recent_turns(self.conn, 12))
        for h in sm._done_history():
            key = (h["role"], h["text"])
            if h["role"] not in ("user", "assistant") or key in recent or h["text"].startswith("(called "):
                continue
            recent.add(key)
            cmd = parse_command(h["text"]) if h["role"] == "user" else None
            if cmd and cmd[0] in ("off_record", "on_record"):
                self.off_record = cmd[0] == "off_record"
                events.append(cmd)
                continue
            if self.off_record:
                continue
            tid = self.store.add_turn(self.conn, h["role"], h["text"])
            if h["role"] == "user":
                self._last_user_turn = tid
                for f in rule_facts(h["text"]):
                    self.store.add_fact(f, source_turn=tid)
                if cmd:
                    events.append(self.apply(cmd, tid, sm))
        for f in list(sm.facts):
            if f in self._seen_facts:
                continue
            self._seen_facts.add(f)
            if not self.off_record:
                self.store.add_fact(f, source_turn=self._last_user_turn)
        if self.embedder is not None and self.embedder.available:
            self.store.embed_missing(self.embedder)  # new lines/facts get vectors before the next round needs them
        self.plan_next(sm)
        return events

    def apply(self, cmd: tuple[str, str], turn_id: int | None, sm=None) -> tuple[str, str]:
        name, arg = cmd
        if name == "remember":
            fact = to_third_person(arg)
            self.store.add_fact(fact, pinned=True, source_turn=turn_id)
            self._seen_facts.add(fact)
            return ("remember", fact)
        if name == "forget":
            gone = self.store.forget(arg)
            if sm is not None:
                sm.facts[:] = [f for f in sm.facts if f not in gone]
            return ("forget", f"{len(gone)} removed")
        if name == "forget_all":
            n = self.store.forget_all()
            if sm is not None:
                sm.facts.clear()
            return ("forget_all", f"{n} removed")
        return cmd


async def inject_note(sm, note: str):
    """Put a memory note into the live realtime session as a silent user-side item, before the user's next
    utterance. Kept out of sm.history (so it is never carried over, extracted from, or stored), but counted in
    sm.est so rotation still happens in time."""
    if not note or sm.ws is None:
        return
    import asyncio, json
    from session_manager import count_tokens, ITEM_OVERHEAD
    n = await asyncio.to_thread(count_tokens, note) + ITEM_OVERHEAD
    await sm.ws.send(json.dumps({"type": "conversation.item.create", "item": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": note}]}}))
    sm.est += n
