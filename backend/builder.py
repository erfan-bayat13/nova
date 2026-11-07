"""Creator mode builder: the prompt and the message list that turn one spoken request into canvas tool calls.

The orchestrator (Connection.build) sends these to llama-server's chat endpoint. The voice session never sees
tools (audio replies and tool calls don't mix), so building runs separately, behind Nova's spoken answer.

The 2B model ignores rules but follows examples, so the system prompt is short and most of the teaching is a
few worked examples sent as real message history (user -> tool calls -> results). They are constant, so
llama-server's prompt cache covers them after the first build.
"""
from __future__ import annotations

import json

import tools

SYSTEM = """You are the hands of a voice assistant. The user just asked for something on their canvas. Do it with tool calls only and never reply with prose.
- Cooking or making food: create a recipe (id "recipe") AND an ingredients checklist (id "ingredients"); start a timer only if they mention a time.
- Timers: start_timer. Things to tick off (to-dos, packing, shopping): checklist. Plain lists: list. A number to watch: stat, counter or progress. Comparisons or data: table or stacked_bar. A few lines of text: note.
- importance: hero for the main thing, side for supporting info, satellite for small urgent things (timers), full for wide charts.
- To change what is already shown, call update_widget with the same id instead of creating a duplicate; when a change affects several widgets (servings change the recipe AND the ingredients) update each of them.
- remove_widget for one thing, clear_canvas when they are done.
- Only call escalate for big jobs (multi-day plans, computed charts, research, a kind of widget you don't have). Never for simple requests.
- If the request needs nothing on the canvas, call no tools.
Widgets you can create:
{widgets}"""

_RECIPE = {"title": "Pasta for four", "servings": 4, "meta": "20 min",
           "steps": ["Boil salted water.", "Cook the pasta for 10 minutes.", "Drain and toss with sauce."]}
_ING = {"title": "Ingredients", "items": [{"id": "pasta", "label": "Pasta", "detail": "400 g"},
                                            {"id": "sauce", "label": "Tomato sauce", "detail": "1 jar"},
                                            {"id": "salt", "label": "Salt"}]}
_NOTE = "(On the canvas now, for reference only, never read this out: recipe (recipe): {\"title\": \"Pasta for four\", \"servings\": 4}; ingredients (checklist): {\"title\": \"Ingredients\"})"


def _tc(i: int, name: str, args: dict) -> dict:
    return {"id": f"ex{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _example(user: str, calls: list[tuple[str, dict]]) -> list[dict]:
    out = [{"role": "user", "content": user},
           {"role": "assistant", "content": "", "tool_calls": [_tc(i, n, a) for i, (n, a) in enumerate(calls)]}]
    out += [{"role": "tool", "tool_call_id": f"ex{i}", "content": '{"ok": true}'} for i in range(len(calls))]
    out.append({"role": "assistant", "content": ""})  # a quiet close: no prose to imitate
    return out


FEWSHOT: list[dict] = (
    _example("I'm cooking pasta for four.", [
        ("create_widget", {"id": "recipe", "widget": "recipe", "props": _RECIPE, "importance": "hero"}),
        ("create_widget", {"id": "ingredients", "widget": "checklist", "props": _ING, "importance": "side"})])
    + _example(f"Make it for six.\n\n{_NOTE}", [
        ("update_widget", {"id": "recipe", "props": {"title": "Pasta for six", "servings": 6}}),
        ("update_widget", {"id": "ingredients", "props": {"items": [
            {"id": "pasta", "label": "Pasta", "detail": "600 g"},
            {"id": "sauce", "label": "Tomato sauce", "detail": "1.5 jars"},
            {"id": "salt", "label": "Salt"}]}})])
    + _example("Start a ten minute timer.", [("start_timer", {"minutes": 10, "label": "Timer"})])
    + _example(f"I'm done, thanks.\n\n{_NOTE}", [("clear_canvas", {})])
    + _example("Make me a packing list for a beach trip.", [
        ("create_widget", {"id": "packing", "widget": "checklist", "importance": "hero", "props": {
            "title": "Beach trip", "items": [{"id": "1", "label": "Sunscreen"}, {"id": "2", "label": "Towel"},
                                             {"id": "3", "label": "Swimsuit"}, {"id": "4", "label": "Sunglasses"}]}})])
    + _example("Track my water, I've had three of eight glasses.", [
        ("create_widget", {"id": "water", "widget": "progress", "importance": "side",
                           "props": {"label": "Water", "value": 3, "total": 8, "unit": "glasses"}})])
)


def tool_list(types: list[str]) -> list[dict]:
    """Canvas tools in the chat API's format. No `say`: Nova already answered out loud."""
    return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
            for t in tools.tool_defs(types) if t["name"] != "say"]


def messages(request: str, canvas_note: str, types: list[str]) -> list[dict]:
    """System prompt + worked examples + the request (with what is on the canvas now, if anything)."""
    user = request + (f"\n\n{canvas_note}" if canvas_note else "")
    return ([{"role": "system", "content": SYSTEM.format(widgets=tools.widget_docs_text(types))}]
            + FEWSHOT + [{"role": "user", "content": user}])
