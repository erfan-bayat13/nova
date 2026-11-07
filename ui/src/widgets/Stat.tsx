import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { fmt, num, str } from './util';

type P = { label?: unknown; value?: unknown; unit?: unknown; delta?: unknown; caption?: unknown };

// "+120" / "−3" for numbers; strings are the model's own words
function delta(v: unknown): string {
  if (typeof v === 'number' && Number.isFinite(v)) return (v > 0 ? '+' : v < 0 ? '−' : '') + fmt(Math.abs(v));
  return str(v).trim();
}

export function Stat({ props: p }: WidgetProps<P>) {
  const label = str(p.label), unit = str(p.unit), caption = str(p.caption), d = delta(p.delta);
  const value = typeof p.value === 'number' ? (Number.isFinite(p.value) ? fmt(p.value) : '–') : str(p.value) || '–';
  const numeric = num(value) !== null && /^[−+-]?[\d,.\s]+$/.test(value);
  return (
    <div className="st">
      {label && <div className="cap">{label}</div>}
      <div className={`st-val num${numeric ? '' : ' txt'}`}>
        <RollingText text={value} />
        {unit && <small>{unit}</small>}
      </div>
      {d && <div className="st-del"><RollingText text={d} /></div>}
      {caption && <div className="st-cap"><RollingText text={caption} /></div>}
    </div>
  );
}
