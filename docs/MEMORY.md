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
every turn ─► turns table (SQLite, FTS5 + vectors)                memory.py
2B model's facts (SessionManager.facts) + cheap first-person rules ─► facts table: key, date, pinned,
   source turn, superseded_by, keywords, vector
session start ─► CORE CARD: pinned + newest facts, <= 400 tokens, appended to the system prompt (stable prefix)
every round  ─► RETRIEVAL NOTE: <= 110 tokens, 0-3 items, sent as one silent item right before the user speaks
rotation / connection close ─► consolidate.py: Claude merges duplicates, rewrites time-bound facts,
                               adds search keywords (needs ANTHROPIC_API_KEY; otherwise skipped)
```

`session_manager.py` is untouched. `ConnectionMemory.sync()` reads `sm.history` and `sm.facts` after each turn
(`Connection.after_turn`, off the reply path, in a worker thread).

### Per-round retrieval ([retrieve.py](../backend/retrieve.py), [embed.py](../backend/embed.py))

The card holds the hottest ~25 facts. Everything else is cold. Each round pulls the few cold items that matter:

- **When the words are known** (typed turns, `text` messages): the query is the user's text.
- **Voice** has no transcript before the reply (the audio streams straight into the model), so the note is
  **prefetched** after each turn from the last exchange and sent at the next `orb_down`. It follows the topic of
  the conversation. A brand-new topic is caught by the card only. Known gap.
- **Hybrid score**: embedding cosine (all-MiniLM-L6-v2, ~18 ms; or a llama.cpp `--embeddings` server, see
  embed.py) + BM25 (FTS5, porter stemming) + query-term coverage + small recency / pinned / curated-fact terms.
  Without an embedder it falls back to keywords + a hand-made synonym map.
- **Abstain by default.** A quality gate drops weak matches, so most rounds get no note. Distractors hurt a 2B
  model more than a missed memory helps.
- **Dedupe**: not in the card, not shown in the last 6 rounds, not from a line still inside the live session,
  no near-duplicates. Only the user's own words are retrieved (never assistant lines, never questions).
- **Echo-safe**: the note has no brackets or inner parentheses, and `strip_context_echo` removes it if the model
  repeats it.

### Measured ([test_retrieval.py](../backend/test_retrieval.py), no model needed)

20 facts + 6 user lines (including a superseded fact and an assistant line that must never come back),
19 answerable questions, 12 that have no answer, plus a held-out set (10 + 10) written after tuning.

| | recall | abstain | stale errors | note size |
|---|---|---|---|---|
| keywords + synonym map, train | 100% | 100% | 0 | avg 54 / max 85 tok |
| hybrid, train (thresholds tuned here) | 100% | 100% | 0 | avg 52 / max 82 tok |
| keywords only, held-out | 60% | 80% | | |
| **hybrid, held-out** | **80%** | **90%** | | |

The held-out numbers are the honest ones (n = 10, so one question is 10 points). The keyword synonym map was
fitted to the train set, which is why it falls apart on new phrasings and why the embedder matters. Public
benchmarks (LoCoMo, LongMemEval) are saturated and vendor-run, so this tiny set about our setup is the one to grow.

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

## Live check (2026-11-07)

One run through the real orchestrator + llama-server (three connections, typed lines in voice mode) worked:
facts and raw lines survived across connections, the notes were injected, "remember that..." came back. It also found
four bugs, now fixed and unit-tested: the 2B extractor missed "I live in Lisbon and my dog is called Biscuit"
(added first-person rules), "forget about the dog" did not match because of the filler words, questions were
replayed as memories, and "moved to Porto" did not supersede "lives in Lisbon" (canonical keys).
**The re-run after those fixes hung** because the llama-server has two slots and another orchestrator (the
canvas app) was holding one. Not a memory bug, but it means the fixed build has only been exercised by unit tests.

## Not done yet

- Re-run the live check with the server to yourself, and with `ORCH_LOG=1` read the `memory note:` lines.
- Old raw lines can contradict a newer fact ("I live in Lisbon" after "moved to Porto"). The note shows ages and
  Claude's pass fixes facts, but raw lines are never rewritten.
- A second embedder path (llama.cpp `--embeddings`, ~100 MB) is written but untested. torch in the orchestrator costs RAM on the 8 GB machine.
- Confirming new names and numbers aloud (ASR errors can become facts).
- Spoken "what do you know" with a confirmation before "forget", and a visible list on the canvas.
- Consolidation needs a real `ANTHROPIC_API_KEY` (model id: `MEMORY_MODEL`, default `claude-haiku-5-5`); only tested with a fake model.
- DSH skills / widget registry and background jobs come after this layer.
