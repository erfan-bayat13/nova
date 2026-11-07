import type { Props } from '../protocol';

export type WidgetProps<P = Props> = {
  id: string;
  props: P;
  emit: (name: string, data?: unknown) => void;
  update: (props: Partial<P>) => void; // local change (e.g. a ticked item), reported via canvas_state
};
