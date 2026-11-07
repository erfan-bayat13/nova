"""Long-horizon limits: transcription length, long spoken replies, long conversations.

Usage:  python3 tests_long.py [asr|rt_asr|long_reply|long_convo|all]
Tracks server RSS (MB) and system free memory during each test. Results -> logs/long_results.jsonl
"""
import asyncio, base64, json, os, subprocess, sys, threading, time, wave

from tests import RT, chat, save_wav, speech_seconds, asr, overlap, mem_free, TONES, VOICE_SUFFIX

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
LONG = os.path.join(LOGS, "long")
os.makedirs(LONG, exist_ok=True)

# Original passage (~560 words) used as ground truth for transcription tests.
PASSAGE = """Every morning the market opens before the sun is fully up. The baker arrives first, carrying trays of bread that are still warm,
and sets them out on a long wooden table. Next comes the fish seller, who spreads crushed ice over his counter and arranges the catch
in neat silver rows. By seven o'clock the square is full of people. Some are shopping for dinner, some are only walking through on
their way to work, and a few are tourists taking photos of the colorful fruit stands. The oranges this week come from the south,
and the strawberries are the first of the season. A small girl asks her father if they can buy a basket of cherries, and he says
yes, but only if she promises to share them with her brother. Near the fountain, an old man plays the accordion. He has played in
the same spot for twenty years, and most of the vendors know his songs by heart. When it starts to rain, everyone moves under the
striped awnings, and the music keeps going. The rain never lasts long here. Within ten minutes the clouds break, the stones of the
square begin to dry, and the crowd spreads out again. At noon the cheese shop offers free samples of a new goat cheese made in the
hills, and a line forms almost immediately. The owner explains that the goats graze on wild herbs, which gives the cheese a light,
grassy flavor. People nod politely, take a second piece, and then buy a whole wheel. In the afternoon the pace slows down. The
vendors sit on folding chairs, drink coffee from paper cups, and talk about the weather, their children, and the price of fuel.
One of them is planning a trip to the coast next month. Another is worried about a leak in the roof of his van. By four o'clock
most of the stands are packing up. Boxes are stacked, tables are folded, and the last tomatoes are sold at half price. A delivery
truck backs carefully into the narrow street, beeping loudly, while a dog watches from a doorway. The baker counts the money in his
drawer and smiles, because he sold every loaf before two. Then the cleaning crew arrives with brooms and a small water truck. They
wash away the crushed ice, the fallen leaves, and the paper wrappers, until the square looks almost new. Pigeons return to the
fountain. The accordion player packs his instrument into a worn black case and walks slowly toward the bus stop. The cafe on the
corner turns on its lights, and the waiters set out candles on the outdoor tables. Couples begin to arrive for dinner, ordering
fresh pasta and glasses of red wine. Somewhere above the square a window opens, and someone starts practicing the piano, playing
the same short melody again and again until it is perfect. By nine o'clock the sky is dark blue, the air is cool, and the market
square is quiet except for the soft clink of plates. Tomorrow, before the sun is fully up, the baker will arrive first again."""
PASSAGE = " ".join(PASSAGE.split())


# ---------------------------------------------------------------- helpers
class MemWatch:
    """Samples server RSS (MB) and system free % every 0.5 s."""

    def __init__(self):
        self.pid = subprocess.run(["pgrep", "-f", "llama serve"], capture_output=True, text=True).stdout.split()[0]
        self.rss, self.free, self._stop = [], [], False

    def __enter__(self):
        def loop():
            while not self._stop:
                # `ps` RSS misses Metal/GPU memory on Apple Silicon; top's MEM (phys footprint) includes it
                r = subprocess.run(["top", "-l", "1", "-pid", self.pid, "-stats", "mem"],
                                   capture_output=True, text=True).stdout.strip().splitlines()[-1].strip()
                num = float(r.rstrip("MGK+-") or 0)
                self.rss.append(int(num * 1024) if r.rstrip("+-").endswith("G") else int(num))
                self.free.append(int(mem_free().rstrip("%")))
                time.sleep(0.5)
        self.t = threading.Thread(target=loop, daemon=True); self.t.start()
        return self

    def __exit__(self, *a):
        self._stop = True; self.t.join()

    def summary(self):
        return {"rss_peak_mb": max(self.rss or [0]), "free_min_pct": min(self.free or [0])}


def log(test, **d):
    d |= {"test": test, "ts": time.strftime("%H:%M:%S")}
    with open(os.path.join(LOGS, "long_results.jsonl"), "a") as f:
        f.write(json.dumps(d) + "\n")


def words(s):
    return [w.strip(".,!?;:'\"“”‘’()-").lower() for w in s.split() if w.strip(".,!?;:'\"“”‘’()-")]


def wer(ref, hyp):
    r, h = words(ref), words(hyp)
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return round(prev[-1] / max(1, len(r)), 3)


def make_speech(n_words, path):
    """`say` the first n_words of PASSAGE as 16 kHz PCM16 WAV; returns (text, seconds)."""
    text = " ".join(PASSAGE.split()[:n_words])
    subprocess.run(["say", "-o", path, "--data-format=LEI16@16000", text], check=True)
    with wave.open(path) as w:
        return text, w.getnframes() / w.getframerate()


# ---------------------------------------------------------------- tests
def t_asr():
    print("\n== Transcription length sweep (chat endpoint, 'Perform ASR in English.')")
    for n in (40, 80, 160, 320, len(PASSAGE.split())):
        path = os.path.join(LONG, f"asr_in_{n}.wav")
        ref, secs = make_speech(n, path)
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        with MemWatch() as m:
            try:
                d, dt = chat([{"role": "system", "content": "Perform ASR in English."},
                              {"role": "user", "content": [{"type": "input_audio",
                                                            "input_audio": {"data": b64, "format": "wav"}}]}],
                             max_tokens=2000)
                hyp = d["choices"][0]["message"]["content"].strip()
                pt = d["timings"]["prompt_n"]
            except Exception as e:
                hyp, dt, pt = f"ERROR {e}", 0, None
                if hasattr(e, "read"):
                    hyp += " " + e.read()[:200].decode(errors="replace")
        w = wer(ref, hyp) if not hyp.startswith("ERROR") else None
        cover = round(len(words(hyp)) / len(words(ref)), 2)
        print(f"  {secs:5.0f}s audio ({n} words): {dt:5.1f}s, {pt} prompt tok, WER {w}, length {cover:.0%} of ref, "
              f"RSS peak {m.summary()['rss_peak_mb']} MB, free min {m.summary()['free_min_pct']}%")
        if w is None or w > 0.1:
            print(f"        tail: …{hyp[-160:]!r}")
        log("asr", audio_s=round(secs, 1), n_words=n, secs=round(dt, 2), prompt_tokens=pt, wer=w, coverage=cover,
            hyp=hyp, **m.summary())


async def t_rt_asr():
    print("\n== Live-mic style: stream audio into a realtime session, then ask about it")
    for n in (80, 320):
        path = os.path.join(LONG, f"asr_in_{n}.wav")
        ref, secs = make_speech(n, path)
        with wave.open(path) as w:
            pcm = w.readframes(w.getnframes())
        with MemWatch() as m:
            rt = await RT.open(TONES["friendly"] + VOICE_SUFFIX)
            t0 = time.time()
            await rt.say_audio(pcm)
            r = await rt.respond(modalities=["text"])
            await rt.say_text("What fruit was mentioned, and what instrument does the old man play?")
            r2 = await rt.respond(modalities=["text"])
            await rt.close()
        ok = "accordion" in r2["text"].lower() if n == 320 else None
        print(f"  {secs:4.0f}s streamed: reply in {r['secs']}s, transcript event: {bool(r['transcript'])}, "
              f"follow-up {r2['secs']}s ok={ok}  RSS peak {m.summary()['rss_peak_mb']} MB\n"
              f"        reply: {r['text'][:140]!r}\n        follow-up: {r2['text'][:160]!r}")
        log("rt_asr", audio_s=round(secs, 1), reply=r["text"], followup=r2["text"], ok=ok,
            transcript=r["transcript"], **m.summary())


async def t_long_reply():
    print("\n== Long spoken replies (text+speech): does voice quality drift?")
    asks = [("short", "Describe a sunrise in one sentence."),
            ("medium", "Tell me a short story about a lighthouse keeper, about 80 words."),
            ("long", "Tell me a detailed story about a lighthouse keeper and a storm, about 250 words."),
            ("xlong", "Tell me a long, detailed story about a lighthouse keeper, a storm and a lost ship, about 500 words.")]
    for label, q in asks:
        with MemWatch() as m:
            rt = await RT.open("You are Nova, a warm storyteller. Speak naturally. No markdown, lists or emojis.")
            await rt.say_text(q)
            r = await rt.respond()
            await rt.close()
        pcm = r["pcm"]
        save_wav(os.path.join(LONG, f"reply_{label}.wav"), pcm)
        speech, tail = speech_seconds(pcm)
        # quality over time: ASR each 20 s chunk, compare to the reply text
        chunk, rate = 20 * 24000 * 2, 24000
        segs = []
        for i in range(0, len(pcm), chunk):
            part = pcm[i:i + chunk]
            if len(part) < rate * 2:  # skip <1 s leftovers
                continue
            heard = asr(part)
            segs.append({"from_s": i // (rate * 2), "match": overlap(heard, r["text"]),
                         "wps": round(len(words(heard)) / (len(part) / (rate * 2)), 2), "heard": heard[:80]})
        full_ratio = round(len(words(" ".join(s["heard"] for s in segs))) / max(1, len(words(r["text"]))), 2)
        print(f"  {label:6s}: {len(words(r['text']))} words, gen {r['secs']}s, first audio {r['ttfa']}s, "
              f"audio {r['audio_s']}s (speech {speech}s, tail {tail}s), RSS peak {m.summary()['rss_peak_mb']} MB, "
              f"free min {m.summary()['free_min_pct']}%")
        for s in segs:
            print(f"          @{s['from_s']:4d}s  heard-in-text {s['match']:.0%}  {s['wps']} words/s  {s['heard']!r}")
        log("long_reply", label=label, n_words=len(words(r["text"])), secs=r["secs"], ttfa=r["ttfa"],
            audio_s=r["audio_s"], speech_s=speech, tail_s=tail, segments=segs, text=r["text"], **m.summary())


async def t_long_convo():
    print("\n== Long conversation in one realtime session until context fills (8K per slot)")
    facts = "My name is Sam, my dog is called Biscuit, and I'm allergic to peanuts."
    filler = ["Give me a tip for cooking rice.", "What's a good stretch for my back?",
              "Suggest a name for a houseplant.", "How do I keep basil fresh?",
              "Tell me a fun fact about octopuses.", "What's a quick breakfast idea?"]
    with MemWatch() as m:
        rt = await RT.open(TONES["friendly"] + VOICE_SUFFIX)
        await rt.say_text(facts)
        await rt.respond(modalities=["text"])
        turn, total_audio = 0, 0.0
        while True:
            turn += 1
            q = filler[turn % len(filler)]
            mode = ["text", "audio"] if turn % 3 == 0 else ["text"]
            await rt.say_text(q)
            r = await rt.respond(modalities=mode)
            total_audio += r["audio_s"]
            if r["errors"]:
                print(f"  turn {turn}: ERROR {r['errors'][0].get('message', r['errors'][0])[:160]}")
                log("long_convo", turn=turn, error=str(r["errors"][0])[:300], **m.summary())
                break
            if turn % 5 == 0:
                await rt.say_text("Quick check: what's my name, my dog's name, and what am I allergic to?")
                rc = await rt.respond(modalities=["text"])
                low = rc["text"].lower()
                recall = sum(k in low for k in ("sam", "biscuit", "peanut"))
                rss = m.rss[-1] if m.rss else None
                print(f"  turn {turn:3d}: reply {r['secs']:4.1f}s, recall {recall}/3, RSS {rss} MB  {rc['text'][:90]!r}")
                log("long_convo", turn=turn, secs=r["secs"], recall=recall, recall_text=rc["text"], rss_mb=rss)
                if rc["errors"]:
                    print(f"  turn {turn}: ERROR {rc['errors']}"); break
            if turn >= 120:
                print("  stopped at 120 turns without error"); break
        await rt.close()
    print(f"  {m.summary()}")
    log("long_convo_summary", turns=turn, **m.summary())


TESTS = {"asr": t_asr, "rt_asr": t_rt_asr, "long_reply": t_long_reply, "long_convo": t_long_convo}

if __name__ == "__main__":
    names = sys.argv[1:] or ["all"]
    for n in (list(TESTS) if names == ["all"] else names):
        fn = TESTS[n]
        try:
            asyncio.run(fn()) if asyncio.iscoroutinefunction(fn) else fn()
        except Exception as e:
            print(f"  {n} CRASHED: {type(e).__name__}: {e}")
            log(n, crashed=f"{type(e).__name__}: {e}")
    print(f"\nmemory free: {mem_free()}")
