import { useEffect, useRef } from 'react';

const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

function Token({ t }: { t: string }) {
  const el = useRef<HTMLSpanElement>(null);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (reduce || !el.current?.animate) return;
    el.current.animate(
      [{ transform: 'translateY(.45em)', opacity: 0, filter: 'blur(2px)' }, { transform: 'none', opacity: 1, filter: 'blur(0)' }],
      { duration: 380, easing: 'cubic-bezier(.32,.72,0,1)' },
    );
  }, [t]);
  return <span ref={el} className="roll">{t}</span>;
}

// Text whose changed words roll in place, like iOS numeric transitions ("5 L" → "7 L").
export function RollingText({ text }: { text: string }) {
  const parts = String(text ?? '').split(/(\s+)/);
  const prev = useRef<string[]>(parts);
  const sameShape = prev.current.length === parts.length;
  useEffect(() => { prev.current = parts; });
  if (!sameShape) return <Token t={String(text)} />;
  return <>{parts.map((t, i) => (/^\s+$/.test(t) ? t : <Token key={i} t={t} />))}</>;
}
