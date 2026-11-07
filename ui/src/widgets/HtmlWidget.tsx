import { useEffect, useRef } from 'react';
import type { WidgetProps } from './types';

type P = { html: string; data?: unknown; height?: number };

// Generated widgets (built by Claude) run walled off: scripts only, no same-origin access.
export function HtmlWidget({ props: p, emit }: WidgetProps<P>) {
  const ref = useRef<HTMLIFrameElement>(null);
  const post = () => ref.current?.contentWindow?.postMessage({ type: 'props', data: p.data }, '*');
  useEffect(post, [p.data]);
  useEffect(() => {
    const on = (e: MessageEvent) => {
      if (e.source !== ref.current?.contentWindow) return;
      const m = e.data;
      if (m && m.type === 'emit' && typeof m.name === 'string') emit(m.name, m.data);
    };
    addEventListener('message', on);
    return () => removeEventListener('message', on);
  }, [emit]);
  return <iframe ref={ref} title="widget" sandbox="allow-scripts" srcDoc={p.html} onLoad={post} style={{ height: p.height ?? 320 }} />;
}
