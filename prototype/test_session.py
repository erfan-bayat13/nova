"""Tests for session_manager.py.

python3 test_session.py rotation   # tiny budget -> many rotations, memory must survive
python3 test_session.py tools      # tool call -> tool result -> spoken confirmation through the manager
python3 test_session.py long       # real budget (6000), 160 mixed turns, must never crash the server
python3 test_session.py crash      # rotation OFF: run until the server crashes, check auto-restart + recovery
"""
import asyncio, json, os, sys, time, wave

from router import TONES, VOICE_SUFFIX
from session_manager import SessionManager, ServerWatchdog, healthy
from tests import TOOLS, CANVAS_SYS, mem_free

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
FACTS = "My name is Sam, my dog is called Biscuit, and I'm allergic to peanuts."
CHECK = "Quick check: what's my name, my dog's name, and what am I allergic to?"
FILLER = ["Give me a tip for cooking rice.", "What's a good stretch for my back?", "Suggest a name for a houseplant.",
          "How do I keep basil fresh?", "Tell me a fun fact about octopuses.", "What's a quick breakfast idea?"]
VOICE = [wave.open(os.path.join(LOGS, f"voice_in_{i}.wav")).readframes(10**9) for i in (0, 1)]


def recall(text):
    low = text.lower()
    return sum(k in low for k in ("sam", "biscuit", "peanut"))


def log(**d):
    with open(os.path.join(LOGS, "session_results.jsonl"), "a") as f:
        f.write(json.dumps(d | {"ts": time.strftime("%H:%M:%S")}) + "\n")


async def conversation(sm, turns, label, check_every=10):
    r = await sm.send_text(FACTS)
    worst, rot_secs = 3, []
    for t in range(1, turns + 1):
        t0 = time.time()
        if t % 7 == 0:
            r = await sm.send_audio(VOICE[t % 2], modalities=("text",))
            kind = "voice in"
        elif t % 4 == 0:
            r = await sm.send_text(FILLER[t % len(FILLER)], modalities=("text", "audio"))
            kind = "speech out"
        else:
            r = await sm.send_text(FILLER[t % len(FILLER)])
            kind = "text"
        if r.rotated:
            rot_secs.append(round(time.time() - t0 - r.secs, 1))
        if r.recovered:
            print(f"  turn {t:3d}: RECOVERED from server crash (est at crash {sm.est_at_crash[-1]})")
        if t % check_every == 0:
            rc = await sm.send_text(CHECK)
            k = recall(rc.text)
            worst = min(worst, k)
            print(f"  turn {t:3d}: recall {k}/3, est {sm.est:5d} tok, rotations {sm.rotations}, "
                  f"recoveries {sm.recoveries}  {rc.text[:80]!r}")
            log(test=label, turn=t, recall=k, est=sm.est, rotations=sm.rotations, recoveries=sm.recoveries,
                reply=rc.text)
    return worst, rot_secs


async def t_rotation():
    print("\n== Rotation with a tiny budget (rotate_at=1500)")
    sm = SessionManager(TONES["friendly"] + VOICE_SUFFIX, rotate_at=1500, verbose=False)
    await sm.start()
    worst, rot_secs = await conversation(sm, 40, "rotation")
    print(f"  summary now: {sm.summary!r}")
    print(f"  worst recall {worst}/3, {sm.rotations} rotations, rotation cost {rot_secs} s, server healthy {healthy()}")
    log(test="rotation_summary", worst=worst, rotations=sm.rotations, rot_secs=rot_secs, summary=sm.summary)
    await sm.close()


async def t_carry():
    print("\n== Fact said just before a rotation must survive it")
    sm = SessionManager(TONES["friendly"] + VOICE_SUFFIX, rotate_at=1500, verbose=True)
    await sm.start()
    await sm.send_text(FACTS)
    t = 0
    while sm.est < 1100:  # get close to the 1500 budget
        t += 1
        await sm.send_text(FILLER[t % len(FILLER)])
    print(f"  near budget after {t} turns (est {sm.est})")
    await sm.send_text("By the way, my sister is called Mia.")
    t0 = time.time()
    while sm.rotations == 0:
        t += 1
        r = await sm.send_text(FILLER[t % len(FILLER)])
    print(f"  rotated; turn incl. rotation took {time.time() - t0:.1f}s total over the turns, last reply {r.secs}s")
    rc = await sm.send_text("What's my sister called, and what's my dog called?")
    ok = "mia" in rc.text.lower() and "biscuit" in rc.text.lower()
    print(f"  {'PASS' if ok else 'FAIL'} {rc.text!r}\n  facts: {sm.facts}")
    log(test="carry", ok=ok, reply=rc.text, summary=sm.summary)
    await sm.close()


async def t_tools():
    print("\n== Tool flow through the manager")
    sm = SessionManager(CANVAS_SYS.format(canvas="empty"), tools=TOOLS)
    await sm.start()
    r = await sm.send_text("I'm cooking pasta for four")
    c = r.calls[0] if r.calls else None
    print(f"  call: {c}")
    r2 = await sm.send_tool_result(c["call_id"], {"ok": True, "id": "w1"}, modalities=("text", "audio"))
    print(f"  confirmation: {r2.text!r} ({r2.audio_s}s audio, first sound {r2.first_audio_s}s)")
    r3 = await sm.send_audio(VOICE[1], modalities=("text",))
    print(f"  voice 'Start a ten minute timer' -> {r3.calls}")
    ok = bool(c) and c["name"] == "create_widget" and r2.audio_s > 0 and r3.calls and r3.calls[0]["name"] == "start_timer"
    print(f"  {'PASS' if ok else 'FAIL'}")
    log(test="tools", ok=ok, call=c, confirm=r2.text, voice_calls=r3.calls)
    await sm.close()


async def t_long():
    print("\n== Real budget (rotate_at=6000), 160 mixed turns: must not crash")
    wd = ServerWatchdog()
    sm = SessionManager(TONES["friendly"] + VOICE_SUFFIX, watchdog=wd)
    await sm.start()
    t0 = time.time()
    worst, rot_secs = await conversation(sm, 160, "long", check_every=20)
    print(f"  {time.time() - t0:.0f}s, worst recall {worst}/3, rotations {sm.rotations} (cost {rot_secs} s), "
          f"recoveries {sm.recoveries}, server restarts {wd.restarts}, memory free {mem_free()}")
    log(test="long_summary", worst=worst, **sm.stats)
    await sm.close()


async def t_crash():
    print("\n== Rotation OFF: run until the server crashes, then recover")
    wd = ServerWatchdog()
    sm = SessionManager(TONES["friendly"] + VOICE_SUFFIX, rotate_at=None, watchdog=wd, verbose=True)
    await sm.start()
    await sm.send_text(FACTS)
    t = 0
    while sm.recoveries == 0 and t < 300:
        t += 1
        await sm.send_text(FILLER[t % len(FILLER)])
    print(f"  crashed after {t} turns; estimated tokens at crash: {sm.est_at_crash} (real limit 8192)")
    rc = await sm.send_text(CHECK)
    print(f"  after recovery: recall {recall(rc.text)}/3  {rc.text!r}")
    r = await sm.send_text("Say hi to Biscuit for me.", modalities=("text", "audio"))
    print(f"  speech after recovery: {r.text!r} ({r.audio_s}s audio)")
    log(test="crash", turns=t, est_at_crash=sm.est_at_crash, recall=recall(rc.text), restarts=wd.restarts)
    await sm.close()
    return wd


if __name__ == "__main__":
    for name in sys.argv[1:] or ["rotation", "tools"]:
        asyncio.run({"carry": t_carry, "rotation": t_rotation, "tools": t_tools, "long": t_long, "crash": t_crash}[name]())
