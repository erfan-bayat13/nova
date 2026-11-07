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
| **⌥⇧C** / **⌥⇧S** / **⌥⇧A**, or the menu-bar / orb menu | Nova looks: one frame from the camera / of the screen under the cursor / of a rectangle you drag on a frozen still of the screen (⌥⇧A, Esc cancels; fastest, since less of the picture is processed), sent once and dropped. A ring shows while it's captured. Holding the orb cancels a capture that hasn't gone yet. |
| Drag the orb | Moves it. |
| Right-click the orb, or the menu-bar dot | Clear canvas, Reload, DevTools, Quit. There's no Dock icon. |

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
Env: `ORB_PTT_KEY` (a uiohook key name, e.g. `MetaRight`, `CtrlRight`), `ORB_HOTKEY`, `ORCH_PORT`, `ORB_PYTHON`, `ORB_PANEL`.

The orb dims while the backend is unreachable.

### Hands-free mode (`?handsfree`)

⌥Space starts a conversation and turns are detected from pauses (`ui/src/conversation.ts`): adaptive
noise floor, onset after 90 ms, end after a 0.8 s pause, barge-in when 6 of the last 10 frames are loud,
fades after 15 s of quiet. llama-server's realtime API ignores `turn_detection` (`server_vad` reports
back `null`, no speech events), so this runs on the client. Slower (the 0.8 s pause comes first) and untuned
for real rooms. Tuning: `?pause=0.8`, `?idle=15`, `?barge=0`, `?barge_rms=1500`.

### Creator mode (canvas)

Ask for something ("I'm cooking pasta for four", "start a ten minute timer") and the orchestrator builds widgets
(the canvas messages of `docs/PROTOCOL.md`, on the same socket). The orb then opens a canvas: the window grows to the
work area of the display it is on, the orb glides to the bottom centre, and the widgets grow out of it and float
over your desktop, laid out by `ui/src/layout.ts` like the canvas page. Hold the orb or Right ⌥ as usual to talk,
interrupt or ask for changes. The window doesn't fade away while widgets exist. When the last one is gone ("I'm
done") they dissolve into the orb, it glides back to its corner and the window shrinks to exactly where it was.

- **Click-through:** while the canvas is open the window ignores the mouse everywhere except over a widget or the orb
  (`setIgnoreMouseEvents(true, {forward: true})`; the page watches the pointer and calls `orbShell.setInteractive`).
  Checklist items, the timer and the orb are clickable, the rest of your desktop is too. The orb can't be dragged
  while it is open.
- **Manual way out:** menu-bar dot or right-click the orb, **Clear canvas** (dissolves every widget, closes the canvas).
- Keyboard focus: the window is shown without activating it. Clicking a widget may still make Electron the active
  app; `ORB_PANEL=1` (macOS) makes it a non-activating panel instead. Untested, off by default.

The page side (phases, layout, glide, click-through logic) was tried in a browser against `ui/mock` with a faked
`orbShell`. The real window resize, `setIgnoreMouseEvents` forwarding and focus behaviour are not tested in Electron yet.

## Files

| File | What |
|---|---|
| `main.cjs` | The window (transparent, frameless, always on top, all Spaces), global hotkey, starts the orchestrator if needed |
| `preload.cjs` | `window.orbShell`: `moveBy`, `menu`, `hide`, `onHotkey`, `onPtt`, `onLook`, the capture calls, and for the canvas `setCanvas(open)`, `setInteractive(on)`, `onClearCanvas`. The only bridge to the page |
| `trayTemplate*.png` | The menu-bar dot |

The page is `ui/` with `?orb`: `ui/src/OrbApp.tsx` (the orb window, push to talk), `ui/src/conversation.ts`
(hands-free mode), `ui/src/voice.ts` (streamed 24 kHz playback, interrupt), `ui/src/Orb.tsx`
(appears/fades, pulses with the real voice). With widgets, `OrbApp.tsx` also draws the canvas (`WidgetFrame`, `widgets/`).

Tested 2026-11-07 with `backend/voice_client.py` (a clip streamed in real time as if held): release → first
sound 0.25–0.30 s over 6 turns; holding during a reply cut it off and answered the new question in 0.30 s;
5 press/stop pairs in a row didn't block the next turn. The hands-free mode was tested in a browser with a
recorded clip as the mic. Not yet tested by hand with the real Right ⌥ key and mic.
