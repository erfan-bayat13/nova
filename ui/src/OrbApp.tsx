// The floating desktop orb (?orb): speech to speech with LFM's own voice.
//
// Push to talk (default): hold Right ⌥ anywhere (desktop/main.cjs), or hold the orb / Space. The orb appears,
// your audio streams to the model while you talk, and the reply starts ~0.25 s after you let go.
// Hold again while it talks to interrupt. A few seconds after the reply, the orb fades away.
// ⌥Space works as a toggle (press to talk, press again to send) if the hold key isn't available.
// ?handsfree: the older hands-free mode (ui/src/conversation.ts), turns detected from pauses.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useCanvas } from './useCanvas';
import { useConversation } from './conversation';
import { startMic, type Mic } from './mic';
import { Orb, type OrbVisual } from './Orb';
import { speechLevel, unlockAudio } from './voice';

const q = new URLSearchParams(location.search);
const WS_URL = q.get('ws') ?? `ws://${location.hostname || 'localhost'}:8766/canvas`;
const HANDSFREE = q.has('handsfree');
const LINGER_MS = Number(q.get('linger') ?? 4) * 1000;   // orb stays this long after the reply
const MIC_WARM_MS = Number(q.get('mic_warm') ?? 30) * 1000; // mic stays open this long after use (no startup lag)
const FADE_MS = 450;
document.documentElement.classList.add('orb-only');

// Bridge to the Electron shell (desktop/preload.cjs). Absent in a normal browser tab.
type Shell = {
  moveBy: (dx: number, dy: number) => void;
  menu: () => void;
  hide: () => void;
  onHotkey: (fn: () => void) => void;
  onPtt: (fn: (kind: 'down' | 'up' | 'cancel') => void) => void;
};
const shell = (window as unknown as { orbShell?: Shell }).orbShell;

export function OrbApp() {
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: innerWidth, h: innerHeight });
  const c = useCanvas(WS_URL, 'voice');
  const [shown, setShown] = useState(!shell);
  const [held, setHeld] = useState(false);
  const heldRef = useRef(false);
  const mic = useRef<Mic | null>(null);
  const micLevel = useRef<(() => number) | null>(null);
  const micOpening = useRef<Promise<Mic | null> | null>(null);
  const timers = useRef<{ hide?: ReturnType<typeof setTimeout>; mic?: ReturnType<typeof setTimeout> }>({});

  const convo = useConversation(c, {
    onEnd: () => setTimeout(() => { if (phase.current === 'off') shell?.hide(); }, FADE_MS),
  });
  const phase = useRef(convo.phase);
  phase.current = convo.phase;

  useLayoutEffect(() => {
    const el = stage.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ---------------- push to talk
  const openMic = () => {
    if (mic.current) return Promise.resolve(mic.current);
    micOpening.current ??= startMic().then((m) => {
      mic.current = m;
      micLevel.current = m?.level ?? null;
      micOpening.current = null;
      return m;
    });
    return micOpening.current;
  };

  const press = useCallback(() => {
    if (heldRef.current) return;
    heldRef.current = true;
    setHeld(true);
    setShown(true);
    clearTimeout(timers.current.hide);
    clearTimeout(timers.current.mic);
    unlockAudio();
    c.orbDown(); // also stops a reply that is playing (barge-in)
    void openMic().then((m) => { if (m && heldRef.current) m.start(c.sendAudio); });
  }, [c]);

  const release = useCallback(() => {
    if (!heldRef.current) return;
    heldRef.current = false;
    setHeld(false);
    mic.current?.stop(); // flushes the last partial frame before orb_up
    c.orbUp();
  }, [c]);

  const cancel = useCallback(() => {
    if (!heldRef.current) return;
    heldRef.current = false;
    setHeld(false);
    mic.current?.stop();
    c.orbCancel();
  }, [c]);

  // after the reply: linger, fade, hide; release the mic a bit later
  const idle = !held && c.orb === 'idle';
  useEffect(() => {
    if (HANDSFREE || !idle || !shown) return;
    const t = timers.current;
    t.hide = setTimeout(() => {
      setShown(false);
      setTimeout(() => { if (!heldRef.current) shell?.hide(); }, FADE_MS);
    }, LINGER_MS);
    t.mic = setTimeout(() => {
      if (heldRef.current) return;
      mic.current?.close();
      mic.current = null;
      micLevel.current = null;
    }, MIC_WARM_MS);
    return () => { clearTimeout(t.hide); clearTimeout(t.mic); };
  }, [idle, shown]);

  // ---------------- inputs
  const api = useRef({ press, release, cancel, toggle: convo.toggle });
  api.current = { press, release, cancel, toggle: convo.toggle };
  useEffect(() => {
    shell?.onPtt((kind) => {
      if (HANDSFREE) return;
      if (kind === 'down') api.current.press();
      else if (kind === 'up') api.current.release();
      else api.current.cancel();
    });
    shell?.onHotkey(() => {
      if (HANDSFREE) api.current.toggle();
      else if (heldRef.current) api.current.release();
      else api.current.press();
    });
    // Space inside the window (or a plain browser tab): hold to talk
    const kd = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat) return;
      e.preventDefault();
      if (HANDSFREE) api.current.toggle(); else api.current.press();
    };
    const ku = (e: KeyboardEvent) => { if (e.code === 'Space' && !HANDSFREE) api.current.release(); };
    addEventListener('keydown', kd); addEventListener('keyup', ku);
    return () => { removeEventListener('keydown', kd); removeEventListener('keyup', ku); };
  }, []);

  // ---------------- look
  let visual: OrbVisual;
  if (HANDSFREE) {
    visual = convo.phase === 'waiting' || convo.phase === 'talking' ? 'listening'
      : convo.phase === 'replying' ? (c.orb === 'speaking' ? 'speaking' : 'thinking') : 'idle';
  } else {
    visual = held ? 'listening' : c.orb === 'speaking' ? 'speaking' : c.orb === 'idle' ? 'idle' : 'thinking';
  }
  const present = !shell || (HANDSFREE ? convo.phase !== 'off' : shown);
  const spot = { x: size.w / 2, y: size.h / 2, r: Math.min(size.w, size.h) * 0.2 };

  return (
    <div className="stage" ref={stage}>
      <Orb spot={spot} state={visual} connected={c.connected} tintWork={false} present={present}
        micLevel={HANDSFREE ? convo.micLevel : micLevel} speechLevel={speechLevel}
        onDown={HANDSFREE ? convo.tap : press} onUp={HANDSFREE ? () => {} : release}
        onDrag={shell ? { start: HANDSFREE ? () => {} : cancel, by: shell.moveBy } : undefined}
        onMenu={shell?.menu} />
    </div>
  );
}
