import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';
import { block, str } from './util';

type P = { title?: unknown; text?: unknown };

export function Note({ props: p }: WidgetProps<P>) {
  const title = str(p.title);
  // keep single line breaks, collapse runs of blank lines into one gap
  const lines: string[] = [];
  for (const l of block(p.text).split(/\r?\n/)) {
    if (l.trim()) lines.push(l.trim());
    else if (lines.length && lines[lines.length - 1] !== '') lines.push('');
  }
  while (lines.length && lines[lines.length - 1] === '') lines.pop();
  return (
    <>
      {title && <h2 className="nt-title"><RollingText text={title} /></h2>}
      <div className="nt-body">
        {lines.map((l, i) => (l ? <p key={i}><RollingText text={l} /></p> : <div key={i} className="nt-gap" />))}
      </div>
    </>
  );
}
