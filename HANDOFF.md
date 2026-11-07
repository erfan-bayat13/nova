# Handoff: frontend → backend

**Date:** 2026-11-07 · **From:** frontend (canvas UI) · **To:** backend (orchestrator, harness, models)

The canvas is done enough to demo. It runs the full demo script against a fake backend today.
What's missing is the real orchestrator behind it. This doc covers what exists, what the
canvas expects from you, and what's still open on both sides.

---

## 1. Where things are

```
hackathon/
├── HANDOFF.md              ← this file
├── docs/
│   ├── CONCEPT.md          product concept, demo script, architecture (locked v1)
│   └── PROTOCOL.md         ★ the canvas ⇄ orchestrator message format. The contract.
├── ui/                     ★ the canvas (Vite + React + TypeScript)
│   ├── mock/server.mjs     fake orchestrator that replays the demo
│   └── README.md           how to run it, file map
├── prototype/              backend findings: LFM tests, session manager, router
│   ├── README.md           all measured results and limits
│   └── session_manager.py  realtime client with rotation + watchdog (use this)
└── models/                 GGUF weights, NOT in git (download, see prototype/README.md)
```

## 2. Run the canvas

```bash
cd ui
npm install
npm run demo
```

Open http://localhost:5173. **Hold the orb (or Space) and let go** to play the next demo line.
Add `?mute` to silence speech. Without a backend running, the orb dims and keeps retrying.

## 3. What the frontend decided (please keep these true)

These came out of the UI sessions with the product owner. Some of them constrain the backend.

1. **It must never look like a chat app.** No transcript, no message bubbles, no "thinking…" text.
   The screen is one orb plus widgets. Nothing else.
2. **Only tool calls reach the screen.** The orchestrator **drops all free text** from the model.
   Anything the system says out loud goes through a `say` tool → `say` message. The canvas never
   displays that text.
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

## 4. What the backend needs to build

Full spec: [docs/PROTOCOL.md](docs/PROTOCOL.md). Short version:

**Serve a WebSocket at `ws://localhost:8765/canvas`.** Stop the mock (`npm run dev` instead of
`npm run demo`) and the canvas connects to you.

### You send the canvas

| message | when |
|---|---|
| `{type:"orb", state}` | `listening` on `orb_down`, `thinking` while LFM works, `working` during a Claude escalation, `idle` when done |
| `{type:"say", text}` | Every spoken reply (from the model's `say` tool call) |
| `{type:"create", id, widget, props, importance}` | `create_widget` tool call |
| `{type:"update", id, props}` | `update_widget` tool call (props are merged) |
| `{type:"remove", id}` / `{type:"clear"}` | `remove_widget` / `clear_canvas` |
| `{type:"pending", id, importance}` | Right when escalation starts, so an empty card appears while Claude works. Send `create` with the same `id` when done. |

### The canvas sends you

| message | what to do |
|---|---|
| `hello {widgets}` | The widget types the canvas can draw. Put these (with their descriptions from PROTOCOL.md) in the local model's tool list. |
| `orb_down` / `orb_up` | Start / end of the user's utterance (push-to-talk). Commit the audio buffer on `orb_up`. |
| `event {id, name, data}` | Widget events like `item_checked`, `timer_done`. Feed them to the model as context, or handle them directly (e.g. `timer_done` → `say "Pasta's ready."`). |
| `canvas_state {widgets}` | The current canvas after every change. **This is what the model sees as the canvas.** Include it (compact) in each turn. |

### Mapping the prototype's tools onto the protocol

The prototype tests already use `create_widget`, `update_widget`, `remove_widget`, `clear_canvas`,
`start_timer`, `escalate`. Suggested mapping:

| tool call | canvas message |
|---|---|
| `create_widget(id, widget, props, importance)` | `create` |
| `update_widget(id, props)` | `update` |
| `remove_widget(id)` / `clear_canvas()` | `remove` / `clear` |
| `start_timer(minutes, label)` | `create` with `widget:"timer"`, `importance:"satellite"`, `props:{label, seconds}` |
| `say(text)` | `say` |
| `escalate(task)` | `pending` + `orb working`, then Claude's result as `create` (built-in type or `html`) |

### Built-in widgets right now

`recipe`, `checklist`, `timer`, `stacked_bar`, `html`. Props for each are in PROTOCOL.md.
`html` is the slot for **Claude-generated widgets**: a full HTML document run in a sandboxed iframe
(scripts only). It receives `{type:"props", data}` and can post back `{type:"emit", name, data}`.
That's how "the cloud teaches, the local model remembers" gets onto the screen: Claude writes the
HTML once, the backend saves it, and next time the local model just calls `create` with it.

## 5. Things from the prototype that touch the UI

From `prototype/README.md`, the ones that matter here:

- **Use text + speech, never speech-only.** Good, since we drop the text anyway.
- **Spoken replies degrade past ~80 words / 30 s.** Our replies are a few words, so fine.
- **One tool call per turn:** "make it for six" updated only the recipe, not the ingredients.
  Options: (a) the orchestrator fans one change out to linked widgets, (b) allow several
  `update`s per turn, or (c) the canvas links widgets (ingredients read `servings` from the recipe).
  **Needs a decision.** The canvas can do (c) if you prefer. Tell us.
- **Realtime takes no images.** Vision goes frame → chat endpoint → description → realtime.
  The canvas doesn't capture camera frames yet (see open items).
- **Sessions must rotate before ~6K tokens** or llama-server crashes. `session_manager.py` handles it.
  Keep `canvas_state` compact for this reason.

## 6. Open items

**Frontend (us):**
- [ ] Stream mic audio to the backend. Right now the mic only animates the orb. Proposed: PCM16 16 kHz
      chunks as binary WebSocket frames between `orb_down` and `orb_up`. **Confirm the format you want.**
- [ ] Play LFM's own audio instead of the browser voice. Proposed: `say` carries base64 PCM16 24 kHz
      chunks, or binary frames. Only `ui/src/voice.ts` changes. **Confirm the format.**
- [ ] Camera: capture one full-resolution frame on request (`{type:"capture"}` → JPEG back).
- [ ] Vision demo scene in the mock.

**Backend (you):**
- [ ] Orchestrator WebSocket at `:8765/canvas` speaking PROTOCOL.md
- [ ] Drop model free text. Speech only via `say`.
- [ ] Map tool calls → canvas messages (table above)
- [ ] Escalation path: `pending` → Claude → `create`. Save generated widgets so the local model can reuse them.
- [ ] Decide on linked widgets (section 5)

**Both:**
- [ ] Agree on the audio formats above before building them.

## 7. How to change the contract

PROTOCOL.md is the single source of truth. If you need a new message or field, change PROTOCOL.md
in the same commit as the code, and add it to `ui/mock/server.mjs` if the demo should use it.
