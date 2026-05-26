// Service worker: lets the browser install the page as a PWA and
// caches the static shell so a brief network blip during reload
// doesn't lose the UI. The WebSocket and /api/* always go to network.
const CACHE = 'sdm-shell-v2';
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icon.svg',
  '/static/icon-128.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Never cache API or websocket — always live from server.
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) return;
  // Network-first for the shell; fall back to cache on failure.
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return resp;
      })
      .catch(() => caches.match(e.request))
  );
});
