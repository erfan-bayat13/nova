"""Fake desktop orb for creator mode: speaks a few requests (macOS `say`) into the voice path and prints what the
canvas would do. No mic, no Electron: it streams the audio in real time between orb_down and orb_up, like the orb.

    ORCH_PORT=8766 python3 backend/creator_client.py                         # pasta -> six -> timer -> chat -> done
    ORCH_PORT=8766 python3 backend/creator_client.py "I'm making pancakes for two" "Make it for eight"

Run it with the orb app QUIT and exactly one orchestrator: a second connection takes llama-server's last slot and the
builder hangs. Each turn prints Nova's spoken line and every canvas message (create/update/remove/clear/pending); the
client echoes canvas_state like the real canvas does, so follow-ups ("make it for six") see what is on screen.
"""
from __future__ import annotations

import asyncio, json, os, subprocess, sys, tempfile, time, wave

import websockets

URL = f"ws://localhost:{int(os.environ.get('ORCH_PORT', 8765))}/canvas"
DEFAULT = ["I'm cooking pasta for four people", "Make it for six", "Start a ten minute timer for the oven",
           "How long does pasta take to cook", "I'm done, thanks"]


def speak(text: str, tmp: str) -> bytes:
    aiff, wav = os.path.join(tmp, "s.aiff"), os.path.join(tmp, "s.wav")
    subprocess.run(["say", "-r", "170", "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    w = wave.open(wav)
    return w.readframes(w.getnframes())


async def main(lines: list[str], settle: float = 25):
    canvas: dict = {}
    t00 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        async with websockets.connect(URL, max_size=None) as ws:
            await ws.send(json.dumps({"type": "hello", "widgets": [], "mode": "voice"}))

            async def pump(seconds: float) -> str:
                end, said = time.time() + seconds, ""
                while time.time() < end:
                    try:
                        m = await asyncio.wait_for(ws.recv(), max(0.05, end - time.time()))
                    except asyncio.TimeoutError:
                        break
                    if isinstance(m, bytes):
                        continue
                    j = json.loads(m)
                    t = j["type"]
                    if t == "speech_end":
                        said = j.get("text", "")
                        print(f"   [{time.time() - t00:5.1f}s] nova says: {said!r} ({len(said.split())} words)")
                    if t in ("create", "update", "remove", "clear", "pending"):
                        print(f"   [{time.time() - t00:5.1f}s] canvas {t} {j.get('id', '')} {j.get('widget', '')} "
                              f"{json.dumps(j.get('props', ''))[:80]}")
                        if t == "create":
                            canvas[j["id"]] = {"widget": j["widget"], "props": j["props"]}
                        elif t == "update" and j["id"] in canvas:
                            canvas[j["id"]]["props"].update(j["props"])
                        elif t == "remove":
                            canvas.pop(j["id"], None)
                        elif t == "clear":
                            canvas.clear()
                        await ws.send(json.dumps({"type": "canvas_state", "widgets": [
                            {"id": i, "widget": w["widget"], "props": w["props"]} for i, w in canvas.items()]}))
                return said

            for line in lines:
                data = speak(line, tmp)
                print(f"you (spoken): {line}")
                await ws.send(json.dumps({"type": "orb_down"}))
                for i in range(0, len(data), 3200):  # 100 ms of 16 kHz PCM16 at a time, in real time
                    await ws.send(data[i:i + 3200])
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.2)
                await ws.send(json.dumps({"type": "orb_up"}))
                await pump(settle)
    print("final canvas:", list(canvas))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DEFAULT))
