import { createRoot } from 'react-dom/client';
import { App } from './App';
import { OrbApp } from './OrbApp';
import './styles.css';

// ?orb: the floating desktop orb (desktop/), otherwise the canvas
const orb = new URLSearchParams(location.search).has('orb');
const root = createRoot(document.getElementById('root')!);
// ?gallery: dev-only page with every widget type (loaded on demand, not part of the main bundle)
if (new URLSearchParams(location.search).has('gallery')) import('./Gallery').then((m) => root.render(<m.Gallery />));
else root.render(orb ? <OrbApp /> : <App />);
