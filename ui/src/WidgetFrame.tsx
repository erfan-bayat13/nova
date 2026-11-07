import { useEffect, useLayoutEffect, useState } from 'react';
import type { Rect, OrbSpot } from './layout';
import type { WidgetState } from './useCanvas';

type Props = { w: WidgetState; rect: Rect; orb: OrbSpot; onGone: (id: string) => void; children: React.ReactNode };

// Grows a card out of the orb, keeps it in its slot, and pulls it back in when it leaves.
export function WidgetFrame({ w, rect, orb, onGone, children }: Props) {
  const [entered, setEntered] = useState(false);

  useLayoutEffect(() => {
    let a = 0, b = 0;
    a = requestAnimationFrame(() => { b = requestAnimationFrame(() => setEntered(true)); });
    return () => { cancelAnimationFrame(a); cancelAnimationFrame(b); };
  }, []);

  useEffect(() => {
    if (w.status !== 'leaving') return;
    const t = setTimeout(() => onGone(w.id), 750 + w.leaveDelay);
    return () => clearTimeout(t);
  }, [w.status, w.id, w.leaveDelay, onGone]);

  const collapsed = !entered || w.status === 'leaving';
  const pending = w.status === 'pending';
  const satellite = w.importance === 'satellite';

  return (
    <section
      className={`w w-${w.widget || 'pending'}${pending ? ' building' : ''}`}
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        maxHeight: rect.h,
        height: satellite ? rect.h : pending ? Math.min(rect.h, 380) : undefined,
        // scaling around the orb's point makes the card come out of, and go back into, the orb
        transformOrigin: `${orb.x - rect.x}px ${orb.y - rect.y}px`,
        transform: collapsed ? 'scale(.04)' : 'none',
        opacity: collapsed ? 0 : 1,
        filter: collapsed ? 'blur(6px)' : 'none',
        transitionDelay: w.status === 'leaving' ? `${w.leaveDelay}ms` : '0ms',
      }}
    >
      <div className="inner">{children}</div>
    </section>
  );
}
