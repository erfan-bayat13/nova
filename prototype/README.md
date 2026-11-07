# LFM3-Omni-2B Prototype

Goal: prove the local model can do what the app needs (see [../docs/CONCEPT.md](../docs/CONCEPT.md), "First-hour check #1"):

1. Answer in **text, speech, or both**, chosen by a **trigger** in our app (not by the model).
2. Change **tone** through the system prompt.
3. **Call tools** (for example `create_widget`) quickly enough to feel live.
4. Run on an **8 GB M2** without crashing the machine.

Model reference: [../LFM3-Omni-2B-reference.md](../LFM3-Omni-2B-reference.md)

---

## The idea

```
 user input (text or voice)
        │
        ▼
 router.py ── pick_mode() ──► "text" | "audio" | "interleaved"
        │     system_prompt() ──► tone preset (+ "no markdown" when speaking)
        ▼
 llama-server (LFM3-Omni-2B Q4_K_M)
        ├─ /v1/chat/completions ── text only (+ tool calls)
        └─ /v1/realtime (WebSocket) ── text and/or 24 kHz speech, streamed
        │
        ▼
 app: show text, play audio, run tool calls
```

- **The app picks the output mode.** Triggers: a UI toggle, voice input, silent mode, headphones, keywords like "read it out", events such as a timer finishing.
- **Tone comes from the system prompt** (presets in `router.py`). The voice can only be `female` or `male`.
- **Text-only turns** (most canvas tool calls) use the plain chat endpoint because it's the simplest and fastest.
- **Spoken turns** use the realtime WebSocket, which streams audio as it's generated.

---

## What we've verified (2026-11-07)

| Check | Result |
|---|---|
| llama.cpp version | ✅ 0.9.0 (build 12110), via `brew install llama.cpp`. Needs ≥ b11960. |
| Model download | ✅ `Q4_K_M` (~1.1 GB) + `mmproj-...-Q4_0.gguf`, cached in `~/.cache/huggingface` |
| Server loads vision + video + audio | ✅ `/props` → `modalities: {vision, video, audio}` |
| Text chat | ✅ ~36 tokens/s generation on M2. First request has a few seconds of warm-up. |
| Tool calling supported by template | ✅ `/props` → `supports_tool_calls: true` (not yet tested end to end) |
| Audio from `/v1/chat/completions` | ❌ Ignored. `modalities: ["text","audio"]` still returns text only. |
| `/v1/audio/speech` | ❌ 404, doesn't exist |
| `/v1/realtime` WebSocket | ✅ Exists. Follows OpenAI Realtime API format (see below). |
| Voices | `female`, `male` (from `/props` → `voices`) |
| Speech output through realtime | ✅ Works with the lighter server settings (`-np 1 -c 4096`). No crash, free memory never dropped below 24%. Results below. |

### Voice test results (2026-11-07, M2 8 GB, Q4_K_M, prompt "Say hello in one short sentence.")

| Case | Total time | First audio | Text | Audio | Verdict |
|---|---|---|---|---|---|
| `sess_text` | 0.6 s | — | "Hello! How can I help you today?" | none | ✅ |
| `sess_audio` (male) | 9.6 s | 0.61 s | none | 26.2 s | ⚠️ ~1 s of speech, then ~25 s of near-silence: the model doesn't stop |
| `sess_both` | 1.8 s | **0.34 s** | "Hello! How can I help you today?" | 4.0 s, all speech | ✅ best for spoken replies |
| `default` | 0.4 s | — | same text | none | Text input → text out, as the model card says |
| `resp_text` | 0.3 s | — | same text | none | ✅ **Mode can be switched per reply** with `response.output_modalities` |

**Takeaways:**
- **For spoken replies, use `["text","audio"]` (both), not `["audio"]` alone.** It's faster, stops properly, and gives us the transcript for free. If the UI shouldn't show text, just hide it.
- **Pick the mode per reply** in `response.create`, so one realtime session can handle every trigger. Tone and tools are still fixed per session.
- Speech-only mode ran past the end once. If we ever need it, cap `max_output_tokens` and trim trailing silence on the client. Not yet retested.
- The server process stayed at ~1.4 GB RAM throughout.

### Realtime protocol (taken from the server binary, OpenAI Realtime style)

Client → server:
- `session.update` — `type: "realtime"`, `instructions`, `tools`, `output_modalities: ["text"] | ["audio"] | ["text","audio"]`, `audio.output.voice`
- `conversation.item.create` — user message (`input_text`) or function call output
- `input_audio_buffer.append` / `.commit` / `.clear` — PCM16 mic audio
- `response.create` — optionally with `response.output_modalities`
- `response.cancel`

Server → client:
- `session.created`, `session.updated`
- `response.output_text.delta` / `.done`
- `response.output_audio.delta` / `.done` (base64 PCM16)
- `response.function_call_arguments.delta` / `.done`
- `conversation.item.input_audio_transcription.delta` / `.completed`
- `response.done`, `error`

**Limit to design around:** `instructions` and `tools` **can't change after the first message** in a session. Changing tone or the tool list means opening a new realtime session. Whether `output_modalities` can change per response is what the `resp_text` test case checks.

---

### Full test suite results (2026-11-07, `-np 2 -c 16384`)

Run: `python3 tests.py [tools|rt_tools|tones|multiturn|audio_only|voice_in|vision|speech_match|all]`.
Long-horizon tests: `python3 tests_long.py`. Then `python3 make_examples.py` builds **`examples.html`**, which lets you play every input and output. To open it:

```bash
cd ~/Documents/hackathon/prototype && python3 -m http.server 8090
```

Then go to http://localhost:8090/examples.html. Opened as a plain file, the audio won't play.

| Test | Result | Notes |
|---|---|---|
| Tool calls, chat endpoint (8 demo lines) | ✅ 8/8, 1.1–2.1 s each | create / update / remove / clear / timer / escalate all correct, args valid JSON |
| Tool calls, realtime + spoken confirmation | ✅ 4/4 | Call in 1.5–2.2 s; after the tool result, it speaks a correct confirmation in 1.3–2.1 s |
| Voice in → tool call | ✅ 2/2, ~2 s | 16 kHz PCM from `say` → `create_widget` / `start_timer(10)` |
| Image in | ✅ 1.4 s | Penguin identified |
| Speech matches text (checked with model ASR) | ✅ 4/4 at 100% | |
| Multi-turn, mode switched per reply | ✅ 4/4 | Remembers name and dish. One reply transcribed as 89% match ("They cook" vs "Bake it") |
| Tones | ✅ after adding an example reply to each preset | Without examples, "coach" sounded the same as "friendly" |
| Speech-only mode | ❌ unreliable | 1 s of speech then silence, or a 0.3 s blip. Capping tokens cuts the speech. More RAM doesn't fix it. **Use text + speech.** |

### Video / camera results

Test videos are built locally by `python3 make_videos.py` (no downloads): `camera.mp4` (penguin → zebra → parrot + `say` voice-over), `screen.mp4` (timer → carbonara recipe → "Mom" notification), `museum.mp4` (camera pans across a placard). Run with `python3 tests.py video`.

| Test | Result |
|---|---|
| Sees animals in order | ✅ penguin → zebra → parrot |
| Hears the soundtrack | ✅ quoted the voice-over word for word |
| Reasons across sound + picture | ❌ said "zebra" was the favorite; the voice-over says "the colorful one" (parrot) |
| Reads a phone screen | ✅ timer counting down, every ingredient, "Mom: Dinner at 7? Bring dessert please" |
| Reads a museum placard | ✅ "Night Harbor", Elena Varga, 1912, Trieste. Missed the year once when asked for "when and where". |
| Speed (full video) | ⚠️ **slow: 11–19 s** (3,000–5,000 prompt tokens). Fixed 2 fps; `max_frames` is ignored. |

**Making it fast:**

| Input | Time | Accuracy |
|---|---|---|
| Full screen video (14 s) | 16.1 s | ✅ |
| Same, last 4 s only | 6.2 s | ✅ |
| Same, half resolution | 6.2 s | ❌ misread "7?" as "7:17" |
| Museum video (8 s) | 11.2 s | ✅ |
| Museum, half resolution | 4.5 s | ❌ "Vargas", "1992" |
| **Museum, one full-res frame** | **2.8 s** | ✅ |

→ **Never downscale text.** For "what am I looking at", send **one full-resolution frame** as an image. Use video (short clips, last few seconds) only when motion or sound matters.

**Point the camera, get a spoken answer** (the "museum on a phone" demo):
- `/v1/realtime` **doesn't accept images** (`unsupported content type: input_image`).
- ❌ Reading a description aloud with the "Perform TTS" instruction: it spoke only a fragment.
- ✅ **Two steps that work:** frame → `/v1/chat/completions` with "Describe exactly what is in this image, including all readable text" (≈1.5 s) → friendly realtime session gets `[Camera sees: …] <question>` and answers in text + speech.
  - "Who painted this and when?" → spoken "Elena Varga painted it in 1912." **First sound at 2.0 s.**
  - "What did my mom just text me?" → reads the message. **First sound at 2.3 s.**
  - An open "What am I looking at?" gives a long answer, with first sound at ~7 s. Keep questions specific or replies short.
- Small bug: emoji in streamed text deltas can arrive as broken bytes (`���`). Strip emoji before display/speech.

**Issues found:**
1. **One tool call per turn.** "Make it for six" updates only the recipe widget, not the ingredients. Fix in the app: linked widgets share one source of truth (the ingredients widget reads `servings` from the recipe), or one `update_widget` call can update several widgets.
2. **The model mixes up "you" and "me" in follow-ups** ("What's my name?" → "My name is Sam"). It's a 2B model. Keep spoken replies short, since the UI *is* the answer.
3. **`-np 1` deadlocks** when a realtime session is open and another request comes in, because the session holds the only slot. Use `-np 2`.

### Long-horizon limits (2026-11-07) — `python3 tests_long.py [asr|rt_asr|long_reply|long_convo]`

Memory is measured with `top`'s MEM column. `ps` RSS misses GPU (Metal) memory on Apple Silicon and under-reports badly.

**Transcription (ASR):** excellent, and length doesn't hurt it.

| Audio | Time | Prompt tokens | WER | Server memory |
|---|---|---|---|---|
| 12 s | 1.8 s | 178 | 2.5% | 1.60 GB |
| 23 s | 3.2 s | 301 | 0% | 1.61 GB |
| 46 s | 5.8 s | 590 | 0.6% | 1.63 GB |
| 95 s | 10.6 s | 1,194 | 1.3% | 1.68 GB |
| 159 s (2.7 min) | 17.5 s | 2,003 | 0.8% | 1.70 GB |

- About **12.6 tokens per second of audio**, transcribed about 9× faster than real time. An 8K slot holds about 10 min of audio in theory. Keep it under ~5 min to leave room for the reply.
- Memory grows only about 100 MB for 2.7 min of audio.
- Streamed into a realtime session, it recalls details from 95 s of audio correctly ("oranges, strawberries, accordion").
- ❌ **It invents things it didn't hear.** Asked about fruit and music from a 23 s clip that mentions neither, it answered "apples" and "violin", even with "say so instead of guessing" in the prompt.
- No `input_audio_transcription` events by default. If the UI needs the user's words, transcribe separately.

**Long spoken replies (text + speech):** quality is fine up to about 30 s, then falls apart.

| Reply | Text words | Audio | Words actually spoken | Speech WER |
|---|---|---|---|---|
| short | 15 | 6 s | 100% | 0% |
| medium | 64 | 26 s | 98% | 6% |
| long | 90 | 36 s | 100% | 2% |
| xlong | 386 | 53 s | **35%** | **30%** (garbled after ~40 s) |

- First audio always arrives in about 0.4–0.7 s, whatever the length.
- Speaking rate is about 2.3–2.8 words/s.
- → **Keep each spoken reply ≤ ~80 words (~30 s).** For anything longer, split it into sentences and speak each one in its own short response. Not tested yet.
- Server memory stayed at about 1.6 GB.

**Long conversation (one realtime session):**
- 100 turns with perfect recall (name, dog, allergy, 3/3 every 5 turns). Replies mostly 0.4–1.5 s, with occasional spikes up to 12 s. Memory flat at ~1.7 GB.
- 💥 **When the session fills its 8K context, the whole server crashes**: `the conversation does not fit in the context` then `GGML_ASSERT(n_ctx > 0 && n_prompt_tokens > 0)`, then abort. It's a llama.cpp bug, and it kills every session, not just that one.
- The server reports **only output tokens** (`response.done.usage.output_tokens`), not context usage.
- → **The app must rotate sessions.** Estimate tokens (≈80 per short text turn, ≈12.6/s of audio in, ≈1.3/word out). Before ~6K, open a new session and put a short summary of key facts in its `instructions`. Also auto-restart the server if it dies.

**Prompt fix:** the friendly preset's example reply leaked word for word after a long monologue. Rewording it as "Style example only, never repeat it" fixed that.

## ⚠️ Memory: server settings

**Current recommended:** `-np 2 -c 16384` (2 slots × 8K context). The server uses ~1.6 GB RAM, and free memory stayed ≥ 17% through all tests. The earlier crashes happened with the default 4 slots × 32K.

The default `llama serve` opens 4 parallel slots, each with the full 32K context. On 8 GB of RAM, adding speech generation probably crashed the Mac (not confirmed). Always start it like this:

```bash
cd ~/Documents/hackathon/prototype && llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384 > logs/server.log 2>&1
```

- `-np 2` allows two requests at once (a realtime session + one other call).
- `-c 16384` is split across slots: 8K context each.

Keep Activity Monitor → Memory open. If memory pressure turns red, press Ctrl+C on the server.

---

## How to run the voice test

**Terminal 1:** start the server with the command above. Wait for `listening on http://127.0.0.1:8080`.

**One-time setup:** the test needs the `websockets` package:

```bash
python3 -m pip install websockets
```

If pip refuses ("externally managed environment"), skip installing and run each case through uv instead:
`uv run --with websockets python probe_realtime.py sess_text`

**Terminal 2:** run one case at a time, starting with the safest:

```bash
cd ~/Documents/hackathon/prototype && python3 probe_realtime.py sess_text
```

```bash
python3 probe_realtime.py sess_audio
```

```bash
python3 probe_realtime.py sess_both
```

| Case | What it tests |
|---|---|
| `sess_text` | Session set to text only |
| `sess_audio` | Session set to speech only, male voice |
| `sess_both` | Session set to text + speech |
| `default` | No setting, so the model chooses |
| `resp_text` | Session set to audio, but one reply asks for text (can the mode change per turn?) |

Each case prints one line:
```
[sess_audio] 4.2s total, first audio 1.1s, text='Hello!...', audio=2.3s@24000Hz -> logs/probe_sess_audio.wav
```

Play the result:
```bash
afplay logs/probe_sess_audio.wav
```

---

## Files

| File | Status | Purpose |
|---|---|---|
| `router.py` | ✅ written | `pick_mode()` trigger router, `TONES` presets, `system_prompt()` |
| `probe_realtime.py` | ✅ run, all 5 cases pass | Tests `output_modalities` on `/v1/realtime`, saves WAV files |
| `tests.py` | ✅ | Full test suite |
| `tests_long.py` | ✅ | Long-horizon limits (ASR length, long replies, long conversations) |
| `make_videos.py` → `videos/` | ✅ | Builds the local test videos |
| **`session_manager.py`** | ✅ | **Use this in the orchestrator**: realtime client + context budget + rotation + server watchdog |
| `test_session.py` | ✅ | Tests for the session manager |
| `make_examples.py` → `examples.html` | ✅ | Playable page of every input and output |
| `logs/` | | server log, probe WAVs, `*.jsonl` results |

---

## Session manager (`session_manager.py`)

The orchestrator talks to the model **only through this**. It guards against the limits found above:

| Problem found in testing | What the manager does |
|---|---|
| A realtime session that fills 8K **crashes the whole server** | Estimates context use and **rotates** to a fresh session before `rotate_at` (6,000) |
| Server reports only output tokens | Text: exact count via `/tokenize`. Audio in: 12.6 tok/s. Replies: exact `usage.output_tokens` (includes audio, ~13 tok/s of speech). +12 per item. |
| Rotation loses memory | **Extracts lasting facts from every user message** in the background (chat endpoint, 2nd slot, JSON schema, ~0.5 s). The new session's `instructions` carry the fact list + the last 4 turns verbatim. |
| One-shot summaries from the 2B model dropped facts and mixed up identities ("My name is Nova", lost "sister Mia") | Replaced by per-message extraction (above). Only facts starting with "The user" are kept, which filters echoed requests and trivia. |
| Rotating mid-turn was slow (3–7 s with summaries) | No summarizing step any more: rotation takes **~1.0 s** |
| Realtime gives no transcript of user speech | Transcribes user audio in the background, then extracts facts from the transcript |
| Server can still die | `ServerWatchdog` attaches to the running server, or spawns one if none answers. The manager restarts it, reopens from the summary, and retries the turn once (`Result.recovered`) |
| Tool results must follow their call | Never rotates between a tool call and its result |
| Realtime takes no images | `see(jpeg, question)` describes the frame on the chat endpoint, then answers in the session |
| Emoji arrive as broken bytes | `clean()` strips emoji and U+FFFD from all text |

```python
from session_manager import SessionManager, ServerWatchdog
sm = SessionManager(instructions, tools=TOOLS, watchdog=ServerWatchdog())
await sm.start()
r = await sm.send_audio(pcm16k, modalities=("text",))          # → r.calls
r = await sm.send_tool_result(r.calls[0]["call_id"], {"ok": True}, modalities=("text", "audio"))  # → r.pcm (24 kHz)
r = await sm.see(jpeg_bytes, "What am I looking at?")
print(sm.stats)  # est_tokens, rotations, recoveries, server_restarts
```

**Test results** (`python3 test_session.py [rotation|tools|long|crash]`):
- `tools` ✅ create_widget → tool result → spoken confirmation (first sound 0.25 s) → spoken "start a ten minute timer" → `start_timer(10)`.
- `rotation` ✅ (budget forced down to 1,500): 3 rotations in 40 turns, recall 3/3 every time, 1.0 s per rotation. Facts from spoken turns were captured too.
- `carry` ✅ A fact said right before a rotation ("my sister is called Mia") survives it. This **failed** with the old summary approach (answered "Lily").
- `long` ✅ Real budget (6,000), 160 mixed turns (text, speech out, voice in): 2 rotations, recall 3/3 at every check, no crash, 25% memory free, 321 s.
- `crash` ✅ Rotation off → the server crashed after 195 turns. The watchdog restarted it in **3.0 s**, the session reopened with the facts, recall 3/3, and speech worked.
  - **Estimate calibration:** at the crash the estimate was **10,758** tokens against the real limit of 8,192, so it **over-counts by ~30%**. That's the safe side: `rotate_at=6000` ≈ 4,600 real tokens. Raise `rotate_at` toward ~7,000 if more context per session is needed. Audio-heavy sessions weren't calibrated separately.
- Note: the watchdog's own server runs detached (`start_new_session`) and keeps running after the app exits. Its log goes to `logs/server_managed.log`.

---

## Next steps

1. [x] Run the voice test (above) and record the results here.
2. [x] Session manager (`session_manager.py`): router-ready realtime client with rotation + watchdog.
3. [x] Tool-call test: the model calls `create_widget` / `update_widget` / `start_timer` from the cooking demo lines, and we measure the time to the tool call.
4. [x] Voice input: mic audio → `input_audio_buffer` → tool call, end to end.
5. [x] Measure response times for text, audio and both. Check peak RAM.
6. [ ] Turn detection (silence detection on the mic) + barge-in (`response.cancel` when the user talks over the reply).
7. [ ] Speak long answers sentence by sentence (≤ 80 words per response).
8. [ ] Linked widgets (ingredients read `servings` from the recipe).
