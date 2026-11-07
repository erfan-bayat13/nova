import { useEffect, useRef, useState } from 'react';
import type { WidgetProps } from './types';

type P = { label?: string; seconds: number };
const C = 2 * Math.PI * 19;

export function Timer({ props: p, emit }: WidgetProps<P>) {
  const total = Math.max(1, Number(p.seconds) || 60);
  const [end, setEnd] = useState(() => Date.now() + total * 1000);
  const [now, setNow] = useState(Date.now());
  const fired = useRef(false);

  // a new duration restarts the timer
  useEffect(() => { setEnd(Date.now() + total * 1000); fired.current = false; }, [total]);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);

  const left = Math.max(0, Math.ceil((end - now) / 1000));
  useEffect(() => {
    if (left === 0 && !fired.current) { fired.current = true; emit('timer_done', { label: p.label }); }
  }, [left, emit, p.label]);

  return (
    <>
      <svg viewBox="0 0 48 48" aria-hidden="true">
        <circle className="track" cx="24" cy="24" r="19" />
        <circle className="prog" cx="24" cy="24" r="19" strokeDasharray={C} strokeDashoffset={C * (1 - left / total)} />
      </svg>
      <div>
        <div className="t" role="timer">{Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}</div>
        {p.label && <div className="lab">{p.label}</div>}
      </div>
    </>
  );
}
