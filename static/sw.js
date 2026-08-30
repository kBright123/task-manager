var CACHE = 'tx-static-v6';
var SHELL_CACHE = 'tx-edu-shell-v1';
var SHELL_URL = '/edu/';
self.addEventListener('install', function (e) { self.skipWaiting(); });
self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (ks) {
      return Promise.all(ks.filter(function (k) { return k !== CACHE && k !== SHELL_CACHE; }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});
self.addEventListener('fetch', function (e) {
  var u;
  try { u = new URL(e.request.url); } catch (err) { return; }
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  // 教育乐园应用壳: 网络优先, 离线回退缓存, 保证断网可进入(数据在 localStorage/后端)
  if (e.request.mode === 'navigate' && (u.pathname === SHELL_URL)) {
    e.respondWith(
      fetch(e.request).then(function (r) {
        if (r.ok) { var cp = r.clone(); caches.open(SHELL_CACHE).then(function (c) { c.put(SHELL_URL, cp); }); }
        return r;
      }).catch(function () {
        return caches.match(SHELL_URL);
      })
    );
    return;
  }
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
