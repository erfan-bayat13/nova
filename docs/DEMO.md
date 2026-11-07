# Demo script (talk to the orb)

Hold **right ⌥**, speak, let go. Every line below was tested on the real model (by spoken clips); timings are from this Mac.

**Before you start**
- One orb only (Orb.app *or* `npm start`, not both): a second one takes llama's last slot and building hangs.
- The orchestrator has your key (it reads it from `~/.zshrc`). If a cloud card says "Cloud help needs ANTHROPIC_API_KEY", restart the backend from a terminal where `echo $ANTHROPIC_API_KEY` prints something.
- Close heavy apps (8 GB, swap was nearly full). The first turn after a restart is slower (cold model).

| # | You say | What should happen | Time |
|---|---|---|---|
| 1 | "Hey Nova, how's it going?" | Friendly spoken reply, a question back. Nothing on screen. | 0.3 s |
| 2 | "I'm cooking pasta for four people." | Nova: "Okay, putting that on the canvas…" + chat. The canvas opens: a **recipe** and an **ingredients checklist**. | 6–12 s |
| 3 | "Make it for six." | The **same** cards update: 6 servings, quantities scaled. | 6–10 s |
| 4 | "Start a ten minute timer for the oven." | A small **timer** appears next to the orb. | 3–4 s |
| 5 | "How long does pasta take to cook?" | Nova answers out loud. **Nothing** new on screen. | 1–2 s |
| 6 | "Can you look at my screen?" → "Yes please." | She asks first, says "Okay, looking at your screen now," then describes it. (Camera needs Camera permission for the app.) | 4–5 s after the yes |
| 7 | "Plan a day by day itinerary for ten days in Spain in June." | Nova starts, an empty shimmering card appears, then a **day-by-day table** from **Claude**, and Nova says it's ready. | 8–15 s |
| 8 | "Explain the difference between a fixed and a variable rate mortgage." | Nova answers out loud first, then a **comparison table** from Claude + one spoken line. | 4–8 s after her answer |
| 9 | "Make me an interactive tip calculator." | Claude builds a **new custom widget** (a working calculator). It's saved in `backend/learned/`. | ~15 s |
| 10 | "I want to book a trip to Spain." | A warm chat: she asks when and what you like. A starter checklist may appear. | 1–8 s |
| 11 | "I'm done, thanks." | "Okay, clearing the canvas…" and the cards dissolve into the orb; the window shrinks back. | 2–3 s |

**The story for the room:** (1) a small local model on this laptop talks and builds the UI around what you're doing; (2) when it's hard, it hands off to Claude and the answer lands as a card; (3) what Claude builds (step 9) is saved, so the local model can reuse it next time.

**If something goes wrong**
- Nova says "putting that on the canvas" but nothing appears: wait ~10 s (builds are slow on this Mac). If still nothing, repeat the request in simpler words ("start a ten minute timer").
- Wrong or odd widget: say "I'm done" and ask again. The 2B model is flaky on some phrasings.
- No voice / everything stuck: the backend or llama-server hung. Quit the orb, stop `llama serve`, start the orb again (it restarts both), wait ~15 s.
- Tray/orb menu → **Clear canvas** is the manual way out.
- Don't test with the speakers near the mic in hands-free mode (Alt+Space): Nova hears herself. Use hold-to-talk.

**Known gaps (don't promise these live):** voice-driven camera until Camera permission is granted; the real window behaviour over full-screen apps and multiple displays; a learned widget being reused by the local model (saved and wired, but only mock-tested).
