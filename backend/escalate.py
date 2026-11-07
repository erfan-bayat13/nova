"""Escalation to the cloud model (Claude): "the cloud teaches, the local model remembers" (docs/CONCEPT.md).

Contract the orchestrator relies on (start_escalation in orchestrator.py):
    result = await escalate(task, canvas, widgets)
    result = {"widget": <built-in type or "html">, "props": {...}, "importance": "full"|"hero"|"side"|"satellite",
              "say": "short line"}
It never raises: every failure comes back as a small `html` note card with a short `say`.
The orchestrator handles the UX around it (`pending` card + orb `working`, then `create` with the same id + `say`).

What it does:
  1. Calls the Anthropic Messages API (plain HTTPS POST with httpx, no SDK; async, so the event loop is never
     blocked). The prompt has the task, the compact canvas state, the built-in widget docs (tools.WIDGET_DOCS) and
     the docs of the widgets learned so far. Claude answers with ONE JSON object: a built-in widget with props, a
     learned widget (`learned_<name>` + its data), or a NEW widget: a complete self-contained HTML document plus
     `name`, `description`, `props_doc`, `data` (this request's data) and `sample_data`.
  2. Parses defensively (code fences, text around the JSON) and validates. A bad answer (not JSON, unknown widget,
     html over 60 KB, `<script src`, external URLs, fetch/XMLHttpRequest/WebSocket) is sent back to Claude once with
     the reason; if the second try fails too, the result is a plain note card describing the failure.
  3. A NEW html widget is saved as backend/learned/<name>.json ({name, description, props_doc, html, sample_data,
     created, height?}). tools.py re-reads that folder on every call, so the local model sees it as the widget type
     `learned_<name>` from the next session on, and creates it itself, on-device, with no cloud call.

Environment (read on every call):
    ANTHROPIC_API_KEY     required. Without it the result is a card saying "Cloud help needs ANTHROPIC_API_KEY".
    ANTHROPIC_BASE_URL    default https://api.anthropic.com (a proxy or a local mock server works too)
    ESCALATE_MODEL        default claude-sonnet-5-5
    ESCALATE_TIMEOUT      seconds per request, default 60
    ESCALATE_EFFORT       output_config.effort, default medium; set to "off" to not send it (models without effort)
One retry on HTTP 429 / 5xx (529 included). Test: `python3 backend/test_escalate.py` (local mock server, no network).
"""
from __future__ import annotations

import asyncio
import html as htmllib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx

import tools

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT = 60.0
DEFAULT_EFFORT = "medium"
API_VERSION = "2023-06-01"
MAX_TOKENS = 16000
MAX_HTML_BYTES = 60 * 1024
RETRY_DELAY = 1.5  # seconds before the one retry on 429 / 5xx (the Retry-After header wins, capped at 5 s)

NO_KEY_TITLE = "Cloud help needs ANTHROPIC_API_KEY"

SYSTEM_PROMPT = """You are the cloud expert behind Nova, a voice-first canvas app. A small on-device model hands you jobs it cannot do itself: multi-step plans, calculations over many items, charts, or a kind of widget it does not have yet. You answer with ONE JSON object and nothing else: no prose, no markdown, no code fence.

Pick one of three forms.

1. A built-in widget. Prefer this whenever one fits the job.
{"widget": "<built-in type>", "props": {...}, "importance": "hero|side|satellite|full", "say": "<short line>"}

2. A learned widget that already exists (listed in the user message).
{"widget": "learned_<name>", "props": {...its data...}, "importance": "...", "say": "..."}

3. A NEW widget, only when nothing above fits. It is a complete, self-contained HTML document.
{"widget": "html", "name": "snake_case_name", "description": "one line: what it shows", "props_doc": "what its data object holds, key by key", "html": "<!doctype html>...", "data": {...the real data for this request...}, "sample_data": {...a small generic example of the same shape...}, "height": 320, "importance": "...", "say": "..."}
Make the widget reusable: name and design it for the kind of job ("macro_planner"), not for this one request. Every number, label and row comes from `data`, never hard-coded.

Rules for the html:
- It runs in a sandboxed iframe with scripts only. It receives its data with window.addEventListener('message', e => { if (e.data && e.data.type === 'props') render(e.data.data); }). That message arrives once after load and again on every update, so render() must redraw in place and cope with missing keys. Show a sensible empty state before any data arrives.
- To tell the app about a user action: parent.postMessage({type: 'emit', name: 'event_name', data: {...}}, '*').
- Inline CSS and JS only. No external requests of any kind: no <script src>, no <link>, no http(s):// URLs, no fetch, XMLHttpRequest or WebSocket, no web fonts, no remote images. Draw charts with inline SVG or <canvas>.
- Keep it small (under about 15 KB) and set "height" (pixels, 160 to 600) so the content fits without scrolling.
- Look: restrained and Apple-like. font-family -apple-system, system-ui, sans-serif; generous spacing, rounded corners, one accent colour (#0a84ff), tabular numbers, no emoji, no heavy borders or shadows, body margin 0.
- Dark first. The canvas is a dark glass card and the iframe background is transparent, so the default is a transparent page with light text (#f5f5f7, secondary rgba(235,235,245,.62)). Add @media (prefers-color-scheme: light) that gives the page its own opaque light surface with rounded corners and dark text, so it also reads on a light system.

importance: hero = the main thing (large, left), side = supporting info (right column), satellite = small and urgent, full = the whole stage width (charts).
say: one short spoken line, at most 10 words, plain text, no numbers read out."""


class _Failure(Exception):
    """A failure with a message that is safe to show on the failure card."""


def _log(msg: str) -> None:
    if os.environ.get("ORCH_LOG", "1") == "1":
        print(f"[escalate] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- result cards

def _note(title: str, body: str, say: str, task: str = "") -> dict:
    """A plain html card (used for failures and the missing key)."""
    extra = f'<p class="t">{htmllib.escape(task[:300])}</p>' if task else ""
    doc = (
        "<!doctype html><meta charset=utf-8><style>"
        "body{margin:0;padding:2px;font:15px/1.45 -apple-system,system-ui,sans-serif;color:#f5f5f7}"
        "h1{font-size:17px;font-weight:600;margin:0 0 6px}p{margin:0 0 6px;color:rgba(235,235,245,.62)}"
        ".t{font-size:13px;color:rgba(235,235,245,.38)}"
        "@media(prefers-color-scheme:light){body{padding:16px;background:#fff;border-radius:14px;color:#1c1c1e}"
        "p{color:#6c6c70}.t{color:#8e8e93}}</style>"
        f"<body><h1>{htmllib.escape(title)}</h1><p>{htmllib.escape(body)}</p>{extra}</body>"
    )
    return {"widget": "html", "props": {"html": doc, "height": 170}, "importance": "full", "say": say}


def _failure_card(reason: str, task: str) -> dict:
    return _note("The cloud couldn't help with that", reason, "The cloud didn't come through.", task)


# ---------------------------------------------------------------- the API call

def _config() -> dict:
    def num(name, default):
        try:
            v = float(os.environ.get(name, ""))
            return v if v > 0 else default
        except ValueError:
            return default

    effort = os.environ.get("ESCALATE_EFFORT")
    effort = DEFAULT_EFFORT if effort is None else effort.strip().lower()
    return {
        "key": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        "base": (os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
        "model": (os.environ.get("ESCALATE_MODEL") or DEFAULT_MODEL).strip(),
        "timeout": num("ESCALATE_TIMEOUT", DEFAULT_TIMEOUT),
        "effort": "" if effort in ("", "off", "none", "0") else effort,
    }


def _retry_delay(resp: httpx.Response) -> float:
    try:
        return max(0.0, min(5.0, float(resp.headers.get("retry-after", ""))))
    except ValueError:
        return RETRY_DELAY


def _api_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error", {})
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except (ValueError, AttributeError):
        msg = None
    return f"Claude API returned HTTP {resp.status_code}" + (f": {str(msg)[:200]}" if msg else "")


async def _call(client: httpx.AsyncClient, cfg: dict, messages: list[dict]) -> tuple[str, str | None]:
    """One Messages API request. Returns (text of the answer, stop_reason). Retries once on 429 / 5xx."""
    url = cfg["base"] + ("/messages" if cfg["base"].endswith("/v1") else "/v1/messages")
    headers = {"x-api-key": cfg["key"], "anthropic-version": API_VERSION, "content-type": "application/json"}
    body = {"model": cfg["model"], "max_tokens": MAX_TOKENS, "system": SYSTEM_PROMPT, "messages": messages}
    if cfg["effort"]:
        body["output_config"] = {"effort": cfg["effort"]}

    retried = False
    while True:
        resp = await client.post(url, headers=headers, json=body)
        if (resp.status_code == 429 or resp.status_code >= 500) and not retried:
            retried = True
            _log(f"HTTP {resp.status_code}, retrying once")
            await asyncio.sleep(_retry_delay(resp))
            continue
        if resp.status_code == 400 and "output_config" in body and re.search(r"output_config|effort", resp.text):
            del body["output_config"]  # a model that has no effort setting (ESCALATE_MODEL override)
            continue
        break
    if resp.status_code >= 400:
        raise _Failure(_api_error(resp))
    try:
        data = resp.json()
    except ValueError:
        raise _Failure("Claude API returned a response that is not JSON") from None
    blocks = data.get("content") if isinstance(data, dict) else None
    text = "".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict) and b.get("type") == "text")
    stop = data.get("stop_reason") if isinstance(data, dict) else None
    if stop == "refusal":
        raise _Failure("Claude declined this request")
    return text, stop


# ---------------------------------------------------------------- prompt

def _short(v):
    if isinstance(v, str):
        return v if len(v) <= 160 else v[:157] + "..."
    if isinstance(v, list):
        return [_short(x) for x in v[:12]] + ([f"...+{len(v) - 12} more"] if len(v) > 12 else [])
    if isinstance(v, dict):
        return {k: _short(x) for k, x in v.items() if k != "html"}
    return v


def _compact_canvas(canvas) -> str:
    items = [{"id": wid, "widget": w.get("widget"), "props": _short(w.get("props", {}))}
             for wid, w in (canvas.items() if isinstance(canvas, dict) else []) if isinstance(w, dict)]
    text = json.dumps(items, ensure_ascii=False) if items else "(empty)"
    return text if len(text) <= 5000 else text[:5000] + " ...(cut)"


def _allowed_builtins(widgets) -> list[str]:
    return [w for w in widgets or [] if isinstance(w, str) and w in tools.WIDGET_DOCS] or list(tools.WIDGET_DOCS)


def _user_prompt(task: str, canvas, allowed: list[str]) -> str:
    builtin = "\n".join(f"- {w}: {tools.WIDGET_DOCS[w]}" for w in allowed)
    learned = tools.learned_docs_text() or "(none yet)"
    return (
        f"TASK (from the user, handed over by the on-device model):\n{str(task).strip()[:4000]}\n\n"
        f"ON THE CANVAS NOW (compact):\n{_compact_canvas(canvas)}\n\n"
        f"BUILT-IN WIDGETS the canvas can draw:\n{builtin}\n\n"
        f"LEARNED WIDGETS already saved (use as \"widget\": \"learned_<name>\", \"props\" = its data):\n{learned}\n\n"
        "Reply with the single JSON object now."
    )


# ---------------------------------------------------------------- parsing and validation

def _extract_json(text: str, stop: str | None = None) -> dict:
    """The first JSON object in `text`: bare, inside a code fence, or with prose around it."""
    text = (text or "").strip()
    if not text:
        raise ValueError("the answer was cut off before it finished: make the widget much smaller"
                         if stop == "max_tokens" else "the answer was empty")
    dec = json.JSONDecoder()
    for cand in [text] + [c.strip() for c in re.findall(r"```[a-zA-Z]*\s*\n?(.*?)```", text, re.S)]:
        try:
            v = json.loads(cand)
        except ValueError:
            v = None
        if isinstance(v, dict):
            return v
        for m in list(re.finditer(r"\{", cand))[:3]:
            try:
                v, _ = dec.raw_decode(cand[m.start():])
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
    if stop == "max_tokens":
        raise ValueError("the answer was cut off before the JSON finished: make the widget much smaller")
    raise ValueError("no JSON object found in the answer")


_FORBIDDEN = [
    (re.compile(r"<script\b[^>]*\bsrc\s*=", re.I), "<script src> is not allowed"),
    (re.compile(r"\bfetch\s*\(", re.I), "fetch( is not allowed"),
    (re.compile(r"XMLHttpRequest", re.I), "XMLHttpRequest is not allowed"),
    (re.compile(r"\bWebSocket\b|\bEventSource\b|\bsendBeacon\b", re.I), "network APIs are not allowed"),
    (re.compile(r"https?://[^\s\"'<>)]*", re.I), "external URLs are not allowed"),
    (re.compile(r"""(?:\b(?:src|href|srcset|action|poster)\s*=\s*|url\(\s*|@import\s+)["']?\s*//""", re.I),
     "protocol-relative URLs are not allowed"),
]


def _html_problem(doc) -> str | None:
    """Why `doc` cannot be a widget, or None when it is fine."""
    if not isinstance(doc, str) or not doc.strip():
        return "html must be a non-empty string holding a complete HTML document"
    size = len(doc.encode("utf-8"))
    if size >= MAX_HTML_BYTES:
        return f"html is too large ({size} bytes): keep it under {MAX_HTML_BYTES} bytes"
    if "<" not in doc:
        return "html does not look like an HTML document"
    scrubbed = re.sub(r"https?://(?:www\.)?w3\.org/[^\s\"'<>)]*", "", doc, flags=re.I)  # xmlns="...svg" is fine
    for rx, why in _FORBIDDEN:
        m = rx.search(scrubbed)
        if m:
            return (f"{why} (found {m.group(0)[:60]!r}): the widget must be fully self-contained "
                    "with no external requests")
    return None


def _height(v):
    try:
        return max(120, min(int(v), 900))
    except (TypeError, ValueError):
        return None


def _check(obj: dict, allowed: list[str]) -> tuple[dict, dict | None]:
    """Validate Claude's answer. Returns (result, spec to save or None). Raises ValueError with the reason."""
    widget = obj.get("widget")
    if not isinstance(widget, str):
        raise ValueError('"widget" is missing: it must be a built-in type, "learned_<name>" or "html"')
    importance = obj.get("importance") if obj.get("importance") in tools.IMPORTANCE else "full"
    say = obj.get("say") if isinstance(obj.get("say"), str) else ""
    say = " ".join(say.split())[:140] or "Here's what I've got."

    def result(wtype, props):
        return {"widget": wtype, "props": props, "importance": importance, "say": say}

    learned = tools.load_learned()
    if widget in learned:  # an existing learned widget, drawn by the canvas's html widget
        data = obj.get("props") if isinstance(obj.get("props"), dict) else obj.get("data")
        return result("html", tools.learned_widget_props(learned[widget], data if isinstance(data, dict) else {})), None

    if widget == "html":
        if "html" not in allowed:
            raise ValueError(f'the canvas cannot draw "html" widgets: use one of {allowed}')
        inner = obj.get("props") if isinstance(obj.get("props"), dict) else {}
        doc = obj.get("html", inner.get("html"))
        problem = _html_problem(doc)
        if problem:
            raise ValueError(problem)
        sample = obj.get("sample_data")
        data = obj.get("data", inner.get("data", sample))
        data = data if data is not None else {}
        height = _height(obj.get("height", inner.get("height")))
        name = tools._slug(re.sub(r"^learned_", "", str(obj.get("name") or "").strip().lower()), "")[:40]
        desc = " ".join(str(obj.get("description") or "").split())
        spec = None
        if name and desc:
            spec = {"name": name, "description": desc, "props_doc": str(obj.get("props_doc") or "").strip(),
                    "html": doc, "sample_data": sample if sample is not None else {}}
            if height:
                spec["height"] = height
        else:
            _log("new html widget has no name/description: shown, but not saved")
        return result("html", tools.learned_widget_props({"html": doc, "height": height}, data)), spec

    if widget in allowed:
        if not isinstance(obj.get("props"), dict):
            raise ValueError(f'"props" must be an object with the props of the {widget} widget')
        return result(widget, obj["props"]), None

    raise ValueError(f"unknown widget {widget!r}: use one of {allowed}, a learned_<name> widget, or \"html\"")


def save_learned(spec: dict) -> str:
    """Write backend/learned/<name>.json (atomically: tools.py may be reading the folder at the same time)."""
    os.makedirs(tools.LEARNED_DIR, exist_ok=True)
    path = os.path.join(tools.LEARNED_DIR, spec["name"] + ".json")
    full = {**spec, "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- entry point

async def _run(cfg: dict, task: str, canvas, widgets) -> dict:
    allowed = _allowed_builtins(widgets)
    messages = [{"role": "user", "content": _user_prompt(task, canvas, allowed)}]
    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        text, stop = await _call(client, cfg, messages)
        for attempt in (1, 2):
            try:
                result, spec = _check(_extract_json(text, stop), allowed)
                break
            except ValueError as e:
                if attempt == 2:
                    raise _Failure(f"Claude's answer could not be used: {e}") from None
                _log(f"answer rejected ({e}); asking Claude to fix it once")
                messages += [
                    {"role": "assistant", "content": text or "(no answer)"},
                    {"role": "user", "content": f"That answer was rejected: {e}.\n"
                                                "Reply again with the complete corrected JSON object only."},
                ]
                text, stop = await _call(client, cfg, messages)
    if spec:
        try:
            _log(f"learned widget saved: {save_learned(spec)}")
        except OSError as e:
            _log(f"could not save learned widget {spec['name']!r}: {e}")  # still shown, just not remembered
    return result


async def escalate(task: str, canvas: dict, widgets: list[str]) -> dict:
    t0 = time.monotonic()
    task = str(task or "").strip()
    cfg = _config()
    if not cfg["key"]:
        _log("no ANTHROPIC_API_KEY")
        return _note(NO_KEY_TITLE, "Set it in the environment of the orchestrator, then restart it.",
                     "I need a cloud key for that one.", task)
    try:
        res = await _run(cfg, task, canvas, widgets)
        _log(f"{cfg['model']} -> {res['widget']} in {time.monotonic() - t0:.1f}s")
        return res
    except _Failure as e:
        reason = str(e)
    except httpx.TimeoutException:
        reason = f"The cloud took longer than {cfg['timeout']:.0f} seconds."
    except httpx.HTTPError as e:
        reason = f"Could not reach the cloud ({type(e).__name__})."
    except Exception as e:  # noqa: BLE001 - the orchestrator must always get a card back
        reason = f"Unexpected error ({type(e).__name__})."
    _log(f"failed: {reason}")
    return _failure_card(reason, task)
