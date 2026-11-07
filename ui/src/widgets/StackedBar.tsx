import { useEffect, useRef, useState } from 'react';
import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';

type P = {
  caption?: string;
  headline?: { value: string; unit?: string };
  legend?: { label: string; value: string }[];
  categories: string[];
  series: { label: string; values: number[] }[];
  goal?: { value: number; label?: string };
  max?: number;
};

const COLORS = ['var(--blue)', 'var(--cyan)', 'var(--gray3)', 'var(--indigo)'];
const X0 = 8, X1 = 650, Y0 = 246, PH = 230;

function useTween(target: number[][]) {
  const [v, setV] = useState(() => target.map((r) => r.map(() => 0)));
  const cur = useRef(v);
  const key = JSON.stringify(target);
  useEffect(() => {
    const from = cur.current, t0 = performance.now(), d = 800;
    let raf = 0;
    const f = (n: number) => {
      const p = Math.min(1, (n - t0) / d), e = 1 - Math.pow(1 - p, 4);
      const next = target.map((r, i) => r.map((x, j) => (from[i]?.[j] ?? 0) + (x - (from[i]?.[j] ?? 0)) * e));
      cur.current = next; setV(next);
      if (p < 1) raf = requestAnimationFrame(f);
    };
    raf = requestAnimationFrame(f);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return v;
}

export function StackedBar({ props: p }: WidgetProps<P>) {
  const cats = p.categories ?? [];
  const series = p.series ?? [];
  const vals = useTween(series.map((s) => cats.map((_, i) => Number(s.values?.[i]) || 0)));
  const totals = cats.map((_, i) => series.reduce((s, _x, k) => s + (series[k].values?.[i] || 0), 0));
  const max = p.max ?? Math.max(p.goal?.value ?? 0, ...totals, 1) * 1.12;
  const ys = (v: number) => Y0 - (v / max) * PH;
  const step = niceStep(max);
  const ticks = Array.from({ length: Math.floor(max / step) + 1 }, (_, i) => i * step);
  const slot = (X1 - X0) / Math.max(1, cats.length), bw = Math.min(36, slot * 0.42);

  return (
    <>
      <div className="ch-head">
        <div>
          {p.caption && <div className="cap"><RollingText text={p.caption} /></div>}
          {p.headline && <div className="kc"><span className="num"><RollingText text={p.headline.value} /></span>{p.headline.unit && <small>{p.headline.unit}</small>}</div>}
        </div>
        {p.legend && (
          <div className="legend">
            {p.legend.map((l, i) => (
              <span key={l.label}><i className="sw" style={{ ['--c' as string]: COLORS[i % COLORS.length] }} />{l.label}<b><RollingText text={l.value} /></b></span>
            ))}
          </div>
        )}
      </div>
      <svg className="chart" viewBox="0 0 700 280" role="img" aria-label={p.caption ?? 'Bar chart'}>
        {ticks.map((t) => (
          <g key={t}><line className="grid" x1={X0} x2={X1} y1={ys(t)} y2={ys(t)} /><text x={X1 + 10} y={ys(t) + 4}>{t.toLocaleString('en-US')}</text></g>
        ))}
        {p.goal && (
          <g><line className="target" x1={X0} x2={X1} y1={ys(p.goal.value)} y2={ys(p.goal.value)} />
            <text x={X1 + 10} y={ys(p.goal.value) + 4} className="goal">{p.goal.label ?? 'Goal'}</text></g>
        )}
        {cats.map((c, i) => {
          const cx = X0 + slot * i + slot / 2, x = cx - bw / 2;
          let base = 0;
          return (
            <g key={i}>
              {series.map((_, k) => {
                const v = vals[k]?.[i] ?? 0, y = ys(base + v), h = Math.max(0, ys(base) - y - (v > 0 ? 2 : 0));
                base += v;
                return <rect key={k} x={x} width={bw} y={y} height={h} rx={k === series.length - 1 ? 5 : 0} style={{ fill: COLORS[k % COLORS.length] }} />;
              })}
              <text x={cx} y={Y0 + 24} textAnchor="middle">{c}</text>
            </g>
          );
        })}
      </svg>
    </>
  );
}

function niceStep(max: number) {
  const raw = max / 3, p = Math.pow(10, Math.floor(Math.log10(raw)));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw;
}
