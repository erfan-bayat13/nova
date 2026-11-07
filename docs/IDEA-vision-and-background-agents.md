# Idea: eyes, a router, and background agents

**Status:** idea, not decided. **Date:** 2026-11-07 · **Builds on:** [CONCEPT.md](CONCEPT.md), [HANDOFF.md](../HANDOFF.md), [LFM3-Omni-2B-reference.md](../LFM3-Omni-2B-reference.md)

---

## The idea in one paragraph

Nova stops waiting to be spoken to. It can **see** (the camera, and what is on the Mac screen), it has a
**router** that decides what kind of help a request needs, and it runs **background agents** that keep
working on small jobs (watch for a condition, prepare a morning briefing, follow up on a timer) and speak
up only when something matters. The orb stays the only interface. The user talks; Nova looks and works in
the background.

---

## Why this fits what we already have

- The local model already takes images. Omni-2B accepts images at native resolution (up to 2,048 tokens per
  image), and video at 2 fps. So "eyes" is mostly plumbing, not a new model.
- The concept already says the omni model "sees the camera." The canvas never built it; the desktop orb can.
- Timers and the tool loop already exist (`backend/tools.py`). A background agent is a timer that thinks.
- Voice mode already speaks without a canvas, so results can be spoken from the orb.

---

## 1. Eyes: camera and screen

Two sources, one input path. Both become an image sent to the model; the model doesn't need to know which.

| | Camera | Screen |
|---|---|---|
| Trigger | "What's this?" / hold a thing up | "What am I looking at?" / "help with this" |
| Capture | Electron renderer, `getUserMedia` | `desktopCapturer` (main process) |
| Mac permission | Camera | Screen Recording |
| Default size | ~768–1024 px longest side | ~1024–1280 px, the window or display the user picked |
| Sent when | Only on request, or when an agent asks | Only on request, or when an agent asks |

**Rules (decided in this doc, change if you disagree):**
- **Never continuous by default.** A frame is taken when the user asks, or when a background agent with
  vision permission is due to check. Continuous watching is a later setting, not the default.
- **Frames are not stored.** They live in memory for the one call, then are dropped. Only the model's
  short text description is kept (in the session facts memory, if at all).
- **Visible indicator** while the camera or screen is in use: the orb changes state (a ring or dot).
  Users must be able to tell it is looking.
- **One key to stop.** A hold-to-pause on the orb cuts all capture and all background vision checks.
- **Local only.** No frame leaves the Mac. Claude escalation receives a text description, not the image,
  unless the user explicitly asks Claude to look.

**Technical notes from our own reference doc:**
- Realtime sessions take no images. So a frame goes in through **chat**, and the answer is then spoken.
  This is the same rule as the current "describe the frame via chat first, then speak" note.
- Images cost context. Omni-2B has a 32K window and our server runs `-c 16384`. A few frames fit; a long
  video does not. Keep one or two frames per question and summarize them into text right away.
- Document and screen reading is a stated strength (DocVQA 92.5, self-reported). That makes "read this
  error / this email / this form" the strongest screen use.

**Demo moments:**
- Hold an ingredient up: "what can I make with this?" (already in CONCEPT.md, now real)
- "Nova, what's this error?" while a terminal is open
- Point at a receipt: "add this to my expenses"

---

## 2. The decision model: what should handle this?

LFM3 ships two **decision models**, specialized from the vision and omni models. The blog doesn't say what
they output, so **we don't know yet whether they are a router**. The idea assumes we need a router no matter
what, and we test the decision model against a simple one.

The router's job: for each request, pick one of

| Decision | Example | Who does it |
|---|---|---|
| **Chat** | "How are you?", small talk | Omni, spoken reply |
| **Act** | "Set a timer", "add milk" | Omni + tool call, short confirmation |
| **Look** | "What's this?" | Capture frame, then Omni answers |
| **Background** | "Tell me when the bus is 5 min away", "brief me at 8" | Spawn a background agent |
| **Escalate** | "Plan my trip to Lisbon" | Claude (via Harness, see ALIGNMENT.md) |
| **Ask** | Ambiguous request | Ask one short question |

**Today** the CHAT / ACT split is a prompt heuristic. That works, but it breaks silently. A router makes the
choice visible and testable.

**How to decide which router:**
1. Build a labelled set of ~50 utterances from our own tests (voice_client.py and the demo script).
2. Run the LFM3 decision model on the set (if it loads on llama.cpp; check the model card first).
3. Compare against Omni-with-a-prompt and a plain keyword rule.
4. Pick the cheapest one that is right ~90% of the time. Latency matters: the router sits in front of every
   turn, so it must add well under 0.3 s, or it kills the voice feel.

**Open:** does the decision model run in the same llama-server (two models on 8 GB is tight), or do we use
Omni for routing and skip the extra model?

---

## 3. Background agents

A background agent is a small, named job with a trigger, a goal, a tool allowlist, and a result rule.

```
trigger  ──►  agent (own short context, allowed tools only)  ──►  result
(time / event / condition)                                       │
                                                  speak it now, or queue it for the next time the user is here
```

**Trigger types**
- **Time:** "brief me every morning at 8", "remind me Friday"
- **Event:** a timer ends, a file appears, a calendar entry starts
- **Condition:** "tell me when the screen shows X" or "when the bus is 5 min away" (vision check on a slow loop, e.g. every 30–60 s, only while the agent is alive)

**Each agent has**
- **Goal** in one sentence, written from the user's words
- **Tools** from an allowlist. Read-only by default. Anything that changes something outside Nova (sending
  a message, booking, deleting) needs a spoken yes first.
- **Budget:** max steps, max minutes, max tokens. An agent that hits its budget stops and says so.
- **Result rule:** speak now if urgent, otherwise queue for the next time the user talks to Nova.
- **Lifespan:** one-off, or until a date, or until cancelled by voice ("stop watching the bus").

**Where it runs (the important constraint)**
- Our realtime session can crash the whole llama server when its context fills (GGML_ASSERT, see
  HANDOFF). **Background agents must not run inside the realtime voice session.** They use their own chat
  session, on a separate slot (`-np 2` already allows two).
- One llama-server, one model loaded. Background work queues behind the voice turn: the user always wins.
  If voice is active, background agents pause.
- Background work uses the same orchestrator process. A small scheduler module, not a new service.

**Morning briefing: the first agent to build.** It's the best demo of the whole idea: no screen needed,
just a schedule, a few tools (calendar, notes or a fixed list, weather), and one spoken summary at 8:00.
It proves the scheduler, the result rule, and the spoken delivery in one feature.

---

## 4. How the three pieces connect

1. User: "Nova, watch my screen for the build and tell me when it passes."
2. Router → **Background** (not Look, because it's ongoing).
3. Scheduler creates an agent: goal = "watch the build", vision allowed, check every 45 s, budget 20 min.
4. Agent checks: capture screen → Omni describes → "still running". Repeat.
5. Agent sees "passed" → result rule: urgent → speak it now from the orb.
6. Agent ends. Facts memory keeps "build passed at 14:32" for later.

---

## What we are not building (yet)

- Continuous always-on camera or screen watching
- Video input as a default (2 fps, large context cost)
- Agents that act outside the Mac without a spoken yes
- Multi-model serving of several LFM3 variants at once on 8 GB
- Our own embedding model for memory (LFM3 has none; add later only if facts memory is not enough)

---

## Build order (proposal)

1. **Camera on request** (desktop orb → `see()` → spoken answer). Smallest visible win.
2. **Screen on request** (same path, `desktopCapturer`, indicator, stop key).
3. **Scheduler + morning briefing** (time trigger, one tool set, spoken result).
4. **Router test** (labelled set, compare decision model vs. Omni vs. keywords), then pick one.
5. **Condition agents** ("watch the screen for X") with a slow vision loop and a budget.
6. **Escalate-to-Claude path** for agents that need a longer plan (ties into ALIGNMENT.md).

Steps 1–3 are enough for a strong demo. Steps 4–6 are the stretch.

---

## Open questions

1. Does the LFM3 decision model load on llama.cpp, and what does it output? (Check the model card before step 4.)
2. Is the screen the whole display, or only a window the user names? (Whole display is more useful and more
   sensitive; a named window is safer for the demo.)
3. Do background results go to the orb only, or also to the canvas if it comes back?
4. What is the first real background task for the demo: morning briefing, or "watch this build"?
5. How do we show what a background agent is doing when the user asks, without a chat log? (The concept rules
   out logs. A short spoken status, or a tiny list widget on the canvas, are candidates.)
