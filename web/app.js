'use strict';

const $ = (id) => document.getElementById(id);
const log = (msg, isErr) => {
  const el = $('status-text');
  el.textContent = msg;
  $('status').classList.toggle('err', !!isErr);
};

let INFO = null;

// --- formatting ---

function pickPrefix(value, baseUnit) {
  // Choose engineering prefix so the displayed number sits in 1..1000.
  const av = Math.abs(value);
  const table = [
    { p: 'G', s: 1e9  }, { p: 'M', s: 1e6  }, { p: 'k', s: 1e3 },
    { p: '',  s: 1    },
    { p: 'm', s: 1e-3 }, { p: 'µ', s: 1e-6 }, { p: 'n', s: 1e-9 },
    { p: 'p', s: 1e-12 },
  ];
  // Decide based on the SCPI mode's default prefix so DCI shows mA, not A.
  // We treat baseUnit as the bare unit (A, V, Ω, Hz, F).
  if (av === 0 || !isFinite(av)) return { value, unit: baseUnit, prefix: '' };
  for (const t of table) {
    if (av >= t.s * 0.999) return { value: value / t.s, prefix: t.p, unit: t.unit || baseUnit };
  }
  return { value, prefix: '', unit: baseUnit };
}

const MODE_BASE_UNIT = {
  DCI: 'A', ACI: 'A', VDC: 'V', VAC: 'V',
  RES: 'Ω', FREQ: 'Hz', CAP: 'F',
};

function formatReading(reading) {
  if (!reading || reading.error) {
    return { value: 'ERR', unit: '', range: reading?.error || '' };
  }
  const baseUnit = MODE_BASE_UNIT[reading.mode] || '';
  const { value, prefix, unit } = pickPrefix(reading.value, baseUnit);
  // 5 significant digits like the SDM's 5.5-digit display
  const absV = Math.abs(value);
  let text;
  if (absV >= 100)       text = value.toFixed(3);
  else if (absV >= 10)   text = value.toFixed(4);
  else                   text = value.toFixed(5);
  // Trim trailing zeros but keep at least 4 decimal places when scale demands it
  return {
    value: text,
    unit: prefix + unit + (reading.mode.endsWith('C') ? ' ' + reading.mode.slice(0,2) : ''),
    range: rangeLabel(reading.mode, reading.range),
  };
}

function rangeLabel(mode, range) {
  if (!INFO || !INFO.modes[mode]) return range;
  const ranges = INFO.modes[mode].ranges;
  const found = ranges.find(([label, arg]) => arg === range);
  if (!found) return range;
  return range === 'AUTO' ? `Auto ${ranges[1]?.[0] || ''}`.trim() : `Manual ${found[0]}`;
}

// --- DOM updates ---

function render(reading) {
  const f = formatReading(reading);
  $('value').textContent = f.value;
  $('unit').textContent = f.unit;
  $('range-tag').textContent = f.range;
  if (!reading || reading.error) return;
  $('mm-min').textContent = formatReading({ ...reading, value: reading.min }).value;
  $('mm-max').textContent = formatReading({ ...reading, value: reading.max }).value;
  $('mode-tag').textContent = reading.mode;
  chart.push(reading);
}

// --- Chart: canvas-based realtime time-series ---

const chart = (() => {
  const canvas = $('chart');
  const ctx = canvas.getContext('2d');
  // Circular buffer: 600 ticks = 2.5 min at 250 ms (sized for the 10-min window).
  const MAX_POINTS = 2400;
  const times = new Float64Array(MAX_POINTS);
  const values = new Float64Array(MAX_POINTS);
  let head = 0, count = 0;
  let windowSec = 120;
  let enabled = true;
  let lastMode = null;
  // Repaint at most ~30 fps even if readings arrive faster.
  let pendingFrame = false;

  function push(reading) {
    if (!enabled || !reading || reading.error || !isFinite(reading.value)) return;
    if (reading.mode !== lastMode) {
      // Mode change resets the trace so units stay consistent on screen.
      head = 0; count = 0; lastMode = reading.mode;
    }
    times[head] = performance.now() / 1000;
    values[head] = reading.value;
    head = (head + 1) % MAX_POINTS;
    if (count < MAX_POINTS) count++;
    if (!pendingFrame) {
      pendingFrame = true;
      requestAnimationFrame(draw);
    }
  }

  function clear() {
    head = 0; count = 0;
    draw();
  }

  function setWindow(sec) {
    windowSec = sec;
    $('chart-window').textContent =
      sec < 60 ? `${sec} s` : `${Math.round(sec / 60)} min`;
    draw();
  }

  function setEnabled(on) {
    enabled = on;
    const b = $('chart-toggle');
    b.classList.toggle('active', on);
    b.textContent = on ? 'Graph On' : 'Graph Off';
    if (on) draw();
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function draw() {
    pendingFrame = false;
    const rect = canvas.getBoundingClientRect();
    const W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    // Axes area
    const padL = 64, padR = 12, padT = 10, padB = 22;
    const plotW = W - padL - padR, plotH = H - padT - padB;

    // Background gridlines
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(padL, padT, plotW, plotH);

    if (count === 0) {
      ctx.fillStyle = '#666';
      ctx.font = '12px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('waiting for data...', W / 2, H / 2);
      return;
    }

    const now = performance.now() / 1000;
    const tMin = now - windowSec;

    // Find min/max within window
    let vMin = Infinity, vMax = -Infinity, visible = 0;
    for (let i = 0; i < count; i++) {
      const idx = (head - 1 - i + MAX_POINTS) % MAX_POINTS;
      const t = times[idx];
      if (t < tMin) break;
      const v = values[idx];
      if (v < vMin) vMin = v;
      if (v > vMax) vMax = v;
      visible++;
    }
    if (visible === 0) { vMin = values[(head - 1 + MAX_POINTS) % MAX_POINTS]; vMax = vMin; }
    if (vMin === vMax) { vMin -= 1; vMax += 1; }
    // 10 % padding so the line doesn't kiss the top/bottom
    const span = vMax - vMin;
    vMin -= span * 0.1;
    vMax += span * 0.1;

    // Y axis labels (5 ticks) — match the LCD's engineering prefix
    const baseUnit = MODE_BASE_UNIT[lastMode] || '';
    // Pick a single prefix for the whole axis based on the midpoint magnitude.
    const ref = pickPrefix((vMin + vMax) / 2, baseUnit);
    const scale = (vMin + vMax) === 0 ? 1 : ref.value / ((vMin + vMax) / 2);
    ctx.strokeStyle = '#222';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#888';
    ctx.font = '11px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i++) {
      const y = padT + (plotH * i) / 4;
      const v = vMax - ((vMax - vMin) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      const label = (v * scale).toFixed(Math.abs(v * scale) >= 100 ? 1 : 3);
      ctx.fillText(`${label} ${ref.prefix}${ref.unit}`, padL - 6, y);
    }

    // X axis labels (window start / mid / now)
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#888';
    const xLabels = ['-' + (windowSec < 60 ? `${windowSec}s` : `${Math.round(windowSec/60)}m`),
                     '-' + (windowSec < 60 ? `${Math.round(windowSec/2)}s` : `${Math.round(windowSec/120)}m`),
                     'now'];
    xLabels.forEach((lab, i) => {
      ctx.fillText(lab, padL + (plotW * i) / 2, padT + plotH + 4);
    });

    // Line trace
    ctx.strokeStyle = '#aaff00';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let started = false;
    for (let i = visible - 1; i >= 0; i--) {
      const idx = (head - 1 - i + MAX_POINTS) % MAX_POINTS;
      const t = times[idx];
      const v = values[idx];
      const x = padL + ((t - tMin) / windowSec) * plotW;
      const y = padT + ((vMax - v) / (vMax - vMin)) * plotH;
      if (!started) { ctx.moveTo(x, y); started = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Last point dot
    const lastIdx = (head - 1 + MAX_POINTS) % MAX_POINTS;
    if (visible > 0) {
      const x = padL + plotW;
      const y = padT + ((vMax - values[lastIdx]) / (vMax - vMin)) * plotH;
      ctx.fillStyle = '#aaff00';
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  window.addEventListener('resize', resize);
  $('chart-window-select').addEventListener('change',
    (e) => setWindow(parseInt(e.target.value, 10)));
  $('chart-toggle').addEventListener('click', () => setEnabled(!enabled));
  $('chart-clear').addEventListener('click', clear);

  setTimeout(resize, 0);
  // Repaint once per second too, so the "now" edge keeps moving even
  // between ticks (e.g. while paused).
  setInterval(() => { if (enabled) draw(); }, 1000);

  return { push, clear, setEnabled, setWindow };
})();

function highlightMode(mode) {
  document.querySelectorAll('.mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
}

function populateRanges(mode) {
  const sel = $('range-select');
  sel.innerHTML = '';
  if (!INFO || !INFO.modes[mode]) return;
  for (const [label, arg] of INFO.modes[mode].ranges) {
    const opt = document.createElement('option');
    opt.value = arg;
    opt.textContent = label;
    sel.appendChild(opt);
  }
  sel.value = INFO.current_range;
}

// --- API calls ---

async function fetchInfo() {
  const r = await fetch('/api/info');
  INFO = await r.json();
  $('idn').textContent = INFO.idn || `${INFO.host}:${INFO.port}`;
  highlightMode(INFO.current_mode);
  populateRanges(INFO.current_mode);
  log(`mode=${INFO.current_mode} range=${INFO.current_range}`);
}

async function setMode(mode, range = 'AUTO') {
  log(`switching to ${mode} ${range}...`);
  try {
    const r = await fetch(`/api/mode/${mode}?range=${encodeURIComponent(range)}`,
                          { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    const body = await r.json();
    INFO.current_mode = body.mode;
    INFO.current_range = body.range;
    highlightMode(body.mode);
    populateRanges(body.mode);
    log(`mode=${body.mode} range=${body.range}`);
  } catch (e) {
    log(`set mode failed: ${e.message}`, true);
  }
}

async function resetMinMax() {
  await fetch('/api/reset-minmax', { method: 'POST' });
  $('mm-min').textContent = '--';
  $('mm-max').textContent = '--';
}

// --- WebSocket ---

let ws = null;
let wsRetry = 1000;

function openWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    wsRetry = 1000;
    $('conn').classList.add('ok');
    log('connected');
  };
  ws.onmessage = (ev) => {
    try { render(JSON.parse(ev.data)); } catch (e) { /* ignore */ }
  };
  ws.onclose = () => {
    $('conn').classList.remove('ok');
    log(`disconnected, retrying in ${wsRetry/1000}s`, true);
    setTimeout(openWS, wsRetry);
    wsRetry = Math.min(wsRetry * 2, 8000);
  };
  ws.onerror = () => { /* onclose follows */ };
}

// --- event wiring ---

document.querySelectorAll('.mode-btn').forEach(b => {
  b.addEventListener('click', () => setMode(b.dataset.mode, 'AUTO'));
});
$('range-select').addEventListener('change', (e) => {
  if (INFO) setMode(INFO.current_mode, e.target.value);
});
$('mm-reset').addEventListener('click', resetMinMax);

// --- PWA install prompt ---
// Chrome fires beforeinstallprompt when the page meets PWA criteria
// (manifest + service worker + secure origin = localhost or HTTPS).
// We stash it and reveal an "Install" button so the user can launch
// the standalone window without going through the address bar menu.
let deferredInstall = null;
const installBtn = $('install-btn');
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredInstall = e;
  installBtn.hidden = false;
});
installBtn.addEventListener('click', async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  await deferredInstall.userChoice;
  deferredInstall = null;
  installBtn.hidden = true;
});
// Already installed — Chrome reports this on launch. iOS uses Share -> Add to Home Screen.
window.addEventListener('appinstalled', () => { installBtn.hidden = true; });

(async () => {
  try { await fetchInfo(); } catch (e) { log(`info failed: ${e.message}`, true); }
  openWS();
})();
