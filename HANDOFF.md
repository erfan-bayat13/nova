# Handoff: the whole project

**Updated:** 2026-11-07 · **Covers:** concept, model research, backend (orchestrator), frontend (canvas)

**One-liner** (from [docs/CONCEPT.md](docs/CONCEPT.md)): *If AI understands what you want, why should you
have to find the right app?* A blank canvas with one voice orb. You say what you're doing, an interface
forms around it, and it goes away when you're done. A small local omni model (LFM3-Omni-2B) does the
everyday work, and Claude handles hard requests and teaches the local model new widgets.

---

## ▶ Start here (next session) — 2026-11-07

**Where it stopped:** the app works end to end (talk to the canvas → the local model builds widgets and
answers), but **the voice the user hears is the browser's built-in voice, and the user hates it.**
The goal is to play **LFM's own voice** (the 24 kHz voice in `prototype/examples.html`, which the user liked).
Nothing for this is committed yet. All work up to here is committed (`af84b43`).

**What we learned while trying (don't repeat these):**
1. **Text + speech output kills tool calls.** With `output_modalities: ["text","audio"]` the model just
   *talks* ("Pasta for four.") and never calls `create_widget`. So the thinking/tool turns must stay
   text-only, and the voice has to come from a separate speaking step.
2. **"Repeat this exactly" doesn't work as TTS.** A separate realtime session told to say the line word
   for word *answers* it instead ("Let me work that one out." → "Understood. I am ready when you are.").
   Only 4/7 lines came out right. First audio was fast though (~0.4 s).
3. **Untested, and the next thing to try:** the model card's TTS mode, with instructions
   `"Perform TTS in English using a female voice."` and **speech-only** output (`["audio"]`). An earlier
   attempt with text + speech output spoke only fragments. Note that speech-only *chat* overran with
   silence (prototype/README), so check for a silent tail. Measure: ASR match vs the line, first-audio
   time, trailing silence. Fallback if it fails: `llama-tts -m … -mm … --tts-voice female` (but that loads
   a second model, ~1.6 GB, risky on 8 GB).
4. If TTS works, the plan:
   - `session_manager`/backend: after a turn's final line is known (CHAT reply or ACT confirmation),
     open a short-lived TTS realtime session and stream its audio deltas to the canvas as **binary frames,
     PCM16 24 kHz mono**, framed by `{type:"speech_start"}` / `{type:"speech_end", text}`. Keep `say` as
     the fallback when there's no audio.
   - Canvas (`ui/src/voice.ts` + `useCanvas.ts`, `ws.binaryType = "arraybuffer"`): schedule the 24 kHz
     chunks on an AudioContext back to back, show `speaking` until the last one ends, stop everything
     on `orb_down` (interrupt).
   - Update PROTOCOL.md in the same commit.

**⚠️ The Mac is an 8 GB M2: the user's machine got very slow during these tests.** Run one heavy thing at a
time. Don't keep a test script, the orchestrator, the browser pane and llama-server all busy at once. Prefer
short tests. Close the browser pane when you're done with it.

**How to bring everything back up** (all of it was stopped at the end of the last session):

```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384
```

```bash
cd ~/Documents/hackathon && ORCH_PORT=8766 python3 backend/orchestrator.py
```

Canvas (from `ui/`: `npm run demo` keeps the mock on 8765 and Vite on 5173), then open in **Chrome** (it needs
the real mic; the Claude app's browser pane has none): http://localhost:5173/?ws=ws://localhost:8766/canvas

**Other recent decisions (this session):**
- Nova **talks normally**: CHAT turns (hello, small talk, quick questions) get a natural 1–3 sentence spoken
  reply. ACT turns (cooking, timers, lists, clearing) call tools and give a short confirmation. See `backend/README.md`.
- No screen note is sent when the canvas is empty: the model answered "[Canvas: empty]" instead of the user.
- Silent taps are ignored (< 0.25 s of speech): the model invented a recipe from silence.
- Friendly tone (Nova) stays the default. Warm-up for the cold first turn (~5–6 s) is still to do after the voice.

## 0. Status at a glance

| Piece | State | Where |
|---|---|---|
| Concept, demo script, architecture | ✅ locked v1 | [docs/CONCEPT.md](docs/CONCEPT.md) |
| Canvas ⇄ orchestrator contract | ✅ v1, + binary mic audio + dev `text` | [docs/PROTOCOL.md](docs/PROTOCOL.md) |
| Local model research (LFM3-Omni-2B on an 8 GB M2) | ✅ done, all limits measured | [prototype/README.md](prototype/README.md), [LFM3-Omni-2B-reference.md](LFM3-Omni-2B-reference.md) |
| Session manager (context rotation, crash recovery, facts memory) | ✅ tested | [prototype/session_manager.py](prototype/session_manager.py) |
| **Backend orchestrator** | ✅ **runs the cooking demo end to end on the real model** (via the test client) | [backend/](backend/README.md) |
| Canvas UI | ✅ runs the full demo against the mock | [ui/](ui/README.md) |
| Canvas ↔ real backend | ✅ **talk to it**: mic streams to the backend, the model builds widgets, the browser voice answers | §2 C |
| Escalation to Claude | ❌ stub (placeholder widget) | [backend/escalate.py](backend/escalate.py) |
| "Cloud teaches, local remembers" (saving Claude widgets) | ❌ not started | §6 |
| Camera / vision in the app | ❌ backend has `see()`, canvas doesn't capture frames | §6 |

---

## 1. Where things are

```
hackathon/
├── HANDOFF.md                  ← this file
├── LFM3-Omni-2B-reference.md   model facts: capabilities, license, runtimes, output modes, tone
├── docs/
│   ├── CONCEPT.md              product concept, demo script, architecture (locked v1)
│   └── PROTOCOL.md             ★ the canvas ⇄ orchestrator message format. The contract.
├── ui/                         ★ the canvas (Vite + React + TypeScript)
│   ├── mock/server.mjs         fake orchestrator that replays the demo
│   └── README.md               how to run it, file map
├── backend/                    ★ the real orchestrator (Python, websockets)
│   ├── orchestrator.py         canvas WebSocket :8765/canvas → model turns → canvas messages
│   ├── tools.py                model tools + tool call → canvas message mapping
│   ├── escalate.py             Claude path (STUB, contract in its docstring)
│   ├── test_client.py          fake canvas: plays the demo against the real model
│   └── README.md               how a turn works, measured timings, known issues
├── prototype/                  model research + the session manager
│   ├── README.md               ★ every measured result and limit (read this before tuning anything)
│   ├── session_manager.py      realtime client: context budget, rotation, facts memory, watchdog
│   ├── router.py               output-mode trigger router + tone presets ("friendly" = Nova, default)
│   ├── tests.py, tests_long.py, test_session.py   test suites
│   ├── make_videos.py, make_examples.py → examples.html   test media + playable results page
│   └── logs/                   results (*.jsonl); audio/video is gitignored, regenerate with the scripts
└── models/                     GGUF weights, NOT in git (llama.cpp downloads them with -hf)
```

## 2. Run it

**Prerequisites:** macOS, `brew install llama.cpp` (needs ≥ build 11960, we use 0.9.0), Python 3.12 with
`pip install -r backend/requirements.txt`, Node for the UI.

**A. Canvas demo with the mock (no model needed):**

```bash
cd ui && npm install && npm run demo
```

Open http://localhost:5173. Hold the orb (or Space) and let go to play the next demo line.

**B. Real model, no UI** (the quickest way to see the backend work):

```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384
```

```bash
ORCH_PORT=8766 python3 backend/orchestrator.py
```

```bash
ORCH_PORT=8766 python3 backend/test_client.py
```

**C. Canvas + real backend (talk to the local model):** start llama-server (as in B), then

```bash
ORCH_PORT=8766 python3 backend/orchestrator.py
```

and open **http://localhost:5173/?ws=ws://localhost:8766/canvas** in Chrome (the UI from A, or `cd ui && npm run dev`).
Hold the orb or Space, speak, let go. Allow the microphone on the first press. Port 8766 lets the mock keep
8765. Without `?ws=`, run the orchestrator on 8765 and use `npm run dev` instead of `npm run demo`.

⚠️ **Always run llama-server with `-np 2 -c 16384` on the 8 GB Mac.** The defaults (4 slots × 32K) crashed the machine.

## 3. What the frontend decided (please keep these true)

These came out of the UI sessions with the product owner. Some of them constrain the backend.

1. **It must never look like a chat app.** No transcript, no message bubbles, no "thinking…" text.
   The screen is one orb plus widgets. Nothing else.
2. **Only tool calls reach the screen.** The orchestrator never sends the model's free text to the
   canvas. Anything the system says out loud arrives as a `say` message, and the canvas never displays that text.
3. **The system speaks**, very briefly (1–6 words is typical: "Six it is. Timer's running.").
   The voice confirms what the screen already shows. It never reads the screen out.
4. **One voice, always.** Even when Claude did the work, the local voice delivers the result.
   The user shouldn't need to know which model worked. (Whether to hint at cloud work at all is
   still open. The canvas supports both, see `?tint`.)
5. **No caption** of what the user said, for now.
6. **The model never sends coordinates.** It sends an `importance` (`hero`, `side`, `satellite`,
   `full`) and the canvas lays things out.
7. **The user can always interrupt.** Pressing the orb stops speech immediately and starts listening.
8. Visual direction is Apple-native and restrained. Reference mockup:
   https://claude.ai/artifact/XYuV9Jgv9sxGxkt1mFk2Sy
9. Default voice personality is the **"friendly" preset** (Nova, warm and casual) from `prototype/router.py`.

## 4. What the local model can and can't do (summary of prototype/README.md)

| ✅ Works well | ⚠️ / ❌ Limits we designed around |
|---|---|
| Tool calls from the demo lines: 8/8 correct, 1–2 s | **Plain text instead of `say`**: we speak its closing line |
| Voice in → tool call (~2 s on short audio in isolation) | Voice turns in the orchestrator are slower (6–8 s), not profiled |
| Transcription: 97.5–100% accurate on 12 s – 2.7 min of audio, ~9× real time | **Invents what it didn't hear** (said "apples, violin" for audio about neither) |
| Speech out (text + speech mode): first sound 0.3–0.7 s, clean up to ~80 words / 30 s | Speech-only mode is broken. Long speech (>40 s) garbles. |
| Reads screens and placards in images/video exactly | Full video is slow (11–19 s). Use one full-resolution frame (~2.8 s). Never downscale text. |
| Point camera → spoken answer: first sound ~2 s | Realtime takes no images: frame → chat endpoint → description → realtime |
| 100+ turn conversations with perfect recall | **8K context overflow crashes the whole server** → session manager rotates at ~6K (estimate over-counts ~30%, safe) |
| Server memory flat at ~1.6–1.7 GB | Model mixes up "you"/"me" in follow-ups. Weak multi-step reasoning (2B). |

## 5. The contract and the backend mapping

Full spec: [docs/PROTOCOL.md](docs/PROTOCOL.md). The backend implements all of it.

| model tool call | canvas message |
|---|---|
| `create_widget(id, widget, props, importance)` | `create` |
| `update_widget(id, props)` | `update` (props merged) |
| `remove_widget(id)` / `clear_canvas()` | `remove` / `clear` |
| `start_timer(minutes, label)` | `create` with `widget:"timer"`, `importance:"satellite"`, `props:{label, seconds}` |
| `say(text)` **or the model's closing line** | `say` |
| `escalate(task)` | `pending` + orb `working`, then Claude's result as `create` (built-in type or `html`) + `say` |
| canvas `event timer_done` | `say "<label>'s done."` (no model call) |

Built-in widgets: `recipe`, `checklist`, `timer`, `stacked_bar`, `html`. `html` is the slot for
**Claude-generated widgets**: a full HTML document run in a sandboxed iframe. It receives `{type:"props", data}`
and can post back `{type:"emit", name, data}`. That's how "the cloud teaches, the local model remembers" gets
onto the screen: Claude writes the HTML once, the backend saves it, and next time the local model calls `create` with it.

## 6. Open items

**Frontend:**
- [x] **Stream mic audio to the backend** (`ui/src/mic.ts`): PCM16 16 kHz mono binary frames between `orb_down` and `orb_up`, last frame flushed before `orb_up`.
- [ ] Play LFM's own audio instead of the browser voice (optional; only `ui/src/voice.ts` changes). Format not decided yet.
- [ ] Camera: capture one full-resolution frame on request (`{type:"capture"}` → JPEG back). Backend has `SessionManager.see()` ready.
- [ ] Vision demo scene in the mock.
- [ ] Linked widgets decision: the model updated only `servings` on "make it for six". Canvas-side linking (ingredients read `servings` from the recipe) is the most reliable fix.

**Backend:**
- [x] Orchestrator WebSocket at `:8765/canvas` speaking PROTOCOL.md
- [x] Free text never on screen; speech only as `say`
- [x] Tool calls → canvas messages, multi-step tool loop
- [x] Session rotation + server crash recovery (session manager)
- [ ] **Escalation for real:** call Claude in `backend/escalate.py` (contract in its docstring), return a built-in widget or `html`
- [ ] **Save Claude-built widgets** (e.g. `backend/learned/`) and add them to the local model's widget list. That's the core of the pitch.
- [ ] Shorter spoken lines (prompt tuning; target 1–6 words, currently ~4–8)
- [ ] **Warm-up** to remove the cold first turn (~5–6 s; warm voice turns take ~2 s). Plan: send a warm-up turn with some context at `hello`.
- [ ] Barge-in: `orb_down` during a turn should cancel it (`response.cancel` in the session manager)
- [ ] Vision path: `capture` → `see()` once the canvas can send frames

**Both:**
- [ ] Decide on linked widgets (above).
- [ ] Run the full demo through the canvas with real mic input once streaming lands.

## 7. How to change the contract

PROTOCOL.md is the single source of truth. If you need a new message or field, change PROTOCOL.md
in the same commit as the code, and add it to `ui/mock/server.mjs` if the demo should use it.

## 8. Git

The whole repo is in git (`main`). Not committed: model weights (`models/`, `*.gguf`), `node_modules/`,
generated test media (`prototype/videos/`, `prototype/logs/*.wav` etc.; regenerate with
`prototype/make_videos.py` and the test scripts), local server logs, `.env`.
