import type { ComponentType } from 'react';
import type { WidgetProps } from './types';
import { Recipe } from './Recipe';
import { Checklist } from './Checklist';
import { Timer } from './Timer';
import { StackedBar } from './StackedBar';
import { HtmlWidget } from './HtmlWidget';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const REGISTRY: Record<string, ComponentType<WidgetProps<any>>> = {
  recipe: Recipe,
  checklist: Checklist,
  timer: Timer,
  stacked_bar: StackedBar,
  html: HtmlWidget,
};
export const WIDGET_TYPES = Object.keys(REGISTRY);
