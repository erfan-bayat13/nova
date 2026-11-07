import { useEffect, useRef } from 'react';
import type { OrbSpot } from './layout';

export type OrbVisual = 'idle' | 'listening' | 'thinking' | 'working' | 'speaking';

type Props = {
  spot: OrbSpot;
  state: OrbVisual;
  connected: boolean;
  tintWork: boolean; // cool tint while working (whether to show cloud work is still open)
  micLevel: React.MutableRefObject<(() => number) | null>;
  speechLevel?: () => number; // loudness of the voice being played, drives the orb while speaking
  onDown: () => void;
  onUp: () => void;
  // Floating desktop orb: dragging moves the window. A press that moves more than a few pixels
  // stops being "talk" (start() drops the audio) and becomes a drag (by() moves the window).
  onDrag?: { start: () => void; by: (dx: number, dy: number) => void };
  onMenu?: () => void;
  present?: boolean; // false: the orb shrinks away (desktop orb between conversations)
  seeing?: boolean; // a frame is being captured for "eyes on request": a thin ring around the orb
};

const DRAG_PX = 6;

const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

// A small dark glass sphere with soft light moving inside. No halo, no wobble.
export function Orb(p: Props) {
  const cv = useRef<HTMLCanvasElement>(null);
  const live = useRef(p);
  live.current = p;
  const pos = useRef({ x: 0, y: 0, r: 0 });
  const holding = useRef(false);
  const drag = useRef<{ x: number; y: number; on: boolean } | null>(null);

  useEffect(() => {
    const canvas = cv.current!;
    const ctx = canvas.getContext('2d')!;
    const o = { appear: 0, cool: 0, level: 0, lt: 0, ltT: 0, env: 0, act: 0, spin: 0, t: 0, dim: 0, see: 0 };
    let raf = 0, last = performance.now(), W = 0, H = 0;

    const resize = () => {
      const dpr = Math.min(2, devicePixelRatio || 1);
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; o.t += dt;
      const { spot, state, connected, tintWork, micLevel, speechLevel } = live.current;
      const P = pos.current;
      if (!P.r) Object.assign(P, spot);
      const k = 1 - Math.pow(0.012, dt);
      P.x += (spot.x - P.x) * k; P.y += (spot.y - P.y) * k; P.r += (spot.r - P.r) * k;

      o.appear += ((live.current.present === false ? 0 : 1) - o.appear) * Math.min(1, dt * 9);
      o.cool += ((state === 'working' && tintWork ? 1 : 0) - o.cool) * Math.min(1, dt * 2);
      o.dim += ((connected ? 0 : 1) - o.dim) * Math.min(1, dt * 3);
      o.see += ((live.current.seeing ? 1 : 0) - o.see) * Math.min(1, dt * 10);
      if (state === 'listening') {
        const mic = micLevel.current;
        if (mic) o.lt = mic();
        else { o.ltT -= dt; if (o.ltT <= 0) { o.lt = Math.random() < 0.2 ? 0.05 : 0.25 + Math.random() * 0.75; o.ltT = 0.07 + Math.random() * 0.12; } }
      } else o.lt = 0;
      o.level += (o.lt - o.level) * Math.min(1, dt * 12);
      const voice = state === 'speaking' && speechLevel ? speechLevel() : -1;
      const envT = state !== 'speaking' ? 0
        : voice >= 0 ? 0.2 + 0.8 * voice // the real voice
        : 0.3 + 0.7 * Math.abs(Math.sin(o.t * 6.8) * Math.sin(o.t * 2.2));
      o.env += (envT - o.env) * Math.min(1, dt * 10);
      const busy = state === 'thinking' || state === 'working';
      o.act += ((busy ? 1 : 0) - o.act) * Math.min(1, dt * 4);
      o.spin += dt * (state === 'thinking' ? 4.2 : state === 'working' ? 1.6 : 0.25);

      draw(ctx, W, H, P, o);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); };
  }, []);

  const hit = (e: React.PointerEvent) => {
    const b = cv.current!.getBoundingClientRect();
    const P = pos.current;
    return Math.hypot(e.clientX - b.left - P.x, e.clientY - b.top - P.y) < P.r * 1.8;
  };

  return (
    <canvas
      ref={cv}
      className="orb"
      role="button"
      aria-label="Hold to talk"
      onPointerDown={(e) => {
        if (e.button !== 0 || !hit(e)) return;
        holding.current = true;
        drag.current = { x: e.screenX, y: e.screenY, on: false };
        cv.current!.setPointerCapture(e.pointerId);
        p.onDown();
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!holding.current || !d || !p.onDrag) return;
        const dx = e.screenX - d.x, dy = e.screenY - d.y;
        if (!d.on && Math.hypot(dx, dy) < DRAG_PX) return;
        if (!d.on) { d.on = true; p.onDrag.start(); }
        p.onDrag.by(dx, dy);
        d.x = e.screenX; d.y = e.screenY;
      }}
      onPointerUp={() => {
        if (!holding.current) return;
        holding.current = false;
        if (!drag.current?.on) p.onUp();
        drag.current = null;
      }}
      onPointerCancel={() => {
        if (!holding.current) return;
        holding.current = false;
        if (!drag.current?.on) p.onUp();
        drag.current = null;
      }}
      onContextMenu={(e) => { if (p.onMenu) { e.preventDefault(); p.onMenu(); } }}
    />
  );
}

type O = { appear: number; cool: number; level: number; env: number; act: number; spin: number; t: number; dim: number; see: number };

function draw(ctx: CanvasRenderingContext2D, W: number, H: number, P: { x: number; y: number; r: number }, o: O) {
  ctx.clearRect(0, 0, W, H);
  if (o.appear < 0.01) return;
  const grow = 1 - Math.pow(1 - o.appear, 3); // ease out
  const s = grow * (reduce ? 1 : 1 + 0.018 * Math.sin(o.t * 1.1) + o.level * 0.14 + o.env * 0.06);
  const r = P.r * s, { x, y } = P;
  ctx.globalAlpha = (1 - o.dim * 0.55) * o.appear;

  const sh = ctx.createRadialGradient(x, y + r * 0.9, 0, x, y + r * 0.9, r * 1.3);
  sh.addColorStop(0, 'rgba(0,0,0,.5)'); sh.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = sh; ctx.fillRect(x - r * 1.5, y, r * 3, r * 2.3);

  const bl = 0.05 + o.level * 0.12 + o.env * 0.08;
  const g0 = ctx.createRadialGradient(x, y, r, x, y, r * 1.9);
  g0.addColorStop(0, `rgba(255,255,255,${bl})`); g0.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g0; ctx.beginPath(); ctx.arc(x, y, r * 1.9, 0, 7); ctx.fill();

  ctx.save(); ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.clip();
  const b = ctx.createRadialGradient(x, y - r * 0.3, r * 0.1, x, y, r);
  b.addColorStop(0, '#2a2a2e'); b.addColorStop(1, '#0e0e10');
  ctx.fillStyle = b; ctx.fillRect(x - r, y - r, r * 2, r * 2);

  ctx.globalCompositeOperation = 'lighter';
  const lc = [255, 255, 255].map((v, i) => Math.round(v + ([120, 160, 255][i] - v) * o.cool)).join(',');
  const blobs: [number, number, number, number][] = [[0.55, 1.0, 0.62, 0.42], [0.45, -1.3, 0.5, 0.3], [0.35, 1.7, 0.44, 0.26]];
  blobs.forEach(([d, sp, rad, al], i) => {
    const a = o.spin * sp + i * 2.1;
    const bx = x + Math.cos(a) * r * d * 0.6, by = y + Math.sin(a) * r * d * 0.6 - r * 0.08, br = r * rad * (1 + o.level * 0.5);
    const gg = ctx.createRadialGradient(bx, by, 0, bx, by, br * 1.6);
    const A = Math.min(0.95, al * (0.55 + o.level * 0.9 + o.env * 0.6 + o.act * 0.35));
    gg.addColorStop(0, `rgba(${lc},${A})`); gg.addColorStop(1, `rgba(${lc},0)`);
    ctx.fillStyle = gg; ctx.fillRect(x - r, y - r, r * 2, r * 2);
  });
  if (o.act > 0.01 && 'createConicGradient' in ctx) {
    const cg = ctx.createConicGradient(o.spin * 1.4, x, y);
    cg.addColorStop(0, 'rgba(255,255,255,0)'); cg.addColorStop(0.12, `rgba(${lc},${0.35 * o.act})`);
    cg.addColorStop(0.3, 'rgba(255,255,255,0)'); cg.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = cg; ctx.fillRect(x - r, y - r, r * 2, r * 2);
  }
  ctx.globalCompositeOperation = 'source-over';

  const rim = ctx.createRadialGradient(x, y, r * 0.7, x, y, r);
  rim.addColorStop(0, 'rgba(0,0,0,0)'); rim.addColorStop(1, 'rgba(0,0,0,.45)');
  ctx.fillStyle = rim; ctx.fillRect(x - r, y - r, r * 2, r * 2);
  const hx = x - r * 0.32, hy = y - r * 0.48;
  const sp = ctx.createRadialGradient(hx, hy, 0, hx, hy, r * 0.42);
  sp.addColorStop(0, 'rgba(255,255,255,.55)'); sp.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = sp; ctx.beginPath(); ctx.ellipse(hx, hy, r * 0.42, r * 0.26, -0.5, 0, 7); ctx.fill();
  ctx.restore();

  ctx.strokeStyle = 'rgba(255,255,255,.16)'; ctx.lineWidth = 0.75;
  ctx.beginPath(); ctx.arc(x, y, r - 0.4, 0, 7); ctx.stroke();
  if (o.see > 0.01) { // capturing a frame: a pulsing ring just outside the sphere
    ctx.strokeStyle = `rgba(255,255,255,${(o.see * (0.5 + 0.35 * Math.sin(o.t * 6))).toFixed(3)})`;
    ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(x, y, r * 1.22, 0, 7); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}
