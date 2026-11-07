// Bridge for the "look at area" overlay (select.html). Exposed as window.areaPicker.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('areaPicker', {
  onInit: (fn) => ipcRenderer.on('init', (_e, data) => fn(data)), // { src }: the still, as a data: URL
  ready: () => ipcRenderer.send('area-ready'),                   // the still is drawn, safe to show the window
  done: (rect) => ipcRenderer.send('area-done', rect),           // { x, y, w, h } in CSS px, or null (cancelled)
});
