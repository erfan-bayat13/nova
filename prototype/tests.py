"""Test suite for LFM3-Omni-2B on llama-server.

Usage:  python3 tests.py [tools|rt_tools|tones|multiturn|audio_only|voice_in|vision|all]
Needs:  server on :8080 started with `-np 1 -c 4096`, and `pip install websockets`.
Results are appended to logs/test_results.jsonl.
"""
import asyncio, base64, json, os, subprocess, sys, time, urllib.error, urllib.request, wave

import websockets

from router import TONES, VOICE_SUFFIX

HTTP = "http://127.0.0.1:8080"
WS = "ws://127.0.0.1:8080/v1/realtime"
HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
os.makedirs(LOGS, exist_ok=True)

# ---------------------------------------------------------------- canvas tools
TOOLS = [
    {"name": "create_widget", "description": "Show a new widget on the canvas.",
     "parameters": {"type": "object", "properties": {
         "type": {"type": "string", "enum": ["recipe", "ingredients", "timer", "note", "list"]},
         "title": {"type": "string"},
         "props": {"type": "object", "description": "Widget data, e.g. {\"servings\": 4}"}},
         "required": ["type", "title"]}},
    {"name": "update_widget", "description": "Change an existing widget's data.",
     "parameters": {"type": "object", "properties": {
         "id": {"type": "string"}, "props": {"type": "object"}}, "required": ["id", "props"]}},
    {"name": "remove_widget", "description": "Remove one widget from the canvas.",
     "parameters": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}},
    {"name": "clear_canvas", "description": "Remove all widgets when the user is done.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "start_timer", "description": "Start a countdown timer.",
     "parameters": {"type": "object", "properties": {
         "minutes": {"type": "number"}, "label": {"type": "string"}}, "required": ["minutes"]}},
    {"name": "escalate", "description": "Hand a hard task (planning, charts, research, new widget types) to the cloud model.",
     "parameters": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}},
]
CHAT_TOOLS = [{"type": "function", "function": t} for t in TOOLS]
RT_TOOLS = [{"type": "function", **t} for t in TOOLS]

CANVAS_SYS = ("You control a visual canvas by calling tools. Always act with a tool call; "
              "reply with at most one short sentence. Current canvas: {canvas}")
EMPTY = "empty"
COOKING = ('[{"id":"w1","type":"recipe","title":"Pasta","props":{"servings":4}},'
           '{"id":"w2","type":"ingredients","title":"Ingredients","props":{"servings":4}}]')

# (prompt, canvas, acceptable tool names, arg check)
TOOL_CASES = [
    ("I'm cooking pasta for four", EMPTY, {"create_widget"}, None),
    ("Start a 10 minute timer for the pasta", COOKING, {"start_timer"}, lambda a: float(a.get("minutes", 0)) == 10),
    ("Actually make it for six", COOKING, {"update_widget"}, lambda a: "6" in json.dumps(a.get("props", {}))),
    ("Remove the ingredients list", COOKING, {"remove_widget"}, lambda a: a.get("id") == "w2"),
    ("I'm done", COOKING, {"clear_canvas"}, None),
    ("Plan my macros for these meals and chart it", COOKING, {"escalate"}, None),
    ("Add a note: buy more parmesan", EMPTY, {"create_widget"}, lambda a: a.get("type") in ("note", "list")),
    ("Set a timer for 90 seconds", EMPTY, {"start_timer"}, lambda a: abs(float(a.get("minutes", 0)) - 1.5) < 0.01),
]


# ---------------------------------------------------------------- helpers
def log(test, **data):
    data |= {"test": test, "ts": time.strftime("%H:%M:%S")}
    with open(os.path.join(LOGS, "test_results.jsonl"), "a") as f:
        f.write(json.dumps(data) + "\n")


def chat(messages, **kw):
    body = json.dumps({"messages": messages, "temperature": 0, **kw}).encode()
    req = urllib.request.Request(f"{HTTP}/v1/chat/completions", body, {"content-type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.load(r)
    return d, time.time() - t0


def mem_free():
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout.strip().splitlines()[-1]
    return out.split()[-1]


def save_wav(path, pcm, rate=24000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)


def speech_seconds(pcm, rate=24000, thresh=300):
    """Seconds of audio louder than `thresh` RMS (in 100 ms windows) and the trailing quiet tail."""
    import array
    a = array.array("h", pcm)
    win = rate // 10
    loud = [((sum(x * x for x in a[i:i + win]) / max(1, len(a[i:i + win]))) ** 0.5) > thresh
            for i in range(0, len(a), win)]
    last = max((i for i, v in enumerate(loud) if v), default=-1)
    return sum(loud) / 10, (len(loud) - 1 - last) / 10


class RT:
    """Minimal realtime client: one session, many turns."""

    def __init__(self, ws):
        self.ws = ws

    @classmethod
    async def open(cls, instructions="", tools=None, voice="female", modalities=("text", "audio")):
        ws = await websockets.connect(WS, max_size=None)
        await ws.recv()  # session.created
        s = {"type": "realtime", "instructions": instructions, "output_modalities": list(modalities),
             "audio": {"output": {"voice": voice}}}
        if tools:
            s["tools"] = tools
        await ws.send(json.dumps({"type": "session.update", "session": s}))
        return cls(ws)

    async def say_text(self, text):
        await self.ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}))

    async def say_audio(self, pcm16_16k):
        for i in range(0, len(pcm16_16k), 32000):
            await self.ws.send(json.dumps({"type": "input_audio_buffer.append",
                                           "audio": base64.b64encode(pcm16_16k[i:i + 32000]).decode()}))
        await self.ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def tool_result(self, call_id, output):
        await self.ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(output)}}))

    async def respond(self, modalities=None, max_tokens=None):
        r = {}
        if modalities:
            r["output_modalities"] = list(modalities)
        if max_tokens:
            r["max_output_tokens"] = max_tokens
        await self.ws.send(json.dumps({"type": "response.create", **({"response": r} if r else {})}))
        t0, res = time.time(), {"text": "", "pcm": b"", "calls": [], "transcript": "", "ttfa": None, "errors": []}
        while True:
            ev = json.loads(await asyncio.wait_for(self.ws.recv(), 150))
            t = ev["type"]
            if t == "error":
                res["errors"].append(ev.get("error", ev)); break
            elif t == "response.output_text.delta":
                res["text"] += ev["delta"]
            elif t == "response.output_audio.delta":
                res["ttfa"] = res["ttfa"] or round(time.time() - t0, 2)
                res["pcm"] += base64.b64decode(ev["delta"])
            elif t == "response.function_call_arguments.done":
                res["calls"].append({"name": ev.get("name"), "call_id": ev.get("call_id"),
                                     "arguments": ev.get("arguments")})
            elif t == "conversation.item.input_audio_transcription.completed":
                res["transcript"] = ev.get("transcript", "")
            elif t == "response.done":
                if not res["calls"]:  # fall back to output items if args event lacked names
                    for item in ev.get("response", {}).get("output", []):
                        if item.get("type") == "function_call":
                            res["calls"].append({k: item.get(k) for k in ("name", "call_id", "arguments")})
                break
        res["secs"] = round(time.time() - t0, 2)
        res["audio_s"] = round(len(res["pcm"]) / 48000, 1)
        return res

    async def close(self):
        await self.ws.close()


def check_call(name, args_raw, ok_names, check):
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
    except json.JSONDecodeError:
        return False, "invalid JSON args"
    if name not in ok_names:
        return False, f"wrong tool {name}"
    try:
        if check and not check(args):
            return False, "args off"
    except Exception as e:
        return False, f"args off ({e})"
    return True, "ok"


# ---------------------------------------------------------------- tests
def t_tools():
    print("\n== Tool calling via /v1/chat/completions")
    passed = 0
    for prompt, canvas, ok_names, check in TOOL_CASES:
        d, dt = chat([{"role": "system", "content": CANVAS_SYS.format(canvas=canvas)},
                      {"role": "user", "content": prompt}], tools=CHAT_TOOLS)
        msg = d["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if calls:
            fn = calls[0]["function"]
            ok, why = check_call(fn["name"], fn["arguments"], ok_names, check)
            shown = f'{fn["name"]}({fn["arguments"]})'
        else:
            ok, why, shown = False, "no tool call", repr(msg.get("content"))
        passed += ok
        print(f'  {"PASS" if ok else "FAIL"} {dt:4.1f}s  "{prompt}" -> {shown[:110]}  [{why}]')
        log("tools", prompt=prompt, ok=ok, why=why, secs=round(dt, 2), call=shown, n_calls=len(calls))
    print(f"  {passed}/{len(TOOL_CASES)} passed")
    return passed, len(TOOL_CASES)


async def t_rt_tools():
    print("\n== Tool calling via /v1/realtime (+ spoken confirmation after tool result)")
    passed = 0
    for prompt, canvas, ok_names, check in TOOL_CASES[:4]:
        rt = await RT.open(CANVAS_SYS.format(canvas=canvas), RT_TOOLS)
        await rt.say_text(prompt)
        r = await rt.respond(modalities=["text"])
        if r["calls"]:
            c = r["calls"][0]
            ok, why = check_call(c["name"], c["arguments"], ok_names, check)
            await rt.tool_result(c["call_id"], {"ok": True})
            r2 = await rt.respond(modalities=["text", "audio"])
            spoken = f'then said {r2["text"]!r} ({r2["audio_s"]}s audio, {r2["secs"]}s)'
            if r2["pcm"]:
                save_wav(os.path.join(LOGS, f"rt_tool_{passed}.wav"), r2["pcm"])
        else:
            ok, why, spoken = False, "no tool call", f'text={r["text"]!r} errors={r["errors"]}'
        passed += ok
        call = f'{r["calls"][0]["name"]}({r["calls"][0]["arguments"]})' if r["calls"] else "-"
        print(f'  {"PASS" if ok else "FAIL"} {r["secs"]:4.1f}s  "{prompt}" -> {call[:90]}  [{why}]\n        {spoken}')
        log("rt_tools", prompt=prompt, ok=ok, why=why, secs=r["secs"], call=call, followup=spoken)
        await rt.close()
    print(f"  {passed}/4 passed")
    return passed, 4


async def t_tones():
    print("\n== Tones (text + speech, same question)")
    q = "I keep getting distracted while studying. Any advice?"
    for tone in TONES:
        rt = await RT.open(TONES[tone] + VOICE_SUFFIX)
        await rt.say_text(q)
        r = await rt.respond()
        speech, tail = speech_seconds(r["pcm"])
        save_wav(os.path.join(LOGS, f"tone_{tone}.wav"), r["pcm"])
        print(f'  {tone:9s} {r["secs"]:4.1f}s first audio {r["ttfa"]}s, audio {r["audio_s"]}s '
              f'(speech {speech}s, silent tail {tail}s)\n            {r["text"]!r}')
        log("tones", tone=tone, text=r["text"], secs=r["secs"], audio_s=r["audio_s"], tail_s=tail)
        await rt.close()


async def t_multiturn():
    print("\n== Multi-turn session, switching modes per reply")
    rt = await RT.open(TONES["friendly"] + VOICE_SUFFIX)
    turns = [("My name is Sam and I'm making lasagna.", ["text"]),
             ("How long should it bake?", ["text", "audio"]),
             ("What's my name and what am I cooking?", ["text"]),
             ("Say goodbye to me.", ["text", "audio"])]
    for text, mode in turns:
        await rt.say_text(text)
        r = await rt.respond(modalities=mode)
        ok = (bool(r["pcm"]) == ("audio" in mode)) and not r["errors"]
        heard = ""
        if r["pcm"]:
            save_wav(os.path.join(LOGS, f"multiturn_{turns.index((text, mode))}.wav"), r["pcm"])
            heard = asr(r["pcm"])
            ok = ok and overlap(r["text"], heard) >= 0.8
        print(f'  {"PASS" if ok else "FAIL"} {"+".join(mode):10s} {r["secs"]:4.1f}s audio {r["audio_s"]}s  '
              f'"{text}" -> {r["text"]!r}{" ERR " + str(r["errors"]) if r["errors"] else ""}')
        if heard:
            print(f'        heard: {heard!r} ({overlap(r["text"], heard):.0%} match)')
        log("multiturn", prompt=text, mode=mode, ok=ok, text=r["text"], secs=r["secs"], audio_s=r["audio_s"])
    await rt.close()
    print(f"  memory free: {mem_free()}")


async def t_audio_only():
    print("\n== Speech-only mode: repeat + max_output_tokens cap")
    for cap in (None, None, 120):
        rt = await RT.open("Keep replies to one short sentence.", modalities=("audio",))
        await rt.say_text("Say hello in one short sentence.")
        r = await rt.respond(max_tokens=cap)
        speech, tail = speech_seconds(r["pcm"])
        print(f'  cap={cap}: {r["secs"]}s, audio {r["audio_s"]}s (speech {speech}s, silent tail {tail}s)')
        log("audio_only", cap=cap, secs=r["secs"], audio_s=r["audio_s"], speech_s=speech, tail_s=tail)
        await rt.close()


async def t_voice_in():
    print("\n== Voice input (macOS `say` -> 16 kHz PCM -> realtime), with tools")
    lines = ["I'm cooking pasta for four", "Start a ten minute timer"]
    for i, line in enumerate(lines):
        path = os.path.join(LOGS, f"voice_in_{i}.wav")
        subprocess.run(["say", "-o", path, "--data-format=LEI16@16000", line], check=True)
        with wave.open(path) as w:
            pcm = w.readframes(w.getnframes())
        canvas = EMPTY if i == 0 else COOKING
        rt = await RT.open(CANVAS_SYS.format(canvas=canvas), RT_TOOLS)
        await rt.say_audio(pcm)
        r = await rt.respond(modalities=["text"])
        call = f'{r["calls"][0]["name"]}({r["calls"][0]["arguments"]})' if r["calls"] else "-"
        ok = bool(r["calls"]) and r["calls"][0]["name"] == ("create_widget", "start_timer")[i]
        print(f'  {"PASS" if ok else "FAIL"} {r["secs"]:4.1f}s  said "{line}" -> {call[:100]}'
              f'{"  text=" + repr(r["text"]) if r["text"] else ""}{" ERR " + str(r["errors"]) if r["errors"] else ""}')
        log("voice_in", line=line, ok=ok, secs=r["secs"], call=call, text=r["text"], errors=r["errors"])
        await rt.close()


def t_vision():
    print("\n== Image input via /v1/chat/completions")
    src = "/Library/User Pictures/Animals/Penguin.heic"
    jpg = os.path.join(LOGS, "vision_penguin.jpg")
    subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "512", src, "--out", jpg], capture_output=True, check=True)
    b64 = base64.b64encode(open(jpg, "rb").read()).decode()
    d, dt = chat([{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        {"type": "text", "text": "What animal is this? Answer in one sentence."}]}])
    text = d["choices"][0]["message"]["content"]
    ok = "penguin" in text.lower()
    print(f'  {"PASS" if ok else "FAIL"} {dt:4.1f}s  -> {text!r}')
    log("vision", ok=ok, secs=round(dt, 2), text=text)


VIDEO_CASES = [  # (video, question, words that must all appear (any-of groups))
    ("camera.mp4", "What animals appear in this video, in order?", [("penguin",), ("zebra",), ("parrot", "macaw")]),
    ("camera.mp4", "Which animal does the speaker say is their favorite?", [("parrot", "macaw", "colorful")]),
    ("screen.mp4", "What is happening on this phone screen?", [("timer", "countdown"), ("carbonara", "recipe", "spaghetti")]),
    ("screen.mp4", "Who sent the message notification and what does it say?", [("mom",), ("7", "seven"), ("dessert",)]),
    ("screen.mp4", "How many people does the recipe serve?", [("4", "four")]),
    ("museum.mp4", "What artwork is this and who made it?", [("night harbor",), ("elena varga", "varga")]),
    ("museum.mp4", "When was it painted and where?", [("1912",), ("trieste",)]),
]


def video_uri(name):
    return "data:video/mp4;base64," + base64.b64encode(open(os.path.join(HERE, "videos", name), "rb").read()).decode()


def t_video():
    print("\n== Video in (chat endpoint), friendly tone")
    passed = 0
    for i, (vid, q, must) in enumerate(VIDEO_CASES):
        try:
            d, dt = chat([{"role": "system", "content": TONES["friendly"]},
                          {"role": "user", "content": [{"type": "video_url", "video_url": {"url": video_uri(vid)}},
                                                       {"type": "text", "text": q}]}])
            text = d["choices"][0]["message"]["content"].strip()
            ptoks = d.get("timings", {}).get("prompt_n")
        except urllib.error.HTTPError as e:
            text, dt, ptoks = f"HTTP {e.code}: {e.read()[:200]!r}", 0, None
        low = text.lower()
        ok = all(any(w in low for w in grp) for grp in must)
        passed += ok
        print(f'  {"PASS" if ok else "FAIL"} {dt:4.1f}s {ptoks} prompt tokens  [{vid}] "{q}"\n        -> {text!r}')
        log("video", prompt=f"{vid}|{q}", video=vid, q=q, ok=ok, secs=round(dt, 2), text=text, prompt_tokens=ptoks)
    print(f"  {passed}/{len(VIDEO_CASES)} passed")


def asr(pcm24k):
    """Transcribe 24 kHz PCM16 with the model's own ASR (resampled to 16 kHz via afconvert)."""
    src, dst = os.path.join(LOGS, "_asr_in.wav"), os.path.join(LOGS, "_asr_16k.wav")
    save_wav(src, pcm24k)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", src, dst], check=True)
    b64 = base64.b64encode(open(dst, "rb").read()).decode()
    d, _ = chat([{"role": "system", "content": "Perform ASR in English."},
                 {"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": b64, "format": "wav"}}]}])
    return d["choices"][0]["message"]["content"].strip()


def overlap(a, b):
    """Share of words in `a` that also appear in `b` (rough match score)."""
    norm = lambda s: [w.strip(".,!?'\"“”‘’").lower() for w in s.split() if w.strip(".,!?'\"“”‘’")]
    wa, wb = norm(a), set(norm(b))
    return round(sum(w in wb for w in wa) / max(1, len(wa)), 2)


async def t_speech_match():
    print("\n== Does the speech say the same thing as the text? (text+speech, checked with model ASR)")
    prompts = ["How long should lasagna bake?",
               "Give me two tips for staying focused while studying.",
               "What can I make with eggs, spinach and cheese?",
               "Say hello in one short sentence."]
    for i, p in enumerate(prompts):
        rt = await RT.open(TONES["friendly"] + VOICE_SUFFIX)
        await rt.say_text(p)
        r = await rt.respond()
        await rt.close()
        save_wav(os.path.join(LOGS, f"match_{i}.wav"), r["pcm"])
        heard = asr(r["pcm"]) if r["pcm"] else ""
        score = overlap(r["text"], heard)
        speech, tail = speech_seconds(r["pcm"])
        ok = score >= 0.8
        print(f'  {"PASS" if ok else "FAIL"} match {score:.0%}  audio {r["audio_s"]}s (speech {speech}s)  "{p}"\n'
              f'        text : {r["text"]!r}\n        heard: {heard!r}')
        log("speech_match", prompt=p, ok=ok, score=score, text=r["text"], heard=heard, audio_s=r["audio_s"])


TESTS = {"video": t_video, "speech_match": t_speech_match, "tools": t_tools, "rt_tools": t_rt_tools, "tones": t_tones, "multiturn": t_multiturn,
         "audio_only": t_audio_only, "voice_in": t_voice_in, "vision": t_vision}

if __name__ == "__main__":
    names = sys.argv[1:] or ["all"]
    if names == ["all"]:
        names = list(TESTS)
    for n in names:
        fn = TESTS[n]
        try:
            asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
        except Exception as e:
            print(f"  {n} CRASHED: {type(e).__name__}: {e}")
            log(n, crashed=f"{type(e).__name__}: {e}")
    print(f"\nmemory free: {mem_free()}")
