"""Fake canvas for testing the orchestrator without the UI.

Plays the demo script (text via the dev `text` message, and one line as real audio via `say`),
prints every message the orchestrator sends, and echoes canvas_state like the real canvas does.

    ORCH_PORT=8766 python3 backend/orchestrator.py      # terminal 1
    ORCH_PORT=8766 python3 backend/test_client.py       # terminal 2
"""
import asyncio, json, os, subprocess, sys, tempfile, time, wave

import websockets

URL = f"ws://localhost:{os.environ.get('ORCH_PORT', 8765)}/canvas"
WIDGETS = ["recipe", "checklist", "timer", "stacked_bar", "html"]
SCRIPT = [
    ("text", "I'm cooking pasta for four."),
    ("text", "Actually make it for six, and start a ten-minute timer."),
    ("voice", "Add parmesan to the ingredients."),
    ("event", ("timer", "timer_done", {"label": "Pasta"})),
    ("text", "Plan my macros for these meals this week and chart it."),
    ("text", "I'm done."),
]


def speech_pcm(text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.wav")
        subprocess.run(["say", "-o", p, "--data-format=LEI16@16000", text], check=True)
        with wave.open(p) as w:
            return w.readframes(w.getnframes())


async def main():
    canvas = {}
    async with websockets.connect(URL, max_size=None) as ws:
        async def state():
            await ws.send(json.dumps({"type": "canvas_state", "widgets": [
                {"id": k, "widget": v["widget"], "props": v["props"]} for k, v in canvas.items()]}))

        async def run_until_idle(timeout=90):
            t0, saw_busy = time.time(), False
            while time.time() - t0 < timeout:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), 15))
                except asyncio.TimeoutError:
                    if saw_busy:
                        return
                    continue
                t = m["type"]
                stamp = f"{time.time() - t0:5.1f}s"
                if t == "orb":
                    print(f"  {stamp} orb {m['state']}")
                    if m["state"] in ("thinking", "working"):
                        saw_busy = True
                    if m["state"] == "idle" and saw_busy:
                        await asyncio.sleep(0.3)
                        return
                elif t == "create":
                    canvas[m["id"]] = {"widget": m["widget"], "props": m["props"]}
                    print(f"  {stamp} create {m['id']} ({m['widget']}, {m['importance']}) {json.dumps(m['props'])[:110]}")
                elif t == "update":
                    if m["id"] in canvas:
                        canvas[m["id"]]["props"].update(m["props"])
                    print(f"  {stamp} update {m['id']} {json.dumps(m['props'])[:110]}")
                elif t == "remove":
                    canvas.pop(m["id"], None); print(f"  {stamp} remove {m['id']}")
                elif t == "clear":
                    canvas.clear(); print(f"  {stamp} clear")
                elif t == "pending":
                    print(f"  {stamp} pending {m['id']} ({m['importance']})")
                elif t == "say":
                    print(f"  {stamp} SAY {m['text']!r}")
                if t in ("create", "update", "remove", "clear"):
                    await state()

        await ws.send(json.dumps({"type": "hello", "widgets": WIDGETS}))
        await state()
        for kind, payload in SCRIPT:
            if kind == "text":
                print(f"\nyou (text): {payload}")
                await ws.send(json.dumps({"type": "text", "text": payload}))
            elif kind == "voice":
                print(f"\nyou (voice): {payload}")
                pcm = speech_pcm(payload)
                await ws.send(json.dumps({"type": "orb_down"}))
                for i in range(0, len(pcm), 3200):  # 100 ms frames, like a mic would send
                    await ws.send(pcm[i:i + 3200])
                await ws.send(json.dumps({"type": "orb_up"}))
            elif kind == "event":
                wid, name, data = payload
                print(f"\ncanvas event: {wid}.{name} {data}")
                await ws.send(json.dumps({"type": "event", "id": wid, "name": name, "data": data}))
                await asyncio.sleep(0.5)
            await run_until_idle()
        print(f"\nfinal canvas: {list(canvas)}")


if __name__ == "__main__":
    asyncio.run(main())
