// The only bridge between the orb page (ui/, ?orb) and the shell. Exposed as window.orbShell.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('orbShell', {
  moveBy: (dx, dy) => ipcRenderer.send('move', dx, dy),
  menu: () => ipcRenderer.send('menu'),
  hide: () => ipcRenderer.send('hide'),
  // creator mode (canvas): grow the window to the display's work area, or restore it. Resolves once it has been
  // resized: { size: {w, h}, from: {x, y, w, h} } (from = where the small window was, in the grown window's own
  // coordinates) on open, { size } on close, null if there was nothing to do.
  setCanvas: (open) => ipcRenderer.invoke('canvas', open),
  // while the canvas is open the window ignores the mouse; call with true when the pointer is over a widget or the
  // orb, false otherwise (no effect while the window is small)
  setInteractive: (on) => ipcRenderer.send('interactive', on),
  onClearCanvas: (fn) => ipcRenderer.on('clear-canvas', () => fn()), // menu: "Clear canvas"
  onHotkey: (fn) => ipcRenderer.on('hotkey', () => fn()),
  onPtt: (fn) => ipcRenderer.on('ptt', (_e, kind) => fn(kind)), // hold-to-talk key: 'down' | 'up' | 'cancel'
  onLook: (fn) => ipcRenderer.on('look', (_e, source) => fn(source)), // shortcut or menu: 'camera' | 'screen' | 'area'
  mediaAccess: (kind) => ipcRenderer.invoke('media-access', kind), // 'granted' | 'denied' | 'restricted' | 'not-determined'
  captureScreen: () => ipcRenderer.invoke('capture-screen'),       // { image } (base64 JPEG) | { error }
  captureArea: () => ipcRenderer.invoke('capture-area'),           // drag a rectangle: { image } | { error: 'cancelled' | ... }
});
