const CACHE_NAME    = 'ecs-v1';
const OFFLINE_URL   = '/offline';
 
// Files to cache for offline use
const STATIC_ASSETS = [
  '/',
  '/offline',
  '/static/css/dashboard.css',
  '/static/css/medical.css',
  '/static/css/fire.css',
  '/static/css/police.css',
  '/static/css/accident.css',
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  'https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Share+Tech+Mono&family=Barlow:wght@300;400;500;600&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css'
];
 
// Install — cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS.filter(url => !url.startsWith('http'))))
      .then(() => self.skipWaiting())
  );
});
 
// Activate — clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});
 
// Fetch — network first, cache fallback, offline page last resort
self.addEventListener('fetch', event => {
  // Skip non-GET and chrome-extension requests
  if (event.request.method !== 'GET') return;
  if (event.request.url.startsWith('chrome-extension')) return;
 
  // API calls — network only, no caching
  const url = new URL(event.request.url);
  const apiRoutes = ['/chat', '/send_alert', '/tts', '/upload_evidence',
                     '/alert_status_latest', '/admin', '/login', '/register'];
  if (apiRoutes.some(r => url.pathname.startsWith(r))) return;
 
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful page responses
        if (response.ok && event.request.destination === 'document') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() =>
        caches.match(event.request)
          .then(cached => cached || caches.match(OFFLINE_URL))
      )
  );
});
 
// Push notifications (for future use)
self.addEventListener('push', event => {
  if (!event.data) return;
  const data = event.data.json();
  self.registration.showNotification(data.title || 'Emergency Alert', {
    body:    data.body    || 'New emergency notification',
    icon:    '/static/icons/icon-192x192.png',
    badge:   '/static/icons/icon-72x72.png',
    vibrate: [200, 100, 200, 100, 200],
    tag:     'emergency-alert',
    data:    { url: data.url || '/' }
  });
});
 
self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
 