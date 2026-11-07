"""Retrieval eval, LongMemEval-style but small and about OUR setup: short personal facts, paraphrased questions,
facts that were updated, and questions with NO answer in memory (the model must be left alone).
No model, no network:  python3 backend/test_retrieval.py

Measures: recall (the right item is in the note), abstention (no note when nothing matches), stale errors
(a superseded fact shows up), and the note's token cost. The thresholds in retrieve.py were tuned on this set.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory import Store, est_tokens  # noqa: E402
from retrieve import Retriever, NOTE_TOKENS  # noqa: E402

DAY = 86400
NOW = time.time()

FACTS = [  # (age in days, text)
    (120, "The user lives in Lisbon."), (10, "The user lives in Porto."),
    (90, "The user's dog is named Biscuit."), (88, "The user's dog is 4 years old."),
    (60, "The user is allergic to peanuts."), (45, "The user is learning Spanish."),
    (30, "The user works as a nurse at a children's hospital."), (21, "The user's sister's birthday is June 3rd."),
    (14, "The user is planning a trip to Kyoto in April."), (9, "The user prefers tea over coffee."),
    (7, "The user's favorite band is Khruangbin."), (5, "The user is training for a half marathon in October."),
    (3, "The user's flight to Berlin leaves on Friday at 7am."), (2, "The user is vegetarian."),
    (50, "The user's manager is named Priya."), (40, "The user plays the cello on weekends."),
    (35, "The user drives a green Honda Civic."), (25, "The user's mother lives in Toronto."),
    (18, "The user is saving up for a new laptop."), (12, "The user's apartment has a balcony garden with tomatoes."),
]
TURNS = [
    (30, "I finally booked the dentist for the fourteenth, it's with Doctor Okafor"),
    (22, "My roommate Dana keeps leaving the dishes, so annoying"),
    (15, "I started reading Dune last night and I can't put it down"),
    (11, "The wifi password at my parents' place is sunflower42"),
    (6, "I need to renew my passport before the Kyoto trip"),
    (4, "Let's call the pasta sauce experiment a success, I used smoked paprika"),
]
CARD = {"The user lives in Porto.", "The user is vegetarian.", "The user prefers tea over coffee.",
        "The user's flight to Berlin leaves on Friday at 7am."}   # pretend these fit the core card already

# (query, substrings that MUST appear in the note, substrings that must NOT)
ANSWERABLE = [
    ("What's my dog called again?", ["Biscuit"], []),
    ("How old is my dog now?", ["4 years"], []),
    ("Can I eat this cookie, it has nuts in it", ["peanut"], []),
    ("What language am I studying these days?", ["Spanish"], []),
    ("Where do I work?", ["nurse"], []),
    ("When is my sister's birthday?", ["June 3rd"], []),
    ("Remind me where I'm going in the spring", ["Kyoto"], []),
    ("What music should we put on, my favourite band?", ["Khruangbin"], []),
    ("How's my running going, the marathon thing", ["half marathon"], []),
    ("Who is my boss?", ["Priya"], []),
    ("Do I play any instruments?", ["cello"], []),
    ("What car do I have?", ["Honda"], []),
    ("Where does my mom live?", ["Toronto"], []),
    ("What am I saving money for", ["laptop"], []),
    ("Any tips for my tomato plants", ["tomato"], []),
    ("When's my dentist appointment and who's the doctor", ["Okafor"], []),
    ("What's the wifi password at my parents", ["sunflower42"], []),
    ("What book am I reading", ["Dune"], []),
    ("Do I need anything for the Kyoto trip", ["passport"], []),
]
# nothing in memory about these: the right note is NO note
ABSTAIN = [
    "What's the capital of France?", "How long should I boil an egg?", "Tell me a joke about cats",
    "What's two hundred times fifteen?", "Can you explain how a rainbow forms?", "Good morning!",
    "Who won the world cup in 2010?", "Translate thank you into Japanese", "How do I center a div in CSS?",
    "What's the weather like on Mars?", "Summarize the plot of Hamlet", "Set a timer for ten minutes",
]


# Held out: written after the synonym map was fixed, never used for tuning. Reported, with a looser bar.
HELD_ANSWER = [
    ("is my pup due for a vet visit, how old is she", ["Biscuit", "4 years"]),
    ("any restaurant suggestions, I can't have anything with peanuts", ["peanut"]),
    ("what was the name of that doctor for my teeth", ["Okafor"]),
    ("what do I do for a living", ["nurse"]),
    ("can you suggest some tunes like my favorite group", ["Khruangbin"]),
    ("who do I report to at the office", ["Priya"]),
    ("do I have anything planned for April", ["Kyoto"]),
    ("what's my sibling's birthday", ["June 3rd"]),
    ("am I still doing my race prep", ["half marathon"]),
    ("which novel was I in the middle of", ["Dune"]),
]
HELD_ABSTAIN = [
    "What's the tallest mountain in the world?", "Play something relaxing please", "How many ounces in a pound?",
    "Write a haiku about autumn rain", "What does DNS stand for?", "Can you recommend a good podcast?",
    "Convert 50 miles to kilometers", "Why is the sky blue?", "Give me a fun fact about octopuses",
    "How do I reverse a string in Python?",
]


_EMB = None


def embedder():
    """The real embedder if one is available here (sentence-transformers or a llama --embeddings server)."""
    global _EMB
    if _EMB is None:
        from embed import Embedder
        _EMB = Embedder()
        _EMB.start()
    return _EMB if _EMB.available else None


def build(emb=None) -> Store:
    s = Store(":memory:")
    for d, t in FACTS:
        fid = s.add_fact(t)
        s.db.execute("UPDATE facts SET ts=? WHERE id=?", (NOW - d * DAY, fid))
    for d, t in TURNS:
        tid = s.add_turn("old-run", "user", t)
        s.db.execute("UPDATE turns SET ts=? WHERE id=?", (NOW - d * DAY, tid))
    s.add_turn("old-run", "assistant", "Your dog Biscuit sounds lovely, and Lisbon is nice")  # must never be retrieved
    s.db.commit()
    if emb:
        s.embed_missing(emb, limit=500)
    return s


def run_eval(verbose=False, emb=None):
    s = build(emb)
    r = Retriever(s, emb)
    hits_ok, stale, costs, misses = 0, 0, [], []
    for q, must, mustnt in ANSWERABLE:
        r.shown.clear()
        hits = r.retrieve(q, conn="now", card_texts=list(CARD), now=NOW)
        note = r.note(hits, now=NOW)
        costs.append(est_tokens(note))
        if all(m.lower() in note.lower() for m in must):
            hits_ok += 1
        else:
            misses.append((q, note))
        stale += any(m.lower() in note.lower() for m in mustnt)
        stale += "Lisbon" in note or "assistant" in note.lower()
    false_pos = []
    for q in ABSTAIN:
        r.shown.clear()
        hits = r.retrieve(q, conn="now", card_texts=list(CARD), now=NOW)
        if hits:
            false_pos.append((q, r.note(hits, now=NOW)))
    res = {"recall": hits_ok / len(ANSWERABLE), "abstain": 1 - len(false_pos) / len(ABSTAIN), "stale": stale,
           "avg_note_tokens": sum(costs) / len(costs), "max_note_tokens": max(costs)}
    if verbose:
        for q, n in misses:
            print("  MISS:", q, "->", n or "(no note)")
        for q, n in false_pos:
            print("  FALSE POSITIVE:", q, "->", n)
    return res


def test_retrieval_quality_keywords_only():
    res = run_eval(verbose=True)
    print("   keywords only:", {k: round(v, 3) for k, v in res.items()})
    assert res["recall"] >= 0.85, res
    assert res["abstain"] >= 0.90, res
    assert res["stale"] == 0, res
    assert res["max_note_tokens"] <= NOTE_TOKENS, res


def test_retrieval_quality_hybrid():
    emb = embedder()
    if emb is None:
        print("   (no embedder here: hybrid eval skipped)")
        return
    res = run_eval(verbose=True, emb=emb)
    print("   hybrid:", {k: round(v, 3) for k, v in res.items()})
    assert res["recall"] >= 0.85, res
    assert res["abstain"] >= 0.90, res
    assert res["stale"] == 0, res
    assert res["max_note_tokens"] <= NOTE_TOKENS, res


def held_out(emb):
    s = build(emb)
    r = Retriever(s, emb)
    ok = 0
    for q, must in HELD_ANSWER:
        r.shown.clear()
        note = r.note(r.retrieve(q, conn="now", card_texts=list(CARD), now=NOW), now=NOW)
        ok += all(m.lower() in note.lower() for m in must)
        if verbose_held:
            print("  held-out", "ok  " if all(m.lower() in note.lower() for m in must) else "MISS", q, "->", note[-90:] or "(none)")
    fp = []
    for q in HELD_ABSTAIN:
        r.shown.clear()
        if r.retrieve(q, conn="now", card_texts=list(CARD), now=NOW):
            fp.append(q)
    print("   held-out", "hybrid:" if emb else "keywords only:",
          {"recall": ok / len(HELD_ANSWER), "abstain": 1 - len(fp) / len(HELD_ABSTAIN)}, fp)
    return ok / len(HELD_ANSWER), len(fp)


def test_held_out_set():
    global verbose_held
    verbose_held = False
    held_out(None)                       # reported only: the keyword fallback is known to be weaker
    emb = embedder()
    if emb:
        rec, fp = held_out(emb)
        assert rec >= 0.7 and fp <= 1, (rec, fp)


verbose_held = True


def test_card_facts_and_repeats_are_not_resent():
    s = build()
    r = Retriever(s)
    assert r.retrieve("do you remember that I'm vegetarian", card_texts=list(CARD), now=NOW) == []   # already in the card
    r.tick()
    first = r.retrieve("what's my dog called", conn="now", card_texts=[], now=NOW)
    assert first and "Biscuit" in first[0].text
    r.commit(first)
    r.tick()
    assert not [h for h in r.retrieve("what's my dog called", conn="now", card_texts=[], now=NOW) if "Biscuit" in h.text]
    for _ in range(7):
        r.tick()
    assert any("Biscuit" in h.text for h in r.retrieve("what's my dog called", conn="now", card_texts=[], now=NOW))


def test_live_session_lines_are_not_retrieved_back():
    s = build()
    s.add_turn("now", "user", "My neighbour grows dahlias and gave me some bulbs")
    r = Retriever(s)
    assert r.retrieve("tell me about the dahlias neighbour", conn="now", card_texts=[], now=NOW) == []
    assert r.retrieve("tell me about the dahlias neighbour", conn="other", card_texts=[], now=NOW)


def test_forgotten_and_superseded_never_surface():
    s = build()
    s.forget("biscuit")
    r = Retriever(s)
    assert not [h for h in r.retrieve("what's my dog called", conn="now", card_texts=[], now=NOW) if "Biscuit" in h.text]
    assert not [h for h in r.retrieve("where do I live", conn="now", card_texts=[], now=NOW) if "Lisbon" in h.text]


def test_empty_and_stopword_queries():
    r = Retriever(build())
    assert r.retrieve("", now=NOW) == [] and r.retrieve("um yeah okay so", now=NOW) == []


if __name__ == "__main__":
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        fn()
        print("ok", name)
