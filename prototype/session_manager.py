"""Session manager for LFM3-Omni-2B on llama-server.

Why it exists (see README "Long-horizon limits"):
  * A realtime session that fills its context crashes the WHOLE llama server (GGML_ASSERT).
  * The server only reports output tokens, so we must estimate context use ourselves.
  * If the server dies anyway, we restart it and carry the conversation over.

What it does:
  * Tracks estimated context per realtime session:
      instructions + tools (exact, via /tokenize)
      + user text (exact) + user audio (~12.6 tok/s) + tool results (exact)
      + replies (exact, from response.done usage.output_tokens; includes audio tokens)
      + a small per-item overhead.
  * Extracts lasting facts from every user message in the background (chat endpoint, second slot).
    One-shot summaries from the 2B model dropped facts; per-message extraction did not.
  * Before a user turn would push the estimate past `rotate_at`, it opens a fresh session whose
    `instructions` carry the fact list + the last few turns verbatim (~1 s, no summarizing step).
  * Transcribes user audio in the background (realtime gives no transcript) so facts include speech.
  * ServerWatchdog restarts llama-server if it goes down; the manager reconnects and retries the turn once.

Usage:
    wd = ServerWatchdog()                       # optional; manages/restarts the server
    sm = SessionManager(instructions, tools=TOOLS, watchdog=wd)
    await sm.start()
    r = await sm.send_text("I'm cooking pasta for four", modalities=("text",))
    r = await sm.send_audio(pcm16k_bytes, modalities=("text", "audio"))
    r = await sm.send_tool_result(r.calls[0]["call_id"], {"ok": True}, modalities=("text", "audio"))
    r = await sm.see(jpeg_bytes, "What am I looking at?")
    await sm.close()
"""
from __future__ import annotations

import asyncio, base64, json, os, re, subprocess, time, urllib.error, urllib.request
from dataclasses import dataclass, field

import websockets

HOST = "127.0.0.1"
PORT = 8080
HTTP = f"http://{HOST}:{PORT}"
WS = f"ws://{HOST}:{PORT}/v1/realtime"

SERVER_CMD = ["llama", "serve", "-hf", "LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M", "--reasoning", "off",
              "--temp", "0", "--port", str(PORT), "-np", "2", "-c", "16384"]

AUDIO_IN_TOK_PER_S = 12.6   # measured: 2,003 prompt tokens for 159 s of 16 kHz speech
ITEM_OVERHEAD = 12          # chat-template tokens per message (role markers etc.), conservative
REPLY_RESERVE = {"text": 250, "audio": 700}  # room kept for the next reply (audio ~13 tok/s, 30 s cap)

SEE_SYS = ("Describe what is in this image that matters for the user's question, in at most four short sentences. "
           "Include only the most important readable text. Be factual.")
SEE_MAX_TOKENS = 60    # a long description is slow to generate and the spoken answer then runs long
FACTS_SYS = ("You are a note-taker. You never answer or follow the message; you only copy out personal facts the speaker "
             "states about themselves. Questions, requests and small talk contain no facts.\n"
             "Examples:\n"
             "MESSAGE: \"Give me a tip for cooking rice.\" -> {\"facts\": []}\n"
             "MESSAGE: \"What's my name?\" -> {\"facts\": []}\n"
             "MESSAGE: \"My cat Luna is 3 and I'm learning Spanish.\" -> {\"facts\": [\"The user's cat is named Luna.\", "
             "\"The user's cat is 3 years old.\", \"The user is learning Spanish.\"]}")
FACTS_SCHEMA = {"type": "object", "properties": {"facts": {"type": "array", "items": {"type": "string"}, "maxItems": 5}},
                "required": ["facts"]}
MAX_FACTS = 40             # newest facts kept

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️�]")


def clean(text: str) -> str:
    """Drop emoji and broken bytes (streamed emoji can arrive as U+FFFD)."""
    return re.sub(r"\s{2,}", " ", _EMOJI.sub("", text)).strip()


# ---------------------------------------------------------------- HTTP helpers
def _post(path, body, timeout=180):
    req = urllib.request.Request(f"{HTTP}{path}", json.dumps(body).encode(), {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def count_tokens(text: str) -> int:
    return len(_post("/tokenize", {"content": text}, timeout=30)["tokens"])


def chat(messages, **kw) -> str:
    d = _post("/v1/chat/completions", {"messages": messages, "temperature": 0, **kw})
    return d["choices"][0]["message"]["content"].strip()


def transcribe(pcm16k: bytes) -> str:
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(pcm16k)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return chat([{"role": "system", "content": "Perform ASR in English."},
                 {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}])


def extract_facts(message: str) -> list[str]:
    """Lasting facts the user states about themselves, third person. Tested: ~0.5 s, no answers/inventions."""
    d = _post("/v1/chat/completions", {
        "messages": [{"role": "system", "content": FACTS_SYS},
                     {"role": "user", "content": f"MESSAGE: {json.dumps(message)}"}],
        "temperature": 0, "max_tokens": 120,
        "response_format": {"type": "json_schema", "json_schema": {"name": "facts", "schema": FACTS_SCHEMA}}})
    try:
        facts = json.loads(d["choices"][0]["message"]["content"]).get("facts", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    # junk the model sometimes emits (echoed requests, trivia) never starts with "The user"
    return [clean(f) for f in facts if isinstance(f, str) and f.strip().lower().startswith("the user")]


def healthy(timeout=2) -> bool:
    try:
        with urllib.request.urlopen(f"{HTTP}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------- watchdog
class ServerWatchdog:
    """Keeps llama-server up. Attaches to a running server; spawns one only when none answers."""

    def __init__(self, cmd=SERVER_CMD, log_path=None, start_timeout=300):
        self.cmd, self.start_timeout = cmd, start_timeout
        self.log_path = log_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "server_managed.log")
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self._lock = asyncio.Lock()

    async def ensure_up(self) -> float:
        """Return seconds spent waiting (0 if it was already up)."""
        async with self._lock:
            if healthy():
                return 0.0
            t0 = time.time()
            if self.proc is None or self.proc.poll() is not None:
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                log = open(self.log_path, "a")
                self.proc = subprocess.Popen(self.cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.restarts += 1
            while time.time() - t0 < self.start_timeout:
                if healthy():
                    return time.time() - t0
                if self.proc.poll() is not None:
                    raise RuntimeError(f"llama-server exited with {self.proc.returncode}; see {self.log_path}")
                await asyncio.sleep(1)
            raise TimeoutError("llama-server did not become healthy")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------------------------------------------------------------- results
@dataclass
class Result:
    text: str = ""
    pcm: bytes = b""                    # 24 kHz PCM16 mono
    calls: list = field(default_factory=list)  # [{"name","call_id","arguments"(dict)}]
    output_tokens: int = 0
    secs: float = 0.0
    first_audio_s: float | None = None
    cancelled: bool = False             # cancel() stopped this reply early (barge-in)
    rotated: bool = False               # a new session was opened before this turn
    recovered: bool = False             # the server crashed/restarted during this turn

    @property
    def audio_s(self):
        return round(len(self.pcm) / 48000, 2)


class ServerGone(Exception):
    pass


# ---------------------------------------------------------------- manager
class SessionManager:
    def __init__(self, instructions: str, tools: list | None = None, voice: str = "female",
                 ctx_limit: int = 8192, rotate_at: int | None = 6000, keep_last: int = 4,
                 watchdog: ServerWatchdog | None = None, verbose: bool = False):
        self.base_instructions = instructions
        self.tools = tools or []
        self.voice = voice
        self.ctx_limit = ctx_limit
        self.rotate_at = rotate_at          # None disables rotation (used to measure the crash point)
        self.keep_last = keep_last
        self.watchdog = watchdog
        self.verbose = verbose

        self.ws = None
        self.est = 0                        # estimated tokens in the current session
        self.facts: list[str] = []          # lasting facts about the user, extracted per message
        self.history: list[dict] = []       # {"role": "user"|"assistant"|"tool", "text": str}
        self._bg: list[asyncio.Task] = []   # background ASR + fact extraction (second slot)
        self._carry: list[dict] = []
        self._awaiting_tool_result = False
        self.rotations = 0
        self.recoveries = 0
        self._cancel = False                # set by cancel(): stop the running reply (barge-in)
        self._stream: bytearray | None = None  # audio of the utterance being streamed in (stream_*)
        self._stream_rotated = False
        self.est_at_crash: list[int] = []

    # ---------------- lifecycle
    async def start(self):
        if self.watchdog:
            await self.watchdog.ensure_up()
        await self._open()

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None

    def _instructions(self) -> str:
        parts = [self.base_instructions]
        if self.facts:
            parts.append("Facts about the user from earlier in this conversation:\n" +
                         "\n".join(f"- {f}" for f in self.facts))
        recent = self._carry
        if recent:
            lines = "\n".join(f'{self.LABEL[h["role"]]}: {h["text"]}' for h in recent)
            parts.append(f"Most recent conversation:\n{lines}")
        return "\n\n".join(parts)

    async def _open(self):
        instr = self._instructions()
        self.ws = await websockets.connect(WS, max_size=None, ping_interval=None)
        await self.ws.recv()  # session.created
        session = {"type": "realtime", "instructions": instr, "output_modalities": ["text"],
                   "audio": {"output": {"voice": self.voice}}}
        if self.tools:
            session["tools"] = [{"type": "function", **t} for t in self.tools]
        await self.ws.send(json.dumps({"type": "session.update", "session": session}))
        while True:  # the server must apply instructions/tools before the first message, or it rejects them
            ev = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if ev["type"] == "session.updated":
                break
            if ev["type"] == "error":
                raise RuntimeError(f'session.update failed: {ev.get("error", {}).get("message", ev)}')
        self.est = (await asyncio.to_thread(count_tokens, instr)) + 20
        if self.tools:
            self.est += await asyncio.to_thread(count_tokens, json.dumps(self.tools)) + 20
        self._awaiting_tool_result = False
        self._log(f"session opened, base {self.est} tokens")

    def _log(self, msg):
        if self.verbose:
            print(f"    [sm] {msg}")

    # ---------------- rotation
    LABEL = {"user": "USER", "assistant": "ASSISTANT", "tool": "TOOL RESULT"}

    def _done_history(self):
        return [h for h in self.history if h["text"] and not h.get("pending")]

    @property
    def summary(self) -> str:
        return " ".join(self.facts)

    def _remember(self, message: str):
        """Extract facts from a user message in the background."""
        async def run():
            for f in await asyncio.to_thread(extract_facts, message):
                if f not in self.facts:
                    self.facts.append(f)
            del self.facts[:-MAX_FACTS]
        self._bg.append(asyncio.create_task(run()))

    async def _settle(self):
        """Wait for background ASR / fact extraction (normally already finished)."""
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)
            self._bg = [t for t in self._bg if not t.done()]

    async def _summarize(self):
        """Carry the fact list + the last few turns verbatim into the next session."""
        await self._settle()
        self._carry = self._done_history()[-self.keep_last:]
        self.history = self._carry + [h for h in self.history if h.get("pending")]

    async def rotate(self, reason="budget"):
        t0 = time.time()
        await self.close()
        await self._summarize()
        await self._open()
        self.rotations += 1
        self._log(f"rotated ({reason}) in {time.time() - t0:.1f}s; summary: {self.summary[:100]!r}")

    async def _make_room(self, incoming: int, modalities) -> bool:
        reserve = REPLY_RESERVE["audio" if "audio" in modalities else "text"]
        need = incoming + reserve
        if need > self.ctx_limit - 1000:
            raise ValueError(f"single input too large for one session ({incoming} tokens)")
        if self.rotate_at is None or self._awaiting_tool_result:
            return False
        if self.est + need > self.rotate_at:
            await self.rotate()
            return True
        return False

    # ---------------- recovery
    async def _recover(self):
        self.est_at_crash.append(self.est)
        self.recoveries += 1
        try:
            if self.ws:
                await self.ws.close()
        except Exception:
            pass
        self.ws = None
        if not self.watchdog:
            raise ServerGone("server down and no watchdog configured")
        waited = await self.watchdog.ensure_up()
        self._log(f"server back after {waited:.1f}s; reopening with summary")
        await self._summarize()
        await self._open()

    def cancel(self):
        """Barge-in: stop the reply that is being generated. The running turn returns early with what it
        had so far (Result.cancelled); audio deltas after this point are not passed to on_audio."""
        self._cancel = True

    def reset_cancel(self):
        """Call at the start of each turn. _respond does not clear cancel() itself, so a barge-in that lands
        while an image is still being described (see) stops that turn before its reply starts."""
        self._cancel = False

    async def _turn(self, send_items, incoming: int, modalities, entry=None, rotated=False,
                    tool_choice: str = "auto", respond: bool = True, on_audio=None) -> Result:
        """Send items + response.create. On server loss: restart, reopen, resend once."""
        for attempt in (1, 2):
            try:
                if self.ws is None:
                    raise ServerGone("no session")
                await send_items()
                self.est += incoming
                if not respond:  # e.g. filing the result of a final `say` call without asking for more
                    self._awaiting_tool_result = False
                    return Result()
                r = await self._respond(modalities, tool_choice, on_audio)
                r.rotated, r.recovered = rotated, attempt == 2
                if entry is not None:
                    entry.pop("pending", None)
                self._bg = [t for t in self._bg if not t.done()]
                return r
            except (websockets.ConnectionClosed, OSError, ServerGone, asyncio.TimeoutError) as e:
                if attempt == 2:
                    raise
                self._log(f"lost server ({type(e).__name__}); recovering")
                await self._recover()

    async def _respond(self, modalities, tool_choice: str = "auto", on_audio=None) -> Result:
        """tool_choice: "auto" | "none" | "required" (the server rejects forcing a specific function).
        on_audio(pcm24k_chunk): called (sync or async) with every audio delta as it arrives, for streaming."""
        resp = {"output_modalities": list(modalities)}
        if tool_choice != "auto":
            resp["tool_choice"] = tool_choice
        await self.ws.send(json.dumps({"type": "response.create", "response": resp}))
        t0, r = time.time(), Result()
        cancel_sent = False
        while True:
            if self._cancel and not cancel_sent:
                cancel_sent = r.cancelled = True
                await self.ws.send(json.dumps({"type": "response.cancel"}))
            ev = json.loads(await asyncio.wait_for(self.ws.recv(), 120))
            t = ev["type"]
            if t == "error" and cancel_sent:
                self._log(f"error while cancelling (ignored): {ev}")
                continue
            if t == "error":
                msg = ev.get("error", {}).get("message", str(ev))
                if "does not fit in the context" in msg:
                    raise ServerGone(msg)  # the server is about to abort
                raise RuntimeError(msg)
            if t == "response.output_text.delta":
                r.text += ev["delta"]
            elif t == "response.output_audio.delta":
                r.first_audio_s = r.first_audio_s or round(time.time() - t0, 2)
                chunk = base64.b64decode(ev["delta"])
                r.pcm += chunk
                if on_audio and not self._cancel:
                    out = on_audio(chunk)
                    if asyncio.iscoroutine(out):
                        await out
            elif t == "response.done":
                resp = ev.get("response", {})
                r.output_tokens = (resp.get("usage") or {}).get("output_tokens", 0)
                for item in resp.get("output", []):
                    if item.get("type") == "function_call":
                        try:
                            args = json.loads(item.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {"_raw": item.get("arguments")}
                        r.calls.append({"name": item.get("name"), "call_id": item.get("call_id"), "arguments": args})
                break
        r.secs = round(time.time() - t0, 2)
        r.text = clean(r.text)
        self.est += r.output_tokens + ITEM_OVERHEAD
        self._awaiting_tool_result = bool(r.calls)
        if r.text:
            self.history.append({"role": "assistant", "text": r.text})
        for c in r.calls:
            self.history.append({"role": "assistant", "text": f'(called {c["name"]} {json.dumps(c["arguments"])})'})
        return r

    # ---------------- public turns
    async def send_text(self, text: str, modalities=("text",), remember: bool = True, context: str = "",
                        tool_choice: str = "auto", on_audio=None) -> Result:
        """`context` (e.g. the current canvas state) is appended after the text, kept out of history/facts."""
        full = f"{text}\n\n{context}" if context else text
        n = await asyncio.to_thread(count_tokens, full) + ITEM_OVERHEAD
        item = {"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": full}]}}

        async def send():
            await self.ws.send(json.dumps(item))
        rotated = await self._make_room(n, modalities)
        entry = {"role": "user", "text": text, "pending": True}
        self.history.append(entry)
        if remember:
            self._remember(text)
        return await self._turn(send, n, modalities, entry, rotated, tool_choice, on_audio=on_audio)

    async def send_audio(self, pcm16k: bytes, modalities=("text", "audio"), context: str = "",
                         tool_choice: str = "auto", on_audio=None) -> Result:
        """`context` is sent as a short text message right before the audio, in the same turn."""
        secs = len(pcm16k) / 32000
        n = int(secs * AUDIO_IN_TOK_PER_S) + ITEM_OVERHEAD
        if context:
            n += await asyncio.to_thread(count_tokens, context) + ITEM_OVERHEAD
        rotated = await self._make_room(n, modalities)
        entry = {"role": "user", "text": "", "pending": True}
        self.history.append(entry)

        async def fill():
            entry["text"] = clean(await asyncio.to_thread(transcribe, pcm16k))
            for f in await asyncio.to_thread(extract_facts, entry["text"]):
                if f not in self.facts:
                    self.facts.append(f)

        async def send():
            if context:
                await self.ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": context}]}}))
            for i in range(0, len(pcm16k), 32000):
                await self.ws.send(json.dumps({"type": "input_audio_buffer.append",
                                               "audio": base64.b64encode(pcm16k[i:i + 32000]).decode()}))
            await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        r = await self._turn(send, n, modalities, entry, rotated, tool_choice, on_audio=on_audio)
        # transcribe only after the reply: running ASR at the same time on the GPU tripled the turn time
        self._bg.append(asyncio.create_task(fill()))
        return r

    # ---------------- streamed utterance (push-to-talk: audio goes in while the user is still talking)
    # Measured: release -> first reply audio 0.23-0.27 s when the audio was appended while holding, vs
    # ~0.5 s when all of it is sent at release. llama-server processes appended audio as it arrives.
    STREAM_RESERVE_S = 30  # room kept for the utterance before we know its length

    async def stream_start(self, modalities=("text", "audio"), context: str = ""):
        """Begin an utterance. Rotates first if needed (never in the middle of one).
        `context` (e.g. what is on the canvas) goes in as a short text item before the audio, like send_audio()."""
        n = int(self.STREAM_RESERVE_S * AUDIO_IN_TOK_PER_S) + ITEM_OVERHEAD
        self._stream_extra = 0
        if context:
            self._stream_extra = await asyncio.to_thread(count_tokens, context) + ITEM_OVERHEAD
            n += self._stream_extra
        self._stream_rotated = await self._make_room(n, modalities)
        self._stream = bytearray()
        if context:
            try:
                await self.ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "message", "role": "user", "content": [{"type": "input_text", "text": context}]}}))
            except Exception:
                pass  # server gone: the turn recovers without the note

    async def stream_append(self, pcm16k: bytes):
        if self._stream is None:
            return
        self._stream += pcm16k
        try:
            await self.ws.send(json.dumps({"type": "input_audio_buffer.append",
                                           "audio": base64.b64encode(pcm16k).decode()}))
        except Exception:
            pass  # server gone: stream_finish recovers and resends the whole utterance

    async def stream_clear(self):
        """Throw the utterance away (silence, a cancelled press)."""
        self._stream = None
        try:
            await self.ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        except Exception:
            pass

    async def stream_finish(self, modalities=("text", "audio"), on_audio=None) -> Result:
        """The user let go: commit what was streamed and reply."""
        pcm = bytes(self._stream or b"")
        self._stream = None
        n = int(len(pcm) / 32000 * AUDIO_IN_TOK_PER_S) + ITEM_OVERHEAD + getattr(self, "_stream_extra", 0)
        self._stream_extra = 0
        entry = {"role": "user", "text": "", "pending": True}
        self.history.append(entry)
        first_try = True

        async def send():
            nonlocal first_try
            if not first_try:  # the server was restarted: the new session never got the audio
                for i in range(0, len(pcm), 32000):
                    await self.ws.send(json.dumps({"type": "input_audio_buffer.append",
                                                   "audio": base64.b64encode(pcm[i:i + 32000]).decode()}))
            first_try = False
            await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        async def fill():
            entry["text"] = clean(await asyncio.to_thread(transcribe, pcm))
            for f in await asyncio.to_thread(extract_facts, entry["text"]):
                if f not in self.facts:
                    self.facts.append(f)
        r = await self._turn(send, n, modalities, entry, self._stream_rotated, on_audio=on_audio)
        self._bg.append(asyncio.create_task(fill()))
        return r

    async def send_tool_result(self, call_id: str, output, modalities=("text",)) -> Result:
        payload = json.dumps(output)
        n = await asyncio.to_thread(count_tokens, payload) + ITEM_OVERHEAD
        item = {"type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id, "output": payload}}

        async def send():
            await self.ws.send(json.dumps(item))
        self.history.append({"role": "tool", "text": payload[:200]})
        # tool output must follow its call in the same session, so never rotate here
        return await self._turn(send, n, modalities)

    async def send_tool_results(self, results: list[tuple[str, object]], modalities=("text",),
                                tool_choice: str = "auto", respond: bool = True) -> Result:
        """Several tool outputs (one per call of the previous reply), then one reply (unless respond=False)."""
        payloads = [(cid, json.dumps(out)) for cid, out in results]
        n = sum([await asyncio.to_thread(count_tokens, p) + ITEM_OVERHEAD for _, p in payloads])

        async def send():
            for cid, p in payloads:
                await self.ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": cid, "output": p}}))
        for _, p in payloads:
            self.history.append({"role": "tool", "text": p[:200]})
        return await self._turn(send, n, modalities, tool_choice=tool_choice, respond=respond)

    async def see(self, jpeg: bytes, question: str, source: str = "camera", modalities=("text", "audio"),
                  on_audio=None) -> Result:
        """Realtime takes no images: describe the frame on the chat endpoint, then answer in the session.
        cancel() during the description returns Result(cancelled=True) without starting a reply."""
        uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        if self._cancel:
            return Result(cancelled=True)
        desc = await asyncio.to_thread(chat, [{"role": "system", "content": SEE_SYS},
                                              {"role": "user", "content": [
                                                  {"type": "image_url", "image_url": {"url": uri}},
                                                  {"type": "text", "text": question}]}], max_tokens=SEE_MAX_TOKENS)
        if self._cancel:
            return Result(cancelled=True)
        what = "The camera sees" if source == "camera" else "The screen shows"
        return await self.send_text(f"[{what}: {clean(desc)}]\n{question}\n(Answer in one or two short sentences.)", modalities, remember=False,
                                    on_audio=on_audio)

    @property
    def stats(self):
        return {"est_tokens": self.est, "rotations": self.rotations, "recoveries": self.recoveries,
                "server_restarts": self.watchdog.restarts if self.watchdog else None,
                "est_at_crash": self.est_at_crash}
