import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import type { ClientMsg, Importance, OrbState, Props, ServerMsg } from './protocol';
import { WIDGET_TYPES } from './widgets';
import { speak, stopSpeaking } from './voice';

export type WidgetState = {
  id: string;
  widget: string; // '' while pending
  props: Props;
  importance: Importance;
  status: 'pending' | 'live' | 'leaving';
  born: number;
  leaveDelay: number;
};
type Widgets = Record<string, WidgetState>;
type Action = ServerMsg | { type: 'gone'; id: string } | { type: 'local'; id: string; props: Props };

let seq = 0;
function reducer(s: Widgets, a: Action): Widgets {
  switch (a.type) {
    case 'pending':
      if (s[a.id] && s[a.id].status !== 'leaving') return s;
      return { ...s, [a.id]: { id: a.id, widget: '', props: {}, importance: a.importance, status: 'pending', born: ++seq, leaveDelay: 0 } };
    case 'create': {
      const p = s[a.id];
      const keep = p && p.status !== 'leaving';
      return { ...s, [a.id]: { id: a.id, widget: a.widget, props: a.props ?? {}, importance: a.importance ?? p?.importance ?? 'hero', status: 'live', born: keep ? p.born : ++seq, leaveDelay: 0 } };
    }
    case 'update':
    case 'local': {
      const p = s[a.id];
      if (!p || p.status === 'leaving') return s;
      return { ...s, [a.id]: { ...p, props: { ...p.props, ...a.props } } };
    }
    case 'remove': {
      const p = s[a.id];
      if (!p || p.status === 'leaving') return s;
      return { ...s, [a.id]: { ...p, status: 'leaving', leaveDelay: 0 } };
    }
    case 'clear': {
      const out: Widgets = {};
      // smallest first, so satellites leave before the big cards
      const order = Object.values(s).filter((w) => w.status !== 'leaving')
        .sort((a, b) => rank(a.importance) - rank(b.importance) || b.born - a.born);
      for (const w of Object.values(s)) out[w.id] = w;
      order.forEach((w, i) => (out[w.id] = { ...w, status: 'leaving', leaveDelay: i * 90 }));
      return out;
    }
    case 'gone': {
      const { [a.id]: _, ...rest } = s;
      return rest;
    }
    default:
      return s;
  }
}
const rank = (i: Importance) => ({ satellite: 0, side: 1, hero: 2, full: 3 })[i];

export function useCanvas(url: string) {
  const [widgets, dispatch] = useReducer(reducer, {});
  const [orb, setOrb] = useState<OrbState>('idle');
  const [speaking, setSpeaking] = useState(false);
  const [connected, setConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  const send = useCallback((m: ClientMsg) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m));
  }, []);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout>;
    const connect = () => {
      const sock = new WebSocket(url);
      ws.current = sock;
      sock.onopen = () => {
        setConnected(true);
        sock.send(JSON.stringify({ type: 'hello', widgets: WIDGET_TYPES } satisfies ClientMsg));
      };
      sock.onclose = () => {
        setConnected(false);
        if (!stopped) retry = setTimeout(connect, 1500);
      };
      sock.onmessage = (e) => {
        let m: ServerMsg;
        try { m = JSON.parse(e.data); } catch { return; }
        if (m.type === 'orb') setOrb(m.state);
        else if (m.type === 'say') speak(m.text, setSpeaking);
        else dispatch(m);
      };
    };
    connect();
    return () => { stopped = true; clearTimeout(retry); ws.current?.close(); };
  }, [url]);

  // the canvas is the source of truth: report it after every change
  useEffect(() => {
    const t = setTimeout(() => send({
      type: 'canvas_state',
      widgets: Object.values(widgets).filter((w) => w.status === 'live').map(({ id, widget, props }) => ({ id, widget, props })),
    }), 200);
    return () => clearTimeout(t);
  }, [widgets, send]);

  const orbDown = useCallback(() => {
    stopSpeaking(setSpeaking); // the user can always interrupt
    setOrb('listening');
    send({ type: 'orb_down' });
  }, [send]);
  const orbUp = useCallback(() => send({ type: 'orb_up' }), [send]);
  // mic audio: raw PCM16 16 kHz mono, binary frames between orb_down and orb_up (PROTOCOL.md)
  const sendAudio = useCallback((frame: ArrayBuffer) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(frame);
  }, []);
  const emit = useCallback((id: string, name: string, data?: unknown) => send({ type: 'event', id, name, data }), [send]);
  const localUpdate = useCallback((id: string, props: Props) => dispatch({ type: 'local', id, props }), []);
  const gone = useCallback((id: string) => dispatch({ type: 'gone', id }), []);

  return { widgets, orb: speaking ? ('speaking' as const) : orb, connected, orbDown, orbUp, sendAudio, emit, localUpdate, gone };
}
