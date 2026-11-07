# Desktop orb

A small orb that isn't there until you talk. **Hold Right ⌥** anywhere, speak, let go. The orb appears
while you hold it, and the reply starts **~0.25 s after you let go**, in the local model's own voice. Hold
again while it talks to interrupt. It fades away a few seconds after the reply, and the conversation's
context carries over to your next press. A small dot in the menu bar shows it's running.

```
desktop/ (Electron)  →  ui/ with ?orb  ⇄  ws :8766/canvas (hello mode:"voice")  ⇄  backend/orchestrator.py  ⇄  llama-server
```

## Run

```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384
```

```bash
cd desktop && npm install && npm start
```

`npm start` builds `ui/` and opens the orb in the bottom-right corner. If nothing listens on
`ORCH_PORT` (default 8766) it starts `backend/orchestrator.py` itself (log:
`prototype/logs/orb_orchestrator.log`) and stops it on quit. The orchestrator starts llama-server if it
isn't running, but starting it yourself first is quicker to debug. macOS asks for the microphone once
("Electron would like to access the microphone").

`npm run dev` loads the page from the Vite dev server (`cd ui && npm run dev`) for live UI edits.

## Using it

| | |
|---|---|
| **Hold Right ⌥** (anywhere), talk, let go | It answers ~0.25 s after you let go. |
| Hold again while it talks | Interrupts it and listens. |
| Hold the orb, or Space when it's focused | Same as Right ⌥. |
| **⌥Space** | Fallback: press to talk, press again to send. |
| ⌥ + another key | Cancelled. That was a shortcut or a special character, not a question. |
| Drag the orb | Moves it. |
| Right-click the orb, or the menu-bar dot | Reload, DevTools, Quit. There's no Dock icon. |

**First run:** macOS asks for **Accessibility** for "Electron" (that's how it sees Right ⌥ being held and
released while you're in other apps). Allow it under System Settings → Privacy & Security → Accessibility.
Hold-to-talk turns on within ~2 s of allowing it (restart the orb if it doesn't). Until then, ⌥Space and
holding the orb work. The microphone prompt comes on the first press.

**Why it's fast:** the mic audio streams into the model *while you hold*, so at release only the commit is
left. Measured on the M2 (4 s utterance): release → first sound **0.25–0.30 s**, every turn including the
first. With all the audio sent at release it was ~0.5 s, and with hands-free pause detection ~1.4 s. Liquid's
own playground (playground.liquid.ai/talk) works the same way: hold, stream, release.

**Settings** (`ORB_URL`, e.g. `http://localhost:5173/?linger=4`): `?linger=4` (seconds the orb stays after
a reply), `?mic_warm=30` (seconds the mic stays open after use, so the next press has no startup lag;
the macOS mic indicator stays on that long), `?handsfree` (the hands-free mode instead of hold, see below).
Env: `ORB_PTT_KEY` (a uiohook key name, e.g. `MetaRight`, `CtrlRight`), `ORB_HOTKEY`, `ORCH_PORT`, `ORB_PYTHON`.

The orb dims while the backend is unreachable.

### Hands-free mode (`?handsfree`)

⌥Space starts a conversation and turns are detected from pauses (`ui/src/conversation.ts`): adaptive
noise floor, onset after 90 ms, end after a 0.8 s pause, barge-in when 6 of the last 10 frames are loud,
fades after 15 s of quiet. llama-server's realtime API ignores `turn_detection` (`server_vad` reports
back `null`, no speech events), so this runs on the client. Slower (the 0.8 s pause comes first) and untuned
for real rooms. Tuning: `?pause=0.8`, `?idle=15`, `?barge=0`, `?barge_rms=1500`.

## Files

| File | What |
|---|---|
| `main.cjs` | The window (transparent, frameless, always on top, all Spaces), global hotkey, starts the orchestrator if needed |
| `preload.cjs` | `window.orbShell`: `moveBy`, `menu`, `hide`, `onHotkey`, `onPtt`. The only bridge to the page |
| `trayTemplate*.png` | The menu-bar dot |

The page is `ui/` with `?orb`: `ui/src/OrbApp.tsx` (the orb window, push to talk), `ui/src/conversation.ts`
(hands-free mode), `ui/src/voice.ts` (streamed 24 kHz playback, interrupt), `ui/src/Orb.tsx`
(appears/fades, pulses with the real voice).

Tested 2026-11-07 with `backend/voice_client.py` (a clip streamed in real time as if held): release → first
sound 0.25–0.30 s over 6 turns; holding during a reply cut it off and answered the new question in 0.30 s;
5 press/stop pairs in a row didn't block the next turn. The hands-free mode was tested in a browser with a
recorded clip as the mic. Not yet tested by hand with the real Right ⌥ key and mic.
