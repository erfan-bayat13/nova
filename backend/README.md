# Backend: orchestrator

The real backend behind the canvas. It speaks [docs/PROTOCOL.md](../docs/PROTOCOL.md) on
`ws://localhost:8765/canvas` and drives the local model (LFM3-Omni-2B on llama-server) through
[`prototype/session_manager.py`](../prototype/session_manager.py).

```
canvas (ui/) ⇄ ws :8765/canvas ⇄ orchestrator.py ⇄ SessionManager ⇄ llama-server :8080 /v1/realtime
                                      └─ escalate.py (Claude API) ─ learned/*.json
```

## Run

```bash
# 1. the model server (8 GB Mac settings; see prototype/README.md)
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384
```

```bash
# 2. the orchestrator (starts llama-server itself if step 1 isn't running)
pip install -r backend/requirements.txt
python3 backend/orchestrator.py
```

```bash
# 3. the canvas, WITHOUT the mock (the mock also uses :8765)
cd ui && npm run dev
```

Talk to it from the canvas, next to the mock: run the orchestrator with `ORCH_PORT=8766`, then open
http://localhost:5173/?ws=ws://localhost:8766/canvas, hold the orb or Space, speak, let go.

Test without the UI (a fake canvas plays the demo script, one line as real speech):

```bash
ORCH_PORT=8766 python3 backend/orchestrator.py
```

```bash
ORCH_PORT=8766 python3 backend/test_client.py
```

## Voice mode (speech to speech, the desktop orb)

When the client's `hello` has `mode: "voice"` (the floating orb in [desktop/](../desktop/README.md)), there
are no tools and no widgets. Each utterance is one model reply in **text + audio**, and the audio is
streamed to the client as binary PCM16 24 kHz frames between `speech_start` and `speech_end`
(PROTOCOL.md). The voice is LFM's own. The system prompt is `VOICE_SYSTEM` (Nova, 1–3 sentences,
≤ ~80 words), and replies over 35 s of audio are cut off because quality drops past that.

Test without a mic (scripted lines, an interrupt, saves `prototype/logs/voice_<n>.wav`):

```bash
ORCH_PORT=8766 python3 backend/voice_client.py
```

In voice mode the mic audio is **streamed into the model while the user holds** (`SessionManager.stream_start /
stream_append / stream_finish / stream_clear`): `orb_down` starts an utterance, every binary frame is appended
right away, `orb_up` commits it. Release → first sound **0.25–0.30 s** (4 s utterance, every turn including
the first), vs ~0.5 s when the audio is sent at release. Silent or too-short presses are cleared
(`input_audio_buffer.clear`), and a press during a reply interrupts it first. Test:
`ORCH_PORT=8766 python3 backend/voice_client.py some_16k_mono.wav`.

Measured 2026-11-07 (M2 8 GB, warm server, text input):

| | |
|---|---|
| First sound | 0.8–1.5 s (the first turn too: the voice prompt is small, no warm-up needed) |
| Generation | faster than real time (12.6 s of speech done in 7.0 s) |
| Trailing silence | 0–0.2 s |
| Speech vs. text | ASR of the streamed audio matched the reply text word for word |
| Interrupt (`orb_down` mid-reply) | turn ends 0.17 s later; the next turn answered normally |

## Cloud escalation and learned widgets

"The cloud teaches, the local model remembers" ([docs/CONCEPT.md](../docs/CONCEPT.md)). When the local model calls
`escalate`, `escalate.py` asks Claude (plain HTTPS POST with `httpx`, async, ~60 s timeout, one retry on 429/5xx).
Claude answers with one JSON object: a built-in widget, an already learned widget, or a **new** widget as a complete
self-contained HTML document (it gets its data by `postMessage({type:'props', data})` and sends events with
`parent.postMessage({type:'emit', name, data}, '*')`, see [PROTOCOL.md](../docs/PROTOCOL.md)). The answer is checked
(html under 60 KB, no `<script src`, external URLs, `fetch(`, `XMLHttpRequest`); a bad one is sent back to Claude once,
then the result is a plain note card. Without a key the card says "Cloud help needs ANTHROPIC_API_KEY". `escalate()`
never raises and keeps its return value: `{widget, props, importance, say}`.

| Env var | Default | |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Required. Read on every call. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | A proxy or a local mock server |
| `ESCALATE_MODEL` | `claude-sonnet-5-5` | |
| `ESCALATE_TIMEOUT` | `60` | Seconds per request |
| `ESCALATE_EFFORT` | `medium` | Sent as `output_config.effort`; `off` leaves it out (models without effort) |

**`learned/`**: a new html widget is saved as `backend/learned/<name>.json`
(`{name, description, props_doc, html, sample_data, created, height?}`; committed on purpose, `.gitkeep` keeps the
folder). `tools.py` re-reads it on every call, so the widget is available from the **next session** on (no restart) as
the widget type `learned_<name>`: `all_widget_types()`, `tool_defs()` and `widget_docs_text()` include it (description
and `props_doc` only, never the code). `create_widget` of a learned type becomes an `html` widget with
`props = {html, data: <what the model passed>, height: <saved or 280>}`, and `update_widget` merges its props into `data`.
A `learned_*` type that was never saved is rejected like any unknown type. To forget a widget, delete its file.

Test (a mock Messages API on localhost, a temp folder for learned widgets, nothing leaves the machine):

```bash
python3 backend/test_escalate.py
```

## Files

| File | What |
|---|---|
| `orchestrator.py` | WebSocket server, one `Connection` per canvas: buffers mic audio, runs model turns, tool loop, orb states, events, escalation UX |
| `tools.py` | Tool definitions for the model (built from the canvas's `hello` widget list) and `to_canvas()`: tool call → canvas messages |
| `escalate.py` | The Claude path: Messages API call, answer validation, saves new widgets to `learned/`. See "Cloud escalation" below. |
| `learned/` | Widgets Claude built, one `<name>.json` each. `tools.py` re-reads the folder on every call. |
| `test_escalate.py` | Tests for `escalate.py` and the learned-widget round trip (mock Messages API, no network). |
| `test_client.py` | Fake canvas for end-to-end tests |
| `voice_client.py` | Fake desktop orb for the voice mode: timings, saved audio, interrupt test |
| `see_client.py` | Fake desktop orb for "eyes on request": sends a `see` frame (JPEG + question), checks the spoken answer and the bad-frame errors |

## How a turn works

1. `orb_down` → orb `listening`, start buffering binary PCM16 16 kHz frames.
2. `orb_up` → orb `thinking`. The audio goes to the model, plus an `(On screen now, for reference only …)` note from `canvas_state` when the screen isn't empty. With an empty screen there's no note: the model used to answer "[Canvas: empty]" instead of the user.
3. **Tool loop** (≤ 5 steps): each call is mapped to canvas messages (`create`/`update`/`remove`/`clear`, timer → `create timer`), and its result goes back to the model, which may call more tools. That lets one utterance update several widgets.
4. What it says out loud (`say`, never shown on screen):
   - **ACT turns** (it called canvas tools): one short confirmation, the first clause of its closing line, ≤ 8 words ("Pasta for four.").
   - **CHAT turns** (hello, small talk, quick facts, how-to questions, no tools): a natural reply, up to 3 sentences / 60 words.
   - **Escalation**: a fixed "Let me work that one out.", then Claude's line when the result lands.
   - If the model called the `say` tool itself, that's used. Copies of the screen note are stripped.
5. orb `idle`.

- `escalate` → `pending` card + orb `working` right away, Claude in the background, then `create` with the same id + `say`.
- `event timer_done` → `say "<label>'s done."` directly, with no model call. Other events go to the model as a short text turn.

## Measured (2026-11-07, M2 8 GB, `test_client.py`)

| Line | What happened | Time |
|---|---|---|
| "I'm cooking pasta for four." | `create recipe` + say "Pasta for four is ready!" | 6.6 s (first turn, cold prompt) |
| "Make it for six, and start a ten-minute timer." | `update recipe` + `create timer` + say | 3.4 s |
| *(voice)* "Add parmesan to the ingredients." | `create ingredients` + say | 7.3 s ⚠️ |
| timer_done event | say "Pasta's done." | instant |
| "Plan my macros … and chart it." | `pending` → orb working → `create` (stub) + say | 3.5 s + stub (measured before the real cloud call) |
| "I'm done." | `clear` + say "The canvas is cleared." | 2.3 s |

## Known issues / decisions made

- **The model rarely calls `say`.** It ends with a plain-text line instead, so we speak that line (clipped). `tool_choice: "required"` is accepted by the server but not enforced after tool results. Forcing a specific function isn't supported.
- **Spoken lines are longer than the 1–6 words the UI wants** ("Updated to six servings and a 10-minute timer."). The prompt asks for 1–6, and the orchestrator clips at 8.
- **The first turn is cold** (~5–6 s). Warm turns, voice included, take ~2 s (canvas test: "start a ten minute timer" → timer in 2.1 s). A warm-up turn at `hello` is the next step.
- **Silence is ignored:** under 0.25 s of actual speech (30 ms windows above RMS 500) is dropped. Before this gate, a silent tap produced a made-up "Grilled Chicken Skillet" recipe.
- **The model sometimes copies the `[Canvas: …]` prefix into its spoken line.** `spoken_line()` strips bracketed text.
- **First turn is slow** (~6 s): the system prompt + tool list is processed on the first message.
- **"Make it for six" updated `servings` only, not the steps or ingredients.** The tool loop allows several updates, but the model doesn't always do them. The handoff's linked-widgets decision (option c, canvas-side) is still open.
- **Barge-in works in voice mode only** (`SessionManager.cancel()` → `response.cancel`). In canvas mode `orb_down` during a turn flips the orb to listening, but the running tool turn still finishes.
