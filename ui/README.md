# Orb canvas

The screen of the app: one orb on black, and widgets that form around what you say.
Vite + React + TypeScript, no UI libraries. Message format: [../docs/PROTOCOL.md](../docs/PROTOCOL.md).

## Run the demo (no backend needed)

```bash
npm install
npm run demo
```

Open http://localhost:5173 and **hold the orb (or Space), then let go**. Each release plays the next
line of the demo script from `mock/server.mjs`:

1. "I'm cooking pasta for four"
2. "Make it for six, and start a ten-minute timer"
3. "I'm done"
4. "Plan my macros… and chart it" (slow, cloud-style work)
5. "Same for next week" (instant)
6. "That's all"

URL options: `?mute` (no speech), `?tint` (orb turns cool blue during cloud work), `?ws=ws://host:port/path`.

## Connecting the real orchestrator

Serve a WebSocket at `ws://localhost:8765/canvas` that speaks the protocol, then stop the mock.
The canvas reconnects on its own. The orb dims while no backend is connected.

## Layout of the code

| File | Job |
|---|---|
| `src/useCanvas.ts` | WebSocket + canvas state (the source of truth, sent back as `canvas_state`) |
| `src/layout.ts` | Places widgets from `importance`. The model never sends coordinates. |
| `src/Orb.tsx` | The glass orb: idle, listening, thinking, working, speaking. Hold to talk. |
| `src/WidgetFrame.tsx` | Grows cards out of the orb and pulls them back in |
| `src/widgets/` | Built-in widgets + the sandboxed `html` widget for generated ones |
| `src/voice.ts` | Speech output (browser voice for now, LFM audio later) |
| `mock/server.mjs` | Fake orchestrator that replays the demo |

## Not done yet

- Microphone audio isn't streamed to the backend yet. The mic is only used to animate the orb.
- Speech uses the browser's voice. LFM's own audio will replace it in `voice.ts`.
