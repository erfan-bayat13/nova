"""Output-mode trigger router + tone presets for LFM3-Omni-2B.

The app decides the output mode; the model never guesses.
Modes: "text" | "audio" | "interleaved" (text + speech).
"""
from dataclasses import dataclass

# Small models copy examples better than they follow descriptions, so each tone has a sample reply.
TONES = {
    "friendly": ("You are Nova, a warm, casual friend. Keep replies short and relaxed. "
                 "Style example only, never repeat it: \"Oh, totally get that! Try putting your phone in another room for a bit.\" "
                 "If you didn't hear or see something, say so instead of guessing."),
    "formal": ("You are a professional assistant. Be concise, precise and polite. No slang, no exclamation marks. "
               "Example reply: \"I recommend scheduling focused study blocks and silencing notifications.\""),
    "coach": ("You are Max, a high-energy coach. Start with a short hype phrase, speak in punchy commands, "
              "and end with encouragement. "
              "Example reply: \"Let's go! Phone away, timer on, twenty-five minutes. You've got this!\""),
}

SPEAK_KEYWORDS = ("read it out", "read this", "say it", "speak", "out loud", "tell me out loud")
VOICE_SUFFIX = " Speak naturally in one or two short sentences. No markdown, lists or emojis."


@dataclass
class Context:
    tone: str = "friendly"
    silent_mode: bool = False
    headphones_on: bool = False


@dataclass
class Request:
    text: str
    input_type: str = "text"  # "text" | "voice"
    force_mode: str | None = None


def pick_mode(req: Request, ctx: Context) -> tuple[str, str]:
    """Return (mode, reason) so the UI/logs can show why a mode was chosen."""
    if req.force_mode:
        return req.force_mode, "forced by UI toggle"
    if ctx.silent_mode:
        return "text", "device is in silent mode"
    if req.input_type == "voice" and ctx.headphones_on:
        return "interleaved", "voice input + headphones"
    if req.input_type == "voice":
        # Tested: speech-only ("audio") overran with ~25 s of silence, while
        # "interleaved" stopped cleanly and was faster. Hide the text in the UI instead.
        return "interleaved", "voice input"
    if any(k in req.text.lower() for k in SPEAK_KEYWORDS):
        return "interleaved", "speak keyword in request"
    return "text", "default"


def system_prompt(ctx: Context, mode: str) -> str:
    prompt = TONES.get(ctx.tone, TONES["friendly"])
    if mode != "text":
        prompt += VOICE_SUFFIX
    return prompt
