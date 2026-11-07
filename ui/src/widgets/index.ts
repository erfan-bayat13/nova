import type { ComponentType } from 'react';
import type { WidgetProps } from './types';
import { Recipe } from './Recipe';
import { Checklist } from './Checklist';
import { Timer } from './Timer';
import { StackedBar } from './StackedBar';
import { HtmlWidget } from './HtmlWidget';
import { Note } from './Note';
import { Stat } from './Stat';
import { List } from './List';
import { Table } from './Table';
import { Progress } from './Progress';
import { Counter } from './Counter';
import './widgets.css';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const REGISTRY: Record<string, ComponentType<WidgetProps<any>>> = {
  recipe: Recipe,
  checklist: Checklist,
  timer: Timer,
  stacked_bar: StackedBar,
  html: HtmlWidget,
  note: Note,
  stat: Stat,
  list: List,
  table: Table,
  progress: Progress,
  counter: Counter,
};
export const WIDGET_TYPES = Object.keys(REGISTRY);
