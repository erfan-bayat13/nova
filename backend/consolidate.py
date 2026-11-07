"""Background memory pass ("sleep-time" consolidation). See docs/MEMORY.md.

Runs off the voice path (after a session rotates, or when the connection goes idle/closes). A bigger model
reads the active facts plus a few recent turns and returns a cleaned list: duplicates merged, time-bound
facts rewritten or dropped ("going to Berlin in July" -> "went to Berlin in July 2026"), contradictions
resolved by date, speech-recognition slips fixed where the context makes them obvious.

The model is pluggable: `consolidate(store, llm=...)` takes any `llm(system, user) -> str`. The default calls
the Claude Messages API when ANTHROPIC_API_KEY is set; without a key it does nothing (the local fact list
stays as the 2B model and the supersede rule left it).
"""
from __future__ import annotations

import json, os, time, urllib.request
from datetime import date

from memory import Store

MODEL = os.environ.get("MEMORY_MODEL", "claude-haiku-5-5")
MAX_FACTS_OUT = 40

SYSTEM = """You maintain a short list of lasting facts about one user, for a voice assistant with a tiny memory.
You get today's date, the current facts (oldest first, with dates), and a few recent conversation lines.
Return ONLY JSON: {"facts": [{"text": "...", "pinned": true|false}]}.
Rules:
- Each fact: one short sentence in third person starting with "The user" (or "The user's ...").
- Merge duplicates. When two facts conflict, keep the newer one. Drop trivia and anything about the assistant.
- Keep pinned facts (the user asked for them) unless the user clearly retracted them.
- Rewrite time-bound facts relative to today's date; drop them when they no longer matter.
- Names, numbers and places may be speech-recognition errors. Fix one only when the conversation lines make
  the right spelling obvious; otherwise leave it.
- Never invent a fact. Never include sensitive inferences (health, religion, politics) the user did not state.
- At most %d facts.""" % MAX_FACTS_OUT


def claude_llm(system: str, user: str) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    body = {"model": MODEL, "max_tokens": 1500, "system": system, "messages": [{"role": "user", "content": user}]}
    req = urllib.request.Request(f"{base}/v1/messages", json.dumps(body).encode(), {
        "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return "".join(b.get("text", "") for b in json.load(r).get("content", []))


def build_prompt(store: Store, turns: int = 12) -> str:
    rows = store.db.execute("SELECT text, pinned, ts FROM facts WHERE superseded_by IS NULL ORDER BY id").fetchall()
    facts = [f'- {r["text"]}{" [pinned]" if r["pinned"] else ""} ({time.strftime("%Y-%m-%d", time.localtime(r["ts"]))})'
             for r in rows]
    recent = store.db.execute("SELECT role, text FROM turns ORDER BY id DESC LIMIT ?", (turns,)).fetchall()[::-1]
    lines = [f'{r["role"].upper()}: {r["text"]}' for r in recent]
    return (f"Today: {date.today().isoformat()}\n\nCurrent facts:\n" + "\n".join(facts) +
            "\n\nRecent conversation:\n" + "\n".join(lines))


def parse(reply: str | None) -> list[dict] | None:
    """The facts list from the model's reply, or None if it is not usable (then nothing changes)."""
    if not reply:
        return None
    start, end = reply.find("{"), reply.rfind("}")
    try:
        data = json.loads(reply[start:end + 1])
    except (ValueError, TypeError):
        return None
    out = []
    for f in data.get("facts", []) if isinstance(data, dict) else []:
        if isinstance(f, dict) and isinstance(f.get("text"), str) and f["text"].lower().startswith("the user"):
            out.append({"text": f["text"].strip(), "pinned": bool(f.get("pinned"))})
    return out[:MAX_FACTS_OUT] or None


def consolidate(store: Store, llm=claude_llm) -> bool:
    """One pass. Returns True if the fact list was rewritten. Never raises: memory keeps working without it."""
    try:
        if not store.active_facts():
            return False
        facts = parse(llm(SYSTEM, build_prompt(store)))
        if facts is None:
            return False
        store.replace_facts(facts)
        return True
    except Exception as e:  # network, bad key, bad JSON: keep what we have
        print(f"consolidate skipped: {type(e).__name__}: {e}", flush=True)
        return False
