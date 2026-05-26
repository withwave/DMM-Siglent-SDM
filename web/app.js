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
}

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

(async () => {
  try { await fetchInfo(); } catch (e) { log(`info failed: ${e.message}`, true); }
  openWS();
})();
