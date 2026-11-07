"""Canvas tools for the local model, and how each call becomes canvas messages (docs/PROTOCOL.md)."""
from __future__ import annotations

import re

# Descriptions only; the model never sees widget code. Keep in sync with docs/PROTOCOL.md.
WIDGET_DOCS = {
    "recipe": "props: title, meta? (e.g. \"25 min\"), servings? (number), steps (list of strings)",
    "checklist": "props: title?, items: [{id, label, detail?, checked?}]  (use for ingredients, to-dos)",
    "timer": "props: label, seconds",
    "stacked_bar": "props: caption, categories (x labels), series [{label, values}], headline? {value, unit?}, "
                   "legend? [{label, value}], goal? {value, label?}, max?",
    "html": "props: html (a full HTML document), data?, height?  (generated widgets; prefer built-ins)",
}
IMPORTANCE = ["hero", "side", "satellite", "full"]


def tool_defs(widgets: list[str]) -> list[dict]:
    """Tool list for the realtime session, limited to the widget types the canvas said it can draw."""
    widgets = [w for w in widgets if w in WIDGET_DOCS] or list(WIDGET_DOCS)
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
    return "\n".join(f"- {w}: {WIDGET_DOCS[w]}" for w in widgets if w in WIDGET_DOCS)


def _slug(s: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s or fallback


def to_canvas(name: str, args: dict, canvas: dict) -> tuple[list[dict], dict]:
    """Map one tool call to canvas messages. Returns (messages, tool_result_for_the_model).

    `canvas` is the orchestrator's view {id: {widget, props}}; it is updated here so later
    calls in the same turn see the change before the canvas echoes canvas_state.
    """
    if name == "create_widget":
        wid = _slug(args.get("id"), _slug(args.get("widget"), "widget"))
        widget = args.get("widget")
        if widget not in WIDGET_DOCS:
            return [], {"ok": False, "error": f"unknown widget type {widget!r}"}
        importance = args.get("importance") if args.get("importance") in IMPORTANCE else "hero"
        props = args.get("props") if isinstance(args.get("props"), dict) else {}
        canvas[wid] = {"widget": widget, "props": props}
        return [{"type": "create", "id": wid, "widget": widget, "props": props, "importance": importance}], \
            {"ok": True, "id": wid}

    if name == "update_widget":
        wid = args.get("id")
        if wid not in canvas:
            return [], {"ok": False, "error": f"no widget {wid!r}; on canvas: {list(canvas)}"}
        props = args.get("props") if isinstance(args.get("props"), dict) else {}
        canvas[wid]["props"] = {**canvas[wid]["props"], **props}
        return [{"type": "update", "id": wid, "props": props}], {"ok": True}

    if name == "remove_widget":
        wid = args.get("id")
        if wid not in canvas:
            return [], {"ok": False, "error": f"no widget {wid!r}"}
        del canvas[wid]
        return [{"type": "remove", "id": wid}], {"ok": True}

    if name == "clear_canvas":
        canvas.clear()
        return [{"type": "clear"}], {"ok": True}

    if name == "start_timer":
        try:
            seconds = max(1, round(float(args.get("minutes", 0)) * 60))
        except (TypeError, ValueError):
            return [], {"ok": False, "error": "minutes must be a number"}
        label = (args.get("label") or "Timer").strip()
        wid = "timer" if "timer" not in canvas or canvas["timer"]["props"].get("label") == label \
            else f"timer_{_slug(label, 'x')}"
        canvas[wid] = {"widget": "timer", "props": {"label": label, "seconds": seconds}}
        return [{"type": "create", "id": wid, "widget": "timer", "importance": "satellite",
                 "props": {"label": label, "seconds": seconds}}], {"ok": True, "id": wid}

    if name == "say":
        text = (args.get("text") or "").strip()
        return ([{"type": "say", "text": text}] if text else []), {"ok": True}

    return [], {"ok": False, "error": f"unknown tool {name!r}"}
