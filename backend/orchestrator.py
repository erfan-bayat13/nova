"""Orchestrator: the canvas WebSocket (docs/PROTOCOL.md) in front of the local model.

    canvas (ui/) ⇄ ws://localhost:8765/canvas ⇄ this ⇄ SessionManager ⇄ llama-server /v1/realtime (LFM3-Omni-2B)
                                                 └── escalate.py (Claude, stubbed)

Run:   python3 backend/orchestrator.py            (stop the UI mock first: `npm run dev`, not `npm run demo`)
Env:   ORCH_PORT (default 8765), ORCH_LOG=1 for per-turn timings

What it does per utterance:
  orb_down → orb listening, start collecting mic audio (binary PCM16 16 kHz mono frames)
  orb_up   → orb thinking → LFM turn (audio + compact canvas state) → tool loop → canvas messages → orb idle
The model's free text never reaches the screen. Its short closing line (or a `say` call) becomes the
`say` message, which the canvas speaks and never displays. After each tool call
the model gets the result and may call more tools (≤ MAX_STEPS), so "make it for six" can update
the recipe AND the ingredients in one utterance.
"""
from __future__ import annotations

import array, asyncio, json, os, re, sys, time

from websockets.asyncio.server import serve

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "prototype"))  # session_manager.py lives with its tests

from session_manager import SessionManager, ServerWatchdog  # noqa: E402
from escalate import escalate  # noqa: E402
from tools import tool_defs, to_canvas, widget_docs_text  # noqa: E402

PORT = int(os.environ.get("ORCH_PORT", 8765))
LOG = os.environ.get("ORCH_LOG", "1") == "1"
MAX_STEPS = 5          # tool calls per utterance
MIN_AUDIO_S = 0.3      # ignore taps shorter than this
MIN_VOICED_S = 0.25    # ...and utterances with less actual speech than this (the model invents content from silence)
VOICE_RMS = 500        # PCM16 RMS above which a 30 ms window counts as speech

SYSTEM = """You are Nova, a warm, casual friend who lives in a visual canvas. Everything you write is spoken aloud.
Two kinds of turns:
1. ACT: the user is doing something a widget helps with (cooking or making food -> recipe + ingredients
   checklist; timers; lists; plans; charts), or asks to change or clear what's shown. Call the tools FIRST,
   then reply with ONE very short, warm line (1-6 words), e.g. "Pasta for four." or "Six it is. Timer's running."
   Never say you did something without calling the tool.
2. CHAT: greetings, small talk, thanks, opinions, quick facts and how-to questions ("how long does pasta take?").
   Don't call any tool, just answer naturally like a friend, in 1-3 short sentences.
Rules:
- Change the canvas only through tool calls. Never mention the canvas, widgets or brackets in what you say.
- When the user says they're done or finished, call clear_canvas.
- When something is on screen, the screen is the answer: never read widget contents out loud.
- A user message may end with "(On screen now ...)": the widgets currently shown. Use their ids to update them instead of creating duplicates. Never repeat that note.
- When a change affects several widgets (e.g. servings change recipe AND ingredients), update each of them.
- Only for big jobs (multi-day plans, calculations over many items, charts, research, a widget type you don't have) call escalate. Never escalate a quick question.
- If you didn't hear or see something, say so instead of guessing.
Widgets you can create:
{widgets}"""


def log(*a):
    if LOG:
        print(time.strftime("%H:%M:%S"), *a, flush=True)


def voiced_seconds(pcm: bytes, rate: int = 16000) -> float:
    """Seconds of 30 ms windows loud enough to be speech."""
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    win = int(rate * 0.03)
    loud = 0
    for i in range(0, len(a) - win + 1, win):
        seg = a[i:i + win]
        if (sum(x * x for x in seg) / win) ** 0.5 > VOICE_RMS:
            loud += 1
    return loud * 0.03


def strip_context_echo(text: str) -> str:
    """Remove copies of the screen note the model sometimes repeats: [Canvas: ...] or (On screen now ...)."""
    text = re.sub(r"\[[^\]]*\]?", "", text)
    return re.sub(r"\(\s*on screen now[^)]*\)?", "", text, flags=re.I)


def conversational(text: str, max_sentences: int = 3, max_words: int = 60) -> str:
    """A natural spoken reply: brackets and markdown removed, at most 3 sentences / 60 words."""
    text = strip_context_echo(text)
    text = re.sub(r"[*_#`>]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    out, n = [], 0
    for sent in re.split(r"(?<=[.!?])\s", text):
        w = len(sent.split())
        if out and (len(out) >= max_sentences or n + w > max_words):
            break
        out.append(sent)
        n += w
    return " ".join(out)


def spoken_line(text: str, max_words: int = 8) -> str:
    """First sentence of the model's closing text, at most `max_words` words. Drops [bracketed] echoes
    of the canvas context, which the model sometimes copies into its reply."""
    text = strip_context_echo(text).strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    first = first.split(":")[0].strip()  # "Here's your list: - Eggs..." -> "Here's your list"
    if first and first[-1] not in ".!?":
        first += "."
    words = first.split()
    if len(words) <= max_words:
        return first
    cut = words[:max_words]
    while cut and cut[-1].lower().strip(",;:") in _DANGLING:  # "...task to the" -> "...task"
        cut.pop()
    return " ".join(cut).rstrip(",;:") + "."


_DANGLING = {"a", "an", "the", "to", "of", "for", "and", "or", "with", "in", "on", "at", "is", "are", "your", "my"}


def compact_canvas(canvas: dict) -> str:
    """Small text view of the canvas for the model (keeps sessions far from the context limit)."""
    if not canvas:
        return ""  # nothing on screen: send no context (the model echoed "[Canvas: empty]" as its whole reply)

    def short(v):
        if isinstance(v, str):
            return v if len(v) <= 60 else v[:57] + "..."
        if isinstance(v, list):
            items = [short(x) for x in v[:8]]
            return items + ([f"...+{len(v) - 8} more"] if len(v) > 8 else [])
        if isinstance(v, dict):
            return {k: short(x) for k, x in v.items() if k not in ("html", "id")}
        return v
    parts = [f'{wid} ({w["widget"]}): {json.dumps(short(w["props"]), ensure_ascii=False)}' for wid, w in canvas.items()]
    return "(On screen now, for reference only, never read this out: " + "; ".join(parts) + ")"


class Connection:
    def __init__(self, ws, watchdog: ServerWatchdog):
        self.ws = ws
        self.watchdog = watchdog
        self.widgets: list[str] = []
        self.canvas: dict = {}           # id -> {widget, props}; authoritative copy comes from canvas_state
        self.audio = bytearray()
        self.listening = False
        self.sm: SessionManager | None = None
        self.lock = asyncio.Lock()       # one model turn at a time
        self.session_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    async def send(self, msg: dict):
        try:
            await self.ws.send(json.dumps(msg))
        except Exception:
            pass

    async def ensure_session(self):
        async with self.session_lock:  # hello warms up a session while the first turn may also need one
            if self.sm is None:
                widgets = self.widgets or ["recipe", "checklist", "timer", "stacked_bar", "html"]
                sm = SessionManager(SYSTEM.format(widgets=widget_docs_text(widgets)),
                                    tools=tool_defs(widgets), watchdog=self.watchdog)
                await sm.start()
                self.sm = sm

    def spawn(self, coro):
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    # ---------------- model turns
    async def turn(self, *, text: str | None = None, pcm: bytes | None = None, label: str = ""):
        async with self.lock:
            t0 = time.time()
            await self.send({"type": "orb", "state": "thinking"})
            try:
                await self.ensure_session()
                ctx = compact_canvas(self.canvas)
                if pcm is not None:
                    r = await self.sm.send_audio(pcm, modalities=("text",), context=ctx)
                else:
                    r = await self.sm.send_text(text, modalities=("text",), context=ctx)
                first = time.time() - t0
                said, steps, escalating = False, 0, False
                while r.calls and steps < MAX_STEPS:
                    steps += 1
                    results = []
                    for c in r.calls:
                        name, args = c["name"], c["arguments"] or {}
                        if name == "escalate":
                            escalating = True
                            results.append((c["call_id"], self.start_escalation(args.get("task", ""))))
                            continue
                        msgs, result = to_canvas(name, args, self.canvas)
                        for m in msgs:
                            await self.send(m)
                        said |= name == "say"
                        results.append((c["call_id"], result))
                        log(f"  {name}({json.dumps(args, ensure_ascii=False)[:120]}) -> {result}")
                    if said:  # spoken confirmation given: file the results, don't ask for more
                        await self.sm.send_tool_results(results, respond=False)
                        r = None
                        break
                    r = await self.sm.send_tool_results(results, modalities=("text",))
                if escalating and not said and not (r is not None and r.text):
                    await self.send({"type": "say", "text": "Let me work that one out."})
                    said = True
                if r is not None and r.calls:  # step limit hit: close the open calls so the session stays valid
                    await self.sm.send_tool_results([(c["call_id"], {"ok": False, "error": "step limit"})
                                                     for c in r.calls], respond=False)
                if r is not None and r.text and not said:
                    # The model's closing text is what it says out loud (it rarely calls `say` itself).
                    # After canvas changes: one short confirmation. Plain conversation: a natural reply,
                    # capped well under the ~80-word limit where speech quality drops.
                    line = ("Let me work that one out." if escalating
                            else spoken_line(r.text) if steps else conversational(r.text))
                    if line:
                        await self.send({"type": "say", "text": line})
                        said = True
                    log(f"  closing line {r.text[:80]!r} -> say {line!r}")
                log(f"turn {label!r}: first reply {first:.1f}s, total {time.time() - t0:.1f}s, "
                    f"{steps} tool steps, est {self.sm.est} tok, rotations {self.sm.rotations}")
            except Exception as e:
                log(f"turn failed: {type(e).__name__}: {e}")
                await self.send({"type": "say", "text": "Sorry, I lost that."})
            finally:
                if not self.listening and not getattr(self, "_working", False):
                    await self.send({"type": "orb", "state": "idle"})

    def start_escalation(self, task: str) -> dict:
        wid = f"cloud_{int(time.time() * 1000) % 100000}"
        self._working = True

        async def run():
            await self.send({"type": "pending", "id": wid, "importance": "full"})
            await self.send({"type": "orb", "state": "working"})
            log(f"  escalate({task!r}) -> {wid}")
            try:
                res = await escalate(task, self.canvas, self.widgets)
                self.canvas[wid] = {"widget": res["widget"], "props": res["props"]}
                await self.send({"type": "create", "id": wid, "widget": res["widget"], "props": res["props"],
                                 "importance": res.get("importance", "full")})
                if res.get("say"):
                    await self.send({"type": "say", "text": res["say"]})
            except Exception as e:
                log(f"  escalation failed: {e}")
                await self.send({"type": "remove", "id": wid})
                await self.send({"type": "say", "text": "That one didn't work out."})
            finally:
                self._working = False
                if not self.listening:
                    await self.send({"type": "orb", "state": "idle"})
        self.spawn(run())
        return {"ok": True, "status": "started", "id": wid}

    # ---------------- canvas messages
    async def on_message(self, raw):
        if isinstance(raw, bytes):  # mic audio: PCM16 16 kHz mono, only between orb_down and orb_up
            if self.listening:
                self.audio.extend(raw)
            return
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            return
        t = m.get("type")
        if t == "hello":
            self.widgets = m.get("widgets") or []
            log(f"canvas connected, widgets: {self.widgets}")
            self.spawn(self.ensure_session())  # warm up while the user gets ready
        elif t == "orb_down":
            self.listening, self.audio = True, bytearray()
            await self.send({"type": "orb", "state": "listening"})
        elif t == "orb_up":
            self.listening = False
            pcm = bytes(self.audio)
            secs, voiced = len(pcm) / 32000, voiced_seconds(pcm)
            if secs >= MIN_AUDIO_S and voiced >= MIN_VOICED_S:
                self.spawn(self.turn(pcm=pcm, label=f"{secs:.1f}s audio, {voiced:.1f}s voiced"))
            else:
                log(f"ignored utterance: {secs:.1f}s audio, {voiced:.2f}s voiced")
                if not self.lock.locked():
                    await self.send({"type": "orb", "state": "idle"})
        elif t == "text":  # dev/testing input, see docs/PROTOCOL.md
            self.spawn(self.turn(text=m.get("text", ""), label=m.get("text", "")[:40]))
        elif t == "canvas_state":
            self.canvas = {w["id"]: {"widget": w["widget"], "props": w.get("props", {})} for w in m.get("widgets", [])}
        elif t == "event":
            await self.on_event(m)

    async def on_event(self, m):
        name, wid, data = m.get("name"), m.get("id"), m.get("data") or {}
        log(f"event {wid}.{name} {data}")
        if name == "timer_done":  # handled directly: no model round trip needed
            await self.send({"type": "say", "text": f"{data.get('label') or 'Timer'}'s done."})
            return
        self.spawn(self.turn(text=f"[Widget event: {wid} {name} {json.dumps(data)}] React only if useful.",
                             label=f"event {name}"))

    async def close(self):
        for t in list(self.tasks):
            t.cancel()
        if self.sm:
            await self.sm.close()


async def main():
    watchdog = ServerWatchdog()
    log("checking llama-server…")
    waited = await watchdog.ensure_up()
    log(f"llama-server up{f' (started, {waited:.0f}s)' if waited else ''}")

    async def handler(ws):
        if ws.request.path != "/canvas":
            await ws.close(1008, "use /canvas")
            return
        conn = Connection(ws, watchdog)
        try:
            async for raw in ws:
                await conn.on_message(raw)
        finally:
            await conn.close()
            log("canvas disconnected")

    async with serve(handler, "localhost", PORT, max_size=None):
        log(f"orchestrator on ws://localhost:{PORT}/canvas")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
