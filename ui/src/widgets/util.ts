// Defensive coercion for widget props. The small local model sometimes sends strings for
// numbers, an object for an array, or a number where text was asked for.

// Any prop → display text ('' for null / NaN, a readable field for {label|text|name…}).
export function str(v: unknown): string {
  if (v == null) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
  if (typeof v === 'boolean') return String(v);
  if (Array.isArray(v)) return v.map(str).filter(Boolean).join(', ');
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>;
    for (const k of ['label', 'text', 'name', 'title', 'value', 'item']) {
      if (typeof o[k] === 'string' || typeof o[k] === 'number') return String(o[k]);
    }
    try { return JSON.stringify(v); } catch { return ''; }
  }
  return '';
}

// A number from a number or a numeric-looking string ("1,840", "40%", "3 of 8" → 3). null if none.
export function num(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string') {
    const m = v.replace(/,/g, '').replace(/−/g, '-').match(/-?\d+(?:\.\d+)?|-?\.\d+/);
    if (m) { const n = Number(m[0]); return Number.isFinite(n) ? n : null; }
  }
  return null;
}

// Many lines of text: an array becomes one line per entry; a literal "\n" (escaped) becomes a break.
export function block(v: unknown): string {
  const s = Array.isArray(v) ? v.map(str).join('\n') : str(v);
  return s.replace(/\\n/g, '\n');
}

// A list of things from an array, an object (its values) or a string (one per line, else per comma).
export function list(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  if (v && typeof v === 'object') return Object.values(v);
  if (typeof v === 'string' && v.trim()) {
    const lines = v.replace(/\\n/g, '\n').split(/\n+/).map((l) => l.replace(/^\s*(?:[-*•]|\d+[.)])\s+/, '').trim()).filter(Boolean);
    return lines.length > 1 ? lines : (lines[0] ?? '').split(/\s*[;,]\s*/).filter(Boolean);
  }
  return [];
}

// 1840 → "1,840", -3 → "−3" (true minus). At most two decimals.
export function fmt(n: number): string {
  return n.toLocaleString('en-US', { maximumFractionDigits: 2 }).replace('-', '−');
}

export function flag(v: unknown): boolean {
  return v === true || (typeof v === 'string' && /^(true|yes|1|on)$/i.test(v.trim())) || v === 1;
}
