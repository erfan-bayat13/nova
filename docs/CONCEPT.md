# Concept (locked v1, 2026-11-07)

> Working name: **TBD**. Candidates: Morph, Unapp, Tabula, Clay, Ambient.

## One-liner
**If AI understands what you want, why should you have to find the right app?**
A blank canvas with one voice orb. You say what you're doing, and an interface forms around that. When you're done, it goes away.

## Core story (the pitch)
1. **No apps, no chat window, no navigation.** The UI exists only for the current moment and changes as you go.
2. **Local first, frontier when needed.** A small on-device omni model handles everyday requests. Hard problems go to Claude.
3. **The cloud teaches, the local model remembers.** When Claude builds a new capability (a new widget type or skill), it's saved and the local model can use it right away. The next similar request stays on-device. The system gains new abilities as you use it.

## Demo script (what must work)
1. **Cooking:** "I'm cooking pasta for four" → recipe, ingredients and a timer appear. "Actually make it for six and start a 10-minute timer" → the *same* widgets update. "I'm done" → they dissolve back into the orb.
2. **Vision:** hold an ingredient up to the camera, "what can I make with this?" → recipe ideas appear, all local.
3. **Escalation:** a hard request (e.g. "plan my macros for these meals and chart it"). The orb visibly hands off to the cloud, live progress shows, and a **brand-new widget** appears. Ask something similar again and it's instant and local.

## Architecture

```
 Browser (React canvas + orb)
   │  mic / camera / touch events            ▲ widget ops (create/update/remove)
   ▼                                         │
 Orchestrator (Python, FastAPI, WebSocket)───┘
   │ audio → LFM (speech to text)
   ▼
 DeepSeek Harness  (custom stripped-down profile)
   ├─ root agent model: LFM3-Omni-2B (Q4 GGUF via llama-server, OpenAI-compatible /v1)
   ├─ canvas tools plugin (TypeScript): create_widget, update_widget, remove_widget, clear_canvas, start_timer
   └─ escalate tool → agent on the Claude route (via llm-pi-ai, anthropic provider)
          └─ writes new widget files + SKILL.md into workspace/ → hot-loaded
             → added to the local model's tool/widget list
```

### Roles
| Piece | Job |
|---|---|
| **LFM3-Omni-2B** (local) | Hears you, sees the camera, small reasoning, calls the canvas tools. Speaks only short confirmations. |
| **DeepSeek Harness** | The agent loop, tools, sessions, skills, plugin hot-reload. Runs on our models, *not* the DeepSeek API. |
| **Canvas tools plugin** | The "hands": harness tool calls → WebSocket → canvas. |
| **React canvas** | The "screen": draws and animates widgets. The canvas state is the single source of truth. |
| **Claude** (cloud) | Hard reasoning and building new widgets and skills. |

### Widget contract (every widget, ours or generated)
- **Description file:** `name`, `purpose`, data it takes (`props` schema), actions it supports, events it emits.
- Gets its props from the canvas and sends user events back (e.g. `item_checked`, `timer_done`).
- **Never calls a model directly.** Generated widgets run inside walled-off iframes.
- The local model sees only the descriptions, never code, which keeps its prompt small.

### Escalation rules
- The local model calls `escalate(task, canvas_state)`, **or**
- a tool fails twice, **or**
- the user says "go deeper" / "that's not right" (always works, and is our reliable demo trigger).

### Design rules
- No visible text log. At most a faint caption of what you just said.
- The orb has clear states: idle, listening, local thinking, cloud working (shows progress), speaking.
- Widgets animate in, change smoothly (4 → 6 counts up), and dissolve out.
- Spoken replies are very short. The UI changing *is* the response.

## Stack
- Front end: Vite + React + Tailwind + Framer Motion
- Orchestrator: Python 3.12 + FastAPI + WebSockets
- Local model: llama.cpp `llama-server`, LFM3-Omni-2B Q4 GGUF (8GB M2, so full BF16 won't fit)
- Agent: DeepSeek Harness (`dsh`), custom profile + our TypeScript plugin
- Cloud: Claude API (`claude-opus-5-5`; switch to `claude-sonnet-5-5` if speed or credits are tight)

## Out of scope (cut list)
Accounts, saved history, mobile, real integrations (calendar, email). Possible exception: one live data source via Claude (web search) for demo step 3.

## First-hour checks (do these before building anything else)
1. LFM Q4 on `llama-server`: tool call via `/v1/chat/completions`, measure latency.
2. Harness boots with our minimal profile, LFM as its model, and calls a dummy `create_widget`. Measure the time from voice to tool call.
3. The same profile on the Claude route works (`ANTHROPIC_API_KEY`).
4. Claude, given our widget template, produces a working widget in under 60s.

**Fallback if check 2 is too slow or unreliable:** LFM handles quick reactions directly in the orchestrator, and the harness (LFM + Claude) handles anything with multiple steps.

## Open
- [ ] Name
- [ ] Team roles
- [ ] Judging criteria / sponsor tracks
- [ ] Can a harness sub-agent use a different model (Claude) from the root (LFM)? Otherwise run a second harness session on the Claude route.
