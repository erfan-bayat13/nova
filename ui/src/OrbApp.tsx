// The floating desktop orb (?orb): speech to speech with LFM's own voice.
//
// Push to talk (default): hold Right ⌥ anywhere (desktop/main.cjs), or hold the orb / Space. The orb appears,
// your audio streams to the model while you talk, and the reply starts ~0.25 s after you let go.
// Hold again while it talks to interrupt. A few seconds after the reply, the orb fades away.
// ⌥Space works as a toggle (press to talk, press again to send) if the hold key isn't available.
// ?handsfree: the older hands-free mode (ui/src/conversation.ts), turns detected from pauses.
//
// Creator mode: when the orchestrator builds widgets (the same canvas messages as the canvas page, App.tsx), the
// orb opens a canvas. The window grows to the work area (shell.setCanvas), the orb glides to the bottom centre and
// the widgets grow out of it, floating over the desktop. The orb keeps working there (hold, interrupt, states, the
// look ring) and the window doesn't hide after a reply. While it's open the window is click-through except over a
// widget or the orb (shell.setInteractive), and the orb can't be dragged. When the last widget is gone the orb glides
// back to where it was, the window shrinks back to its saved bounds, and the old linger/fade/hide resumes.
//   small → opening → open → closing → collapsing → small (the two "ing"s around a window resize wait for it to land)

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useCanvas } from './useCanvas';
import { useConversation } from './conversation';
import { startMic, type Mic } from './mic';
import { Orb, type OrbVisual } from './Orb';
import { orbSpot, layout, type OrbSpot } from './layout';
import { WidgetFrame } from './WidgetFrame';
import { REGISTRY } from './widgets';
import { speechLevel, unlockAudio } from './voice';
import { mark, turnStart } from './timing';
import { grabCamera, type Source } from './look';

const q = new URLSearchParams(location.search);
const WS_URL = q.get('ws') ?? `ws://${location.hostname || 'localhost'}:8766/canvas`;
const HANDSFREE = q.has('handsfree');
const LINGER_MS = Number(q.get('linger') ?? 4) * 1000;   // orb stays this long after the reply
const MIC_WARM_MS = Number(q.get('mic_warm') ?? 30) * 1000; // mic stays open this long after use (no startup lag)
const FADE_MS = 450;
const GLIDE_MS = 600; // the orb's trip back to its corner, before the window shrinks
document.documentElement.classList.add('orb-only');

type Size = { w: number; h: number };
type Phase = 'small' | 'opening' | 'open' | 'closing' | 'collapsing';
type Resize = { open: boolean; before: Size; done: boolean; from?: OrbSpot }; // a window resize in flight
const spotOf = (r: { x: number; y: number; w: number; h: number }): OrbSpot => ({ x: r.x + r.w / 2, y: r.y + r.h / 2, r: Math.min(r.w, r.h) * 0.2 });
const smallSpot = (s: Size): OrbSpot => spotOf({ x: 0, y: 0, w: s.w, h: s.h }); // the orb alone in its window

// Bridge to the Electron shell (desktop/preload.cjs). Absent in a normal browser tab.
type Shell = {
  moveBy: (dx: number, dy: number) => void;
  menu: () => void;
  hide: () => void;
  // grow the window to the work area / restore it; resolves once resized. `from`: the small window, in the grown one
  setCanvas: (open: boolean) => Promise<{ size: { w: number; h: number }; from?: { x: number; y: number; w: number; h: number } } | null>;
  setInteractive: (on: boolean) => void; // canvas open: the window takes the mouse (true) or lets it through (false)
  onClearCanvas: (fn: () => void) => void; // menu: "Clear canvas"
  onHotkey: (fn: () => void) => void;
  onPtt: (fn: (kind: 'down' | 'up' | 'cancel') => void) => void;
  onLook: (fn: (source: LookKind) => void) => void;
  mediaAccess: (kind: Source) => Promise<string>; // systemPreferences.getMediaAccessStatus, 'granted' when allowed
  captureScreen: () => Promise<{ image: string } | { error: string }>;
  captureArea: () => Promise<{ image: string } | { error: string }>; // drag a rectangle; error 'cancelled' if abandoned
};
type LookKind = Source | 'area'; // 'area' is a dragged part of the screen, sent to the model as a 'screen' frame
const shell = (window as unknown as { orbShell?: Shell }).orbShell;

export function OrbApp() {
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: innerWidth, h: innerHeight });
  const lookRef = useRef<(k: LookKind) => void>(() => {}); // set below, once `look` exists
  const c = useCanvas(WS_URL, 'voice', (k) => lookRef.current(k));
  const [shown, setShown] = useState(!shell);
  const [held, setHeld] = useState(false);
  const heldRef = useRef(false);
  const mic = useRef<Mic | null>(null);
  const micLevel = useRef<(() => number) | null>(null);
  const micOpening = useRef<Promise<Mic | null> | null>(null);
  const timers = useRef<{ hide?: ReturnType<typeof setTimeout>; mic?: ReturnType<typeof setTimeout> }>({});

  // ---------------- creator mode: widgets open a canvas
  const list = Object.values(c.widgets).sort((a, b) => a.born - b.born);
  const want = list.length > 0; // includes pending and leaving widgets: the canvas stays until the last one is gone
  const [canvasPhase, setCanvasPhase] = useState<Phase>('small');
  const [resize, setResize] = useState<Resize | null>(null);
  const [jump, setJump] = useState<OrbSpot>(); // the orb starts from here after a window resize (Orb `from`)
  const home = useRef<OrbSpot>(); // where the small orb was on screen, in the grown window's coordinates
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const canvasUp = want || canvasPhase !== 'small'; // the window is, or is about to be, grown: never hide it
  const canvasUpRef = useRef(false);
  canvasUpRef.current = canvasUp;

  const convo = useConversation(c, {
    onEnd: () => setTimeout(() => { if (phase.current === 'off' && !canvasUpRef.current) shell?.hide(); }, FADE_MS),
  });
  const phase = useRef(convo.phase);
  phase.current = convo.phase;

  useLayoutEffect(() => {
    const el = stage.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // widgets exist → grow the window; none left → glide the orb home, then shrink it
  useEffect(() => {
    if (canvasPhase === 'small' && want) {
      const before = sizeRef.current;
      setCanvasPhase('opening');
      setResize({ open: true, before, done: !shell, from: smallSpot(before) });
      void shell?.setCanvas(true)
        .then((r) => setResize((z) => z && { ...z, done: true, from: r?.from ? spotOf(r.from) : z.from }))
        .catch(() => setResize((z) => z && { ...z, done: true }));
    } else if (canvasPhase === 'open' && !want) {
      setCanvasPhase('closing');
    } else if (canvasPhase === 'closing') {
      if (want) { setCanvasPhase('open'); return; }
      const t = setTimeout(() => {
        setCanvasPhase('collapsing');
        setResize({ open: false, before: sizeRef.current, done: !shell });
        void shell?.setCanvas(false)
          .then(() => setResize((z) => z && { ...z, done: true }))
          .catch(() => setResize((z) => z && { ...z, done: true }));
      }, GLIDE_MS);
      return () => clearTimeout(t);
    }
  }, [canvasPhase, want]);

  // the resize has landed (the window reported back and the page's own size changed): swap the orb's frame of
  // reference at once, so it doesn't move on screen, and carry on
  useEffect(() => {
    if (!resize?.done) return;
    const finish = () => {
      setResize(null);
      if (resize.open) { home.current = resize.from; setJump(resize.from); setCanvasPhase('open'); }
      else { setJump(smallSpot(sizeRef.current)); setCanvasPhase('small'); }
    };
    if (!shell || size.w !== resize.before.w || size.h !== resize.before.h) { finish(); return; }
    const t = setTimeout(finish, 600); // the size never changed (or the page missed it): don't wait forever
    return () => clearTimeout(t);
  }, [resize, size]);

  // while the canvas is open the window ignores the mouse: tell it when the pointer is over a widget or the orb
  const dock = orbSpot(true, size.w, size.h);
  const spot = canvasPhase === 'open' ? dock
    : canvasPhase === 'closing' || canvasPhase === 'collapsing' ? home.current ?? smallSpot(size)
    : smallSpot(size);
  const spotRef = useRef(spot);
  spotRef.current = spot;
  useEffect(() => {
    if (!shell || canvasPhase === 'small') return; // the small window is all orb: it always takes the mouse
    let sent = false; // what the window was last told (it starts click-through when it grows)
    let down = false; // a button is held on the orb: stay interactive until it's let go
    const tell = (on: boolean) => { if (on !== sent) { sent = on; shell.setInteractive(on); } };
    const over = (x: number, y: number) => {
      const card = document.elementFromPoint(x, y)?.closest('.w');
      if (card && Number(getComputedStyle(card).opacity) > 0.2) return true; // not one that has dissolved
      const o = spotRef.current;
      return Math.hypot(x - o.x, y - o.y) < Math.max(o.r * 1.8, 28);
    };
    const move = (e: MouseEvent) => tell(down || over(e.clientX, e.clientY));
    const press = () => { down = true; };
    const lift = () => { down = false; };
    const leave = () => tell(down);
    addEventListener('mousemove', move, true);
    addEventListener('pointermove', move, true);
    addEventListener('pointerdown', press, true);
    addEventListener('pointerup', lift, true);
    addEventListener('pointercancel', lift, true);
    document.documentElement.addEventListener('mouseleave', leave);
    return () => {
      removeEventListener('mousemove', move, true);
      removeEventListener('pointermove', move, true);
      removeEventListener('pointerdown', press, true);
      removeEventListener('pointerup', lift, true);
      removeEventListener('pointercancel', lift, true);
      document.documentElement.removeEventListener('mouseleave', leave);
    };
  }, [canvasPhase === 'small']);

  // ---------------- push to talk
  const openMic = () => {
    if (mic.current) return Promise.resolve(mic.current);
    const opened = performance.now();
    micOpening.current ??= startMic().then((m) => {
      mic.current = m;
      micLevel.current = m?.level ?? null;
      micOpening.current = null;
      console.log(`[timing] mic opened after ${(performance.now() - opened).toFixed(0)} ms (cold start)`);
      return m;
    });
    return micOpening.current;
  };

  // ---------------- eyes on request: one frame from the camera or the screen (ui/src/look.ts)
  const [seeing, setSeeing] = useState<Source | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const lookId = useRef(0); // bumps on every new look and every cancel, so a stale capture is dropped
  const noteTimer = useRef<ReturnType<typeof setTimeout>>();

  const flash = (msg: string) => {
    setNote(msg);
    clearTimeout(noteTimer.current);
    noteTimer.current = setTimeout(() => setNote(null), 4000);
  };

  // holding the orb (or Space, or the PTT key) cancels a capture that hasn't been sent yet
  const stopLook = useCallback(() => {
    lookId.current++;
    setSeeing(null);
  }, []);

  const look = useCallback(async (kind: LookKind) => {
    const source: Source = kind === 'area' ? 'screen' : kind;
    if (heldRef.current) return;
    if (!c.connected) return flash('Not connected');
    const id = ++lookId.current;
    console.log(`[look] ${kind} requested`);
    const alive = () => lookId.current === id;
    setShown(true);
    setSeeing(source);
    const fail = (msg: string) => { console.log(`[look] failed: ${msg}`); if (alive()) { setSeeing(null); flash(msg); } };
    try {
      let image: string | null = null;
      if (source === 'camera') {
        if (shell && (await shell.mediaAccess('camera')) !== 'granted') return fail('Camera access off');
        if (!alive()) return;
        image = await grabCamera(alive);
      } else {
        if (!shell) return fail('Screen needs the desktop app');
        if ((await shell.mediaAccess('screen')) !== 'granted') {
          if (alive()) console.warn('[look] Screen Recording is off: System Settings → Privacy & Security → Screen & System Audio Recording');
          return fail('Screen access off');
        }
        if (!alive()) return;
        const r = await (kind === 'area' ? shell.captureArea() : shell.captureScreen());
        if (!alive()) return;
        if ('error' in r) {
          if (r.error === 'cancelled') { console.log('[look] area cancelled'); setSeeing(null); return; } // nothing to report
          return fail('Screen capture failed');
        }
        image = r.image;
      }
      if (!alive()) return;
      if (!image) return fail('Capture failed');
      console.log(`[look] ${kind} frame ready (${Math.round(image.length / 1024)} KB), sending`);
      c.see(source, image); // the frame goes out once, then nothing is kept
      setSeeing(null);
    } catch (e) {
      console.warn('[look]', e);
      fail(source === 'camera' ? ((e as Error).name === 'NotAllowedError' ? 'Camera access off' : 'Camera failed') : 'Screen failed');
    }
  }, [c]);

  const press = useCallback(() => {
    stopLook();
    if (heldRef.current) return;
    heldRef.current = true;
    setHeld(true);
    setShown(true);
    clearTimeout(timers.current.hide);
    clearTimeout(timers.current.mic);
    unlockAudio();
    turnStart();
    mark(`press (mic ${mic.current ? 'warm' : 'closed'})`);
    c.orbDown(); // also stops a reply that is playing (barge-in)
    void openMic().then((m) => { if (m && heldRef.current) m.start(c.sendAudio); });
  }, [c, stopLook]);

  const release = useCallback(() => {
    if (!heldRef.current) return;
    heldRef.current = false;
    setHeld(false);
    turnStart();
    mark('release');
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

  // after the reply: linger, fade, hide (not while the canvas is open or on its way); release the mic a bit later
  const idle = !held && !seeing && c.orb === 'idle';
  useEffect(() => {
    if (want) setShown(true); // a widget arrived while the orb was faded away: it comes back with them
  }, [want]);
  useEffect(() => {
    if (HANDSFREE || !idle || !shown || canvasUp) return;
    const t = timers.current;
    t.hide = setTimeout(() => {
      setShown(false);
      setTimeout(() => { if (!heldRef.current && !canvasUpRef.current) shell?.hide(); }, FADE_MS);
    }, LINGER_MS);
    t.mic = setTimeout(() => {
      if (heldRef.current) return;
      mic.current?.close();
      mic.current = null;
      micLevel.current = null;
    }, MIC_WARM_MS);
    return () => { clearTimeout(t.hide); clearTimeout(t.mic); };
  }, [idle, shown, canvasUp]);

  // ---------------- inputs
  const api = useRef({ press, release, cancel, toggle: convo.toggle, look, clear: c.clear });
  api.current = { press, release, cancel, toggle: convo.toggle, look, clear: c.clear };
  lookRef.current = look;
  useEffect(() => {
    shell?.onPtt((kind) => {
      if (HANDSFREE) return;
      if (kind === 'down') api.current.press();
      else if (kind === 'up') api.current.release();
      else api.current.cancel();
    });
    shell?.onLook((source) => { void api.current.look(source); }); // shortcut or menu: ⌥⇧S / ⌥⇧C
    shell?.onClearCanvas(() => api.current.clear()); // menu: the widgets dissolve, the canvas closes
    shell?.onHotkey(() => {
      if (HANDSFREE) api.current.toggle();
      else if (heldRef.current) api.current.release();
      else api.current.press();
    });
    // Space inside the window (or a plain browser tab): hold to talk
    const kd = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || (e.target as Element | null)?.closest?.('button,input,textarea')) return; // a widget's button keeps its Space
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
    visual = held ? 'listening' : c.orb === 'speaking' ? 'speaking' : c.orb === 'idle' ? 'idle' : c.orb === 'working' ? 'working' : 'thinking';
  }
  const present = !shell || canvasUp || (HANDSFREE ? convo.phase !== 'off' : shown);
  const { rects } = layout(list, size.w, size.h);

  return (
    <div className="stage" ref={stage}>
      <Orb spot={spot} from={jump} hold={!!shell && (canvasPhase === 'opening' || canvasPhase === 'collapsing')}
        state={visual} connected={c.connected} tintWork={false} present={present} seeing={seeing !== null}
        micLevel={HANDSFREE ? convo.micLevel : micLevel} speechLevel={speechLevel}
        onDown={HANDSFREE ? convo.tap : press} onUp={HANDSFREE ? () => {} : release}
        onDrag={shell && canvasPhase === 'small' ? { start: HANDSFREE ? () => {} : cancel, by: shell.moveBy } : undefined}
        onMenu={shell?.menu} />
      {canvasPhase === 'open' && list.map((w) => {
        const Comp = REGISTRY[w.widget];
        return (
          <WidgetFrame key={w.id} w={w} rect={rects[w.id]} orb={dock} onGone={c.gone}>
            {Comp && <Comp id={w.id} props={w.props} emit={(n, d) => c.emit(w.id, n, d)} update={(p) => c.localUpdate(w.id, p)} />}
          </WidgetFrame>
        );
      })}
      {note && <div className="orb-note" style={{ top: spot.y + spot.r + 8 }}>{note}</div>}
    </div>
  );
}
