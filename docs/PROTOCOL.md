# Canvas protocol (v1)

The canvas (`ui/`) and the orchestrator talk over one WebSocket: `ws://localhost:8765/canvas`.
Every message is one JSON object with a `type` field.

The canvas only draws what this protocol tells it to. Model text is never shown on screen: the
orchestrator drops it, and anything the system says out loud arrives as a `say` message.

## Orchestrator → canvas

| type | fields | what the canvas does |
|---|---|---|
| `orb` | `state`: `idle` \| `listening` \| `thinking` \| `working` | Sets the orb's state. `working` means a long job (e.g. Claude building a widget). |
| `say` | `text` | Speaks the text with the browser's voice. The orb shows `speaking` until it ends. The text is never displayed. In voice mode it's only the fallback when a reply came back without audio. |
| `speech_start` | – | **Voice mode.** A reply in LFM's own voice starts. Binary frames follow. |
| *(binary frame)* | raw **PCM16, 24 kHz, mono**, little-endian | **Voice mode.** The reply's audio, streamed as the model makes it (any chunk size). The client plays the chunks back to back as they arrive and shows `speaking` from the first sound until the last chunk has played. |
| `speech_end` | `text` | **Voice mode.** The reply is complete. `text` is what was said, for logs and tests only, never displayed. |
| `pending` | `id`, `importance` | Shows an empty shimmering card where a widget is being built. A later `create` with the same `id` fills it in. |
| `create` | `id`, `widget`, `props`, `importance` | Adds a widget, growing out of the orb. If `id` already exists, it replaces its props in place. |
| `update` | `id`, `props` | Merges `props` into the widget. Changed words and numbers roll in place. |
| `remove` | `id` | The widget shrinks back into the orb. |
| `clear` | – | Removes all widgets, one after another. |
| `look` | `source`: `screen` \| `camera` \| `area` | **Voice mode.** Sent right after a reply (`speech_end`) in which Nova asked "want me to look?", the user said yes, and Nova announced it ("Okay, looking at your screen now."). The orb takes one frame the same way as its hotkeys (`area` = drag a rectangle) and sends it as a `see`; that `see` is answered using what the user just asked, not the default question. Nothing is sent if there was no ask first. |
| `error` | `text` | **Voice mode.** The orchestrator refused a client message (e.g. a bad `see` frame). `text` says why, in plain words. Nothing else changes: the orb state is untouched and no reply follows. |

`importance` decides placement. The model never sends coordinates.

- `hero`: the main thing (a recipe). Large, left of center.
- `side`: supporting info (ingredients). Right column.
- `satellite`: small and urgent (a timer). Sits next to the orb.
- `full`: takes the whole stage width (a chart).

## Canvas → orchestrator

| type | fields | when |
|---|---|---|
| `hello` | `widgets`: list of widget types the canvas can draw, `mode?`: `canvas` (default) \| `voice` | On connect. `voice` = speech to speech, no tools, no widgets (the floating desktop orb, `desktop/`). |
| `orb_down` | – | The user starts holding the orb (or Space). Start listening. |
| `orb_up` | – | The user lets go. End of the utterance. |
| `orb_cancel` | – | Drop the audio, no turn. Sent with `orb_down` to just stop a reply, or when a conversation ends mid-utterance. |
| `see` | `source`: `camera` \| `screen`, `image`: base64 JPEG, `question?`: string | **Voice mode, eyes on request.** The orb sends one frame (a webcam or screen capture) and optionally a question. The orchestrator describes the image with the model and answers the question (default `"What am I looking at?"`) out loud: `speech_start`, binary PCM16 24 kHz audio, `speech_end`, the same as a voice reply. `image` is raw base64 of a JPEG, **without** the `data:` prefix, at most **1.5 MB decoded** (`1,500,000` bytes). Rejected with `error` (no reply) if `image` is missing, not valid base64, or too large, or if `source` is not `camera`/`screen`, or if the client is not in voice mode. A `see` is a turn like any other: `orb_down` during it interrupts it. |

The desktop orb is push to talk (hold Right ⌥). In voice mode the orchestrator passes the mic frames to the model **as they arrive** between `orb_down` and `orb_up`, instead of buffering them, so the reply starts ~0.25 s after `orb_up`. Its optional hands-free mode detects turns itself (`ui/src/conversation.ts`) and sends the same messages. llama-server ignores the realtime `turn_detection` setting, so there is no server-side VAD.
| `event` | `id`, `name`, `data` | A widget event, e.g. `item_checked`, `timer_done` |
| `canvas_state` | `widgets`: `[{id, widget, props}]` | After any change (debounced 200 ms). This is what the model sees as the current canvas. |
| *(binary frame)* | raw **PCM16, 16 kHz, mono**, little-endian | Mic audio, sent only between `orb_down` and `orb_up`. Any chunk size works (100 ms = 3,200 bytes is a good default). The orchestrator buffers it and sends the whole utterance to the model on `orb_up`. Taps under 0.3 s are ignored. The canvas sends these from `ui/src/mic.ts` (device rate → 16 kHz, linear resampling). The orchestrator also drops utterances with under 0.25 s of actual speech, because the model invents content from silence. |
| `text` | `text` | **Dev/testing only.** Acts as if the user said `text`. Used by `backend/test_client.py`. The real canvas never sends it. |

**Interrupting:** `orb_down` while a reply is playing stops it. The client stops playback and drops
any frames still in flight; the orchestrator stops forwarding audio and cancels the model's reply
(`response.cancel`, measured: the turn ends ~0.2 s later), so the next turn starts right away.

A `see` reply is interrupted the same way: `orb_down` during the image description or the reply stops it. The image is never sent into the realtime session (it takes no images): the model describes it on its chat endpoint first, and the description goes into the conversation as text.

**Speech out by mode:** canvas mode speaks `say` lines with the browser voice (tool turns must stay
text-only: with audio output on, the model stops calling tools). Voice mode streams LFM's own voice.

## Built-in widgets

Descriptions only. The local model sees these, never the code.

### `recipe`
Props: `title`, `meta?` (e.g. "25 min"), `servings?` (number), `steps` (list of strings).

### `checklist`
Props: `title?`, `items`: `[{id, label, detail?, checked?}]`.
Events: `item_checked {item, checked}`.

### `timer`
Props: `label`, `seconds`. Changing `seconds` restarts it.
Events: `timer_done {label}`.

### `stacked_bar`
Props: `caption`, `headline? {value, unit?}`, `legend? [{label, value}]`, `categories` (x-axis labels),
`series [{label, values}]` (stacked bottom to top), `goal? {value, label?}`, `max?`.

### `html` (generated widgets)
Props: `html` (a full document), `data?`, `height?`. Runs in a sandboxed iframe with scripts only.
The canvas posts `{type: "props", data}` into it on load and on every update.
The widget can send `{type: "emit", name, data}` to the parent, which becomes an `event`.
