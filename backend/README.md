# Backend: orchestrator

The real backend behind the canvas. It speaks [docs/PROTOCOL.md](../docs/PROTOCOL.md) on
`ws://localhost:8765/canvas` and drives the local model (LFM3-Omni-2B on llama-server) through
[`prototype/session_manager.py`](../prototype/session_manager.py).

```
canvas (ui/) ⇄ ws :8765/canvas ⇄ orchestrator.py ⇄ SessionManager ⇄ llama-server :8080 /v1/realtime
                                      └─ escalate.py (Claude, STUB)
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

## Files

| File | What |
|---|---|
| `orchestrator.py` | WebSocket server, one `Connection` per canvas: buffers mic audio, runs model turns, tool loop, orb states, events, escalation UX |
| `tools.py` | Tool definitions for the model (built from the canvas's `hello` widget list) and `to_canvas()`: tool call → canvas messages |
| `escalate.py` | **Stub** for the Claude path. Returns a placeholder `html` widget after 1.5 s. Its docstring has the contract and the plan. |
| `test_client.py` | Fake canvas for end-to-end tests |

## How a turn works

1. `orb_down` → orb `listening`, start buffering binary PCM16 16 kHz frames.
2. `orb_up` → orb `thinking`. The audio plus a compact `[Canvas: …]` line (from `canvas_state`) goes to the model.
3. **Tool loop** (≤ 5 steps): each call is mapped to canvas messages (`create`/`update`/`remove`/`clear`, timer → `create timer`), and its result goes back to the model, which may call more tools. That lets one utterance update several widgets.
4. The model's **closing line** (first sentence, ≤ 8 words) becomes `say`. If it called the `say` tool itself, that's used instead. Free text never reaches the screen.
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
| "Plan my macros … and chart it." | `pending` → orb working → `create` (stub) + say | 3.5 s + stub |
| "I'm done." | `clear` + say "The canvas is cleared." | 2.3 s |

## Known issues / decisions made

- **The model rarely calls `say`.** It ends with a plain-text line instead, so we speak that line (clipped). `tool_choice: "required"` is accepted by the server but not enforced after tool results. Forcing a specific function isn't supported.
- **Spoken lines are longer than the 1–6 words the UI wants** ("Updated to six servings and a 10-minute timer."). The prompt asks for 1–6, and the orchestrator clips at 8.
- **The first turn is cold** (~5–6 s). Warm turns, voice included, take ~2 s (canvas test: "start a ten minute timer" → timer in 2.1 s). A warm-up turn at `hello` is the next step.
- **Silence is ignored:** under 0.25 s of actual speech (30 ms windows above RMS 500) is dropped. Before this gate, a silent tap produced a made-up "Grilled Chicken Skillet" recipe.
- **The model sometimes copies the `[Canvas: …]` prefix into its spoken line.** `spoken_line()` strips bracketed text.
- **First turn is slow** (~6 s): the system prompt + tool list is processed on the first message.
- **"Make it for six" updated `servings` only, not the steps or ingredients.** The tool loop allows several updates, but the model doesn't always do them. The handoff's linked-widgets decision (option c, canvas-side) is still open.
- **No barge-in on the model side**: `orb_down` during a turn flips the orb to listening, but the running turn still finishes and its messages still arrive.
