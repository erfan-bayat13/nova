// Message shapes shared with the orchestrator. Spec: ../docs/PROTOCOL.md

export type Importance = 'hero' | 'side' | 'satellite' | 'full';
export type OrbState = 'idle' | 'listening' | 'thinking' | 'working';
export type Props = Record<string, unknown>;
export type Mode = 'canvas' | 'voice';

export type ServerMsg =
  | { type: 'orb'; state: OrbState }
  | { type: 'say'; text: string }
  | { type: 'speech_start' }
  | { type: 'speech_end'; text?: string }
  | { type: 'pending'; id: string; importance: Importance }
  | { type: 'create'; id: string; widget: string; props: Props; importance: Importance }
  | { type: 'update'; id: string; props: Props }
  | { type: 'remove'; id: string }
  | { type: 'clear' };

export type ClientMsg =
  | { type: 'hello'; widgets: string[]; mode?: Mode }
  | { type: 'orb_down' }
  | { type: 'orb_cancel' }
  | { type: 'orb_up' }
  | { type: 'event'; id: string; name: string; data?: unknown }
  | { type: 'canvas_state'; widgets: { id: string; widget: string; props: Props }[] };
