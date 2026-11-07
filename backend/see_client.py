"""Fake desktop orb for "eyes on request": sends one `see` frame (a JPEG + a question) and checks the spoken answer.

    ORCH_PORT=8766 python3 backend/see_client.py                          # prototype/logs/see_test.jpg, default question
    ORCH_PORT=8766 python3 backend/see_client.py photo.jpg "What colour is the mug?"

No JPEG handy? On the Mac: screencapture -x -t jpg prototype/logs/see_test.jpg

First it sends three bad frames (no image, not base64, too big) and checks each one gets an `error` back.
Then the real frame: it must come back as speech_start, binary PCM16 24 kHz audio, speech_end with text.
Exits 1 if anything is missing. The reply audio is saved to prototype/logs/see_<n>.wav like voice_client.py.
"""
from __future__ import annotations

import asyncio, base64, json, os, sys, time

import websockets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from voice_client import reply, save  # noqa: E402  (same speech-collecting helper as the voice test)

PORT = int(os.environ.get("ORCH_PORT", 8765))
URL = f"ws://localhost:{PORT}/canvas"
DEFAULT_IMAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "prototype", "logs", "see_test.jpg")
MAX_IMAGE_BYTES = 1_500_000


async def expect_error(ws, frame: dict, what: str) -> bool:
    await ws.send(json.dumps(frame))
    try:
        ev = json.loads(await asyncio.wait_for(ws.recv(), 5))
    except asyncio.TimeoutError:
        print(f"[bad frame] {what}: NO error message (timeout)")
        return False
    ok = ev.get("type") == "error"
    print(f"[bad frame] {what}: {'ok' if ok else 'FAILED'} -> {ev.get('text')!r}")
    return ok


async def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE
    question = sys.argv[2] if len(sys.argv) > 2 else "What am I looking at?"
    if not os.path.exists(path):
        sys.exit(f"no image at {path} (see the docstring for a one-line screencapture)")
    jpeg = open(path, "rb").read()
    if len(jpeg) > MAX_IMAGE_BYTES or not jpeg.startswith(b"\xff\xd8"):
        sys.exit(f"{path} must be a JPEG under {MAX_IMAGE_BYTES} bytes")

    ok = True
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "widgets": [], "mode": "voice"}))
        ok &= await expect_error(ws, {"type": "see", "source": "camera"}, "no image")
        ok &= await expect_error(ws, {"type": "see", "source": "camera", "image": "not base64!!"}, "not base64")
        ok &= await expect_error(ws, {"type": "see", "source": "camera",
                                      "image": "A" * (MAX_IMAGE_BYTES * 4 // 3 + 100)}, "too big")

        frame = {"type": "see", "source": "camera", "image": base64.b64encode(jpeg).decode(), "question": question}
        t0 = time.time()
        await ws.send(json.dumps(frame))
        text, pcm, first, _ = await reply(ws, t0)
        print(f"[see] {question!r} ({len(jpeg)} bytes JPEG): first audio {first or -1:.2f}s, "
              f"{len(pcm) / 48000:.1f}s speech, done {time.time() - t0:.1f}s -> {save(pcm, 200)}\n    {text!r}")
        if not pcm or not text:
            print("[see] FAILED: no spoken reply with audio and text")
            ok = False
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
