// Places widgets from their importance. The model never picks coordinates.
import type { WidgetState } from './useCanvas';

export type Rect = { x: number; y: number; w: number; h: number };
export type OrbSpot = { x: number; y: number; r: number };

const DOCK = 64; // orb center distance from the bottom when docked

export function orbSpot(docked: boolean, W: number, H: number): OrbSpot {
  return docked ? { x: W / 2, y: H - DOCK, r: 20 } : { x: W / 2, y: H * 0.47, r: Math.min(34, W * 0.08) };
}

function stack(items: WidgetState[], x: number, y: number, w: number, h: number, gap: number, out: Record<string, Rect>) {
  if (!items.length) return;
  const each = (h - gap * (items.length - 1)) / items.length;
  items.forEach((it, i) => (out[it.id] = { x, y: y + i * (each + gap), w, h: each }));
}

export function layout(ws: WidgetState[], W: number, H: number) {
  const rects: Record<string, Rect> = {};
  const docked = ws.length > 0;
  const orb = orbSpot(docked, W, H);
  const pad = Math.max(16, W * 0.05);
  const top = pad;
  const avail = Math.max(200, H - 120 - top);
  const colW = Math.min(960, W - pad * 2);
  const x0 = (W - colW) / 2;
  const gap = 16;
  const by = (k: string) => ws.filter((w) => w.importance === k);
  const full = by('full'), hero = by('hero'), side = by('side'), sats = by('satellite');
  const wide = W >= 760;

  if (full.length || !wide) {
    // one column: full-width cards stacked
    stack([...full, ...hero, ...side], x0, top, colW, avail, 12, rects);
  } else if (hero.length && side.length) {
    const hw = Math.round(colW * 0.6);
    stack(hero, x0, top, hw, avail, gap, rects);
    stack(side, x0 + hw + gap, top, colW - hw - gap, avail, gap, rects);
  } else if (hero.length) {
    const w = Math.min(colW, 720);
    stack(hero, (W - w) / 2, top, w, avail, gap, rects);
  } else {
    const w = Math.min(colW, 440);
    stack(side, (W - w) / 2, top, w, avail, gap, rects);
  }

  // satellites sit beside the orb: right, left, further right, further left…
  const sw = wide ? 170 : Math.min(160, W / 2 - 44 - pad);
  sats.forEach((s, i) => {
    const n = Math.floor(i / 2);
    const right = i % 2 === 0;
    const off = 36 + 8 + n * (sw + 12);
    rects[s.id] = { x: right ? W / 2 + off : W / 2 - off - sw, y: orb.y - 36, w: sw, h: 72 };
  });

  return { rects, orb };
}
