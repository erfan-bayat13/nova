"""Orchestrator: the canvas WebSocket (docs/PROTOCOL.md) in front of the local model.

    canvas (ui/) ⇄ ws://localhost:8765/canvas ⇄ this ⇄ SessionManager ⇄ llama-server /v1/realtime (LFM3-Omni-2B)
                                                 └── escalate.py (Claude, stubbed)

Two modes, picked by the client's `hello` (docs/PROTOCOL.md):
  canvas (default) — tool turns build widgets, the closing line goes out as `say`.
  voice            — speech to speech, no tools: the model answers in its OWN voice, streamed to the client
                     as binary PCM16 24 kHz frames between `speech_start` and `speech_end`. Used by the
                     floating desktop orb (desktop/). `orb_down` during a reply interrupts it.
                     A `see` frame (camera/screen JPEG + question) is described on the chat endpoint and
                     answered with the same voice reply path; the image never goes into the realtime session.
                     Mic audio is passed to the model WHILE the user is still talking (stream_* in the
                     session manager), so the reply starts ~0.25 s after `orb_up` instead of ~0.5 s.

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

import array, asyncio, base64, json, os, re, sys, time, uuid

from websockets.asyncio.server import serve

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "prototype"))  # session_manager.py lives with its tests

from session_manager import SessionManager, ServerWatchdog, _post  # noqa: E402
from escalate import escalate  # noqa: E402
import builder  # noqa: E402
import tools as tools_mod  # noqa: E402
from tools import tool_defs, to_canvas, widget_docs_text  # noqa: E402
from memory import Store, ConnectionMemory, inject_note  # noqa: E402  (long-term memory, docs/MEMORY.md)
from embed import Embedder  # noqa: E402
from consolidate import consolidate  # noqa: E402

PORT = int(os.environ.get("ORCH_PORT", 8765))
LOG = os.environ.get("ORCH_LOG", "1") == "1"
MEMORY_ON = os.environ.get("MEMORY", "1") == "1"   # MEMORY=0 runs without long-term memory
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


VOICE_SYSTEM = """You are Nova, a warm, upbeat friend and assistant the user talks to by voice on their computer. Everything you say is spoken aloud.
Be vocal and engaged, like a real assistant who enjoys the conversation: react to what they say, add a quick helpful thought or a fun detail, and usually end with one friendly follow-up question that moves things forward. Two to four sentences (about 25 to 60 words) is normal; never more than 80 words.
When they bring up a plan, a trip or a project, talk it through with them first: ask about the details that matter (when, where, how many, what they like) and share ideas. Don't dump long lists out loud.
No markdown, lists, emojis, sound effects or stage directions. Say numbers and units the way people speak them.
If you didn't hear or understand something, say so and ask them to repeat instead of guessing.

You can look at the user's screen, their camera, or a part of the screen they pick, but only after they say yes. You see nothing until a note describing the picture arrives after you say you are looking, so never describe their screen or camera before that. Once the note arrives, use it to answer what they asked, in a sentence or two.
Always ask first, then look only after a yes. When you say you are looking, say only that one line and stop: the picture comes next. Examples:
User: Can you look at my screen?
You: Sure, want me to take a look at your screen?
User: Yes please.
You: Okay, looking at your screen now.
User: What is this thing I'm holding?
You: Want me to look through the camera?
User: Yeah.
You: Okay, looking through the camera now.
User: Can you check just one part of my screen?
You: Sure, want me to look at an area you pick?
User: Yes.
You: Okay, select the area you want me to look at.
User: Look at my screen please.
You: Sure, want me to take a look at your screen?
User: Yes.
You: Okay, looking at your screen now.
User: Take a look at this.
You: Want me to look through the camera, or at your screen?
User: The screen.
You: Okay, looking at your screen now.
User: Look at my screen.
You: Want me to take a look at your screen?
User: No.
You: No problem, I won't look.

You can also build things on a canvas that floats on their screen: recipes, checklists, timers, lists, notes, numbers, tables, charts, plans. A note in parentheses starting "(On the canvas now" lists what is already there; never read it out loud.
Behind the scenes a helper puts things on their screen whenever they ask (a recipe, a timer, a list, a plan, a change, clearing it). You never do that yourself and you never announce it: do not say "canvas", "screen", "widget", "putting that up" or "clearing". Just answer like a relaxed friend would: react to what they said, add a quick thought, and ask one casual follow-up question so the conversation keeps going. Remember everything said earlier in this conversation and build on it. If they ask for something to be made, started, changed or cleared, say it is handled in your own words ("Sure, coming right up.", "Done, fresh start!"). Always repeat the exact numbers they said, never change them and then keep talking. If they only mention what they are doing, chat about it and, at most once, offer ("want me to set up a recipe for that?"). Examples:
User: I'm cooking pasta for four.
You: Ooh, pasta night, nice! Are you doing a homemade sauce or keeping it easy?
User: Yeah, set up a recipe for it.
You: Sure thing, four plates of pasta coming right up. Do you want a garlicky sauce or something creamy?
User: Start a twenty minute timer.
You: Twenty minutes, I'll keep it ticking. What are you waiting on?
User: Make it for six.
You: Six it is, a bigger crowd, even better! Is it a special occasion?
User: I want to book a trip to Spain.
You: Ooh, Spain, I love that! When are you thinking of going, and are you more into beaches, or cities and food?
User: I'm thinking of redoing my living room.
You: Ooh, fun project! What style are you drawn to, and is it more a fresh coat of paint or a full makeover?
User: Probably June for ten days, mostly cities and food.
You: Madrid, Barcelona and Seville make a great mix for ten days. Want me to sketch a plan, or keep brainstorming first?
User: Yes, plan it.
You: Great, sketching it now. Do you want mostly trains between them, or a couple of short flights?
User: I'm done, thanks.
You: Anytime, all cleared! That was fun, what are you up to next?
User: How long does pasta take to cook?
You: About ten minutes for most pasta, until it's tender but still has a bite. Do you like it with a little bite or softer?
User: What's a good name for a cat?
You: How about Mochi or Luna? Are you getting a kitten, or adopting an older one?"""
# After a voice reply: this spoken line (taught in VOICE_SYSTEM) means "build it". The builder (Connection.build) then
# turns the user's last request into canvas tool calls on the chat endpoint, while Nova has already answered.
BUILD_NOW_RE = re.compile(r"\b(putting|adding|setting up|updating|changing|clearing|removing)\b[^.?!]*\bcanvas\b", re.I)
# "I'm done" and friends clear the canvas without asking the model: it is the one request that must never be missed
# (the 2B sometimes answers it with prose) and the words are unambiguous. Everything else goes to the builder.
CLEAR_RE = re.compile(r"\b(i'?m|i am|we'?re|we are|all)\s+(all\s+)?(done|finished)\b|\bclear (it|that|this|everything|the (canvas|screen))\b|\bthat'?s (all|everything)\b|\bstart over\b|\b(get rid of|wipe|remove|delete|clean up) (it|that|this|everything|all of it|the (canvas|screen|board))\b|\bclear (all|out)\b", re.I)
COMMENT_AFTER_BUILD = os.environ.get("NOVA_BUILD_COMMENT", "1") == "1"  # Nova remarks on what she built, in her own voice
# Nova sometimes says the canvas line for a plain question about the topic at hand ("how long does pasta take?"). A bare
# question with no canvas words in it builds nothing, so a wrong line never puts an unwanted widget on the screen.
QUESTION_RE = re.compile(r"^\s*(how|what|what's|whats|why|when|where|who|which|is|are|do|does|did|will|would|should)\b", re.I)
CANVAS_WORDS_RE = re.compile(r"\b(make|show|add|put|start|set|create|track|plan|list|timer|chart|note|table|recipe|remind|build|clear|remove|update|change)\b", re.I)
# A hard question ("explain how fixed and variable mortgages differ") is answered out loud by the 2B first, quickly, then handed
# to Claude, whose answer arrives as a card with a spoken one-liner. Only question-shaped requests that look hard (or are long).
HARD_Q_RE = re.compile(r"\b(explain|compare|comparison|differences?|pros and cons|best way|walk me through|step[- ]by[- ]step|in detail|"
                       r"recommend|analy[sz]e|summar[iy][sz]e|which is better|should i (buy|get|choose|take|use)|how (does|do|can|should) .{12,})", re.I)
BIG_JOB_RE = re.compile(r"\b(itinerary|budget|calculate|work out|research|analy[sz]e|compare|comparison|pros and cons|chart|graph|"
                        r"meal plan|workout plan|study plan|schedule for|plan (a|my|our|the) .{6,}|\d+[- ]day|business plan|essay|report)\b", re.I)


def is_hard(text: str) -> bool:
    """Big jobs go to Claude (escalate.py): any request shape, not only questions. Timers and clearing stay local."""
    t = text or ""
    if CLEAR_RE.search(t) or re.search(r"\b(timer|countdown)\b", t, re.I) or len(t.split()) < 5:
        return False
    return bool(HARD_Q_RE.search(t) or BIG_JOB_RE.search(t) or len(t.split()) >= 18)


ASK_RE = re.compile(r"^\s*(explain|compare|tell me|walk me|give me|help me understand)\b", re.I)
BUILD_STEPS = 3     # model calls per build: a follow-up only happens when a tool call failed, so the model can fix it
MAX_REPLY_AUDIO_S = 35  # speech quality drops past ~30-40 s (prototype/README.md): cut it off there
MAX_IMAGE_BYTES = 1_500_000        # `see` frames: decoded JPEG size limit (docs/PROTOCOL.md)
SEE_DEFAULT_QUESTION = "What am I looking at?"
LOOK_FOLLOW_UP = "Now answer what I just asked, using what you see."  # a look Nova asked for, not a hotkey
# Voice mode has no tools, so the model asks and acts through fixed spoken lines (VOICE_SYSTEM): one asking
# permission, then one announcing the look. The code only acts on an announcement that follows an ask.
LOOK_OFFER_RE = re.compile(r"\b(want me to|do you want me to|would you like me to|should i|shall i|can i|could i|may i)\b[^.?!]*\b(look|take a look|check|see)\b", re.I)
LOOK_NOW = [  # most specific first
    ("area", re.compile(r"\b(select|pick|choose|drag)\b[^.?!]*\barea\b|\blooking at (the|an?) (selected |picked |chosen )?area\b|\barea you (picked|selected|chose)", re.I)),
    ("camera", re.compile(r"looking (through|at|with) (the|your) camera", re.I)),
    ("screen", re.compile(r"looking at (the|your|that) (screen|display|desktop)", re.I)),
]


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
    text = re.sub(r"\(\s*remembered from before[^)]*\)?", "", text, flags=re.I)
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


def compact_canvas(canvas: dict, label: str = "On screen now, for reference only, never read this out") -> str:
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
    return f"({label}: " + "; ".join(parts) + ")"


def parse_see(m: dict) -> tuple[bytes, str, str]:
    """Validate a `see` frame (docs/PROTOCOL.md). Returns (jpeg, source, question); raises ValueError with the
    message to send back to the client."""
    source = m.get("source")
    if source not in ("camera", "screen"):
        raise ValueError('see: source must be "camera" or "screen"')
    image = m.get("image")
    if not isinstance(image, str) or not image:
        raise ValueError("see: image missing")
    if image.startswith("data:"):
        raise ValueError("see: send raw base64, without the data: prefix")
    if len(image) > MAX_IMAGE_BYTES * 4 // 3 + 4:  # cheap check before decoding
        raise ValueError(f"see: image larger than {MAX_IMAGE_BYTES} bytes")
    try:
        jpeg = base64.b64decode(image, validate=True)
    except ValueError:  # binascii.Error is a ValueError
        raise ValueError("see: image is not valid base64")
    if len(jpeg) > MAX_IMAGE_BYTES:
        raise ValueError(f"see: image larger than {MAX_IMAGE_BYTES} bytes")
    q = m.get("question")
    question = q.strip() if isinstance(q, str) and q.strip() else SEE_DEFAULT_QUESTION
    return jpeg, source, question


class Connection:
    def __init__(self, ws, watchdog: ServerWatchdog, store: Store | None = None, embedder: Embedder | None = None):
        self.ws = ws
        self.watchdog = watchdog
        self.mem = ConnectionMemory(store, uuid.uuid4().hex[:8], embedder) if store else None
        self.mem_lock = asyncio.Lock()
        self._rotations_seen = 0
        self.widgets: list[str] = []
        self.canvas: dict = {}           # id -> {widget, props}; authoritative copy comes from canvas_state
        self.audio = bytearray()
        self.listening = False
        self.sm: SessionManager | None = None
        self.lock = asyncio.Lock()       # one model turn at a time
        self.session_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.mode = "canvas"             # or "voice" (speech to speech, see module docstring)
        self.speaking = False            # voice mode: a reply is being streamed to the client
        self.interrupted = False         # voice mode: orb_down during the reply, stop forwarding audio
        self.look_offered = False        # voice mode: the last reply asked "want me to look?", waiting for a yes
        self.look_requested = False      # voice mode: we told the orb to look; the next `see` frame answers that
        self.last_pcm: bytes | None = None  # voice mode: the user's last utterance, for the canvas builder
        self.last_text = ""              # ...or the last typed (dev) request
        self.build_lock = asyncio.Lock() # one canvas build at a time
        self.streaming = False           # voice mode: mic frames go straight to the model
        self.released: asyncio.Event | None = None  # voice mode: set on orb_up / orb_cancel

    async def send(self, msg: dict):
        try:
            await self.ws.send(json.dumps(msg))
        except Exception:
            pass

    async def ensure_session(self):
        async with self.session_lock:  # hello warms up a session while the first turn may also need one
            card = self.mem.card() if self.mem else ""
            with_card = lambda base: f"{base}\n\n{card}" if card else base  # noqa: E731  stable prefix, same each rotation
            if self.sm is None and self.mode == "voice":
                sm = SessionManager(with_card(VOICE_SYSTEM), watchdog=self.watchdog)
                await sm.start()
                self.sm = sm
            elif self.sm is None:
                widgets = self.widgets or ["recipe", "checklist", "timer", "stacked_bar", "html"]
                sm = SessionManager(with_card(SYSTEM.format(widgets=widget_docs_text(widgets))),
                                    tools=tool_defs(widgets), watchdog=self.watchdog)
                await sm.start()
                self.sm = sm

    async def after_turn(self):
        """Off the voice path: wait for the transcript and fact extraction, then persist them. Voice commands
        ("remember that...", "forget...", "off the record") are applied by memory.py; a rotation or a clean
        fact list triggers the background consolidation (a bigger model, only if ANTHROPIC_API_KEY is set)."""
        if not (self.mem and self.sm):
            return
        try:
            async with self.mem_lock:
                await self.sm._settle()
                for name, detail in await asyncio.to_thread(self.mem.sync, self.sm):  # embeds: keep it off the loop
                    log(f"  memory: {name} {detail}")
                if self.mem.next_note:
                    log(f"  memory: next round will get {self.mem.next_note[-100:]!r}")
            if self.sm.rotations > self._rotations_seen:
                self._rotations_seen = self.sm.rotations
                if await asyncio.to_thread(consolidate, self.mem.store):
                    log(f"  memory consolidated: {self.mem.store.stats()}")
        except Exception as e:
            log(f"  memory sync failed: {type(e).__name__}: {e}")

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
                note = self.mem.take_note(text if text and not text.startswith("[Widget event") else None) if self.mem else ""
                if note:
                    ctx = f"{ctx}\n{note}" if ctx else note
                    log(f"  memory note: {note[-120:]!r}")
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
                self.spawn(self.after_turn())
                if not self.listening and not getattr(self, "_working", False):
                    await self.send({"type": "orb", "state": "idle"})

    async def voice_turn(self, *, text: str | None = None, pcm: bytes | None = None, label: str = "", act: bool = True):
        """Speech to speech: one model reply in text + audio, the audio streamed to the client as it arrives.
        act=False for turns we start ourselves (announcements): their reply never starts a look or a build."""
        async with self.lock:
            if act:
                self.last_pcm, self.last_text = pcm, text or ""
            await self._voice_reply(text=text, pcm=pcm, label=label, act=act)

    async def see_turn(self, jpeg: bytes, source: str, question: str):
        """Voice mode, `see` frame: describe the image, then answer the question out loud (same reply path)."""
        async with self.lock:
            await self._voice_reply(see=(jpeg, source, question), label=f"see {source}: {question[:40]!r}")

    async def utterance(self, released: asyncio.Event):
        """Voice mode, orb_down → orb_up: stream the mic into the model while the user talks, reply on release.
        `released` is created in on_message (not here) so an orb_cancel right after orb_down always finds it."""
        async with self.lock:  # waits for an interrupted reply to wind down (~0.2 s); frames buffer meanwhile
            if released.dropped:
                return
            try:
                await self.ensure_session()
                ctx = compact_canvas(self.canvas, "On the canvas now")
                if self.mem:  # one small memory note, built after the last turn, rides in the same item as the canvas
                    async with self.mem_lock:
                        note = self.mem.take_note()
                    if note:
                        ctx = f"{ctx}\n{note}" if ctx else note
                        log(f"  memory note: {note[-120:]!r}")
                await self.sm.stream_start(context=ctx)
                sent = 0
                while sent < len(self.audio):  # what arrived while we waited
                    chunk = bytes(self.audio[sent:])
                    sent += len(chunk)
                    await self.sm.stream_append(chunk)
                self.streaming = released is self.released  # from here on_message appends directly
                await released.wait()
                self.streaming = False
                pcm = bytes(self.audio)
                secs, voiced = len(pcm) / 32000, voiced_seconds(pcm)
                if released.dropped or secs < MIN_AUDIO_S or voiced < MIN_VOICED_S:
                    await self.sm.stream_clear()
                    if not released.dropped:
                        log(f"ignored utterance: {secs:.1f}s audio, {voiced:.2f}s voiced")
                    if not self.listening:
                        await self.send({"type": "orb", "state": "idle"})
                    return
            except Exception as e:
                self.streaming = False
                log(f"utterance failed: {type(e).__name__}: {e}")
                await self.send({"type": "orb", "state": "idle"})
                return
            self.last_pcm, self.last_text = pcm, ""
            await self._voice_reply(stream=True, label=f"{secs:.1f}s audio, {voiced:.1f}s voiced, streamed")

    async def _voice_reply(self, *, text: str | None = None, pcm: bytes | None = None, stream: bool = False,
                           see: tuple | None = None, label: str = "", act: bool = True):
        t0 = time.time()
        self.interrupted, self.speaking = False, False
        await self.send({"type": "orb", "state": "thinking"})
        first: list[float] = []
        sent = 0

        async def on_audio(chunk: bytes):
            nonlocal sent
            if self.interrupted:
                return
            if not self.speaking:
                self.speaking = True
                first.append(time.time() - t0)
                await self.send({"type": "speech_start"})
            try:
                await self.ws.send(chunk)
            except Exception:
                pass
            sent += len(chunk)
            if sent / 48000 > MAX_REPLY_AUDIO_S:
                self.sm.cancel()

        try:
            await self.ensure_session()
            self.sm.reset_cancel()  # a barge-in from an earlier turn must not stop this one
            mods = ("text", "audio")
            if self.mem and not stream:  # typed / one-shot voice / `see`: the streamed path injects at stream_start
                note = self.mem.take_note(text)
                if note:
                    await inject_note(self.sm, note)
                    log(f"  memory note: {note[-120:]!r}")
            if see is not None:
                jpeg, source, question = see
                r = await self.sm.see(jpeg, question, source=source, modalities=mods, on_audio=on_audio)
            elif stream:
                r = await self.sm.stream_finish(mods, on_audio=on_audio)
            elif pcm is not None:
                r = await self.sm.send_audio(pcm, modalities=mods, on_audio=on_audio)
            else:
                r = await self.sm.send_text(text, modalities=mods, on_audio=on_audio)
            if self.speaking:
                await self.send({"type": "speech_end", "text": r.text})
            elif r.text and not self.interrupted:  # no audio came back: let the client voice the text
                await self.send({"type": "say", "text": conversational(r.text)})
            log(f"voice {label!r}: first audio after release {first[0] if first else -1:.2f}s, total {time.time() - t0:.1f}s, "
                f"{r.audio_s:.1f}s speech{', INTERRUPTED' if r.cancelled else ''}, est {self.sm.est} tok: {r.text[:80]!r}")
            if act and not r.cancelled and not self.interrupted:
                await self.maybe_look(r.text)
                self.maybe_build(r.text)
                self.maybe_hard_question(r.text)
        except Exception as e:
            log(f"voice turn failed: {type(e).__name__}: {e}")
            if self.speaking:
                await self.send({"type": "speech_end", "text": ""})
            await self.send({"type": "say", "text": "Sorry, I lost that."})
        finally:
            self.speaking = False
            self.spawn(self.after_turn())
            if not self.listening:
                await self.send({"type": "orb", "state": "idle"})

    async def maybe_look(self, text: str):
        """After a voice reply: a spoken "looking now" line that follows a spoken ask makes the orb take a frame."""
        offered, self.look_offered = self.look_offered, bool(LOOK_OFFER_RE.search(text or ""))
        if not offered:
            return
        for source, rx in LOOK_NOW:
            if rx.search(text or ""):
                self.look_offered, self.look_requested = False, True
                log(f"  look {source}: Nova asked, the user agreed")
                await self.send({"type": "look", "source": source})
                return

    def maybe_hard_question(self, reply: str):
        """After a voice reply that did not start a build: a hard question also goes to Claude."""
        if self.last_pcm or self.last_text:  # build() steps aside for big jobs
            self.spawn(self._hard_question(self.last_text))

    async def _hard_question(self, typed: str = ""):
        text = (typed or await self.sm.last_user_text()).strip()
        words = len(text.split())
        if not is_hard(text):
            return
        log(f"  hard question -> Claude: {text[:80]!r}")
        self.start_escalation(text)

    def maybe_build(self, text: str):
        """After every voice reply: build() decides from the user's own words whether anything goes on the canvas."""
        if self.last_pcm or self.last_text:  # build() decides from what the user asked
            self.spawn(self.build(self.last_pcm, self.last_text))

    async def build(self, pcm: bytes | None, text: str = ""):
        """Creator mode: turn the user's last request into canvas tool calls (create/update/remove widgets) on the
        chat endpoint, which takes a free llama slot while the voice session keeps its own. Widgets reach the
        canvas as they are made. Nova has already answered out loud; this runs behind her."""
        async with self.build_lock:
            t0 = time.time()
            try:
                request = (text or await self.sm.last_user_text()).strip()  # the transcript the session makes anyway
                log(f"  build heard: {request[:80]!r}")
                if not request:
                    return
                t_asr = time.time() - t0
                if self.canvas and CLEAR_RE.search(request):
                    out, result = to_canvas("clear_canvas", {}, self.canvas)
                    for msg in out:
                        await self.send(msg)
                    log(f"build {request[:50]!r}: cleared the canvas (no model call), asr {t_asr:.1f}s")
                    return
                last_nova = next((t for r_, t in reversed(self.sm.recent_dialogue(4)) if r_ != "user"), "")
                said_yes = re.search(r"\b(yes|yeah|yep|sure|please|do it|go ahead)\b", request, re.I) and re.search(r"want me to|shall i|should i|set up|sketch", last_nova, re.I)
                if not CANVAS_WORDS_RE.search(request) and not said_yes:
                    log(f"build {request[:50]!r}: no explicit ask, just chatting")
                    return
                if is_hard(request):
                    log(f"build {request[:50]!r}: big job, Claude handles it")
                    return
                await self.send({"type": "orb", "state": "thinking"})
                tm = re.search(r"(\d+)\s*(minutes?|mins?|hours?|seconds?|secs?)\b", builder.digits(request), re.I)
                if tm and re.search(r"\b(timer|countdown|remind)", request, re.I):  # exact: the 2B kept saying 10 minutes
                    n, u = int(tm.group(1)), tm.group(2).lower()
                    mins = n * 60 if u.startswith("hour") else (n / 60 if u.startswith("sec") else n)
                    out, result = to_canvas("start_timer", {"minutes": mins, "label": "Timer"}, self.canvas)
                    for msg in out:
                        await self.send(msg)
                    log(f"build {request[:50]!r}: timer {mins} min (no model call)")
                    return
                types = self.widgets or tools_mod.all_widget_types()
                tools = builder.tool_list(types)
                convo = builder.conversation_note(self.sm.recent_dialogue(8), request)
                msgs = builder.messages(request, compact_canvas(self.canvas, "On the canvas now, for reference only, never read this out"),
                                        types, convo)
                steps = made = 0
                nudged, built = False, []
                before = json.loads(json.dumps(self.canvas))  # to compare with after the model's updates (servings_fix)
                while steps < BUILD_STEPS:
                    steps += 1
                    d = await asyncio.to_thread(_post, "/v1/chat/completions",
                                                {"messages": msgs, "tools": tools, "temperature": 0,
                                                 "max_tokens": 700 if steps == 1 else 300})
                    m = d["choices"][0]["message"]
                    calls = m.get("tool_calls") or []
                    if not calls:
                        break
                    msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
                    failed = False
                    for c in calls:
                        fn = c.get("function", {})
                        name, args = fn.get("name", ""), fn.get("arguments") or {}
                        if isinstance(args, str):
                            try:
                                args = json.loads(args or "{}")
                            except ValueError:
                                args = {}
                        if "banana" in json.dumps(args).lower() and "banana" not in request.lower() and "banana" not in (convo_note_text := convo.lower()):
                            result = {"ok": True}  # the 2B copied its banana bread example: drop it
                            log("  build: dropped a banana bread leak")
                        elif name == "escalate":
                            result = self.start_escalation(args.get("task", request))
                        else:
                            out, result = to_canvas(name, args, self.canvas)
                            for msg in out:
                                await self.send(msg)
                                if msg.get("type") == "create":
                                    p = msg.get("props") or {}
                                    built.append(f"a {msg.get('widget', 'widget').replace('_', ' ')} ({str(p.get('title') or p.get('label') or p.get('caption') or msg.get('id'))[:40]})")
                            made += bool(out)
                        log(f"  build {name}({json.dumps(args, ensure_ascii=False)[:110]}) -> {result}")
                        msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": json.dumps(result)})
                        failed |= not result.get("ok", True)
                    if not failed:  # everything worked: no follow-up call (each one costs seconds)...
                        recipe_alone = "recipe" in self.canvas and "ingredients" not in self.canvas
                        if recipe_alone and not nudged and steps < BUILD_STEPS:  # ...except the one cooking always needs: the 2B often stops after the recipe
                            nudged = True
                            msgs.append({"role": "user", "content": 'Also add the ingredients checklist for that recipe (id "ingredients").'})
                            continue
                        break
                for name, args in builder.servings_fix(builder.digits(request), before, self.canvas):
                    out, result = to_canvas(name, args, self.canvas)
                    for msg in out:
                        await self.send(msg)
                    made += bool(out)
                    log(f"  build fix {name}({json.dumps(args, ensure_ascii=False)[:100]}) -> {result}")
                if built and COMMENT_AFTER_BUILD and not self.listening:  # same proven announce format as "timer is done"
                    await self.say(f"{built[0].split(' (')[0]} is up on their screen now, with everything you talked about.")
                log(f"build {request[:50]!r}: {made} canvas changes in {steps} steps, asr {t_asr:.1f}s, total {time.time() - t0:.1f}s")
            except Exception as e:
                log(f"build failed: {type(e).__name__}: {e}")
            finally:
                if not self.listening and not self.speaking and not self.lock.locked() and not getattr(self, "_working", False):
                    await self.send({"type": "orb", "state": "idle"})

    async def say(self, text: str):
        """A short line for the user: in voice mode Nova says it in her own voice (never the browser voice)."""
        if self.mode == "voice":
            self.spawn(self.voice_turn(text=f"(Tell the user, in one short friendly sentence: {text})",
                                       label="announce", act=False))
        else:
            await self.send({"type": "say", "text": text})

    def drop_utterance(self) -> bool:
        """End the utterance being streamed, if any, without a reply. True if there was one."""
        ev = self.released
        if ev is None or ev.is_set():
            return False
        ev.dropped = True
        self.streaming = False
        ev.set()
        return True

    def interrupt(self):
        """orb_down while a voice reply is running: stop forwarding audio and stop the model."""
        if self.lock.locked() and self.mode == "voice":
            self.interrupted = True
            if self.sm:
                self.sm.cancel()

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
                    await self.say(res["say"])
            except Exception as e:
                log(f"  escalation failed: {e}")
                await self.send({"type": "remove", "id": wid})
                await self.say("That one didn't work out.")
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
                if self.streaming:
                    await self.sm.stream_append(raw)
            return
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            return
        t = m.get("type")
        if t == "hello":
            self.widgets = m.get("widgets") or []
            self.mode = "voice" if m.get("mode") == "voice" else "canvas"
            log(f"{self.mode} client connected" + (f", widgets: {self.widgets}" if self.mode == "canvas" else ""))
            self.spawn(self.ensure_session())  # warm up while the user gets ready
        elif t == "orb_down":
            self.interrupt()
            self.drop_utterance()  # a press without a release before it: throw that one away
            self.listening, self.audio = True, bytearray()
            await self.send({"type": "orb", "state": "listening"})
            if self.mode == "voice":
                ev = self.released = asyncio.Event()
                ev.dropped = False  # orb_cancel (or a new press) throws this utterance away
                self.spawn(self.utterance(ev))
        elif t == "orb_cancel":  # drop the audio, no turn (a stopped reply, a press that became a drag)
            self.listening, self.audio = False, bytearray()
            if not self.drop_utterance() and not self.lock.locked():
                await self.send({"type": "orb", "state": "idle"})
        elif t == "orb_up" and self.mode == "voice":
            self.listening = False
            if self.released:
                self.released.set()
        elif t == "orb_up":
            self.listening = False
            pcm = bytes(self.audio)
            secs, voiced = len(pcm) / 32000, voiced_seconds(pcm)
            if secs >= MIN_AUDIO_S and voiced >= MIN_VOICED_S:
                run = self.voice_turn if self.mode == "voice" else self.turn
                self.spawn(run(pcm=pcm, label=f"{secs:.1f}s audio, {voiced:.1f}s voiced"))
            else:
                log(f"ignored utterance: {secs:.1f}s audio, {voiced:.2f}s voiced")
                if not self.lock.locked():
                    await self.send({"type": "orb", "state": "idle"})
        elif t == "see":  # camera or screen frame, voice mode only (docs/PROTOCOL.md)
            if self.mode != "voice":
                await self.send({"type": "error", "text": "see: only in voice mode"})
                return
            try:
                jpeg, source, question = parse_see(m)
            except ValueError as e:
                log(f"  rejected {e}")
                await self.send({"type": "error", "text": str(e)})
                return
            if self.look_requested and not (isinstance(m.get("question"), str) and m["question"].strip()):
                question = LOOK_FOLLOW_UP
            self.look_requested = False
            log(f"  see {source}: {len(jpeg)} bytes{' (waiting for the previous turn)' if self.lock.locked() else ''}")
            self.spawn(self.see_turn(jpeg, source, question))
        elif t == "text":  # dev/testing input, see docs/PROTOCOL.md
            run = self.voice_turn if self.mode == "voice" else self.turn
            self.spawn(run(text=m.get("text", ""), label=m.get("text", "")[:40]))
        elif t == "canvas_state":
            self.canvas = {w["id"]: {"widget": w["widget"], "props": w.get("props", {})} for w in m.get("widgets", [])}
        elif t == "event":
            await self.on_event(m)

    async def on_event(self, m):
        name, wid, data = m.get("name"), m.get("id"), m.get("data") or {}
        log(f"event {wid}.{name} {data}")
        if name == "timer_done":  # handled directly: no model round trip needed
            await self.say(f"The {data.get('label') or 'timer'} timer is done." if self.mode == "voice"
                           else f"{data.get('label') or 'Timer'}'s done.")
            return
        if self.mode == "voice":  # no tools in the voice session; ticks and counters reach us through canvas_state
            return
        self.spawn(self.turn(text=f"[Widget event: {wid} {name} {json.dumps(data)}] React only if useful.",
                             label=f"event {name}"))

    async def close(self):
        for t in list(self.tasks):
            t.cancel()
        if self.mem and self.sm:  # last chance to save this conversation, then tidy the fact list
            try:
                await self.sm._settle()
                self.mem.sync(self.sm)
                await asyncio.wait_for(asyncio.to_thread(consolidate, self.mem.store), 20)
            except Exception as e:
                log(f"  memory close failed: {type(e).__name__}: {e}")
        if self.sm:
            await self.sm.close()


async def main():
    watchdog = ServerWatchdog()
    store = Store() if MEMORY_ON else None
    embedder = Embedder() if store else None
    if embedder:  # picking a backend can take seconds (torch): do it in a thread while llama-server comes up
        def warm():
            embedder.start()
            log(f"embedder: {embedder.name or 'none, keyword retrieval only'}")
        asyncio.get_running_loop().run_in_executor(None, warm)
    if store:
        log(f"memory on: {store.stats()} ({os.path.relpath(store.db.execute('PRAGMA database_list').fetchone()[2])})")
    log("checking llama-server…")
    waited = await watchdog.ensure_up()
    log(f"llama-server up{f' (started, {waited:.0f}s)' if waited else ''}")

    async def handler(ws):
        if ws.request.path != "/canvas":
            await ws.close(1008, "use /canvas")
            return
        conn = Connection(ws, watchdog, store, embedder)
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
