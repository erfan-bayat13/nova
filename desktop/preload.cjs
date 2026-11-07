// The only bridge between the orb page (ui/, ?orb) and the shell. Exposed as window.orbShell.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('orbShell', {
  moveBy: (dx, dy) => ipcRenderer.send('move', dx, dy),
  menu: () => ipcRenderer.send('menu'),
  hide: () => ipcRenderer.send('hide'),
  onHotkey: (fn) => ipcRenderer.on('hotkey', () => fn()),
  onPtt: (fn) => ipcRenderer.on('ptt', (_e, kind) => fn(kind)), // hold-to-talk key: 'down' | 'up' | 'cancel'
});
