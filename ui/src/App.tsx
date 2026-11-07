import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useCanvas } from './useCanvas';
import { layout } from './layout';
import { Orb } from './Orb';
import { WidgetFrame } from './WidgetFrame';
import { REGISTRY } from './widgets';
import { startMic, type Mic } from './mic';

const q = new URLSearchParams(location.search);
const WS_URL = q.get('ws') ?? `ws://${location.hostname || 'localhost'}:8765/canvas`;
const TINT_WORK = q.has('tint'); // ?tint shows cloud work as a cool tint on the orb

export function App() {
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: innerWidth, h: innerHeight });
  const c = useCanvas(WS_URL);
  const mic = useRef<Mic | null>(null);
  const micLevel = useRef<(() => number) | null>(null);
  const micAsked = useRef(false);
  const held = useRef(false);

  useLayoutEffect(() => {
    const el = stage.current!;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Hold the orb (or Space) to talk: mic audio streams to the orchestrator as PCM16 16 kHz frames
  // until release. The last partial frame is flushed before orb_up so the utterance isn't cut.
  const down = () => {
    held.current = true;
    c.orbDown();
    if (mic.current) mic.current.start(c.sendAudio);
    else if (!micAsked.current) {
      micAsked.current = true;
      startMic().then((m) => {
        mic.current = m;
        micLevel.current = m?.level ?? null;
        if (m && held.current) m.start(c.sendAudio); // permission prompt finished while still holding
      });
    }
  };
  const up = () => {
    held.current = false;
    mic.current?.stop();
    c.orbUp();
  };

  // Space works as hold-to-talk too
  const keys = useRef({ down, up, held: false });
  keys.current.down = down;
  keys.current.up = up;
  useEffect(() => {
    const k = keys.current;
    const kd = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat || (e.target as Element | null)?.closest?.('button,input,textarea')) return;
      e.preventDefault(); k.held = true; k.down();
    };
    const ku = (e: KeyboardEvent) => { if (e.code === 'Space' && k.held) { k.held = false; k.up(); } };
    addEventListener('keydown', kd); addEventListener('keyup', ku);
    return () => { removeEventListener('keydown', kd); removeEventListener('keyup', ku); };
  }, []);

  const list = Object.values(c.widgets).sort((a, b) => a.born - b.born);
  const { rects, orb } = layout(list, size.w, size.h);

  return (
    <div className="stage" ref={stage}>
      <Orb spot={orb} state={c.orb} connected={c.connected} tintWork={TINT_WORK} micLevel={micLevel} onDown={down} onUp={up} />
      {list.map((w) => {
        const Comp = REGISTRY[w.widget];
        return (
          <WidgetFrame key={w.id} w={w} rect={rects[w.id]} orb={orb} onGone={c.gone}>
            {Comp && <Comp id={w.id} props={w.props} emit={(n, d) => c.emit(w.id, n, d)} update={(p) => c.localUpdate(w.id, p)} />}
          </WidgetFrame>
        );
      })}
    </div>
  );
}
