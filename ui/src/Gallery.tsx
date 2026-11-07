// Dev only (?gallery): every widget type once with realistic props, plus the small ones as 170 x 72 chips.
import { useState } from 'react';
import { REGISTRY } from './widgets';

type Sample = { widget: string; props: Record<string, unknown>; wide?: boolean; short?: boolean };

const SAMPLES: Sample[] = [
  { widget: 'recipe', props: { title: 'Lemon garlic chicken', meta: '35 min · easy', servings: 4, steps: ['Pat the chicken dry and season well.', 'Sear skin side down for 6 minutes until golden.', 'Add garlic, lemon and stock, then roast at 200 °C for 20 minutes.'] } },
  { widget: 'checklist', props: { title: 'Ingredients', items: [{ id: 'a', label: 'Chicken thighs', detail: '800 g' }, { id: 'b', label: 'Garlic', detail: '6 cloves', checked: true }, { id: 'c', label: 'Lemons', detail: '2' }, { id: 'd', label: 'Chicken stock', detail: '250 ml' }] } },
  { widget: 'timer', props: { label: 'Roast', seconds: 1200 } },
  { widget: 'stacked_bar', wide: true, props: { caption: 'Calories this week', headline: { value: '1,840', unit: 'kcal avg' }, legend: [{ label: 'Protein', value: '120 g' }, { label: 'Carbs', value: '210 g' }, { label: 'Fat', value: '64 g' }], categories: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], series: [{ label: 'Protein', values: [500, 560, 480, 520, 540, 600, 450] }, { label: 'Carbs', values: [800, 760, 900, 840, 780, 1000, 850] }, { label: 'Fat', values: [500, 450, 520, 480, 560, 640, 500] }], goal: { value: 2000, label: 'Goal' } } },
  { widget: 'html', props: { height: 90, html: '<meta name="color-scheme" content="dark"><body style="margin:0;font:15px -apple-system;color:#f5f5f7;display:grid;place-items:center;height:90px">generated widget (sandboxed iframe)</body>' } },
  { widget: 'note', props: { title: 'Dinner plan', text: 'Chicken tonight, leftovers for lunch.\nBuy lemons on the way home.\n\nCall Mum about Sunday.' } },
  { widget: 'stat', props: { label: 'Calories today', value: 1840, unit: 'kcal', delta: '+120', caption: '160 kcal left of your 2,000 goal' } },
  { widget: 'list', props: { title: 'Packing', ordered: false, items: ['Passport', 'Charger and adapter', 'Sunscreen', 'Running shoes', 'Book'] } },
  { widget: 'table', props: { title: 'Macros', columns: ['Food', 'Protein', 'Carbs', 'kcal'], rows: [['Chicken thigh', '38 g', '0 g', 310], ['Rice, 1 cup', '4 g', '45 g', 205], ['Broccoli', '3 g', '6 g', 35], ['Olive oil, 1 tbsp', '0 g', '0 g', 119], ['Lemon', '1 g', '5 g', 17]] } },
  { widget: 'progress', props: { label: 'Chapters read', value: 3, total: 8 } },
  { widget: 'counter', props: { label: 'Glasses of water', value: 5, step: 1 } },
  { widget: 'table', short: true, props: { title: 'Long table (scrolls in the card)', columns: ['Day', 'Steps'], rows: Array.from({ length: 16 }, (_, i) => [`Day ${i + 1}`, String(6000 + ((i * 937) % 4000))]) } },
];
const CHIPS: Sample[] = [
  { widget: 'stat', props: { label: 'Calories', value: 1840, unit: 'kcal', delta: '+120' } },
  { widget: 'stat', props: { label: 'Weather', value: 'Partly cloudy' } },
  { widget: 'progress', props: { label: 'Water', value: 40 } },
  { widget: 'progress', props: { label: 'Chapters', value: 3, total: 8 } },
  { widget: 'counter', props: { label: 'Laps', value: 12 } },
  { widget: 'timer', props: { label: 'Tea', seconds: 240 } },
];

// holds props in state so local changes (counter, checklist) work like they do on the canvas
function Card({ s }: { s: Sample }) {
  const Comp = REGISTRY[s.widget];
  const [props, setProps] = useState(s.props);
  return (
    <section className={`w w-${s.widget}`}>
      <div className="inner">
        <Comp id={s.widget} props={props} emit={(n, d) => console.log('emit', s.widget, n, d)} update={(p) => setProps((x) => ({ ...x, ...p }))} />
      </div>
    </section>
  );
}

export function Gallery() {
  return (
    <div className="gallery">
      <h1>Widget gallery ({Object.keys(REGISTRY).length} types)</h1>
      <div className="g-chips">{CHIPS.map((s, i) => <Card key={i} s={s} />)}</div>
      <div className="g-grid">
        {SAMPLES.map((s, i) => (
          <div key={i} className={[s.wide && 'g-wide', s.short && 'g-short'].filter(Boolean).join(' ') || undefined}>
            <div className="g-tag">{s.widget}</div>
            <Card s={s} />
          </div>
        ))}
      </div>
    </div>
  );
}
