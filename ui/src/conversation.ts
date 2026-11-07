// Hands-free conversation for the desktop orb: no holding, no "press again to send".
//
//   off ──start()──▶ waiting ──you speak──▶ talking ──you pause ~0.8 s──▶ replying ──reply played──▶ waiting …
//                       │                                                  │
//                       └── 15 s of quiet: end() ◀──────────────────────────┘ speak over it: barge-in → talking
//
// Turn detection runs on the 30 ms PCM frames from mic.ts: a speech onset (a few loud frames above the
// adaptive noise floor) sends `orb_down` plus ~300 ms of pre-roll, so the first syllable isn't cut;
// a pause sends `orb_up`. The protocol is unchanged, the orchestrator just sees press/release.

import { useCallback, useEffect, useRef, useState } from 'react';
import { startMic, type Mic } from './mic';
import { unlockAudio } from './voice';
import type { useCanvas } from './useCanvas';

type Canvas = ReturnType<typeof useCanvas>;
export type Phase = 'off' | 'waiting' | 'talking' | 'replying';

const q = new URLSearchParams(location.search);
const FRAME_S = 0.03;
const PRE = 10;                 // pre-roll frames (300 ms)
const ON_FRAMES = 3;            // 90 ms above threshold = you started talking
const ON_MIN = 600;             // PCM16 RMS; the backend counts > 500 as speech
const OFF_MIN = 400;
const END_FRAMES = Math.round(Number(q.get('pause') ?? 0.8) / FRAME_S); // pause that ends your turn
const MAX_FRAMES = Math.round(30 / FRAME_S);                          // hard cap per utterance
const IDLE_MS = Number(q.get('idle') ?? 15) * 1000;                   // quiet this long → the orb goes away
const AFTER_REPLY_MS = 300;     // ignore the mic right after a reply (room echo tail)
// Barge-in while it's talking: much louder and longer than a normal onset, so the orb's own voice
// coming back through the mic doesn't interrupt it (echo cancellation removes most of it). ?barge=0 disables.
const BARGE = q.get('barge') !== '0';
const BARGE_MIN = Number(q.get('barge_rms') ?? 1500);
const BARGE_WIN = 10;           // look at the last 300 ms…
const BARGE_HITS = 6;           // …and barge in when 6 of those frames are loud (speech dips between syllables)

function rms(f: ArrayBuffer): number {
  const a = new Int16Array(f);
  let s = 0;
  for (let i = 0; i < a.length; i++) s += a[i] * a[i];
  return Math.sqrt(s / Math.max(1, a.length));
}

export function useConversation(c: Canvas, opts: { onEnd?: () => void } = {}) {
  const [phase, setPhaseState] = useState<Phase>('off');
  const ph = useRef<Phase>('off');
  const cRef = useRef(c);
  cRef.current = c;
  const onEnd = useRef(opts.onEnd);
  onEnd.current = opts.onEnd;
  const mic = useRef<Mic | null>(null);
  const micLevel = useRef<(() => number) | null>(null);
  const idle = useRef<ReturnType<typeof setTimeout>>();
  const v = useRef({ pre: [] as ArrayBuffer[], on: 0, off: 0, len: 0, floor: 200, quietUntil: 0, recent: [] as boolean[] });
  const starting = useRef(false);

  const setPhase = (p: Phase) => { ph.current = p; setPhaseState(p); };

  const end = useCallback(() => {
    clearTimeout(idle.current);
    const p = ph.current;
    if (p === 'off') return;
    const cc = cRef.current;
    if (p === 'talking' || p === 'replying') { cc.orbDown(); cc.orbCancel(); } // stop the reply, drop the audio
    mic.current?.close();
    mic.current = null;
    micLevel.current = null;
    setPhase('off');
    onEnd.current?.();
  }, []);

  const toWaiting = useCallback(() => {
    setPhase('waiting');
    const st = v.current;
    st.on = 0; st.pre = []; st.recent = [];
    st.quietUntil = performance.now() + AFTER_REPLY_MS;
    clearTimeout(idle.current);
    idle.current = setTimeout(end, IDLE_MS);
  }, [end]);

  const begin = () => {
    clearTimeout(idle.current);
    const cc = cRef.current, st = v.current;
    cc.orbDown(); // also stops any reply that is playing, and cancels it on the backend
    for (const f of st.pre) cc.sendAudio(f);
    st.pre = []; st.on = 0; st.off = 0; st.len = 0;
    setPhase('talking');
  };

  const finish = () => {
    cRef.current.orbUp();
    setPhase('replying');
  };

  const onFrame = (f: ArrayBuffer) => {
    const r = rms(f), st = v.current, p = ph.current;
    if (p === 'talking') {
      cRef.current.sendAudio(f);
      st.len++;
      st.off = r < Math.max(OFF_MIN, st.floor * 2) ? st.off + 1 : 0;
      if (st.off >= END_FRAMES || st.len >= MAX_FRAMES) finish();
      return;
    }
    st.pre.push(f);
    if (st.pre.length > PRE) st.pre.shift();
    if (p === 'waiting') {
      if (performance.now() < st.quietUntil) return;
      if (r < st.floor * 2) st.floor = Math.min(1500, Math.max(50, st.floor * 0.97 + r * 0.03));
      st.on = r > Math.max(ON_MIN, st.floor * 3) ? st.on + 1 : 0;
      if (st.on >= ON_FRAMES) begin();
    } else if (p === 'replying' && BARGE) {
      const talking = cRef.current.orb === 'speaking';
      if (!talking) { // still thinking: a normal onset adds to what you said
        st.on = r > Math.max(ON_MIN, st.floor * 3) ? st.on + 1 : 0;
        if (st.on >= ON_FRAMES) begin();
        return;
      }
      st.recent.push(r > Math.max(BARGE_MIN, st.floor * 6));
      if (st.recent.length > BARGE_WIN) st.recent.shift();
      if (st.recent.filter(Boolean).length >= BARGE_HITS) { st.recent = []; begin(); }
    }
  };

  const start = useCallback(async () => {
    if (ph.current !== 'off' || starting.current) return;
    starting.current = true;
    unlockAudio();
    const m = await startMic();
    starting.current = false;
    if (!m) return;
    mic.current = m;
    micLevel.current = m.level;
    m.start(onFrame);
    toWaiting();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toWaiting]);

  // the reply is over (played to the end, or the utterance was ignored): listen again
  useEffect(() => {
    if (phase === 'replying' && c.orb === 'idle') toWaiting();
  }, [phase, c.orb, toWaiting]);

  useEffect(() => () => { clearTimeout(idle.current); mic.current?.close(); }, []);

  const toggle = useCallback(() => (ph.current === 'off' ? void start() : end()), [start, end]);

  // a click on the orb: start / interrupt the reply / send now / stop
  const tap = useCallback(() => {
    const p = ph.current, cc = cRef.current;
    if (p === 'off') void start();
    else if (p === 'replying') { cc.orbDown(); cc.orbCancel(); toWaiting(); }
    else if (p === 'talking') finish();
    else end();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start, end, toWaiting]);

  return { phase, start, end, toggle, tap, micLevel };
}
