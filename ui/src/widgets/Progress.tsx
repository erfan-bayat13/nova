import { useEffect, useState } from 'react';
import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { fmt, num, str } from './util';

type P = { label?: unknown; value?: unknown; total?: unknown; unit?: unknown };

export function Progress({ props: p }: WidgetProps<P>) {
  const label = str(p.label), unit = str(p.unit);
  const value = num(p.value) ?? 0;
  const t = num(p.total);
  const total = t && t > 0 ? t : 100;
  const pct = Math.max(0, Math.min(100, (value / total) * 100));

  // "40%" when it is out of 100 with no unit, else "3 of 8" / "1.5 of 2.5 L"
  const percent = total === 100 && !unit;
  const big = percent ? String(Math.max(0, Math.round((value / total) * 100))) : fmt(value);
  const rest = percent ? '%' : `of ${fmt(total)}${unit ? ` ${unit}` : ''}`;

  // grow from empty on first draw, then follow the value
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const r = requestAnimationFrame(() => setShown(pct));
    return () => cancelAnimationFrame(r);
  }, [pct]);

  return (
    <div className="pg">
      {label && <div className="cap">{label}</div>}
      <div className="pg-val num">
        <RollingText text={big} />
        <small className={percent ? 'pc' : undefined}>{rest}</small>
      </div>
      <div className="pg-bar" role="progressbar" aria-label={label || 'Progress'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <i style={{ width: `${shown}%` }} />
      </div>
    </div>
  );
}
