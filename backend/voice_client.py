"""Fake desktop orb for the voice mode: talks to the orchestrator like ui/ does with `hello {mode:"voice"}`.

    ORCH_PORT=8766 python3 backend/voice_client.py                 # scripted lines + an interrupt test
    ORCH_PORT=8766 python3 backend/voice_client.py some.wav        # push to talk 3x with a 16 kHz mono wav, streamed in real time

For each reply it measures first-audio time, speech length and trailing silence, and saves the
streamed audio to prototype/logs/voice_<n>.wav (gitignored) so you can listen to it.
"""
from __future__ import annotations

import array, asyncio, json, os, sys, time, wave

import websockets

PORT = int(os.environ.get("ORCH_PORT", 8765))
URL = f"ws://localhost:{PORT}/canvas"
LOGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prototype", "logs")

LINES = [
    "Hey Nova, how's it going?",
    "What's a quick dinner I can make with eggs and spinach?",
    "How long should I boil the eggs for a soft yolk?",
    "Thanks!",
]


def trailing_silence(pcm: bytes, rate=24000, rms=300) -> float:
    a = array.array("h", pcm[: len(pcm) // 2 * 2])
    win = int(rate * 0.03)
    end = len(a)
    while end - win > 0:
        seg = a[end - win:end]
        if (sum(x * x for x in seg) / win) ** 0.5 > rms:
            break
        end -= win
    return round((len(a) - end) / rate, 2)


def save(pcm: bytes, n: int) -> str:
    os.makedirs(LOGS, exist_ok=True)
    path = os.path.join(LOGS, f"voice_{n}.wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    return os.path.relpath(path)


async def reply(ws, t0: float, interrupt_after: float | None = None):
    """Collect one reply. Returns (text, pcm, first_audio_s, interrupted_at)."""
    pcm, first, text, cut = bytearray(), None, "", None
    while True:
        m = await asyncio.wait_for(ws.recv(), 120)
        if isinstance(m, bytes):
            first = first or time.time() - t0
            pcm += m
            if interrupt_after and cut is None and len(pcm) / 48000 >= interrupt_after:
                cut = time.time()
                await ws.send(json.dumps({"type": "orb_down"}))
                await ws.send(json.dumps({"type": "orb_cancel"}))
            continue
        ev = json.loads(m)
        if ev["type"] == "speech_end":
            text = ev.get("text", "")
        elif ev["type"] == "say":
            text = "(say) " + ev["text"]
        elif ev["type"] == "orb" and ev["state"] == "idle":
            return text, bytes(pcm), first, cut


async def main():
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "widgets": [], "mode": "voice"}))
        n = 0
        if len(sys.argv) > 1:  # one spoken utterance from a wav file
            with wave.open(sys.argv[1]) as w:
                assert w.getframerate() == 16000 and w.getnchannels() == 1, "need 16 kHz mono"
                audio = w.readframes(w.getnframes())
            for n in range(1, 4):  # push to talk: frames sent in real time while "holding", like the orb does
                await ws.send(json.dumps({"type": "orb_down"}))
                for i in range(0, len(audio), 960):
                    await ws.send(audio[i:i + 960])
                    await asyncio.sleep(0.03)
                t0 = time.time()
                await ws.send(json.dumps({"type": "orb_up"}))
                text, pcm, first, _ = await reply(ws, t0)
                print(f"[hold {n}] first audio {first or -1:.2f}s after release, {len(pcm) / 48000:.1f}s speech "
                      f"-> {save(pcm, 100 + n)}\n    {text!r}")
            return
        for line in LINES:
            n += 1
            t0 = time.time()
            await ws.send(json.dumps({"type": "text", "text": line}))
            text, pcm, first, _ = await reply(ws, t0)
            print(f"[{n}] {line!r}\n    first audio {first or -1:.2f}s, {len(pcm) / 48000:.1f}s speech, "
                  f"tail silence {trailing_silence(pcm)}s, done {time.time() - t0:.1f}s -> {save(pcm, n)}\n    {text!r}")
        # barge-in: ask for something long, interrupt after 1.5 s of audio
        n += 1
        t0 = time.time()
        await ws.send(json.dumps({"type": "text", "text": "Tell me a long story about a lighthouse keeper and a cat."}))
        text, pcm, first, cut = await reply(ws, t0, interrupt_after=1.5)
        print(f"[{n}] interrupt test: first audio {first or -1:.2f}s, {len(pcm) / 48000:.1f}s audio received, "
              f"turn ended {time.time() - cut:.2f}s after orb_down" if cut else f"[{n}] reply too short to interrupt")
        # and the next turn must still work
        n += 1
        t0 = time.time()
        await ws.send(json.dumps({"type": "text", "text": "Never mind. What's two plus two?"}))
        text, pcm, first, _ = await reply(ws, t0)
        print(f"[{n}] after interrupt: first audio {first or -1:.2f}s, {len(pcm) / 48000:.1f}s speech -> {save(pcm, n)}\n    {text!r}")


if __name__ == "__main__":
    asyncio.run(main())
