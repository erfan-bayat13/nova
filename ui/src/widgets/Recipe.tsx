import { RollingText } from '../RollingText';
import type { WidgetProps } from './types';

type P = { title: string; meta?: string; servings?: number; steps: string[] };

export function Recipe({ props: p }: WidgetProps<P>) {
  return (
    <>
      <div className="rc-head">
        <div>
          <h2>{p.title}</h2>
          {p.meta && <div className="meta">{p.meta}</div>}
        </div>
        {p.servings != null && (
          <div className="serv">
            <div className="big num"><RollingText text={String(p.servings)} /></div>
            <div className="u">servings</div>
          </div>
        )}
      </div>
      <ol className="steps">
        {(p.steps ?? []).map((s, i) => <li key={i}><span><RollingText text={s} /></span></li>)}
      </ol>
    </>
  );
}
