"""Probe llama-server /v1/realtime: which output_modalities work, and where they can be set."""
import asyncio, base64, json, sys, time, wave
import websockets

URL = "ws://127.0.0.1:8080/v1/realtime"


async def run(label, session, response=None, text="Say hello in one short sentence."):
    async with websockets.connect(URL, max_size=None) as ws:
        first = json.loads(await ws.recv())
        if session:
            await ws.send(json.dumps({"type": "session.update", "session": session}))
        await ws.send(json.dumps({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}}))
        await ws.send(json.dumps({"type": "response.create", **({"response": response} if response else {})}))
        t0, ttfa, txt, pcm, rate, types = time.time(), None, "", b"", 24000, []
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), 120))
            t = ev["type"]; types.append(t)
            if t == "error":
                print(f"[{label}] ERROR {ev}"); return
            if t == "session.updated":
                fmt = ev["session"].get("audio", {}).get("output", {}).get("format", {})
                rate = fmt.get("rate", rate)
            if t == "response.output_text.delta":
                txt += ev["delta"]
            if t == "response.output_audio.delta":
                ttfa = ttfa or time.time() - t0
                pcm += base64.b64decode(ev["delta"])
            if t == "response.done":
                break
        dt = time.time() - t0
        out = None
        if pcm:
            out = f"logs/probe_{label}.wav"
            with wave.open(out, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm)
        uniq = sorted(set(types))
        print(f"[{label}] {dt:.1f}s total, first audio {ttfa and round(ttfa,2)}s, text={txt!r}, "
              f"audio={len(pcm)/2/rate:.1f}s@{rate}Hz -> {out}\n    first_event={first['type']} events={uniq}")


CASES = {
    "default": (None, None),
    "sess_text": ({"type": "realtime", "output_modalities": ["text"]}, None),
    "sess_audio": ({"type": "realtime", "output_modalities": ["audio"], "audio": {"output": {"voice": "male"}}}, None),
    "sess_both": ({"type": "realtime", "output_modalities": ["text", "audio"]}, None),
    "resp_text": ({"type": "realtime", "output_modalities": ["audio"]}, {"output_modalities": ["text"]}),
}


async def main():
    for label in sys.argv[1:] or CASES:
        try:
            await asyncio.wait_for(run(label, *CASES[label]), 150)
        except Exception as e:
            print(f"[{label}] FAILED {type(e).__name__}: {e}")


asyncio.run(main())
