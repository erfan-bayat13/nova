import { useRef } from 'react';
import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { fmt, num, str } from './util';

type P = { label?: unknown; value?: unknown; step?: unknown };

const round = (n: number) => Math.round(n * 1e6) / 1e6; // 0.1 + 0.2 stays 0.3

export function Counter({ props: p, emit, update }: WidgetProps<P>) {
  const label = str(p.label);
  const value = num(p.value) ?? 0;
  const step = Math.abs(num(p.step) ?? 1) || 1;
  // clicks in quick succession must build on each other, before the new value has rendered
  const cur = useRef(value);
  cur.current = value;
  const bump = (dir: 1 | -1) => {
    const next = round(cur.current + dir * step);
    cur.current = next;
    update({ value: next });
    emit('changed', { value: next });
  };
  return (
    <div className="ct">
      {label && <div className="cap">{label}</div>}
      <div className="ct-val num" aria-live="polite"><RollingText text={fmt(value)} /></div>
      <button type="button" className="ct-btn minus" aria-label={`Decrease${label ? ` ${label}` : ''}`} onClick={() => bump(-1)}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10" /></svg>
      </button>
      <button type="button" className="ct-btn plus" aria-label={`Increase${label ? ` ${label}` : ''}`} onClick={() => bump(1)}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10M8 3v10" /></svg>
      </button>
    </div>
  );
}
