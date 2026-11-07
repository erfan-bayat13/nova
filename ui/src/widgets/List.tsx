import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { flag, list, str } from './util';

type P = { title?: unknown; items?: unknown; ordered?: unknown };

export function List({ props: p }: WidgetProps<P>) {
  const title = str(p.title);
  const items = list(p.items).map(str).filter((s) => s.trim());
  const Tag = flag(p.ordered) ? 'ol' : 'ul';
  return (
    <>
      {title && <div className="cap">{title}</div>}
      <Tag className={`ls ${Tag === 'ol' ? 'ordered' : 'bulleted'}`}>
        {items.map((s, i) => <li key={i}><span><RollingText text={s} /></span></li>)}
      </Tag>
    </>
  );
}
