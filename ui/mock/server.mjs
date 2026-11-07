// Fake orchestrator. Speaks the real protocol (docs/PROTOCOL.md) and replays the demo:
// each time you hold and release the orb (or Space), the next line of the script "happens".
// Run: npm run mock   (then open http://localhost:5173)
import { WebSocketServer } from 'ws';

const PORT = Number(process.env.MOCK_PORT) || 8765;
const wss = new WebSocketServer({ port: PORT, path: '/canvas' });

const steps = (servings) => [
  servings === 4 ? 'Boil 5 L of water with 2 tbsp salt.' : 'Boil 7 L of water with 3 tbsp salt.',
  'Slice the garlic thin while the water heats.',
  'Cook the spaghetti 9 minutes, one under the packet time.',
  'Warm the oil, garlic and chili on low until the garlic turns pale gold.',
  'Toss with a ladle of pasta water, then the parsley and parmesan.',
];
const items = (n) => {
  const q = n === 4
    ? ['400 g', '6 cloves', '120 ml', '1 tsp', '½ bunch', '60 g']
    : ['600 g', '9 cloves', '180 ml', '1½ tsp', '¾ bunch', '90 g'];
  return ['Spaghetti', 'Garlic', 'Olive oil', 'Chili flakes', 'Parsley', 'Parmesan']
    .map((label, i) => ({ id: label.toLowerCase().replace(/\s/g, '_'), label, detail: q[i] }));
};

// grams of [protein, carbs, fat] per day
const THIS_WEEK = [[150, 230, 70], [138, 250, 66], [160, 210, 74], [145, 240, 68], [132, 260, 80], [120, 300, 85], [140, 220, 64]];
const NEXT_WEEK = [[155, 215, 68], [150, 225, 65], [162, 205, 70], [148, 230, 66], [150, 235, 72], [135, 260, 78], [145, 210, 62]];
function macros(days, caption) {
  const kcal = days.map(([p, c, f]) => [p * 4, c * 4, f * 9]);
  const avg = (j) => Math.round(days.reduce((s, d) => s + d[j], 0) / days.length);
  const avgKcal = Math.round(kcal.reduce((s, d) => s + d[0] + d[1] + d[2], 0) / days.length);
  return {
    caption,
    headline: { value: avgKcal.toLocaleString('en-US'), unit: 'kcal' },
    legend: [{ label: 'Protein', value: `${avg(0)} g` }, { label: 'Carbs', value: `${avg(1)} g` }, { label: 'Fat', value: `${avg(2)} g` }],
    categories: ['M', 'T', 'W', 'T', 'F', 'S', 'S'],
    series: ['Protein', 'Carbs', 'Fat'].map((label, j) => ({ label, values: kcal.map((d) => d[j]) })),
    goal: { value: 2200, label: 'Goal' },
    max: 2600,
  };
}

// [ms after release, message]
const SCRIPT = [
  { you: "I'm cooking pasta for four.", at: [
    [0, { type: 'orb', state: 'thinking' }],
    [700, { type: 'create', id: 'recipe', widget: 'recipe', importance: 'hero', props: { title: 'Spaghetti aglio e olio', meta: '25 min · Pantry staples', servings: 4, steps: steps(4) } }],
    [840, { type: 'create', id: 'ingredients', widget: 'checklist', importance: 'side', props: { title: 'Ingredients', items: items(4) } }],
    [1000, { type: 'orb', state: 'idle' }],
    [1000, { type: 'say', text: 'Pasta for four.' }],
  ] },
  { you: 'Actually make it for six, and start a ten-minute timer.', at: [
    [0, { type: 'orb', state: 'thinking' }],
    [600, { type: 'update', id: 'recipe', props: { servings: 6, steps: steps(6) } }],
    [720, { type: 'update', id: 'ingredients', props: { items: items(6) } }],
    [1050, { type: 'create', id: 'timer', widget: 'timer', importance: 'satellite', props: { label: 'Pasta', seconds: 600 } }],
    [1150, { type: 'orb', state: 'idle' }],
    [1150, { type: 'say', text: "Six it is. Timer's running." }],
  ] },
  { you: "I'm done.", at: [
    [0, { type: 'orb', state: 'thinking' }],
    [400, { type: 'clear' }],
    [450, { type: 'orb', state: 'idle' }],
    [500, { type: 'say', text: 'Enjoy.' }],
  ] },
  { you: 'Plan my macros for these meals this week and chart it.', at: [
    [0, { type: 'orb', state: 'thinking' }],
    [700, { type: 'pending', id: 'macros', importance: 'full' }],
    [800, { type: 'orb', state: 'working' }],
    [850, { type: 'say', text: 'Let me work that one out.' }],
    [5800, { type: 'create', id: 'macros', widget: 'stacked_bar', importance: 'full', props: macros(THIS_WEEK, 'This week · daily average') }],
    [5900, { type: 'orb', state: 'idle' }],
    [5950, { type: 'say', text: "There. Your week's macros." }],
  ] },
  { you: 'Now do the same for next week.', at: [
    [0, { type: 'orb', state: 'thinking' }],
    [350, { type: 'update', id: 'macros', props: macros(NEXT_WEEK, 'Next week · daily average') }],
    [420, { type: 'orb', state: 'idle' }],
    [450, { type: 'say', text: 'Done.' }],
  ] },
  { you: "That's all, thanks.", at: [
    [0, { type: 'orb', state: 'thinking' }],
    [400, { type: 'clear' }],
    [450, { type: 'orb', state: 'idle' }],
    [500, { type: 'say', text: 'Anytime.' }],
  ] },
];

wss.on('connection', (ws) => {
  let i = 0;
  let timers = [];
  const send = (m) => ws.readyState === ws.OPEN && ws.send(JSON.stringify(m));
  const stop = () => { timers.forEach(clearTimeout); timers = []; };
  console.log('canvas connected');

  ws.on('message', (raw) => {
    let m;
    try { m = JSON.parse(raw); } catch { return; }
    if (m.type === 'hello') console.log('canvas can draw:', m.widgets.join(', '));
    else if (m.type === 'orb_down') { stop(); send({ type: 'orb', state: 'listening' }); }
    else if (m.type === 'orb_up') {
      if (i >= SCRIPT.length) { i = 0; send({ type: 'clear' }); }
      const scene = SCRIPT[i++];
      console.log(`\n[${i}/${SCRIPT.length}] you: "${scene.you}"`);
      timers = scene.at.map(([t, msg]) => setTimeout(() => send(msg), t));
    } else if (m.type === 'event') console.log('event:', m.id, m.name, JSON.stringify(m.data ?? {}));
    else if (m.type === 'canvas_state') console.log('canvas:', m.widgets.map((w) => w.id).join(', ') || '(empty)');
  });
  ws.on('close', () => { stop(); console.log('canvas disconnected'); });
});

console.log(`mock orchestrator on ws://localhost:${PORT}/canvas. Hold and release the orb to step through the demo.`);
