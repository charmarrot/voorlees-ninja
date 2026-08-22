/* Service worker: de app-schil en bewaarde verhalen werken zonder internet. */
const SCHIL = 'voorlees-schil-v1';
const VERHALEN = 'voorlees-verhalen-v1';
const SCHIL_BESTANDEN = [
  '/',
  '/static/styles.css',
  '/static/app.js',
  '/static/icoon.svg',
  '/static/icoon-192.png',
  '/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SCHIL)
      .then((bak) => bak.addAll(SCHIL_BESTANDEN))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((namen) => Promise.all(
        namen
          .filter((naam) => naam.startsWith('voorlees-') && naam !== SCHIL && naam !== VERHALEN)
          .map((naam) => caches.delete(naam))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const verzoek = event.request;
  if (verzoek.method !== 'GET') return;

  const url = new URL(verzoek.url);
  if (url.origin !== self.location.origin) return;

  // Nooit API-antwoorden bewaren: die moeten altijd vers zijn.
  if (url.pathname.startsWith('/api/')) return;

  // Media (plaatjes en geluid): eerst uit de bewaarde verhalen.
  if (url.pathname.startsWith('/media/')) {
    event.respondWith(
      caches.match(verzoek).then((bewaard) => bewaard || fetch(verzoek))
    );
    return;
  }

  // Pagina's: eerst het net, met de bewaarde schil als vangnet.
  if (verzoek.mode === 'navigate') {
    event.respondWith(
      fetch(verzoek)
        .then((antwoord) => {
          // Alleen de echte startpagina mag de bewaarde app-schil vervangen.
          if (url.pathname === '/' && antwoord.ok) {
            const kopie = antwoord.clone();
            caches.open(SCHIL).then((bak) => bak.put('/', kopie)).catch(() => {});
          }
          return antwoord;
        })
        .catch(() => caches.match('/').then((bewaard) => bewaard || nietBeschikbaar()))
    );
    return;
  }

  // Statische bestanden: uit de cache, en op de achtergrond verversen.
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith(
      caches.match(verzoek).then((bewaard) => {
        const vers = fetch(verzoek).then((antwoord) => {
          if (antwoord && antwoord.ok) {
            const kopie = antwoord.clone();
            caches.open(SCHIL).then((bak) => bak.put(verzoek, kopie)).catch(() => {});
          }
          return antwoord;
        }).catch(() => bewaard);
        return bewaard || vers;
      })
    );
  }
});

function nietBeschikbaar() {
  return new Response(
    '<!doctype html><meta charset="utf-8"><title>Offline</title>' +
    '<body style="background:#0a0912;color:#ece2f5;font-family:system-ui;' +
    'display:grid;place-items:center;height:100vh;text-align:center">' +
    '<div><div style="font-size:3rem">🌙</div><p>Even geen internet.<br>' +
    'Bewaarde verhaaltjes kun je gewoon lezen.</p></div>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' }, status: 503 }
  );
}
