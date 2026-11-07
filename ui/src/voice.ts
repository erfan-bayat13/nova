// Speech output. For now this is the browser's own voice; the orchestrator will later stream
// LFM audio instead, and only this file has to change.

let fallback: ReturnType<typeof setTimeout> | undefined;
const muted = new URLSearchParams(location.search).has('mute');

function pickVoice(): SpeechSynthesisVoice | undefined {
  const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en'));
  return vs.find((v) => /Ava|Samantha|Zoe|Allison/.test(v.name)) ?? vs[0];
}

export function speak(text: string, setSpeaking: (b: boolean) => void) {
  clearTimeout(fallback);
  setSpeaking(true);
  const done = () => { clearTimeout(fallback); setSpeaking(false); };
  // keeps the orb honest if speech never fires its end event
  fallback = setTimeout(done, 1200 + text.length * 80);
  if (muted || !('speechSynthesis' in window)) {
    clearTimeout(fallback);
    fallback = setTimeout(done, 500 + text.length * 60);
    return;
  }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  const v = pickVoice();
  if (v) u.voice = v;
  u.onend = done;
  u.onerror = done;
  speechSynthesis.speak(u);
}

export function stopSpeaking(setSpeaking: (b: boolean) => void) {
  clearTimeout(fallback);
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  setSpeaking(false);
}
