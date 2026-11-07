# Long-term memory

Branch `memory`. Code: `backend/memory.py`, `backend/consolidate.py`, hooks in `backend/orchestrator.py`.
Tests (no model needed): `python3 backend/test_memory.py`. Turn it off with `MEMORY=0`.

## Why it looks like this

Research (benchmarks, shipped products, memory frameworks, the DeepSeek Harness repo) pointed the same way:

- The 2B model does **not** decide what to remember. No evidence an untuned 1–3B model calls `remember` /
  `recall` reliably, and frameworks (Mem0, Zep, Letta) need several LLM calls per write.
- Verbatim logs plus a small curated fact list match or beat fancier extraction. No graph.
- Memory is injected automatically into a stable prompt prefix, never fetched mid-turn on the voice path.
- Stale facts are the main failure in shipped products, so conflicts are resolved by code (newest wins), and a
  bigger model rewrites the list in the background.
- The DeepSeek Harness has **no** cross-session memory. It is the skill / background-job engine, not this.

## How it works

```
every turn ─► turns table (SQLite, FTS5 keyword search)          memory.py
2B model's per-message facts (already in SessionManager.facts)
            ─► facts table: key, date, pinned, source turn, superseded_by
session start ─► core card: pinned + newest active facts, ≤ 400 tokens, appended to the system prompt
rotation / connection close ─► consolidate.py: Claude merges duplicates, rewrites time-bound facts,
                               fixes obvious ASR slips (needs ANTHROPIC_API_KEY; otherwise skipped)
```

`session_manager.py` is untouched. `ConnectionMemory.sync()` reads `sm.history` and `sm.facts` after each turn
(`Connection.after_turn`, spawned off the reply path).

## Voice commands (deterministic, not model judgment)

| Say | Effect |
|---|---|
| "remember that my sister's birthday is June 3rd" | pinned fact, always in the card |
| "forget about the dog" / "forget the Kyoto trip" | deletes matching facts **and** the turns they came from |
| "forget everything" | wipes facts and turns |
| "off the record" / "back on the record" | nothing stored while off |

"What do you know about me?" needs no code: the card is in the prompt, so the model answers from it.

## Rules worth knowing

- A fact supersedes an older one with the same key (`fact_key`: "the user's cat is named X", "the user lives in X").
  Keys are a cheap heuristic. A wrong key means two facts coexist, and the Claude pass cleans them up.
- Memory is untrusted input. Only the user's own lines and the local model's extraction write facts.
  Camera / screen descriptions and web content never do.
- Data lives in `backend/data/memory.db` (git-ignored, `MEMORY_DB` overrides). Everything is local.

## Not done yet

- **Not run against the live model.** Tested with fakes only (`test_memory.py` includes the orchestrator wiring).
  First real check: talk to the orb, quit, relaunch, ask what it knows.
- Per-turn snippet retrieval (`Store.search` exists but nothing calls it; voice has no transcript before the reply).
- Confirming new names and numbers aloud (ASR errors can become facts; the Claude pass is the only guard now).
- Spoken "what do you know" with a confirmation before "forget", and a visible list on the canvas.
- DSH skills / widget registry and background jobs. They come after this layer (see the research notes).
- Consolidation needs a real `ANTHROPIC_API_KEY`; the model id is `MEMORY_MODEL` (default `claude-haiku-5-5`).
