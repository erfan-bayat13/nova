"""Canvas tools for the local model, and how each call becomes canvas messages (docs/PROTOCOL.md)."""
from __future__ import annotations

import json
import os
import re

# Descriptions only; the model never sees widget code. Keep in sync with docs/PROTOCOL.md.
WIDGET_DOCS = {
    "recipe": "props: title, meta? (e.g. \"25 min\"), servings? (number), steps (list of strings)",
    "checklist": "props: title?, items: [{id, label, detail?, checked?}]  (use for ingredients, to-dos)",
    "timer": "props: label, seconds",
    "stacked_bar": "props: caption, categories (x labels), series [{label, values}], headline? {value, unit?}, "
                   "legend? [{label, value}], goal? {value, label?}, max?",
    "html": "props: html (a full HTML document), data?, height?  (generated widgets; prefer built-ins)",
    "note": "props: title?, text (a short paragraph; lines separated by newlines)",
    "stat": "props: label, value (a number), unit?, delta? (e.g. \"+120\"), caption?  (one big number)",
    "list": "props: title?, items (list of strings), ordered? (true = numbered)  (plain list, no checkboxes)",
    "table": "props: title?, columns (list of strings), rows (list of rows, each a list of cells)",
    "progress": "props: label, value, total? (default 100), unit?  (a progress bar, \"3 of 8\" or \"40%\")",
    "counter": "props: label, value (a number), step? (default 1)  (big number with - and + buttons)",
}
IMPORTANCE = ["hero", "side", "satellite", "full"]


# ---- learned widgets: "the cloud teaches, the local model remembers" (docs/CONCEPT.md) ----
# escalate.py saves every new html widget Claude builds as backend/learned/<name>.json. They are exposed to the
# local model as widget types `learned_<name>` and drawn with the canvas's `html` widget. The directory is re-read
# on every call, so a widget learned during one session is usable at the next one without a restart.
LEARNED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned")
LEARNED_PREFIX = "learned_"
LEARNED_HEIGHT = 280


def _slug(s, fallback: str) -> str:
    s = s if isinstance(s, str) else ("" if s is None else str(s))
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s or fallback


def load_learned() -> dict[str, dict]:
    """{"learned_<name>": spec} for every valid backend/learned/*.json (spec keys: name, description, props_doc,
    html, sample_data, created, height?). Unreadable or malformed files are skipped. Never raises."""
    out: dict[str, dict] = {}
    try:
        files = sorted(f for f in os.listdir(LEARNED_DIR) if f.endswith(".json"))
    except OSError:
        return out
    for fn in files:
        try:
            with open(os.path.join(LEARNED_DIR, fn), encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("html"), str) or not spec["html"].strip():
            continue
        name = _slug(spec.get("name"), _slug(fn[:-5], ""))
        if name:
            out[LEARNED_PREFIX + name] = {**spec, "name": name}
    return out


def learned_widget_props(spec: dict, data) -> dict:
    """Props of the canvas `html` widget that draws a learned widget with `data`."""
    try:
        height = int(spec.get("height") or LEARNED_HEIGHT)
    except (TypeError, ValueError):
        height = LEARNED_HEIGHT
    return {"html": spec["html"], "data": data if data is not None else {}, "height": max(80, min(height, 900))}


def _one_line(v, limit: int) -> str:
    s = " ".join(str(v or "").split())
    return s if len(s) <= limit else s[:limit - 3] + "..."


def learned_docs_text() -> str:
    """One line per learned widget for the local model's prompt (description + props, never code)."""
    lines = []
    for wtype, spec in load_learned().items():
        doc = _one_line(spec.get("props_doc"), 400)
        lines.append(f"- {wtype}: {_one_line(spec.get('description'), 200)}" + (f" props: {doc}" if doc else ""))
    return "\n".join(lines)


def all_widget_types() -> list[str]:
    """Every widget type the model may create right now: the built-ins plus the learned ones (re-read each call)."""
    return list(WIDGET_DOCS) + list(load_learned())


def _with_learned(widgets) -> list[str]:
    """`widgets` limited to known types. Learned types named in the list are kept; when the canvas can draw `html`,
    all learned types are added (a canvas `hello` only lists built-ins, since learned ones render as `html`)."""
    learned = load_learned()
    widgets = [w for w in (widgets or []) if isinstance(w, str) and (w in WIDGET_DOCS or w in learned)]
    if "html" in widgets:
        widgets += [w for w in learned if w not in widgets]
    return widgets


def tool_defs(widgets: list[str]) -> list[dict]:
    """Tool list for the realtime session, limited to the widget types the canvas said it can draw
    (plus the learned widgets, see above)."""
    widgets = _with_learned(widgets) or _with_learned(all_widget_types())
    return [
        {"name": "create_widget",
         "description": "Show a new widget. importance: hero = main thing, side = supporting info, "
                        "satellite = small and urgent, full = wide chart.",
         "parameters": {"type": "object", "properties": {
             "id": {"type": "string", "description": "short unique id, e.g. \"recipe\", \"ingredients\""},
             "widget": {"type": "string", "enum": widgets},
             "props": {"type": "object"},
             "importance": {"type": "string", "enum": IMPORTANCE}},
             "required": ["id", "widget", "props", "importance"]}},
        {"name": "update_widget", "description": "Change props of a widget already on the canvas (props are merged).",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}, "props": {"type": "object"}},
                        "required": ["id", "props"]}},
        {"name": "remove_widget", "description": "Remove one widget.",
         "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        {"name": "clear_canvas", "description": "Remove all widgets when the user is done.",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "start_timer", "description": "Start a countdown timer.",
         "parameters": {"type": "object", "properties": {"minutes": {"type": "number"}, "label": {"type": "string"}},
                        "required": ["minutes"]}},
        {"name": "say", "description": "Speak a very short confirmation out loud (1-6 words). Never read the screen out.",
         "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        {"name": "escalate", "description": "Hand a BIG multi-step job to the cloud expert: plans over many days or "
                                            "items, charts of computed data, a new kind of widget. Never for "
                                            "questions you can answer in a sentence.",
         "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}},
    ]


def widget_docs_text(widgets: list[str]) -> str:
    """Prompt text for the local model: one line per widget type in `widgets` (built-in or learned)."""
    learned = load_learned()
    text = "\n".join(f"- {w}: {WIDGET_DOCS[w]}" for w in widgets if isinstance(w, str) and w in WIDGET_DOCS)
    extra = learned_docs_text() if any(w in learned for w in _with_learned(widgets)) else ""
    return f"{text}\n{extra}" if text and extra else (text or extra)


def _html_update(cur: dict, props: dict) -> dict:
    """Props of an `update` for an html widget. `html` and `height` replace as usual; everything else is the
    widget's data (`data` itself, or any other key) and is merged into the current `data`."""
    new = dict(props)
    out = {k: new.pop(k) for k in ("html", "height") if k in new}
    inner = new.pop("data", None)
    old = cur.get("data") if isinstance(cur.get("data"), dict) else {}
    if inner is not None and not isinstance(inner, dict):
        if new:  # a non-object `data` plus loose keys: keep the loose keys, they are the update
            inner = None
        else:
            out["data"] = inner
            return out
    out["data"] = {**old, **(inner or {}), **new}
    return out


def to_canvas(name, args, canvas: dict) -> tuple[list[dict], dict]:
    """Map one tool call to canvas messages. Returns (messages, tool_result_for_the_model).

    `canvas` is the orchestrator's view {id: {widget, props}}; it is updated here so later
    calls in the same turn see the change before the canvas echoes canvas_state.
    Never raises: odd model output comes back as {"ok": False, "error": ...}.
    """
    try:
        return _to_canvas(name, args if isinstance(args, dict) else {}, canvas)
    except Exception as e:  # noqa: BLE001 - the model's output is untrusted; one bad call must not end the turn
        return [], {"ok": False, "error": f"bad {name!r} call: {type(e).__name__}"}


def _to_canvas(name, args: dict, canvas: dict) -> tuple[list[dict], dict]:
    if name == "create_widget":
        widget = args.get("widget")
        wid = _slug(args.get("id"), _slug(widget if isinstance(widget, str) else "", "widget"))
        learned = load_learned()
        if not isinstance(widget, str) or not (widget in WIDGET_DOCS or widget in learned):
            return [], {"ok": False, "error": f"unknown widget type {widget!r}"}
        importance = args.get("importance") if args.get("importance") in IMPORTANCE else "hero"
        props = args.get("props") if isinstance(args.get("props"), dict) else {}
        if widget in learned:  # drawn by the canvas's `html` widget: what the model passes is the widget's data
            widget, props = "html", learned_widget_props(learned[widget], props)
        canvas[wid] = {"widget": widget, "props": props}
        return [{"type": "create", "id": wid, "widget": widget, "props": props, "importance": importance}], \
            {"ok": True, "id": wid}

    if name == "update_widget":
        wid = args.get("id")
        if not isinstance(wid, str) or wid not in canvas:
            return [], {"ok": False, "error": f"no widget {wid!r}; on canvas: {list(canvas)}"}
        props = args.get("props") if isinstance(args.get("props"), dict) else {}
        cur = canvas[wid].get("props") if isinstance(canvas[wid].get("props"), dict) else {}
        if canvas[wid].get("widget") == "html" and "html" in cur:  # learned or generated widget
            props = _html_update(cur, props)
        canvas[wid]["props"] = {**cur, **props}
        return [{"type": "update", "id": wid, "props": props}], {"ok": True}

    if name == "remove_widget":
        wid = args.get("id")
        if not isinstance(wid, str) or wid not in canvas:
            return [], {"ok": False, "error": f"no widget {wid!r}"}
        del canvas[wid]
        return [{"type": "remove", "id": wid}], {"ok": True}

    if name == "clear_canvas":
        canvas.clear()
        return [{"type": "clear"}], {"ok": True}

    if name == "start_timer":
        try:
            seconds = max(1, round(float(args.get("minutes", 0)) * 60))
        except (TypeError, ValueError, OverflowError):
            return [], {"ok": False, "error": "minutes must be a number"}
        label = (args.get("label") if isinstance(args.get("label"), str) else "").strip() or "Timer"
        wid = "timer" if "timer" not in canvas or (canvas["timer"].get("props") or {}).get("label") == label \
            else f"timer_{_slug(label, 'x')}"
        canvas[wid] = {"widget": "timer", "props": {"label": label, "seconds": seconds}}
        return [{"type": "create", "id": wid, "widget": "timer", "importance": "satellite",
                 "props": {"label": label, "seconds": seconds}}], {"ok": True, "id": wid}

    if name == "say":
        text = (args.get("text") if isinstance(args.get("text"), str) else "").strip()
        return ([{"type": "say", "text": text}] if text else []), {"ok": True}

    return [], {"ok": False, "error": f"unknown tool {name!r}"}
