import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { list, str } from './util';

type P = { title?: unknown; columns?: unknown; rows?: unknown };

// "12", "1,840", "40%", "$3.50", "12 g", "−3", "1:30"
const NUMERIC = /^[+\-−~≈<>]?\s*[$€£¥]?\s*\d[\d,]*(?:\.\d+)?(?:[:/]\d+)?\s*(?:%|k|m|b|g|kg|mg|lb|lbs|oz|kcal|cal|min|mins|h|hr|s|ms|x|°|°c|°f)?$/i;
const MAX_ROWS = 200;

// columns and rows as the model might send them: lists, "a | b" strings, or objects keyed by column
function normalize(p: P) {
  const raw = list(p.rows).slice(0, MAX_ROWS);
  let cols = list(p.columns).map(str);
  const firstObj = raw.find((r) => r && typeof r === 'object' && !Array.isArray(r)) as Record<string, unknown> | undefined;
  if (!cols.length && firstObj) cols = Object.keys(firstObj);
  const rows = raw.map((r): string[] => {
    if (Array.isArray(r)) return r.map(str);
    if (r && typeof r === 'object') {
      const o = r as Record<string, unknown>;
      return cols.length ? cols.map((c) => str(o[c] ?? o[c.toLowerCase()])) : Object.values(o).map(str);
    }
    const s = str(r);
    const sep = /[|\t]/.test(s) ? /\s*[|\t]\s*/ : cols.length > 1 ? /\s*,\s*/ : null;
    return sep ? s.split(sep) : [s];
  });
  const n = Math.max(cols.length, ...rows.map((r) => r.length));
  const head = Array.from({ length: n }, (_, j) => cols[j] ?? '');
  const body = rows.map((r) => Array.from({ length: n }, (_, j) => r[j] ?? ''));
  const right = head.map((_, j) => {
    const cells = body.map((r) => r[j].trim()).filter(Boolean);
    return cells.length > 0 && cells.every((c) => NUMERIC.test(c));
  });
  return { head, body, right };
}

export function Table({ props: p }: WidgetProps<P>) {
  const title = str(p.title);
  const { head, body, right } = normalize(p);
  const cls = (j: number) => (right[j] ? 'r' : undefined);
  return (
    <>
      {title && <div className="cap">{title}</div>}
      {head.length > 0 && (
        <table className="tb">
          {head.some(Boolean) && (
            <thead><tr>{head.map((h, j) => <th key={j} className={cls(j)}>{h}</th>)}</tr></thead>
          )}
          <tbody>
            {body.map((r, i) => (
              <tr key={i}>{r.map((c, j) => <td key={j} className={cls(j)}><RollingText text={c} /></td>)}</tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
