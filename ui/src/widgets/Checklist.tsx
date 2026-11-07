import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';

type Item = { id: string; label: string; detail?: string; checked?: boolean };
type P = { title?: string; items: Item[] };

export function Checklist({ props: p, emit, update }: WidgetProps<P>) {
  const toggle = (it: Item) => {
    const checked = !it.checked;
    update({ items: p.items.map((x) => (x.id === it.id ? { ...x, checked } : x)) });
    emit('item_checked', { item: it.id, checked });
  };
  return (
    <>
      {p.title && <div className="cap">{p.title}</div>}
      <ul className="ing">
        {(p.items ?? []).map((it) => (
          <li key={it.id}>
            <button type="button" aria-pressed={!!it.checked} onClick={() => toggle(it)}>
              <span className="dot" />
              <span className="nm">{it.label}</span>
              {it.detail && <span className="q"><RollingText text={it.detail} /></span>}
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
