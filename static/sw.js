var CACHE = 'tx-static-v1';
self.addEventListener('install', function (e) { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (ks) {
      return Promise.all(ks.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});
self.addEventListener('fetch', function (e) {
  var u;
  try { u = new URL(e.request.url); } catch (err) { return; }
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  if (u.pathname.indexOf('/static/') !== 0 && u.pathname !== '/sw.js') return;
  e.respondWith(
    caches.match(e.request).then(function (hit) {
      if (hit) {
        // 后台静默更新缓存(stale-while-revalidate)
        fetch(e.request).then(function (r) {
          if (r.ok) { var cp = r.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, cp); }); }
        }).catch(function () {});
        return hit;
      }
      return fetch(e.request).then(function (r) {
        if (r.ok) { var cp2 = r.clone(); caches.open(CACHE).then(function (c) { c.put(e.request, cp2); }); }
        return r;
      });
    })
  );
});
