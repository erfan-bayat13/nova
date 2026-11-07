# Frontend ⇄ backend alignment (2026-11-07)

Why this exists: the two sides felt like they were drifting. After reading both codebases, they
mostly aren't. The real open question is **what the DeepSeek Harness is for**. This doc lays out
where things stand, the concrete gaps, what the harness can actually do (read from its source),
the options for using it, and a recommendation.

---

## 1. Where things actually are

| Piece | State | Notes |
|---|---|---|
| Canvas UI (`ui/`) | ✅ works, demo replays end to end | Speaks PROTOCOL.md. Built-in widgets + sandboxed `html` widget. |
| Mock backend (`ui/mock/`) | ✅ | Replays the demo. Stays as the stage fallback. |
| Orchestrator (`backend/orchestrator.py`) | ✅ first version | **Already speaks PROTOCOL.md.** WebSocket `:8765/canvas`, LFM realtime via `session_manager.py`, tool loop (≤5 steps), drops free text, `say` tool, `timer_done` handled directly. |
| Canvas tools (`backend/tools.py`) | ✅ | `create/update/remove_widget`, `clear_canvas`, `start_timer`, `say`, `escalate` → canvas messages. Matches the UI's widget types. |
| Session manager (`prototype/session_manager.py`) | ✅ tested | Rotation, fact carry-over, crash recovery. |
| Escalation (`backend/escalate.py`) | ⚠️ stub | Returns a placeholder `html` card after 1.5 s. |
| DeepSeek Harness | ❌ not used anywhere yet | This is the drift. See sections 3–5. |

So the plumbing between the two sides is aligned. The **brain behind `escalate`** and the
**harness's role** are what's undecided.

## 2. Concrete gaps between the two sides

| # | Gap | Owner | Fix |
|---|---|---|---|
| 1 | Orchestrator expects mic audio as **binary PCM16 16 kHz mono** frames between `orb_down` and `orb_up`. **The canvas doesn't send audio yet**, so voice can't work end to end. | Frontend | Capture mic → resample to 16 kHz → send binary frames while the orb is held. |
| 2 | Orchestrator accepts a dev `{type:"text", text}` message. It's referenced but **not in PROTOCOL.md**. | Both | Add it to PROTOCOL.md (dev/testing only). |
| 3 | **Voice:** orchestrator asks LFM for text only and sends `say` text; the canvas speaks it with the **browser voice**. LFM's own voice (the "friendly"/Nova preset) isn't used. | Decide | Keep browser voice for the demo (instant, reliable) or switch `say` to LFM audio (PCM16 24 kHz). See decision 2. |
| 4 | **Learned widgets:** `tools.WIDGET_DOCS` is a fixed list. Nothing yet adds a widget Claude built to the local model's list. | Backend | Widget library + reload into the tool list at session rotation (section 5). |
| 5 | **Camera / vision** (demo scene 2): no frame capture in the canvas, no `see()` call in the orchestrator. | Both | Only if vision stays in the demo. See decision 3. |
| 6 | Escalation `importance` is always `full`; the id is `cloud_<n>`. Fine for now. | – | Nothing. |

## 3. What the DeepSeek Harness actually is (read from its source)

Repo: github.com/deepseek-ai/deepseek-harness (developer preview, Node, built on Cordis).

- **Everything is a plugin.** The model adapter, the tools, the agent loop and its web UI are all
  plugins. A running `dsh` is a plugin tree built from a **profile**: `web`, `headless`, `sdk`,
  `sdk-minimal`, or `acp`.
- **It can be driven from Python.** The `sdk` profile runs a JSON-RPC server over stdio. The Python
  package `deepseek-harness-sdk` (module `deepseek_harness`) starts it with a bundled runtime. Calls include
  `initialize`, `session/prompt`, `session/query`, `session/wait`, `shutdown`. It streams
  `session.event` and `session.status` (`running`/`idle`), and also `subagent.started`/`.finished`.
  → **Our Python orchestrator can call it directly.**
- **Models.** The `llm-pi-ai` adapter routes to many providers from config:
  - `anthropic` with `apiKeyEnv: ANTHROPIC_API_KEY` → **Claude**
  - any OpenAI-compatible server via `api: openai-completions` + `baseURL` → **LFM on llama-server**
- **Subagents** can pick their provider/model per call, so a root on one model can delegate to another.
- **Tools** are plugins: `ctx.tools.register(defineTool({ name, description, parameters, execute }))`.
- **Skills** are `SKILL.md` files (or `<name>.md`) in watched folders. New or changed skills are
  picked up live.
- **How its UI evolves ("Creator mode"):** the agent writes a plugin with a Node half and a **React
  browser half** that registers into named **slots** of dsh's own web app. It installs the plugin with its
  `plugin_manager` tool (with approval), and hot-reload mounts it while the app runs. **This only grows
  dsh's own web app**, which is a chat UI (sidebar, transcript, tool cards). It can't mount into our canvas.
- Hot-reload is **on** in the web profile and **off** by default in the SDK profile. A profile patch can turn it on.

## 4. Options for using the harness

### A. No harness
Orchestrator + LFM realtime for everything. `escalate` calls the Claude API directly.
- ➕ Simplest. It's what the backend already half-does.
- ➖ Drops the harness completely. The "it learns" step is hand-written.

### B. Harness as the escalation brain ⭐ recommended
Fast loop as today: canvas ⇄ orchestrator ⇄ LFM realtime. On `escalate`, the orchestrator sends the
task to a **harness session running on Claude** through the Python SDK. Claude works in a workspace
folder with the harness's own tools (files, shell, skills) and writes:
- `workspace/widgets/<name>/widget.html`: the new widget (follows the `html` widget contract)
- `workspace/widgets/<name>/widget.json`: `{name, description, props}`. This is what the local model sees.
- optionally `workspace/skills/<name>.md`: how to use it. Harness skills, so they compound.

The orchestrator puts the result on the canvas (`pending` → `create`), registers the widget, and the
**next LFM session (rotation) gets it in its tool list**. Ask again → handled locally, no cloud.
- ➕ Uses the harness for what it's good at: multi-step agent work, file writing, skills that grow,
  a persisted session that remembers past widgets it built.
- ➕ Doesn't touch the voice loop, which already works and is fast.
- ➕ Gives a clean pitch: "Claude in the harness builds it once. The local model reuses it forever."
- ➖ One more process (Node `dsh`). The SDK is a developer preview (breaking changes possible).
- To verify first: the `sdk` profile with an `anthropic` route, and the Python SDK installs on the M2.

### C. Harness as the whole brain
LFM becomes the harness's root model (pi-ai → llama-server `/v1`). The canvas tools become a
dsh plugin. Claude is a subagent.
- ➕ The purest "everything runs through the harness" story.
- ➖ **Loses the realtime voice path.** The harness talks to models over chat completions, which
  return no audio. So the app would need separate transcription and speech, and our tests showed
  reading arbitrary text aloud through LFM is unreliable.
- ➖ **Likely too big for the 2B model.** Harness system prompts and tool schemas are large, and each
  llama-server slot has only 8K context. Not measured, but the risk is high.
- ➖ Throws away the working orchestrator and session manager.

### D. Demo inside dsh's own web app (Creator mode)
Rebuild the canvas as dsh client plugins and let the agent write new ones live.
- ➕ Shows DeepSeek's exact "UI that grows" mechanism.
- ➖ It looks like a chat app: sidebar, transcript, tool cards. That conflicts with the core UI rule.
- ➖ Biggest rebuild, heavy TypeScript plugin toolchain, under a day left.

## 5. How "the UI evolves" works under option B

```
user: "plan my macros and chart it"
  LFM (no stacked_bar? or too hard) → escalate(task)
  orchestrator → canvas: pending card + orb working
  orchestrator → harness (Python SDK, session on Claude): task + canvas + widget contract
      Claude: builds macro_chart widget.html + widget.json (+ skill), tests it, done
  orchestrator → canvas: create {widget:"html", props:{html, data}}  → card fills in
  orchestrator: adds macro_chart to the widget library
  next LFM session rotation → macro_chart is in LFM's create_widget list
user: "same for next week"
  LFM → create_widget("macro_chart", data) → instant, on-device
```

The UI evolves because the **set of widgets the local model can use grows**. Each new widget
comes from Claude, through the harness. The canvas doesn't need changing: `html` widgets already
render in a sandbox. If generated widgets should look native, the widget contract gives Claude
our CSS tokens (colors, font, radius).

## 6. Decisions needed (product owner)

1. **Harness role:** B (recommended), A, C or D?
2. **Voice for the demo:** browser voice now (works today), or LFM's own voice (more on-brand,
   needs audio streaming both ways)?
3. **Vision scene:** keep it in the demo, or cut it to protect time?

## 7. Next steps if B is chosen

**Backend:**
1. Spike (≤ 1 h): run `dsh --profile sdk` via the Python SDK with an `anthropic` route; send one
   prompt; read the events back. Confirm it runs on the M2 alongside llama-server.
2. Replace `escalate.py`'s stub with a harness session call. Give it the widget contract as a skill.
3. Widget library (`workspace/widgets/`) + reload into `tools.WIDGET_DOCS` at session rotation.

**Frontend:**
1. Stream mic audio (gap 1).
2. Add the `text` dev message to PROTOCOL.md (gap 2).
3. Give the `html` widget our design tokens so generated widgets match the look.
4. Optional: a "learned" moment, e.g. a subtle glint when a learned widget is used locally for the first time.
