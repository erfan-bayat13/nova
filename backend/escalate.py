"""Escalation to the cloud model (Claude). STUB — see HANDOFF.md "Backend open items".

Contract the orchestrator relies on:
    result = await escalate(task, canvas, widgets)
    result = {"widget": <built-in type or "html">, "props": {...}, "importance": "full"|"hero"|..., "say": "short line"}

The orchestrator already handles the UX around it: `pending` card + orb `working` right away,
then `create` with the same id + `say` when this returns, and orb `idle`.

To make it real:
  1. Call the Claude API with the task, the compact canvas state and the widget docs
     (tools.WIDGET_DOCS). Ask for JSON in the shape above. Prefer a built-in widget; use `html`
     (a full document, see docs/PROTOCOL.md) only for a new kind of widget.
  2. Save new `html` widgets (e.g. backend/learned/<name>.html + a one-line description) and add
     them to the local model's widget docs, so next time the local model can `create` it itself.
     That's the "the cloud teaches, the local model remembers" step from docs/CONCEPT.md.
"""
from __future__ import annotations

import asyncio, html


async def escalate(task: str, canvas: dict, widgets: list[str]) -> dict:
    await asyncio.sleep(1.5)  # stands in for the cloud call so the pending/working UX is visible
    doc = ("<!doctype html><meta charset=utf-8><body style=\"font:15px -apple-system,system-ui;margin:16px;"
           "color:#1c1c1e\"><b>Cloud task</b><p>" + html.escape(task) + "</p>"
           "<p style=\"color:#8e8e93\">Escalation is stubbed (backend/escalate.py).</p></body>")
    return {"widget": "html", "props": {"html": doc, "height": 160}, "importance": "full",
            "say": "Here's what I've got."}
