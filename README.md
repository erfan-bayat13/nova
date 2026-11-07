# Nova

**If AI understands what you want, why should you have to find the right app?**

Nova is a blank canvas with one voice orb. You say what you're doing, and an interface forms around it:
a recipe, a checklist, a timer. When you're done, it dissolves back into the orb. There is no chat window
and no navigation. Nova talks to you like a friend, and the screen changes behind her.

> Built at a one-day hackathon (2026-11-07).

## How it works

- **Local first.** A small omni model, [LFM3-Omni-2B](LFM3-Omni-2B-reference.md) (Q4 GGUF on `llama-server`), hears you, talks back in real time (first sound about 0.25 s after you let go) and builds widgets with tool calls. It runs on an 8 GB M2.
- **Claude when it's hard.** Big jobs (a ten-day itinerary, a comparison table) are handed to Claude, and the answer lands as a card.
- **The cloud teaches, the local model remembers.** When Claude builds a new widget, it's saved in [`backend/learned/`](backend/learned) and the local model can create it itself next time.
- **It can see, but asks first.** Camera, screen or a dragged area, only after Nova asks "want me to look?" and you say yes. Frames stay in memory.
- **Memory.** Nova keeps facts about you across sessions ([docs/MEMORY.md](docs/MEMORY.md)).

```
desktop/ (Electron orb) → ui/ (React canvas) ⇄ ws :8766/canvas ⇄ backend/orchestrator.py ⇄ llama-server :8080
                                                                        └─ escalate.py → Claude API
```

## Repo layout

| Path | What |
|---|---|
| [`backend/`](backend/README.md) | Python orchestrator: voice sessions, widget builder, Claude escalation, memory |
| [`ui/`](ui/README.md) | React canvas: orb and widgets (Vite, `?gallery` shows every widget) |
| [`desktop/`](desktop/README.md) | Electron floating orb, hold right ⌥ to talk |
| [`prototype/`](prototype/README.md) | First-hour model checks: latency, tone, tools, limits of the 2B |
| [`ios/`](ios/README.md) | iOS app |
| [`docs/`](docs) | [Concept](docs/CONCEPT.md), [protocol](docs/PROTOCOL.md), [demo script](docs/DEMO.md), [alignment](docs/ALIGNMENT.md) |
| [`deck/`](deck) | Pitch deck (HTML keynote, PDF, PPTX) |
| [`HANDOFF.md`](HANDOFF.md) | Detailed state of the project, open issues and lessons |

## Quick start (macOS, Apple Silicon)

1. Start the model server (starting it yourself first makes problems easier to debug):

```bash
llama serve -hf LiquidAI/LFM3-Omni-2B-GGUF:Q4_K_M --reasoning off --temp 0 --port 8080 -np 2 -c 16384
```

2. Install the backend dependencies:

```bash
pip install -r backend/requirements.txt
```

3. Optional, for Claude hand-offs:

```bash
export ANTHROPIC_API_KEY=your-key
```

4. Run the desktop orb (it starts the orchestrator itself):

```bash
cd desktop && npm install && npm start
```

Hold **right ⌥**, speak, let go. Shortcuts: ⌥⇧C camera, ⌥⇧S screen, ⌥⇧A drag an area.
Run exactly **one** orchestrator against one `llama-server`, or builds hang.

To work on the UI alone with a mock backend: `cd ui && npm install && npm run demo`.

## Demo

[docs/DEMO.md](docs/DEMO.md) is a line-by-line script: pasta for four, scale to six, timer, "look at my screen", a Claude-planned itinerary, and a brand-new tip calculator built by Claude.

## Known limits

- Spoken replies degrade past ~80 words / 30 s. Sessions are rotated before the 8K context fills, because a full one crashes `llama-server`.
- The 2B model follows examples, not rules, so prompts are written as few-shot examples.
- Builds take 4–20 s on an 8 GB Mac. See [HANDOFF.md](HANDOFF.md) for the full list.
