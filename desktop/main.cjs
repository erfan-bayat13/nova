// Floating desktop orb: a small transparent always-on-top window with the orb from ui/ (?orb mode),
// talking speech to speech with the local model through backend/orchestrator.py (voice mode).
// It stays hidden until you talk: HOLD Right ⌥ anywhere, speak, let go (push to talk, watched with a global
// key hook, uiohook-napi, which needs the Accessibility permission). ⌥Space is a press/press-again fallback.
// The page hides the window again a few seconds after the reply. A menu-bar dot shows it's running.
//
//   npm start      build ui/ and open the orb (starts the orchestrator if nothing listens on ORCH_PORT)
//   npm run dev    load the orb from the Vite dev server instead (cd ui && npm run dev)
//
// Env: ORCH_PORT (8766), ORB_PTT_KEY (hold-to-talk key, a uiohook key name: AltRight), ORB_HOTKEY (Alt+Space),
//      ORB_CAMERA_HOTKEY (Alt+Shift+C), ORB_SCREEN_HOTKEY (Alt+Shift+S), ORB_AREA_HOTKEY (Alt+Shift+A, drag a
//      rectangle): "eyes on request", one frame to the model.
//      ORB_URL (load the page from here, e.g. http://localhost:5173/?handsfree), ORB_PYTHON (python3)

const { app, BrowserWindow, desktopCapturer, globalShortcut, ipcMain, Menu, nativeImage, screen, session, systemPreferences, Tray } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PORT = Number(process.env.ORCH_PORT || 8766);
const HOTKEY = process.env.ORB_HOTKEY || 'Alt+Space';
const PTT_KEY = process.env.ORB_PTT_KEY || 'AltRight';
const CAMERA_HOTKEY = process.env.ORB_CAMERA_HOTKEY || 'Alt+Shift+C';
const SCREEN_HOTKEY = process.env.ORB_SCREEN_HOTKEY || 'Alt+Shift+S';
const AREA_HOTKEY = process.env.ORB_AREA_HOTKEY || 'Alt+Shift+A';
const SIZE = 120;   // window edge in points; the orb is 0.2 × this in radius (24), the rest is room for its glow
const MARGIN = 24;
const MAX_SIDE = 1024;                  // "eyes on request": longest side of a frame, in pixels
const MAX_B64 = 1.5 * 1024 * 1024;      // and the base64 JPEG stays under 1.5 MB
const AREA_MAX_SIDE = 768;              // a dragged area is sent at its own pixels, shrunk only past this
const AREA_MIN_DIP = 24;                // a drag smaller than this counts as a cancel

let win = null;
let backend = null; // the orchestrator, only if we started it
let tray = null;

function portOpen(port) {
  return new Promise((resolve) => {
    const s = net.connect({ port, host: '127.0.0.1' });
    s.once('connect', () => { s.destroy(); resolve(true); });
    s.once('error', () => resolve(false));
  });
}

async function ensureBackend() {
  if (await portOpen(PORT)) return; // already running (e.g. started by hand)
  const logPath = path.join(ROOT, 'prototype', 'logs', 'orb_orchestrator.log');
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  const out = fs.openSync(logPath, 'a');
  // the orchestrator starts llama-server itself if it isn't running (ServerWatchdog)
  backend = spawn(process.env.ORB_PYTHON || 'python3', [path.join(ROOT, 'backend', 'orchestrator.py')], {
    cwd: ROOT, env: { ...process.env, ORCH_PORT: String(PORT) }, stdio: ['ignore', out, out],
  });
  backend.on('exit', (code) => { console.log(`orchestrator exited (${code})`); backend = null; });
  console.log(`started orchestrator on :${PORT}, log: ${path.relative(ROOT, logPath)}`);
}

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  win = new BrowserWindow({
    width: SIZE, height: SIZE,
    x: workArea.x + workArea.width - SIZE - MARGIN,
    y: workArea.y + workArea.height - SIZE - MARGIN,
    frame: false, transparent: true, hasShadow: false, resizable: false, maximizable: false,
    fullscreenable: false, skipTaskbar: true, alwaysOnTop: true, show: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      backgroundThrottling: false,                  // keep playing and animating when not focused
      autoplayPolicy: 'no-user-gesture-required',   // the hotkey can start audio without a click
    },
  });
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.setContentProtection(true); // the orb is left out of screen captures, so "look at screen" doesn't see itself

  const ws = `ws://localhost:${PORT}/canvas`;
  if (process.env.ORB_URL) {
    const u = new URL(process.env.ORB_URL);
    u.searchParams.set('orb', '1');
    u.searchParams.set('ws', ws);
    win.loadURL(u.toString());
  } else {
    win.loadFile(path.join(ROOT, 'ui', 'dist', 'index.html'), { query: { orb: '1', ws } });
  }
  win.on('closed', () => { win = null; });
  // the page's [look] / [timing] logs show up in this terminal too (no need to open DevTools)
  win.webContents.on('console-message', (e, _level, message) => {
    const msg = typeof message === 'string' ? message : e.message;
    if (msg && /^\[(look|timing)\]/.test(msg)) console.log(msg);
  });
}

const pttLabel = () => PTT_KEY.replace('AltRight', 'right ⌥').replace('MetaRight', 'right ⌘').replace('CtrlRight', 'right ⌃');
const keyLabel = (k) => k.replace('Alt', '⌥').replace('CommandOrControl', '⌘').replace('Shift', '⇧').replace(/\+/g, '');
const hotkeyLabel = () => keyLabel(HOTKEY);

// the hotkey (or the menu): show the orb if hidden, and let the page start or end the conversation
function talk() {
  if (!win) return;
  if (!win.isVisible()) win.showInactive();
  win.webContents.send('hotkey');
}

// the shortcut or menu: show the orb if hidden, and let the page take one frame and send it
function look(source) {
  if (!win) return;
  if (!win.isVisible()) win.showInactive();
  win.webContents.send('look', source);
}

const lookItems = () => [
  { label: `Look through camera  ${keyLabel(CAMERA_HOTKEY)}`, click: () => look('camera') },
  { label: `Look at screen  ${keyLabel(SCREEN_HOTKEY)}`, click: () => look('screen') },
  { label: `Look at an area…  ${keyLabel(AREA_HOTKEY)}`, click: () => look('area') },
];

// camera and screen access (macOS). Asks once for the camera; the screen can only be allowed in Settings.
async function mediaAccess(kind) {
  if (process.platform !== 'darwin') return 'granted';
  if (kind !== 'camera' && kind !== 'screen') return 'denied';
  if (kind === 'camera' && systemPreferences.getMediaAccessStatus('camera') === 'not-determined') {
    await systemPreferences.askForMediaAccess('camera');
  }
  return systemPreferences.getMediaAccessStatus(kind);
}

// A still of one screen at the given pixel size: the one the cursor is on, else any screen that gives a picture.
// macOS sometimes hands back empty pictures right after launch or while a screen wakes, so try a few times.
async function grabDisplay(display, widthPx, heightPx) {
  for (let attempt = 1; attempt <= 4; attempt++) {
    const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: widthPx, height: heightPx } });
    const ordered = [...sources.filter((s) => s.display_id === String(display.id)), ...sources.filter((s) => s.display_id !== String(display.id))];
    const src = ordered.find((s) => !s.thumbnail.isEmpty());
    console.log(`[look] screens (try ${attempt}): ${sources.map((s) => `${s.name} ${JSON.stringify(s.thumbnail.getSize())}`).join(', ')}; cursor display ${display.id}`);
    if (src) return { img: src.thumbnail, display: screen.getAllDisplays().find((d) => String(d.id) === src.display_id) ?? display };
    await new Promise((r) => setTimeout(r, 300));
  }
  return null;
}

const toJpegBase64 = (img) => {
  let image = '';
  for (const q of [70, 50, 35]) {
    image = img.toJPEG(q).toString('base64');
    if (image.length <= MAX_B64) break;
  }
  return image;
};

const fitTo = (img, maxSide) => {
  const { width, height } = img.getSize();
  if (Math.max(width, height) <= maxSide) return img;
  const j = maxSide / Math.max(width, height);
  return img.resize({ width: Math.round(width * j), height: Math.round(height * j), quality: 'good' });
};

const screenDenied = () => process.platform === 'darwin' && systemPreferences.getMediaAccessStatus('screen') !== 'granted';

// one still of the screen the cursor is on, as base64 JPEG. Kept in memory only; the caller sends it and drops it.
async function captureScreen() {
  if (screenDenied()) return { error: 'denied' };
  const display = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const k = MAX_SIDE / Math.max(display.size.width, display.size.height);
  const got = await grabDisplay(display, Math.round(display.size.width * k), Math.round(display.size.height * k));
  if (!got) return { error: 'empty' };
  return { image: toJpegBase64(fitTo(got.img, MAX_SIDE)) };
}

// "Look at area": freeze the screen, let the user drag a rectangle over the still, send only that part.
// The still is taken before the overlay opens, so the overlay is never in the picture.
function pickArea(display, img) {
  return new Promise((resolve) => {
    const ov = new BrowserWindow({
      x: display.bounds.x, y: display.bounds.y, width: display.bounds.width, height: display.bounds.height,
      frame: false, hasShadow: false, resizable: false, movable: false, fullscreenable: false, skipTaskbar: true,
      alwaysOnTop: true, show: false, backgroundColor: '#000000',
      webPreferences: { preload: path.join(__dirname, 'select-preload.cjs'), contextIsolation: true },
    });
    let settled = false;
    const finish = (rect) => {
      if (settled) return;
      settled = true;
      ipcMain.removeListener('area-ready', onReady);
      ipcMain.removeListener('area-done', onDone);
      if (!ov.isDestroyed()) ov.destroy();
      resolve(rect);
    };
    const mine = (e) => e.sender === ov.webContents;
    const onReady = (e) => { if (mine(e)) { ov.show(); ov.focus(); } };
    const onDone = (e, rect) => { if (mine(e)) finish(rect); };
    ipcMain.on('area-ready', onReady);
    ipcMain.on('area-done', onDone);
    ov.on('closed', () => finish(null));
    ov.on('blur', () => finish(null)); // clicking away or switching app cancels
    ov.setAlwaysOnTop(true, 'screen-saver');
    ov.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
    ov.loadFile(path.join(__dirname, 'select.html'));
    ov.webContents.once('did-finish-load', () => {
      ov.webContents.send('init', { src: 'data:image/jpeg;base64,' + img.toJPEG(80).toString('base64') });
    });
  });
}

// crop a still to a rectangle given in the display's own points (the still has `scale` pixels per point)
function cropStill(img, rect, scale) {
  const { width, height } = img.getSize();
  const x = Math.max(0, Math.min(width - 1, Math.round(rect.x * scale)));
  const y = Math.max(0, Math.min(height - 1, Math.round(rect.y * scale)));
  const w = Math.max(1, Math.min(width - x, Math.round(rect.w * scale)));
  const h = Math.max(1, Math.min(height - y, Math.round(rect.h * scale)));
  return img.crop({ x, y, width: w, height: h });
}

async function captureArea() {
  if (screenDenied()) return { error: 'denied' };
  const cursorDisplay = screen.getDisplayNearestPoint(screen.getCursorScreenPoint());
  const pxW = Math.round(cursorDisplay.size.width * cursorDisplay.scaleFactor);
  const pxH = Math.round(cursorDisplay.size.height * cursorDisplay.scaleFactor);
  const got = await grabDisplay(cursorDisplay, pxW, pxH);
  if (!got) return { error: 'empty' };
  const { img, display } = got;
  const rect = await pickArea(display, img);
  if (!rect || rect.w < AREA_MIN_DIP || rect.h < AREA_MIN_DIP) return { error: 'cancelled' };
  const scale = img.getSize().width / display.size.width;
  const crop = cropStill(img, rect, scale);
  console.log(`[look] area ${Math.round(rect.w)}x${Math.round(rect.h)} pt -> ${JSON.stringify(crop.getSize())} px`);
  return { image: toJpegBase64(fitTo(crop, AREA_MAX_SIDE)) };
}

function menuItems() {
  return [
    { label: `Hold ${pttLabel()} to talk`, enabled: false },
    { label: `Talk  ${hotkeyLabel()}`, click: talk },
    ...lookItems(),
    { type: 'separator' },
    { label: 'Reload', click: () => win?.reload() },
    { label: 'Open DevTools', click: () => win?.webContents.openDevTools({ mode: 'detach' }) },
    { type: 'separator' },
    { label: 'Quit Orb', click: () => app.quit() },
  ];
}

function showMenu() {
  if (!win) return;
  Menu.buildFromTemplate([
    { label: `Hold ${pttLabel()} (or the orb) to talk`, enabled: false },
    { type: 'separator' },
    ...lookItems(),
    { type: 'separator' },
    { label: 'Reload', click: () => win.reload() },
    { label: 'Open DevTools', click: () => win.webContents.openDevTools({ mode: 'detach' }) },
    { type: 'separator' },
    { label: 'Quit Orb', click: () => app.quit() },
  ]).popup({ window: win });
}

app.whenReady().then(async () => {
  session.defaultSession.setPermissionRequestHandler((_wc, perm, cb) => cb(perm === 'media'));
  session.defaultSession.setPermissionCheckHandler((_wc, perm) => perm === 'media');
  if (process.platform === 'darwin') {
    void systemPreferences.askForMediaAccess('microphone'); // macOS prompt, once (don't hold the window for it)
    app.dock?.hide(); // a floating accessory, not a regular app: quit from the orb's right-click menu
  }

  ipcMain.on('move', (_e, dx, dy) => {
    if (!win) return;
    const [x, y] = win.getPosition();
    win.setPosition(Math.round(x + dx), Math.round(y + dy));
  });
  ipcMain.on('menu', showMenu);
  ipcMain.on('hide', () => win?.hide());
  ipcMain.handle('media-access', (_e, kind) => mediaAccess(kind));
  ipcMain.handle('capture-screen', () => captureScreen());
  ipcMain.handle('capture-area', () => captureArea());

  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'trayTemplate.png')));
  tray.setToolTip(`Orb: hold ${pttLabel()} to talk`);
  tray.setContextMenu(Menu.buildFromTemplate(menuItems()));

  await ensureBackend();
  createWindow();

  const ok = globalShortcut.register(HOTKEY, talk); // press: start talking; press again: send
  if (!ok) console.warn(`could not register ${HOTKEY} (taken by another app?); set ORB_HOTKEY`);
  for (const [accel, source] of [[CAMERA_HOTKEY, 'camera'], [SCREEN_HOTKEY, 'screen'], [AREA_HOTKEY, 'area']]) {
    if (!globalShortcut.register(accel, () => look(source))) console.warn(`could not register ${accel} (taken by another app?)`);
  }
  startPushToTalk();
});

// Hold PTT_KEY anywhere: 'down' when pressed, 'up' when released, 'cancel' if another key is pressed while
// holding (it was a ⌥-shortcut or a special character, not a question).
function startPushToTalk() {
  let hook;
  try {
    hook = require('uiohook-napi');
  } catch (e) {
    console.warn('uiohook-napi not available, hold-to-talk off:', e.message);
    return;
  }
  const { uIOhook, UiohookKey } = hook;
  const key = UiohookKey[PTT_KEY];
  if (key === undefined) return console.warn(`unknown ORB_PTT_KEY ${PTT_KEY}`);
  if (process.platform === 'darwin' && !systemPreferences.isTrustedAccessibilityClient(true)) {
    // shows the macOS prompt; the hook works once Electron is allowed in Privacy & Security → Accessibility
    console.warn('hold-to-talk needs Accessibility permission (System Settings → Privacy & Security → Accessibility), then restart');
  }
  let down = false;
  const send = (kind) => {
    console.log(`[ptt] ${kind} ${new Date().toISOString()} window ${win ? 'ok' : 'none'}`);
    win?.webContents.send('ptt', kind);
  };
  uIOhook.on('keydown', (e) => {
    if (e.keycode === key) {
      if (down) return;
      down = true;
      if (win && !win.isVisible()) win.showInactive();
      send('down');
    } else if (down) {
      console.log(`[ptt] other key ${e.keycode} pressed while holding`);
      down = false;
      send('cancel');
    }
  });
  uIOhook.on('keyup', (e) => {
    if (e.keycode === key && down) { down = false; send('up'); }
    else if (e.keycode === key) console.log('[ptt] keyup ignored (not down)');
  });
  const tryStart = () => {
    try {
      uIOhook.start();
      console.log(`hold-to-talk on: ${PTT_KEY}`);
      app.on('will-quit', () => uIOhook.stop());
      return true;
    } catch (e) {
      return false;
    }
  };
  if (tryStart()) return;
  // not allowed yet: keep checking, and turn on as soon as Accessibility is granted
  const poll = setInterval(() => {
    if (systemPreferences.isTrustedAccessibilityClient(false) && tryStart()) clearInterval(poll);
  }, 2000);
}

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (backend) backend.kill('SIGINT');
});
app.on('window-all-closed', () => app.quit());
