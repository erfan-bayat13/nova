# Demo script (talk to the orb)

Hold **right ⌥**, speak, let go. Say each line **exactly** as written: the phrasings are picked so the right thing triggers.
Nova never says "canvas" any more: she just talks, and things appear on screen behind her.

**Before you start (2 minutes)**
1. Quit the Orb app, then start it again so the backend runs the latest code. Only one orb: never Orb.app and `npm start` together (a second one takes llama's last slot and nothing gets built).
2. Wait ~15 s, then say the warm-up line (step 0) once off-stage: the first turn after a restart is slow.
3. Check the key: in a terminal `echo $ANTHROPIC_API_KEY` prints something. Otherwise Claude cards say "Cloud help needs ANTHROPIC_API_KEY".
4. Close heavy apps. Use hold-to-talk, not hands-free (Nova hears herself through the speakers).

## The script

| # | You say | What happens | Shows off |
|---|---|---|---|
| 0 | *(off-stage)* "Hey Nova, how's it going?" | Friendly reply + a question. Nothing on screen. | warm-up |
| 1 | "Hey Nova, I'm cooking pasta for four people tonight." | She chats and asks about the sauce, maybe offers a recipe. **Nothing on screen yet.** | local voice, under 0.3 s to first word |
| 2 | "Yeah, set up a recipe for it." | She answers in her own words. ~6–12 s later a **recipe** and an **ingredients checklist** appear, and she says it's up. | local model builds the UI |
| 3 | "Make it for six." | The **same** cards update: 6 servings, quantities scaled. | memory of the conversation and the screen |
| 4 | "Start a twenty minute timer for the oven." | A **20 min timer** appears next to the orb (exact, every time). | instant local action |
| 5 | "How long does pasta take to cook?" | She just answers. **Nothing** new on screen. | knows chat from action |
| 6 | "Can you look at my screen?" → "Yes please." | She asks first, says "Okay, looking at your screen now," then describes it. | vision, privacy-first |
| 7 | "I'm done, thanks." | Cards dissolve into the orb. | clear |
| 8 | "Plan a day by day itinerary for ten days in Spain in June." | She replies right away; a shimmering card appears, then a **day-by-day plan from Claude**, and she says it's ready. | **hand-off to Claude** |
| 9 | "Explain the difference between a fixed and a variable rate mortgage." | She answers out loud first, then a **comparison table from Claude** lands. | local answer + Claude depth |
| 10 | "Make me an interactive tip calculator." | Claude builds a **brand-new working widget**, saved in `backend/learned/` for reuse. | **Claude teaches, the local model remembers** |
| 11 | "I'm done, thanks." | Everything clears. End. | |

**The story for the room (30 s):** a small model running on this laptop talks to you in real time and quietly builds the interface around what you're doing (steps 1–7). When a job is too big, it hands off to Claude, and the answer lands as a card (8–9). And when Claude builds something new, it's saved, so the local model can do it next time (10).

## If something goes wrong (stay calm, keep talking)
- Nothing appears after a request: wait ~10 s (builds are slow on this Mac). Then repeat with a clear verb: "**Set up** a recipe for pasta", "**Start** a timer".
- Wrong or odd widget: "I'm done, thanks" and ask again.
- Claude card slow: keep chatting with Nova, it lands in 8–20 s.
- Everything stuck / no voice: quit the orb, stop `llama serve`, start the orb again (it restarts both), wait ~15 s.
- Manual way out: tray / orb menu → **Clear canvas**.

**Don't promise live:** camera (needs Camera permission), full-screen apps / multiple displays, the local model reusing a learned widget.

**Safe trims if short on time:** do 1 → 2 → 4 → 8 → 10 → 11 (about 2 minutes).
