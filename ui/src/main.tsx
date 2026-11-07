import { createRoot } from 'react-dom/client';
import { App } from './App';
import { OrbApp } from './OrbApp';
import './styles.css';

// ?orb: the floating desktop orb (desktop/), otherwise the canvas
const orb = new URLSearchParams(location.search).has('orb');
createRoot(document.getElementById('root')!).render(orb ? <OrbApp /> : <App />);
