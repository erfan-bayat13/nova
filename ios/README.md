# Nova for iPhone (model runs on the phone)

Hold the orb, talk, let go: LFM3-Omni-2B answers out loud, with no Mac and no network once the model is
downloaded. The phone downloads the model itself on first launch (~1.4 GB: Q4_K_M + the audio projector).

**Status: builds for device; LlamaEngine written, not yet run on a phone.
Done: download screen, hold-to-talk orb, mic capture (PCM16 16 kHz), streaming playback (PCM16 24 kHz),
turn timings on screen. Not done: `LlamaEngine` (the real `VoiceEngine`; the app uses `StubEngine` until then).

## Build

```bash
ios/scripts/build-llama.sh   # builds llama.xcframework for a real iPhone (needs full Xcode)
cd ios && xcodegen generate  # makes Nova.xcodeproj from project.yml
open Nova.xcodeproj          # pick your team under Signing, plug in the phone, Run
```

## How the engine will work

`vendor/llama.cpp` (v0.9.0, git-ignored) includes `tools/mtmd` with `mtmd_helper_gen_audio_*`, the LFM3-Audio
speech generator (codec decoder + ISTFT). So speech in and out can run in-process with no server.
`LlamaEngine` should mirror `tools/mtmd/mtmd-cli.cpp`'s audio path.

## Risks to test first

- **Memory.** Model 1.1 GB + projector 0.27 GB + KV cache. The project sets the increased-memory-limit
  entitlement; check whether your signing allows it. Keep the context small (2–4K) on the phone.
- **Speed.** Real-time factor on the iPhone's GPU (Metal) is the real test. Shown on screen after each turn.
- **Free Apple ID signing** expires after 7 days.
