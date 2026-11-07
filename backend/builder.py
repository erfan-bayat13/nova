"""Creator mode builder: the prompt and the message list that turn one spoken request into canvas tool calls.

The orchestrator (Connection.build) sends these to llama-server's chat endpoint. The voice session never sees
tools (audio replies and tool calls don't mix), so building runs separately, behind Nova's spoken answer.

The 2B model ignores rules but follows examples, so the system prompt is short and most of the teaching is a
few worked examples sent as real message history (user -> tool calls -> results). They are constant, so
llama-server's prompt cache covers them after the first build.
"""
from __future__ import annotations

import json
import re

import tools

SYSTEM = """You are the hands of a voice assistant. The user just asked for something on their canvas. Do it with tool calls only and never reply with prose.
- Cooking or making food: create a recipe (id "recipe") AND an ingredients checklist (id "ingredients"); start a timer only if they mention a time.
- Timers: start_timer. Things to tick off (to-dos, packing, shopping): checklist. Plain lists: list. A number to watch: stat, counter or progress. Comparisons or data: table or stacked_bar. A few lines of text: note.
- importance: hero for the main thing, side for supporting info, satellite for small urgent things (timers), full for wide charts.
- To change what is already shown, call update_widget with the same id instead of creating a duplicate; when a change affects several widgets (servings change the recipe AND the ingredients) update each of them.
- When the user changes servings or amounts, set the new `servings` and the new title AND rescale every ingredient quantity to match (never resend the old numbers).
- remove_widget for one thing, clear_canvas when they are done.
- Only call escalate for big jobs (multi-day plans, computed charts, research, a kind of widget you don't have). Never for simple requests.
- The assistant has already told the user you are putting it on the canvas, so always put something useful there. For a trip or project they have only just mentioned, make a short starter checklist (the next steps, e.g. flights, hotel, things to see) titled after it.
- If the request is only a question with no use for the canvas, call no tools.
Widgets you can create:
{widgets}"""

_RECIPE = {"title": "Banana bread", "servings": 6, "meta": "1 hr",
           "steps": ["Mash three ripe bananas.", "Mix in the butter, sugar, egg and flour.", "Bake at 175 C for 50 minutes."]}
_ING = {"title": "Ingredients", "items": [{"id": "bananas", "label": "Bananas", "detail": "3 ripe"},
                                            {"id": "flour", "label": "Flour", "detail": "250 g"},
                                            {"id": "sugar", "label": "Sugar", "detail": "100 g"}]}
_NOTE = "(On the canvas now, for reference only, never read this out: recipe (recipe): {\"title\": \"Banana bread\", \"servings\": 6}; ingredients (checklist): {\"title\": \"Ingredients\"})"


def _tc(i: int, name: str, args: dict) -> dict:
    return {"id": f"ex{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _example(user: str, calls: list[tuple[str, dict]]) -> list[dict]:
    out = [{"role": "user", "content": user},
           {"role": "assistant", "content": "", "tool_calls": [_tc(i, n, a) for i, (n, a) in enumerate(calls)]}]
    out += [{"role": "tool", "tool_call_id": f"ex{i}", "content": '{"ok": true}'} for i in range(len(calls))]
    out.append({"role": "assistant", "content": ""})  # a quiet close: no prose to imitate
    return out


FEWSHOT: list[dict] = (
    _example("I'm baking banana bread this afternoon.", [
        ("create_widget", {"id": "recipe", "widget": "recipe", "props": _RECIPE, "importance": "hero"}),
        ("create_widget", {"id": "ingredients", "widget": "checklist", "props": _ING, "importance": "side"})])
    + _example(f"Make it for twelve.\n\n{_NOTE}", [
        ("update_widget", {"id": "recipe", "props": {"title": "Banana bread for 12", "servings": 12}}),
        ("update_widget", {"id": "ingredients", "props": {"items": [
            {"id": "bananas", "label": "Bananas", "detail": "6 ripe"},
            {"id": "flour", "label": "Flour", "detail": "500 g"},
            {"id": "sugar", "label": "Sugar", "detail": "200 g"}]}})])
    + _example("Set a 25 minute timer.", [("start_timer", {"minutes": 25, "label": "Timer"})])
    + _example(f"All finished, thank you.\n\n{_NOTE}", [("clear_canvas", {})])
)


_NUMBERS = {w: str(i) for i, w in enumerate(
    "two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split(), 2)}
_NUMBERS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60", "ninety": "90", "a hundred": "100"})
_NUM_RE = re.compile(r"\b(" + "|".join(sorted(_NUMBERS, key=len, reverse=True)) + r")\b", re.I)


def digits(text: str) -> str:
    """Spoken numbers as digits ("make it for six" -> "make it for 6"): the 2B handles digits far better than words.
    "one" is left alone (no one, one of them)."""
    text = _COMPOUND.sub(lambda m: str(_TENS[m.group(1).lower()] + _UNITS[m.group(2).lower()]), text)
    return _NUM_RE.sub(lambda m: _NUMBERS[m.group(1).lower()], text)


_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90}
_UNITS = {w: i for i, w in enumerate("one two three four five six seven eight nine".split(), 1)}
_COMPOUND = re.compile(r"\b(" + "|".join(_TENS) + r")[ -](" + "|".join(_UNITS) + r")\b", re.I)


def _servings_in(request: str) -> int | None:
    m = (re.search(r"\b(?:for|serves|serving|servings of)\s+(\d{1,3})\b(?!\s*(?:minutes?|mins?|hours?|seconds?|secs?))", request, re.I)
         or re.search(r"\b(\d{1,3})\s+(?:people|persons|servings|portions|guests|slices)\b", request, re.I))
    return int(m.group(1)) if m else None


def _scale_detail(detail: str, f: float) -> str:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)(?:/(\d+))?(.*)$", detail or "")
    if not m:
        return detail
    n = float(m.group(1)) / (float(m.group(2)) if m.group(2) else 1)
    v = round(n * f, 2)
    return (str(int(v)) if v == int(v) else f"{v:g}") + m.group(3)


def servings_fix(request: str, before: dict, after: dict) -> list[tuple[str, dict]]:
    """The 2B sometimes answers "make it for six" with updates that still say four. When the request names a new
    number of servings and the recipe's `servings` did not change, set it, fix the number in the title, and scale
    every ingredient quantity the model left as it was. Returns update_widget calls (empty when nothing to fix)."""
    n = _servings_in(request)
    old = (before.get("recipe") or {}).get("props", {}).get("servings")
    cur = (after.get("recipe") or {}).get("props", {}).get("servings")
    try:
        old, cur = float(old), float(cur)
    except (TypeError, ValueError):
        return []
    if n is None or n <= 0 or old <= 0 or cur != old or n == old:
        return []
    f = n / old
    title = (after["recipe"]["props"].get("title") or "")
    calls = [("update_widget", {"id": "recipe", "props": {
        "servings": n, "title": re.sub(rf"\b{int(old)}\b", str(n), title) if title else title}})]
    ing, was = after.get("ingredients"), (before.get("ingredients") or {}).get("props", {}).get("items") or []
    if ing and isinstance(ing["props"].get("items"), list):
        old_detail = {i.get("id") or i.get("label"): i.get("detail") for i in was if isinstance(i, dict)}
        items = []
        for it in ing["props"]["items"]:
            if not isinstance(it, dict):
                items.append(it)
                continue
            key = it.get("id") or it.get("label")
            if it.get("detail") and old_detail.get(key) == it.get("detail"):  # the model left the old quantity
                it = {**it, "detail": _scale_detail(it["detail"], f)}
            items.append(it)
        calls.append(("update_widget", {"id": "ingredients", "props": {"items": items}}))
    return calls


def tool_list(types: list[str]) -> list[dict]:
    """Canvas tools in the chat API's format. No `say`: Nova already answered out loud."""
    return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
            for t in tools.tool_defs(types) if t["name"] != "say"]


def conversation_note(dialogue: list[tuple[str, str]], request: str, max_chars: int = 220) -> str:
    """The last few lines of the chat, so a request like "June, ten days, cities and food" still knows it is about Spain.
    Nova's canvas lines are dropped and the current request (the last user line) is left out."""
    lines = list(dialogue)
    if lines and lines[-1][0] == "user":
        lines.pop()
    out = []
    for role, text in lines[-4:]:
        text = re.sub(r"Okay, (putting that on|clearing) the canvas\.?\s*", "", text).strip()
        if text:
            out.append(f"{'User' if role == 'user' else 'Nova'}: {text[:max_chars]}")
    return ("(Earlier in this conversation, only for context, already handled: " + " | ".join(out) + ")") if out else ""


_SELF_CONTAINED_RE = re.compile(r"\b(cook|cooking|make|making|bake|baking|timer|recipe|list|note|chart|track|table|plan)\b", re.I)


def messages(request: str, canvas_note: str, types: list[str], convo_note: str = "") -> list[dict]:
    """System prompt + worked examples + the request (with the chat so far and what is on the canvas, if anything).
    The chat is only added to short requests that lean on it ("June, ten days, cities and food"): given to a
    self-contained one ("I'm cooking pasta") the 2B copied the earlier topic instead."""
    if len(request.split()) > 10 or _SELF_CONTAINED_RE.search(request):
        convo_note = ""
    user = digits(request) + (f"\n\n{convo_note}" if convo_note else "") + (f"\n\n{canvas_note}" if canvas_note else "")
    return ([{"role": "system", "content": SYSTEM.format(widgets=tools.widget_docs_text(types))}]
            + FEWSHOT + [{"role": "user", "content": user}])
