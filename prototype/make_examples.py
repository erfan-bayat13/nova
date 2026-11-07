"""Build examples.html: every test input and output, playable. Run after tests.py."""
import html, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")

latest = {}  # (test, key) -> most recent result
for line in open(os.path.join(LOGS, "test_results.jsonl")):
    d = json.loads(line)
    key = d.get("prompt") or d.get("tone") or d.get("line") or d["test"]
    latest[(d["test"], key)] = d


def get(test, key):
    return latest.get((test, key), {})


def audio(name):
    p = os.path.join(LOGS, name)
    return f'<audio controls preload="none" src="logs/{name}"></audio>' if os.path.exists(p) else "<em>no file</em>"


def esc(s):
    return html.escape(str(s or ""))


def badge(ok):
    return '<span class="ok">PASS</span>' if ok else '<span class="bad">FAIL</span>'


rows = []


def section(title, note=""):
    rows.append(f"<h2>{title}</h2>" + (f'<p class="note">{note}</p>' if note else ""))


def card(inp, out, extra=""):
    rows.append(f'<div class="card"><div class="col"><div class="lbl">Input</div>{inp}</div>'
                f'<div class="col"><div class="lbl">Output</div>{out}{extra}</div></div>')


section("1. Voice in → tool call",
        "Spoken by macOS <code>say</code>, sent as 16 kHz audio over <code>/v1/realtime</code>.")
for i, line in enumerate(["I'm cooking pasta for four", "Start a ten minute timer"]):
    d = get("voice_in", line)
    card(f"<p>“{esc(line)}”</p>{audio(f'voice_in_{i}.wav')}",
         f"<p>{badge(d.get('ok'))} <code>{esc(d.get('call'))}</code></p><p class='meta'>{d.get('secs')} s</p>")

section("2. Tool call → spoken confirmation",
        "Text in, tool call out, then the app sends the tool result back and the model confirms in text + speech.")
for i, prompt in enumerate(["I'm cooking pasta for four", "Start a 10 minute timer for the pasta",
                            "Actually make it for six", "Remove the ingredients list"]):
    d = get("rt_tools", prompt)
    card(f"<p>“{esc(prompt)}”</p>",
         f"<p>{badge(d.get('ok'))} <code>{esc(d.get('call'))}</code></p><p>{esc(d.get('followup'))}</p>"
         f"{audio(f'rt_tool_{i}.wav')}")

section("3. Tones", "Same question: “I keep getting distracted while studying. Any advice?”")
for tone in ("friendly", "formal", "coach"):
    d = get("tones", tone)
    card(f"<p><b>{tone}</b> preset</p>",
         f"<p>{esc(d.get('text'))}</p>{audio(f'tone_{tone}.wav')}<p class='meta'>{d.get('secs')} s total</p>")

section("4. Does speech match the text?", "Audio transcribed back with the model’s own speech-to-text.")
for i, p in enumerate(["How long should lasagna bake?", "Give me two tips for staying focused while studying.",
                       "What can I make with eggs, spinach and cheese?", "Say hello in one short sentence."]):
    d = get("speech_match", p)
    card(f"<p>“{esc(p)}”</p>",
         f"<p>{badge(d.get('ok'))} {int((d.get('score') or 0) * 100)}% match</p>"
         f"<p><b>text:</b> {esc(d.get('text'))}</p><p><b>heard:</b> {esc(d.get('heard'))}</p>{audio(f'match_{i}.wav')}")

section("5. Multi-turn session (mode switched per reply)")
for i, p in enumerate(["My name is Sam and I'm making lasagna.", "How long should it bake?",
                       "What's my name and what am I cooking?", "Say goodbye to me."]):
    d = get("multiturn", p)
    card(f"<p>“{esc(p)}”</p><p class='meta'>mode: {'+'.join(d.get('mode') or [])}</p>",
         f"<p>{badge(d.get('ok'))} {esc(d.get('text'))}</p>" + (audio(f"multiturn_{i}.wav") if d.get("audio_s") else ""))

section("6. Image in", "")
d = get("vision", "vision")
card('<img src="logs/vision_penguin.jpg" alt="penguin"><p>“What animal is this?”</p>',
     f"<p>{badge(d.get('ok'))} {esc(d.get('text'))}</p><p class='meta'>{d.get('secs')} s</p>")

section("7. Video in (sees + hears)",
        "Sent as a full video over <code>/v1/chat/completions</code>. llama.cpp samples 2 frames per second; "
        "a 12 s clip ≈ 5,000 tokens ≈ 15–19 s on the M2.")
for vid in ("camera.mp4", "screen.mp4", "museum.mp4"):
    qs = [d for (t, k), d in latest.items() if t == "video" and d.get("video") == vid]
    out = "".join(f"<p>{badge(d.get('ok'))} <b>{esc(d.get('q'))}</b><br>{esc(d.get('text'))}"
                  f"<span class='meta'> · {d.get('secs')} s, {d.get('prompt_tokens')} tokens</span></p>" for d in qs)
    card(f'<video controls preload="metadata" src="videos/{vid}" style="width:100%;max-height:320px"></video>', out)

section("8. Point the camera, get a spoken answer",
        "Realtime doesn’t accept images, so: one frame → chat endpoint describes it (≈1.5 s) → "
        "friendly realtime session answers in text + speech using that description.")
for name, q, img in (("museum2", "Who painted this and when?", "museum_frame.jpg"),
                     ("screen", "What did my mom just text me?", "screen_frame.jpg"),
                     ("museum", "What am I looking at?", "museum_frame.jpg")):
    card(f'<img src="videos/small/{img}" style="max-width:220px"><p>“{esc(q)}”</p>',
         audio(f"see_speak_{name}.wav"))

section("9. Long spoken replies",
        "Same storyteller prompt, longer and longer. Fine up to ~30 s; the 386-word story falls apart after ~40 s "
        "and only 35% of it is ever spoken.")
long_rows = {}
lp = os.path.join(LOGS, "long_results.jsonl")
if os.path.exists(lp):
    for line in open(lp):
        d = json.loads(line)
        if d.get("test") == "long_reply" and "label" in d:
            long_rows[d["label"]] = d
for label in ("short", "medium", "long", "xlong"):
    d = long_rows.get(label, {})
    card(f"<p><b>{label}</b> · {d.get('n_words')} words of text</p>",
         f"<p class='meta'>{d.get('audio_s')} s audio · first sound {d.get('ttfa')} s</p>"
         f"<p>{esc((d.get('text') or '')[:400])}{'…' if len(d.get('text') or '') > 400 else ''}</p>"
         f"{audio('long/reply_' + label + '.wav')}")

section("10. Known problem: speech-only mode",
        "With <code>output_modalities: [\"audio\"]</code> the model says ~1 s and then keeps generating silence. "
        "Use text + speech instead.")
card("<p>“Say hello in one short sentence.” (speech only)</p>",
     f"{audio('probe_sess_audio.wav')}<p class='meta'>26 s file, ~1 s of speech</p>")

page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LFM3-Omni Examples</title><style>
:root{{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--card:#fff;--line:#e7e5e4;--ok:#15803d;--bad:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;--card:#292524;--line:#44403c;--ok:#4ade80;--bad:#f87171}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif;max-width:960px;margin:0 auto;padding:24px 16px}}
h1{{margin:0 0 4px}} h2{{margin:32px 0 6px;font-size:18px}} .note,.meta{{color:var(--muted);font-size:13px;margin:4px 0}}
.card{{display:grid;grid-template-columns:1fr 1.6fr;gap:16px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:8px 0}}
@media (max-width:640px){{.card{{grid-template-columns:1fr}}}}
.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}} p{{margin:4px 0}}
audio{{width:100%;margin-top:6px}} img{{max-width:160px;border-radius:8px}} code{{font-size:12.5px;word-break:break-word}}
.ok{{color:var(--ok);font-weight:600}} .bad{{color:var(--bad);font-weight:600}}
</style></head><body><h1>LFM3-Omni-2B — test inputs &amp; outputs</h1>
<p class="note">Q4_K_M on M2 8 GB · llama-server <code>-np 2 -c 16384</code> · regenerate with <code>python3 make_examples.py</code></p>
{''.join(rows)}</body></html>"""
open(os.path.join(HERE, "examples.html"), "w").write(page)
print("wrote", os.path.join(HERE, "examples.html"))
