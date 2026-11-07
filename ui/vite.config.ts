import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' so the build also loads from file:// in the desktop shell (desktop/main.cjs)
export default defineConfig({ base: './', plugins: [react()], server: { port: 5173 } });
