# LFM3-Omni-2B — Project Reference

Quick reference for using **LiquidAI/LFM3-Omni-2B** as the single local AI model in our app.
Research date: 2026-11-07. Facts marked _(unverified)_ still need testing in a prototype.

- Model card: https://huggingface.co/LiquidAI/LFM3-Omni-2B
- GGUF builds: https://huggingface.co/LiquidAI/LFM3-Omni-2B-GGUF
- License: https://huggingface.co/LiquidAI/LFM3-Omni-2B/blob/main/LICENSE

---

## 1. What the model is

| | |
|---|---|
| Size | ~2.2B params (LFM3-1.7B backbone + vision encoder + audio encoder + audio codec) |
| Input | text, images (native res, ≤2,048 tokens/image), video (+ soundtrack, 2 fps, 4–384 frames), audio (16 kHz) |
| Output | text, speech (24 kHz), or **interleaved text + speech** |
| Context | 32K tokens (input + output) |
| Text languages | 16 — EN, AR, ZH, FR, DE, IT, JA, KO, PT, ES, VI, TH, ID, HI, RU, PL |
| Speech languages | 19 — AR, DA, DE, EL, EN-GB, EN-US, FI, FR, HE, IT, JA, KO, NL, PL, PT, ES, SV, TR, ZH |
| Tool calling | Yes (via `tools=` in the chat template), including from spoken requests |
| Reasoning | **No** — non-reasoning model, `enable_thinking=True` not supported |

**One model replaces:** ASR (Whisper) + LLM + vision model + TTS.

### Strengths
- Voice chat (speech-in → speech-out), live translation, accessibility
- Document/screen reading (DocVQA 92.5)
- Audio+video understanding (tops its size class on Daily-Omni, WorldSense — self-reported)

### Weaknesses — design around these
1. **Tool calling is mediocre** (52.2 vs 72.4 for Gemma 4 E4B, Liquid's own eval). Keep tool lists small, strict JSON schemas, validate + retry.
2. **No reasoning** — weak at multi-step planning/math.
3. **2B model** — limited world knowledge; trails Phi-4-multimodal / Qwen2.5-Omni 7B on some benchmarks.
4. **Video eats context fast** — cap frames for long clips.
5. **No embeddings, no image generation** — add a small embedding model (~100 MB) for RAG/memory if needed.

---

## 2. License (LFM Open License v1.0)

- ✅ Free commercial use **only while the company's annual revenue is < $10M USD**.
- ❌ Above $10M → commercial use is not licensed; need a deal with Liquid AI.
- ✅ Can bundle/redistribute weights in the app — must include the license + NOTICE, mark modified files.
- ❌ Can't use Liquid AI trademarks/branding for marketing.
- License terminates automatically on non-compliance.

---

## 3. Runtimes

| Runtime | Use for | Notes |
|---|---|---|
| **llama.cpp (GGUF)** | ✅ **Shipping** (desktop + mobile) | Needs llama.cpp **b11960 (v0.8.0)+**. Has OpenAI-compatible server + `/v1/realtime` voice WebSocket |
| Transformers | Prototyping, full feature access | BF16, `transformers>=5.20.2`, `trust_remote_code=True` |
| SGLang | Server, text only | ❌ No speech output |
| LEAP SDK | ❌ **Don't use** | Deprecated (last release v0.10.7, 2026-05-18), never supported LFM3 |
| MLX / ONNX / vLLM | — | Not listed on the model card |

### GGUF sizes
| Quant | Size |
|---|---|
| Q4_0 | 1.05 GB |
| **Q4_K_M** (recommended) | 1.1 GB |
| Q8_0 | 1.85 GB |
| BF16 / F16 | 3.47 GB |

Plus `mmproj-LFM3-Omni-2B-Q8_0.gguf` (vision/audio projector; auto-downloaded with `-hf`).

### Mobile (LEAP replacement per Liquid's migration guide)
- **iOS / macOS:** `llama.xcframework` from a llama.cpp release, call the C API from Swift (`import llama`). Metal enabled. Min iOS 16.4 / macOS 13.3.
- **Android:** build llama.cpp with the NDK — use upstream `examples/llama.android` or a custom JNI wrapper. Download models via `WorkManager`/`DownloadManager`.
- _(unverified)_ Speech output on mobile through llama.cpp — test early.

---

## 4. Quick start — llama.cpp

```bash
brew install llama.cpp
```

**Server (web UI + OpenAI API on :8080, realtime voice at `/v1/realtime`):**
```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080
```

**ASR (speech → text):**
```bash
llama cli -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --audio speech.wav -sys "Perform ASR in English." -p "<__media__>" --temp 0
```

**Image:**
```bash
llama cli -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --image photo.png -p "Describe this image." --temp 0
```

**Video (needs ffmpeg):**
```bash
llama cli -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --video clip.mp4 -sys "Answer questions about the video using what you see and hear." -p "What happens here?" --temp 0
```

**TTS (text → speech):**
```bash
llama-tts -m LFM3-Omni-2B-Q4_K_M.gguf -mm mmproj-LFM3-Omni-2B-Q8_0.gguf -p "Hello world" -o out.wav --tts-lang en --tts-voice female
```

Notes:
- `--video-fps` has no effect; video is always 2 fps, 4–384 frames.
- _(unverified)_ Exact server request fields for choosing text vs audio vs interleaved output aren't documented — test `/v1/realtime`; fall back to system-prompt steering.

---

## 5. Sampling settings (required)

| Output | Settings |
|---|---|
| Text | Greedy — `temp 0` |
| Speech / interleaved | `audio_temperature=0.4`, `audio_repetition_penalty=1.2` (stored in the GGUF for llama.cpp) |

Chat template: ChatML-style (`<|im_start|>` / `<|im_end|>`), every assistant turn opens with an empty `<think></think>`. Use `processor.apply_chat_template()` — don't hand-build it.

---

## 6. Controlling output mode (text / audio / both)

| Mode | `generation_mode` | Output |
|---|---|---|
| Text | `"text"` | text only |
| Speech | `"audio"` | 24 kHz audio |
| Both | `"interleaved"` | text **and** audio |

If not set, the model picks itself (usually matches input modality). Weaker alternative: add `"Respond in text."` / `"Respond with interleaved text and audio."` to the system prompt.

**Pattern: the app decides via a trigger router — don't let the model guess.**

```python
def pick_mode(req, ctx):
    if req.get("force_mode"):                    # UI toggle / API flag
        return req["force_mode"]
    if ctx.silent_mode or ctx.in_meeting:         # device state
        return "text"
    if req["input_type"] == "voice" and ctx.headphones_on:
        return "interleaved"                      # speak + show transcript
    if req["input_type"] == "voice":
        return "audio"
    if any(k in req["text"].lower() for k in ("read it out", "say it", "speak")):
        return "interleaved"                      # keyword trigger
    return "text"
```

Trigger ideas: UI speaker toggle · input was voice · silent mode / headphones / app backgrounded · keyword ("read this to me") · events (timer, notification, tool result to announce).

Compute-saving option: generate text first, then voice only if needed with a second pass using `"Perform TTS in English using a female voice."` (slower than interleaved, but no wasted audio).

---

## 7. Controlling tone

### Text tone — ✅ via system prompt (also applies to spoken output, since speech = the same words)

```python
TONES = {
    "friendly": "You are Nova, a warm, upbeat assistant. Use casual language and keep replies short.",
    "formal":   "You are a professional assistant. Be concise, precise and polite. No slang.",
    "coach":    "You are an encouraging coach. Be energetic and motivating, one tip at a time.",
}

system = TONES[ctx.tone]
if mode != "text":
    system += " Speak naturally; no markdown, lists or emojis."
```

Tips for a 2B model:
- Short, concrete instructions beat long personality descriptions.
- Tone first, output-format instructions last.
- Add one example reply if it drifts — small models copy examples better than they follow descriptions.

### Voice tone — ⚠️ limited
- Documented controls: **gender (female/male)** and **language** only.
- Emotion/speed/pitch/custom voices: not documented. _(unverified)_ "speak excitedly"-style prompts may or may not work.
- Workarounds: adjust speed/pitch on-device (iOS `AVAudioUnitTimePitch`, Android `PlaybackParams`), or use a separate TTS model for expressive voices (loses the single-model setup).

---

## 8. Full Transformers example (prototyping)

```python
# pip install "transformers>=5.20.2" soundfile
import soundfile as sf
from transformers import AutoProcessor, AutoModelForMultimodalLM

MODEL = "LiquidAI/LFM3-Omni-2B"
processor = AutoProcessor.from_pretrained(MODEL, trust_remote_code=True)
model = AutoModelForMultimodalLM.from_pretrained(MODEL, trust_remote_code=True, torch_dtype="bfloat16", device_map="auto")
# codec = <Liquid audio codec, loaded as shown on the model card>

messages = [
    {"role": "system", "content": TONES["friendly"]},
    {"role": "user", "content": "Give me one tip for staying focused."},
]
inputs = processor.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt", return_dict=True).to(model.device)
prompt_len = inputs["input_ids"].shape[1]

mode = "interleaved"
gen = dict(max_new_tokens=512, generation_mode=mode)
if mode != "text":
    gen |= dict(audio_temperature=0.4, audio_repetition_penalty=1.2)

out = model.generate(**inputs, **gen)
text = processor.decode(out.sequences[0, prompt_len:], skip_special_tokens=True)
print(text)

if mode != "text":
    wav = codec.decode(out.audio_codes[:1, :, :out.audio_lengths[0]]).audio_values[0]
    sf.write("reply.wav", wav.float().cpu().numpy(), 24_000)
```

> Check the model card for the exact codec loading code — the card's quick start uses `AutoModelForMultimodalLM`, while its "Use this model" snippet shows `AutoModelForImageTextToText`.

---

## 9. Suggested app architecture

```
Mic / Camera / Files ──► LFM3-Omni-2B (llama.cpp, GGUF Q4_K_M)
                            │   ▲
                 mode+tone  │   │ system prompt (tone) + generation_mode (trigger router)
                            ▼
                     text + speech out (streamed)
                            │
                            ├─► Tool router (validate JSON, retry) ──► local actions
                            └─► Small embedding model + vector DB ──► memory / file search
```

---

## 10. Open questions to test in the prototype

Findings so far are in [prototype/README.md](prototype/README.md). In short: `/v1/chat/completions` returns **text only** and ignores audio requests. Speech comes from the **`/v1/realtime` WebSocket** (OpenAI Realtime format, `output_modalities`, voices `female`/`male`). On 8 GB RAM, run the server with `-np 1 -c 4096`.

- [x] Request fields for text / audio / interleaved: `output_modalities` on `/v1/realtime`. **Tested:** text 0.6 s; text+audio 1.8 s with first audio at 0.34 s; it can switch per reply. Audio-only overran with silence, so use text+audio for speech.
- [ ] Speech output via llama.cpp on iOS and Android
- [ ] Real RAM usage + latency of Q4_K_M on target devices
- [ ] Whether voice delivery changes with tone prompts
- [ ] Tool-calling reliability with our actual tool set
