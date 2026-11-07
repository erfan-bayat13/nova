// Speech output.
//
// Voice mode (desktop orb): the orchestrator streams LFM's own voice as binary PCM16 24 kHz mono frames
// between `speech_start` and `speech_end`. We schedule each chunk back to back on one AudioContext, so
// playback starts with the first chunk instead of waiting for the whole reply.
//
// `say` (canvas mode, and the fallback when a reply has no audio) still uses the browser's voice.

import { mark } from './timing';

const muted = new URLSearchParams(location.search).has('mute');
const RATE = 24000;
const LEAD = 0.06; // seconds of headroom before the first chunk, so small network jitter doesn't click

type SetSpeaking = (b: boolean) => void;

let ctx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let levelBuf: Float32Array | null = null;
let nextAt = 0;
let live = new Set<AudioBufferSourceNode>();
let accepting = false;  // between speech_start and an interrupt
let ended = true;       // speech_end received for the current reply
let setSpeakingRef: SetSpeaking | null = null;
let fallback: ReturnType<typeof setTimeout> | undefined;

function audio(): AudioContext {
  if (!ctx) {
    ctx = new AudioContext();
    analyser = ctx.createAnalyser();
    analyser.fftSize = 512;
    analyser.connect(ctx.destination);
    levelBuf = new Float32Array(analyser.fftSize);
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

/** Call from a user gesture (orb press) so the AudioContext may start playing later. */
export function unlockAudio() {
  audio();
}

/** 0..1 loudness of what is playing right now, for the orb. */
export function speechLevel(): number {
  if (!analyser || !levelBuf || !live.size) return 0;
  analyser.getFloatTimeDomainData(levelBuf);
  let s = 0;
  for (const v of levelBuf) s += v * v;
  return Math.min(1, Math.sqrt(s / levelBuf.length) * 5);
}

function finishIfDone() {
  if (ended && live.size === 0) setSpeakingRef?.(false);
}

let firstChunk = true; // timing: log the first chunk of each reply once

export function speechStart(setSpeaking: SetSpeaking) {
  clearTimeout(fallback);
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  setSpeakingRef = setSpeaking;
  accepting = true;
  ended = false;
  firstChunk = true;
  mark('speech_start received');
}

export function speechChunk(buf: ArrayBuffer) {
  if (!accepting || muted) return;
  const ac = audio();
  const pcm = new Int16Array(buf, 0, buf.byteLength >> 1);
  if (!pcm.length) return;
  const b = ac.createBuffer(1, pcm.length, RATE); // the context resamples 24 kHz to the device rate
  const ch = b.getChannelData(0);
  for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
  const src = ac.createBufferSource();
  src.buffer = b;
  src.connect(analyser!);
  const at = Math.max(nextAt, ac.currentTime + LEAD);
  if (firstChunk) {
    firstChunk = false;
    mark(`first audio chunk arrived, scheduled ${((at - ac.currentTime) * 1000).toFixed(0)} ms ahead (ctx ${ac.state})`);
  }
  src.start(at);
  nextAt = at + b.duration;
  live.add(src);
  setSpeakingRef?.(true); // the orb shows "speaking" from the first sound, "thinking" until then
  src.onended = () => { live.delete(src); finishIfDone(); };
}

export function speechEnd() {
  ended = true;
  finishIfDone();
}

/** The browser voice, for `say`. */
export function speak(text: string, setSpeaking: SetSpeaking) {
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
  const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith('en'));
  const v = vs.find((x) => /Ava|Samantha|Zoe|Allison/.test(x.name)) ?? vs[0];
  if (v) u.voice = v;
  u.onend = done;
  u.onerror = done;
  speechSynthesis.speak(u);
}

/** Interrupt: silence everything now and drop any chunks still in flight for this reply. */
export function stopSpeaking(setSpeaking: SetSpeaking) {
  clearTimeout(fallback);
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  accepting = false;
  ended = true;
  for (const s of live) {
    s.onended = null;
    try { s.stop(); } catch { /* already stopped */ }
  }
  live = new Set();
  nextAt = 0;
  setSpeaking(false);
}
