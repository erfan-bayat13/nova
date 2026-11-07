# Handoff: the whole project

**Updated:** 2026-11-07 · **Covers:** concept, model research, backend (orchestrator), frontend (canvas)

**One-liner** (from [docs/CONCEPT.md](docs/CONCEPT.md)): *If AI understands what you want, why should you
have to find the right app?* A blank canvas with one voice orb. You say what you're doing, an interface
forms around it, and it goes away when you're done. A small local omni model (LFM3-Omni-2B) does the
everyday work, and Claude handles hard requests and teaches the local model new widgets.

---

## ▶ Latest-latest (2026-11-07, evening): creator mode (talk, and a canvas opens)

Committed on `voice-orb` (`e5ca536` … `78f3063`). Design is in the PROTOCOL.md "Creator mode" paragraph.

**How it works:** you ask ("I'm cooking pasta for four", "start a ten minute timer", "make it for six", "I'm done"). Nova answers with a
fixed spoken line (taught by examples in `VOICE_SYSTEM`): "Okay, putting that on the canvas." / "Okay, clearing the canvas." The orchestrator
(`maybe_build` → `Connection.build`) then takes the transcript the session already makes (`sm.last_user_text()`), and runs the **builder**
(`backend/builder.py`): a tool-calling turn on llama-server's chat endpoint with the system prompt, worked examples as real message history, and the
canvas state. It sends `create/update/remove/clear` as calls are made; a failed call gets one follow-up so the model can fix it. `escalate` goes to
real Claude (`backend/escalate.py`, needs `ANTHROPIC_API_KEY`; new html widgets are saved in `backend/learned/` and become `learned_<name>` types
the local model can create itself). Six new widgets: note, stat, list, table, progress, counter (`?gallery` shows all). The orb page opens a canvas:
the window grows to the work area, widgets float out of the orb, the orb docks at the bottom, click-through except over widgets/orb, "Clear canvas" in
the menus. Announcements (timer done, cloud result) are spoken by Nova (`Connection.say`), not the browser voice.

**Tested:** text turns on the real model (pasta, update to six, timer, clear, progress, escalation against a mock Claude server); escalation 13/13 on a mock
server; the orb page against the mock in a browser with a faked shell. The real Electron path by synthetic hotkey and `say` through the speakers worked
once (the orb heard it, Nova answered, a build started).

**⚠️ Open, important:**
- **llama-server hang: fixed and verified.** It hung once when the builder ran its own ASR at the same time as the session's after-reply ASR (two audio
  requests at once: both slots busy, ~0 % CPU). The builder now waits for the session's own transcript (`sm.last_user_text()`). After a restart the full
  spoken suite ran clean. Rules that remain: one orchestrator only, never two audio chat requests at once.
- **Talkative Nova (added last):** `VOICE_SYSTEM` now asks for a warmer, more vocal friend (2–4 sentences, a follow-up question, talk plans through first). The canvas line
  is the FIRST sentence and she keeps chatting after it (`BUILD_NOW_RE` matches anywhere in the reply). The builder gets the last few chat lines
  (`builder.conversation_note`) so "June, ten days, cities and food" still knows it is about Spain, always puts a starter widget up (a bare "I want to book a trip to
  Spain" makes a starter checklist), and when it is done Nova says one short line through `Connection.say` (`NOVA_BUILD_COMMENT=0` turns that off).
  Known: she sometimes says the canvas line for a bare idea (harmless now, the builder puts a starter widget up); a long prompt (~800 words) dilutes the examples.
  Tested: builder alone on a Spain conversation (starter list, then plan, packing list). The full spoken flow was verified before the final tweaks; the last
  runs were disturbed by a second client (an `Orb.app` copy of the desktop app launched from another session attached to the orchestrator and took llama's second slot).
- **Verified by voice:** `python3 backend/creator_client.py` (orb app quit, one orchestrator) speaks pasta → "make it for six" → timer → chat → "I'm done" through
  the real voice path (real ASR, real builder). Recipe + ingredients appear, six rescales them (`builder.servings_fix`, because the 2B often resends the old
  numbers), the timer starts, chat builds nothing, "I'm done" clears (`CLEAR_RE`, no model call).
- Builder lessons: examples sent as chat history work, but an example that EQUALS a likely request makes the model say it's already done (prose);
  keep examples about other things (banana bread, 25-minute timer). Spoken number words become digits first (`builder.digits`).
- Real Electron: the actual window resize, click-through while unfocused, first click on a widget, focus stealing, full-screen apps and multiple
  displays are untested (the page logic was only checked in a browser). `ORB_PANEL=1` is an untested non-activating-panel option.
- Hold-to-talk by synthetic ⌥ key events isn't seen by the key hook; use ⌥Space (hands-free toggle) for scripted tests.
- Builds take 4–20 s (swap was 4 GB of 5 GB used). The 2B is flaky on some phrasings (e.g. updates a widget that doesn't exist; "thanks, that's all" didn't clear).
- No real Claude call has been made (no key in this environment). The widget `html` contract and validation are covered by mock tests only.
- Voice-mode `hello` still sends `widgets: []` (the builder then offers every type). The mic stays open after first use (older bug, not touched).

---

## ▶ Latest (2026-11-07, afternoon): Nova can see, and asks before looking

Code is committed on `voice-orb` (last: `0f45915`). Idea doc: [docs/IDEA-vision-and-background-agents.md](docs/IDEA-vision-and-background-agents.md).

**What works (tested on the real model over text turns; real voice and the orb page path by hand: not yet):**
- **Eyes on request** (desktop orb): ⌥⇧C camera, ⌥⇧S screen, ⌥⇧A **drag an area** (frozen still, crosshair, Esc cancels), also in the orb/tray menu.
  One frame, JPEG ≤ 1.5 MB, kept in memory, sent once as a `see` message ([PROTOCOL.md](docs/PROTOCOL.md)). No disk, never stored.
- **Ask, then look** (voice mode has no tools, so it uses fixed spoken lines taught with *examples* in `VOICE_SYSTEM`):
  Nova asks "want me to take a look at your screen?", you say yes, she says "Okay, looking at your screen now." The orchestrator
  acts only on that line *after an ask* (`maybe_look` in `backend/orchestrator.py`) and sends `{type:"look", source}`; the orb takes the frame,
  and the answer uses what you originally asked. 10/10 looks fired in text tests (screen, camera, area), none on declines or small talk.
- The image is described on the chat endpoint (capped at 60 tokens), the description goes into the realtime session as text, then Nova speaks.

**Learnings worth keeping:**
- **Rules in the prompt were ignored by the 2B; examples worked.** Without examples it skipped the ask and invented what was on screen.
- **Two orchestrators on one llama-server hang the `see` call** (it needs a free slot; `-np 2`). Run exactly one orchestrator.
- **`desktopCapturer` returns empty pictures sometimes** (one screen, or both right after launch). Capture retries up to 4×, falls back to any screen.
  On this Mac, Screen 2 returned empty every time; the overlay opens on whichever screen gives a picture.
- **Latency:** look → first audio ≈ 3–5 s warm (8–9 s on the first turn after a restart). The image is no longer the main cost
  (area crop was not faster than the full screen at 768 px). The rest is the second step (realtime takes the description as text) and
  spoken replies that run 10–15 s because the model ignores "one or two sentences".
- Launching the orb from a non-Terminal shell changes which app macOS grants Camera / Screen Recording to.

**Not done / open:**
- **Camera permission was off** in macOS; turn it on for the app that launches the orb, restart the orb. Camera capture is untested.
- Real-voice test of ask-then-look, and the orb page's handling of `look`, by hand.
- The orb ignores the backend's `error` message (a rejected frame gives no feedback).
- Spoken look replies are long; time the "description → realtime" step separately.
- **Decision model (Liquid d1):** `d1-2B` / `d1-Omni-2B` answer typed questions with probabilities in one forward pass (no text). Good fit for a
  router / "escalate to Claude?" gate, but Python `transformers>=5.19` only (no official GGUF), so it can't run in llama-server; 8 GB makes a
  second model tight. Plan: test on ~50 of our utterances before adopting. Background agents: designed in the idea doc, not built.
- `ios/` in the repo is unrelated to this work; ignore it. `prototype/logs/see_test.jpg` is a generated test image.

---

## ▶ Start here (next session) — 2026-11-07, evening

**Direction change:** the canvas is parked. First the app is a **speech-to-speech agent on the Mac**: a
floating desktop orb ([desktop/](desktop/README.md)) that answers in **LFM's own voice**. Widgets come back later.

**What works now:**
- **Voice mode** in the orchestrator (`hello {mode:"voice"}`): no tools, one text + audio reply per utterance,
  audio streamed to the client as binary PCM16 24 kHz frames between `speech_start` / `speech_end`
  ([PROTOCOL.md](docs/PROTOCOL.md)). This sidesteps the old problem (audio output kills tool calls) because voice
  mode has no tools.
- Measured: first sound 0.8–1.5 s (no warm-up needed), faster than real time, streamed audio matches the text
  word for word, **interrupt ends the turn in 0.17 s** (`SessionManager.cancel()` → `response.cancel` works on llama-server).
  Details: [backend/README.md](backend/README.md#voice-mode-speech-to-speech-the-desktop-orb).
- **Desktop orb** (Electron): small (24 pt radius), hidden until you **hold Right ⌥** (global key hook,
  uiohook-napi, needs Accessibility). Talk, let go, the reply starts **0.25–0.30 s** later because the mic
  audio streams into the model *while you hold* (`SessionManager.stream_*`). Hold again to interrupt. It fades
  a few seconds after the reply; context carries over. Same model as Liquid's playground (hold, stream, release).
- Hands-free mode still exists behind `?handsfree` (`ui/src/conversation.ts`), but it's slower (0.8 s pause
  detection first). llama-server has no server-side VAD: `turn_detection` is ignored.
- `backend/voice_client.py`: headless test of all of the above.

**Not yet verified by hand:** holding the real Right ⌥ key with the real mic (the backend path was tested
with a clip streamed in real time). Needs the Accessibility permission on first run.

**Next ideas:** packaging as a real .app, then bring the canvas back as a second window driven by tool turns, with the voice loop speaking the results.

**Old learnings that still hold:** "repeat this exactly" isn't usable as TTS (it answers the line instead);
speech-only output overruns with silence. Canvas mode still uses the browser voice for `say`.

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

Desktop orb (starts the orchestrator on 8766 itself if it isn't running):

```bash
cd ~/Documents/hackathon/desktop && npm install && npm start
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
| **Desktop orb (speech to speech, LFM's own voice)** | ✅ **current focus**; headless-tested, mic round trip to verify by hand | [desktop/](desktop/README.md) |
| Canvas UI | ✅ runs the full demo against the mock (parked) | [ui/](ui/README.md) |
| Canvas ↔ real backend | ✅ **talk to it**: mic streams to the backend, the model builds widgets, the browser voice answers | §2 C |
| Escalation to Claude | ❌ stub (placeholder widget) | [backend/escalate.py](backend/escalate.py) |
| "Cloud teaches, local remembers" (saving Claude widgets) | ❌ not started | §6 |
| Camera / screen / area vision (desktop orb) | ✅ hotkeys + ask-then-look; real voice and camera not yet tested by hand | Latest block above |

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
├── desktop/                    ★ floating desktop orb (Electron), loads ui/ with ?orb
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
- [x] Play LFM's own audio (voice mode / desktop orb): streamed PCM16 24 kHz, see PROTOCOL.md.
- [x] (done in the desktop orb, see Latest) Camera: capture one frame on request (`{type:"capture"}` → JPEG back). Backend has `SessionManager.see()` ready.
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
- [x] Barge-in in voice mode (`SessionManager.cancel()`). Canvas tool turns still run to the end.
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
