"""Tests for escalate.py (cloud escalation) and the learned-widget round trip in tools.py.

    python3 backend/test_escalate.py

No pytest, no network: a mock Messages-API server runs in a thread on 127.0.0.1, and learned widgets are
written to a temp folder (tools.LEARNED_DIR is pointed there), so backend/learned/ is never touched.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import escalate  # noqa: E402
import tools  # noqa: E402


# ---------------------------------------------------------------- mock Messages API

class Mock:
    """Serves queued responses to POST /v1/messages and records what it was sent."""

    def __init__(self):
        self.queue: list[tuple[int, dict, float]] = []
        self.requests: list[dict] = []
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                mock.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                      "body": body})
                status, payload, delay = mock.queue.pop(0) if mock.queue else (418, {"error": {"message": "unexpected request"}}, 0)
                time.sleep(delay)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass  # the client gave up (timeout test)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reset(self):
        self.queue.clear()
        self.requests.clear()

    def reply_text(self, text: str, stop: str = "end_turn", delay: float = 0, thinking: bool = False):
        content = ([{"type": "thinking", "thinking": "", "signature": "x"}] if thinking else []) + \
                  [{"type": "text", "text": text}]
        self.queue.append((200, {"id": "msg_test", "type": "message", "role": "assistant", "model": "mock",
                                 "content": content, "stop_reason": stop,
                                 "usage": {"input_tokens": 1, "output_tokens": 1}}, delay))

    def reply_json(self, obj: dict, **kw):
        self.reply_text(json.dumps(obj), **kw)

    def reply_error(self, status: int, message: str = "boom"):
        self.queue.append((status, {"type": "error", "error": {"type": "api_error", "message": message}}, 0))


# ---------------------------------------------------------------- fixtures

CHART_HTML = ("<!doctype html><html><head><meta charset=utf-8><style>"
              "body{margin:0;font:15px -apple-system,system-ui,sans-serif;color:#f5f5f7}"
              "@media (prefers-color-scheme: light){body{background:#fff;color:#1c1c1e}}</style></head>"
              "<body><div id=r>Waiting for data</div><script>"
              "addEventListener('message',function(e){if(e.data&&e.data.type==='props'){"
              "document.getElementById('r').textContent=JSON.stringify(e.data.data);}});"
              "document.addEventListener('click',function(){parent.postMessage({type:'emit',name:'tap',data:{}},'*');});"
              "</script></body></html>")

NEW_WIDGET = {
    "widget": "html", "name": "Macro Planner", "description": "Daily macros as three rings with a calorie total",
    "props_doc": "data: {days: [{label, protein, carbs, fat}], goal_kcal?}", "html": CHART_HTML,
    "data": {"days": [{"label": "Mon", "protein": 120, "carbs": 200, "fat": 60}], "goal_kcal": 2200},
    "sample_data": {"days": [{"label": "Day 1", "protein": 100, "carbs": 150, "fat": 50}]},
    "height": 320, "importance": "full", "say": "Here's your macro plan.",
}

BUILTIN = {"widget": "stacked_bar", "importance": "full", "say": "Here are your macros.",
           "props": {"caption": "Macros", "categories": ["Mon", "Tue"], "series": [{"label": "Protein", "values": [100, 110]}]}}

TASK = "Plan my macros for these meals and chart it"
CANVAS = {"recipe": {"widget": "recipe", "props": {"title": "Pasta", "steps": ["Boil", "Drain"], "html": "SECRET-HTML"}}}
WIDGETS = ["recipe", "checklist", "timer", "stacked_bar", "html"]


# ---------------------------------------------------------------- tiny runner

RESULTS: list[tuple[str, bool, str]] = []
MOCK: Mock
TMP: str


def test(fn):
    def run():
        MOCK.reset()
        for f in os.listdir(TMP):
            os.remove(os.path.join(TMP, f))
        os.environ["ESCALATE_NO_SHELL_KEY"] = "1"  # never pick up the real key from the login shell
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        os.environ["ANTHROPIC_BASE_URL"] = MOCK.url
        for k in ("ESCALATE_MODEL", "ESCALATE_TIMEOUT", "ESCALATE_EFFORT"):
            os.environ.pop(k, None)
        try:
            fn()
            RESULTS.append((fn.__name__, True, ""))
            print(f"PASS  {fn.__name__}")
        except Exception:  # noqa: BLE001
            RESULTS.append((fn.__name__, False, traceback.format_exc()))
            print(f"FAIL  {fn.__name__}\n{traceback.format_exc()}")
    run.__name__ = fn.__name__
    TESTS.append(run)
    return fn


TESTS: list = []


def go(task=TASK, canvas=CANVAS, widgets=WIDGETS) -> dict:
    return asyncio.run(escalate.escalate(task, canvas, widgets))


def assert_contract(res: dict):
    assert set(res) >= {"widget", "props", "importance", "say"}, res
    assert res["importance"] in ("full", "hero", "side", "satellite"), res
    assert isinstance(res["say"], str) and res["say"], res
    assert isinstance(res["props"], dict)


def is_note_card(res: dict) -> bool:
    return res["widget"] == "html" and "<!doctype html>" in res["props"]["html"] and "data" not in res["props"]


def learned_files() -> list[str]:
    return sorted(f for f in os.listdir(TMP) if f.endswith(".json"))


# ---------------------------------------------------------------- escalate: the five mock cases

@test
def a_builtin_widget():
    MOCK.reply_json(BUILTIN, thinking=True)  # a thinking block next to the text must be ignored
    res = go()
    assert_contract(res)
    assert res["widget"] == "stacked_bar" and res["importance"] == "full", res
    assert res["props"] == BUILTIN["props"] and res["say"] == "Here are your macros."
    assert len(MOCK.requests) == 1
    r = MOCK.requests[0]
    assert r["path"] == "/v1/messages", r["path"]
    assert r["headers"]["x-api-key"] == "test-key" and r["headers"]["anthropic-version"] == "2023-06-01"
    b = r["body"]
    assert b["model"] == "claude-sonnet-5-5" and b["max_tokens"] > 1000
    assert "temperature" not in b and "top_p" not in b  # rejected by newer models
    assert b["messages"][-1]["role"] == "user" and "prefill" not in json.dumps(b)
    prompt = b["messages"][0]["content"]
    assert TASK in prompt and "stacked_bar:" in prompt and "Pasta" in prompt  # task, widget docs, canvas state
    assert "SECRET-HTML" not in prompt, "html props must not be sent as canvas state"
    assert "emit" in b["system"] and "props" in b["system"]
    assert learned_files() == [], "a built-in widget must not be saved"


@test
def b_new_html_widget_in_code_fence_is_saved():
    MOCK.reply_text("Sure, here you go:\n```json\n" + json.dumps(NEW_WIDGET) + "\n```\nHope it helps!")
    res = go()
    assert_contract(res)
    assert res["widget"] == "html" and res["importance"] == "full"
    assert res["props"]["html"] == CHART_HTML
    assert res["props"]["data"] == NEW_WIDGET["data"], "the shown widget gets this request's data"
    assert res["props"]["height"] == 320
    assert learned_files() == ["macro_planner.json"], learned_files()
    with open(os.path.join(TMP, "macro_planner.json")) as f:
        spec = json.load(f)
    assert set(spec) >= {"name", "description", "props_doc", "html", "sample_data", "created"}, spec
    assert spec["name"] == "macro_planner" and spec["html"] == CHART_HTML
    assert spec["description"] == NEW_WIDGET["description"] and spec["props_doc"] == NEW_WIDGET["props_doc"]
    assert spec["sample_data"] == NEW_WIDGET["sample_data"] and spec["created"].endswith("+00:00")
    # the local model can use it right away
    assert "learned_macro_planner" in tools.all_widget_types()


@test
def c_external_url_is_rejected_and_retried_once():
    bad = {**NEW_WIDGET, "name": "bad_one",
           "html": CHART_HTML.replace("<script>", "<script src=\"https://cdn.example.com/chart.js\"></script><script>", 1)}
    MOCK.reply_json(bad)
    MOCK.reply_json({**NEW_WIDGET, "name": "good_one"})
    res = go()
    assert_contract(res)
    assert len(MOCK.requests) == 2, f"expected one retry, got {len(MOCK.requests)} requests"
    msgs = MOCK.requests[1]["body"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"], msgs
    assert "rejected" in msgs[2]["content"] and "<script src>" in msgs[2]["content"]
    assert res["widget"] == "html" and res["props"]["html"] == CHART_HTML
    assert learned_files() == ["good_one.json"], "only the corrected widget may be saved"

    # still bad after the fix: a plain card, nothing saved, no third request
    MOCK.reset()
    ext = {**NEW_WIDGET, "html": CHART_HTML.replace("<body>", "<body><img src=\"http://evil.example/x.png\">")}
    MOCK.reply_json(ext)
    MOCK.reply_json(ext)
    res = go()
    assert_contract(res)
    assert len(MOCK.requests) == 2
    assert is_note_card(res) and "external URL" in res["props"]["html"], res
    assert learned_files() == ["good_one.json"]


@test
def d_529_then_success():
    escalate.RETRY_DELAY = 0
    MOCK.reply_error(529, "Overloaded")
    MOCK.reply_json(BUILTIN)
    res = go()
    assert len(MOCK.requests) == 2, len(MOCK.requests)
    assert res["widget"] == "stacked_bar", res
    # 429 as well, but only one retry: a second 5xx ends in a card, not a loop
    MOCK.reset()
    MOCK.reply_error(429, "slow down")
    MOCK.reply_error(500, "still down")
    res = go()
    assert len(MOCK.requests) == 2 and is_note_card(res) and "HTTP 500" in res["props"]["html"], res
    assert_contract(res)


@test
def e_garbage_answer():
    MOCK.reply_text("I'm sorry, I can't build that.")
    MOCK.reply_text("{not json at all")
    res = go()
    assert_contract(res)
    assert len(MOCK.requests) == 2, "garbage gets one fix request"
    assert is_note_card(res) and "no JSON object" in res["props"]["html"], res
    # garbage first, valid after the fix request
    MOCK.reset()
    MOCK.reply_text("Let me think about that...")
    MOCK.reply_json(BUILTIN)
    res = go()
    assert len(MOCK.requests) == 2 and res["widget"] == "stacked_bar"
    # an unknown widget type and a truncated answer are rejected the same way
    MOCK.reset()
    MOCK.reply_json({"widget": "hologram", "props": {}})
    MOCK.reply_text('{"widget": "html", "html": "<!doctype html><p>cut', stop="max_tokens")
    res = go()
    assert is_note_card(res) and "cut off" in res["props"]["html"], res


# ---------------------------------------------------------------- escalate: other behaviour

@test
def f_no_api_key():
    os.environ.pop("ANTHROPIC_API_KEY")
    res = go()
    assert_contract(res)
    assert is_note_card(res) and "ANTHROPIC_API_KEY" in res["props"]["html"], res
    assert "Cloud help needs ANTHROPIC_API_KEY" in res["props"]["html"]
    assert len(res["say"].split()) <= 10
    assert MOCK.requests == [], "no request without a key"


@test
def g_http_error_timeout_and_unreachable_never_raise():
    MOCK.reply_error(401, "invalid x-api-key")
    res = go()
    assert len(MOCK.requests) == 1 and is_note_card(res) and "401" in res["props"]["html"], res
    MOCK.reset()
    os.environ["ESCALATE_TIMEOUT"] = "0.3"
    MOCK.reply_json(BUILTIN, delay=1.5)
    res = go()
    assert is_note_card(res) and "longer than" in res["props"]["html"], res
    assert_contract(res)
    os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"  # nothing listens there
    res = go()
    assert is_note_card(res) and "Could not reach" in res["props"]["html"], res
    assert_contract(res)


@test
def h_does_not_block_the_event_loop():
    MOCK.reply_json(BUILTIN, delay=0.6)

    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1
        t = asyncio.create_task(ticker())
        res = await escalate.escalate(TASK, CANVAS, WIDGETS)
        t.cancel()
        return res, ticks
    res, ticks = asyncio.run(main())
    assert res["widget"] == "stacked_bar"
    assert ticks >= 15, f"the event loop only ticked {ticks} times during a 0.6 s call"


@test
def i_env_vars_model_and_effort():
    os.environ["ESCALATE_MODEL"] = "claude-opus-5-5"
    MOCK.reply_json(BUILTIN)
    go()
    b = MOCK.requests[0]["body"]
    assert b["model"] == "claude-opus-5-5" and b["output_config"] == {"effort": "medium"}
    MOCK.reset()
    os.environ["ESCALATE_EFFORT"] = "off"
    os.environ["ANTHROPIC_BASE_URL"] = MOCK.url + "/v1/"  # trailing /v1/ must not double up
    MOCK.reply_json(BUILTIN)
    go()
    assert MOCK.requests[0]["path"] == "/v1/messages" and "output_config" not in MOCK.requests[0]["body"]


@test
def j_html_validation():
    ok = escalate._html_problem
    assert ok(CHART_HTML) is None
    assert ok('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"></svg>') is None, "svg xmlns is not a request"
    for bad in ('<p>see https://example.com</p>', '<link rel=stylesheet href="//cdn.test/y.css">','<script src="a.js"></script>', "<script>fetch('/x')</script>", "<script>new XMLHttpRequest()</script>",
                "<script>new WebSocket('x')</script>", '<img src="https://x.test/a.png">',
                '<div style="background:url(//cdn.test/a.png)"></div>', "<style>@import '//x.test/a.css'</style>"):
        assert ok(bad), f"should be rejected: {bad}"
    assert ok("<p>" + "x" * 62000 + "</p>") and "too large" in ok("<p>" + "x" * 62000 + "</p>")
    assert ok("") and ok(None) and ok(123) and ok("plain text")


@test
def k_reuses_a_learned_widget():
    with open(os.path.join(TMP, "gauge.json"), "w") as f:
        json.dump({"name": "gauge", "description": "A dial", "props_doc": "value 0-100", "html": CHART_HTML,
                   "sample_data": {}, "created": "2026-11-07T00:00:00+00:00", "height": 200}, f)
    MOCK.reply_json({"widget": "learned_gauge", "props": {"value": 42}, "importance": "side", "say": "Done."})
    res = go()
    assert_contract(res)
    assert res["widget"] == "html" and res["importance"] == "side"
    assert res["props"] == {"html": CHART_HTML, "data": {"value": 42}, "height": 200}, res["props"]
    assert "learned_gauge: A dial props: value 0-100" in MOCK.requests[0]["body"]["messages"][0]["content"]
    assert learned_files() == ["gauge.json"]


# ---------------------------------------------------------------- tools.py: the learned-widget round trip

def write_learned(name="gauge", **over):
    spec = {"name": name, "description": "A dial that shows one value", "props_doc": "value (0-100), label?",
            "html": CHART_HTML, "sample_data": {"value": 50}, "created": "2026-11-07T00:00:00+00:00", **over}
    with open(os.path.join(TMP, f"{name}.json"), "w") as f:
        json.dump(spec, f)


@test
def l_learned_round_trip_through_tools():
    assert tools.all_widget_types() == list(tools.WIDGET_DOCS), "nothing learned yet"
    write_learned()  # picked up on the very next call, no restart
    types = tools.all_widget_types()
    assert types == list(tools.WIDGET_DOCS) + ["learned_gauge"], types

    # tool_defs: canvas hello lists built-ins only; learned ones are added because the canvas can draw html
    enum = tools.tool_defs(WIDGETS)[0]["parameters"]["properties"]["widget"]["enum"]
    assert enum == WIDGETS + ["learned_gauge"], enum
    assert "learned_gauge" not in tools.tool_defs(["recipe", "timer"])[0]["parameters"]["properties"]["widget"]["enum"]
    assert tools.tool_defs(types)[0]["parameters"]["properties"]["widget"]["enum"] == types  # explicit list works too
    assert "learned_gauge" in tools.tool_defs([])[0]["parameters"]["properties"]["widget"]["enum"]

    # widget_docs_text: description + props_doc, never code
    docs = tools.widget_docs_text(WIDGETS)
    assert "- learned_gauge: A dial that shows one value props: value (0-100), label?" in docs, docs
    assert "<script" not in docs and "recipe:" in docs
    assert "learned_gauge" in tools.widget_docs_text(types)
    assert "learned_gauge" not in tools.widget_docs_text(["recipe"])

    # create_widget -> an html widget message: props = {html, data, height}
    canvas: dict = {}
    msgs, result = tools.to_canvas("create_widget", {"id": "dial", "widget": "learned_gauge",
                                                     "props": {"value": 70, "label": "Protein"},
                                                     "importance": "side"}, canvas)
    assert result == {"ok": True, "id": "dial"}, result
    assert msgs == [{"type": "create", "id": "dial", "widget": "html", "importance": "side",
                     "props": {"html": CHART_HTML, "data": {"value": 70, "label": "Protein"}, "height": 280}}], msgs
    assert canvas["dial"]["widget"] == "html"

    # update_widget merges into data (and keeps html/height)
    msgs, result = tools.to_canvas("update_widget", {"id": "dial", "props": {"value": 90}}, canvas)
    assert result == {"ok": True} and msgs == [{"type": "update", "id": "dial",
                                                "props": {"data": {"value": 90, "label": "Protein"}}}], msgs
    assert canvas["dial"]["props"]["data"] == {"value": 90, "label": "Protein"}
    assert canvas["dial"]["props"]["html"] == CHART_HTML and canvas["dial"]["props"]["height"] == 280
    msgs, _ = tools.to_canvas("update_widget", {"id": "dial", "props": {"data": {"label": "Carbs"}}}, canvas)
    assert msgs[0]["props"] == {"data": {"value": 90, "label": "Carbs"}}, msgs
    # the orchestrator replaces its canvas view from canvas_state: same shape, still works
    echoed = {"dial": {"widget": "html", "props": dict(canvas["dial"]["props"])}}
    msgs, _ = tools.to_canvas("update_widget", {"id": "dial", "props": {"value": 5}}, echoed)
    assert msgs[0]["props"]["data"] == {"value": 5, "label": "Carbs"}
    # a plain built-in update is untouched
    c2 = {"t": {"widget": "timer", "props": {"label": "Pasta", "seconds": 60}}}
    msgs, _ = tools.to_canvas("update_widget", {"id": "t", "props": {"seconds": 90}}, c2)
    assert msgs == [{"type": "update", "id": "t", "props": {"seconds": 90}}] and c2["t"]["props"]["seconds"] == 90

    # saved height is used; an unsaved learned type is rejected like any unknown type
    write_learned("tall", height=444)
    msgs, _ = tools.to_canvas("create_widget", {"id": "x", "widget": "learned_tall", "props": {}, "importance": "hero"}, {})
    assert msgs[0]["props"]["height"] == 444
    msgs, result = tools.to_canvas("create_widget", {"id": "y", "widget": "learned_ghost", "props": {}}, canvas)
    assert msgs == [] and result["ok"] is False and "unknown widget type" in result["error"], result
    assert "y" not in canvas

    # re-read on every call: removing the file removes the type
    os.remove(os.path.join(TMP, "gauge.json"))
    assert "learned_gauge" not in tools.all_widget_types()
    msgs, result = tools.to_canvas("create_widget", {"id": "d2", "widget": "learned_gauge", "props": {}}, {})
    assert msgs == [] and result["ok"] is False


@test
def m_broken_learned_files_and_odd_model_output():
    with open(os.path.join(TMP, "broken.json"), "w") as f:
        f.write("{not json")
    with open(os.path.join(TMP, "nohtml.json"), "w") as f:
        json.dump({"name": "nohtml", "description": "x"}, f)
    write_learned("fine")
    assert tools.all_widget_types()[-1:] == ["learned_fine"] and len(tools.load_learned()) == 1
    # to_canvas never raises on odd output
    canvas = {"w": {"widget": "recipe"}}  # no props at all
    odd = [("create_widget", None), ("create_widget", {"widget": ["x"], "props": 3}), ("create_widget", {"widget": {}}),
           ("create_widget", {"id": 5, "widget": "learned_fine", "props": [1], "importance": 9}),
           ("update_widget", {"id": ["a"], "props": 1}), ("update_widget", {"id": "w", "props": {"title": "T"}}),
           ("update_widget", {"id": "w", "props": None}), ("remove_widget", {"id": {}}), ("remove_widget", "w"),
           ("start_timer", {"minutes": float("inf")}), ("start_timer", {"minutes": "x", "label": 3}),
           ("start_timer", {"minutes": 1, "label": ["a"]}), ("say", {"text": 5}), ("say", None),
           ("clear_canvas", 7), (None, None), (["x"], {}), ("escalate", {"task": 1})]
    for name, args in odd:
        msgs, result = tools.to_canvas(name, args, canvas)
        assert isinstance(msgs, list) and isinstance(result, dict) and "ok" in result, (name, args, result)


def main() -> int:
    global MOCK, TMP
    MOCK = Mock()
    TMP = tempfile.mkdtemp(prefix="learned_test_")
    tools.LEARNED_DIR = TMP
    escalate.RETRY_DELAY = 0
    os.environ["ORCH_LOG"] = "0"
    real_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "learned")
    before = sorted(os.listdir(real_dir)) if os.path.isdir(real_dir) else []
    try:
        for run in TESTS:
            run()
    finally:
        MOCK.server.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)
    after = sorted(os.listdir(real_dir)) if os.path.isdir(real_dir) else []
    if before != after:
        RESULTS.append(("backend/learned untouched", False, f"{before} -> {after}"))
        print(f"FAIL  backend/learned was modified: {before} -> {after}")
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed" + (f", FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
