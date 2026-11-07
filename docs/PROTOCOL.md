# Canvas protocol (v1)

The canvas (`ui/`) and the orchestrator talk over one WebSocket: `ws://localhost:8765/canvas`.
Every message is one JSON object with a `type` field.

The canvas only draws what this protocol tells it to. Model text is never shown on screen: the
orchestrator drops it, and anything the system says out loud arrives as a `say` message.

## Orchestrator → canvas

| type | fields | what the canvas does |
|---|---|---|
| `orb` | `state`: `idle` \| `listening` \| `thinking` \| `working` | Sets the orb's state. `working` means a long job (e.g. Claude building a widget). |
| `say` | `text` | Speaks the text (browser speech for now). The orb shows `speaking` until it ends. The text is never displayed. |
| `pending` | `id`, `importance` | Shows an empty shimmering card where a widget is being built. A later `create` with the same `id` fills it in. |
| `create` | `id`, `widget`, `props`, `importance` | Adds a widget, growing out of the orb. If `id` already exists, it replaces its props in place. |
| `update` | `id`, `props` | Merges `props` into the widget. Changed words and numbers roll in place. |
| `remove` | `id` | The widget shrinks back into the orb. |
| `clear` | – | Removes all widgets, one after another. |

`importance` decides placement. The model never sends coordinates.

- `hero`: the main thing (a recipe). Large, left of center.
- `side`: supporting info (ingredients). Right column.
- `satellite`: small and urgent (a timer). Sits next to the orb.
- `full`: takes the whole stage width (a chart).

## Canvas → orchestrator

| type | fields | when |
|---|---|---|
| `hello` | `widgets`: list of widget types the canvas can draw | On connect |
| `orb_down` | – | The user starts holding the orb (or Space). Start listening. |
| `orb_up` | – | The user lets go. End of the utterance. |
| `event` | `id`, `name`, `data` | A widget event, e.g. `item_checked`, `timer_done` |
| `canvas_state` | `widgets`: `[{id, widget, props}]` | After any change (debounced 200 ms). This is what the model sees as the current canvas. |
| *(binary frame)* | raw **PCM16, 16 kHz, mono**, little-endian | Mic audio, sent only between `orb_down` and `orb_up`. Any chunk size works (100 ms = 3,200 bytes is a good default). The orchestrator buffers it and sends the whole utterance to the model on `orb_up`. Taps under 0.3 s are ignored. *(Implemented in `backend/orchestrator.py`; the canvas doesn't stream yet.)* |
| `text` | `text` | **Dev/testing only.** Acts as if the user said `text`. Used by `backend/test_client.py`. The real canvas never sends it. |

Speech out is still the `say` text, spoken by the browser voice. Streaming LFM's own 24 kHz audio is a
possible later change. It would add a message without changing `say`.

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
