/* Світло є?: офлайн-кеш.
   Сторінка і живі дані (графік, аварії): спершу мережа, без мережі збережена копія.
   Дані адрес і будинків: одразу з кешу, у фоні оновлюються.
   Бібліотека карти та іконки: з кешу. Фрагменти карти OSM: переглянуті, до 600 штук. */
var V = "svitlo-v1", TILES = "svitlo-tiles-v1";
var SHELL = ["./", "index.html", "vendor/leaflet/leaflet.js", "vendor/leaflet/leaflet.css", "manifest.webmanifest", "icons/icon-192.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(V).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k !== V && k !== TILES; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function key(req) { var u = new URL(req.url); u.search = ""; return u.href; }   // ?t=... не множить копії
function networkFirst(req) {
  return fetch(req).then(function (r) {
    if (r.ok) { var c = r.clone(); caches.open(V).then(function (cc) { cc.put(key(req), c); }); }
    return r;
  }).catch(function () { return caches.match(key(req)).then(function (r) { return r || Response.error(); }); });
}
function staleWhileRevalidate(req, name) {
  return caches.open(name).then(function (c) {
    return c.match(key(req)).then(function (hit) {
      var net = fetch(req).then(function (r) { if (r.ok) c.put(key(req), r.clone()); return r; }).catch(function () { return hit; });
      return hit || net;
    });
  });
}
function cacheFirst(req) {
  return caches.match(key(req)).then(function (hit) {
    return hit || fetch(req).then(function (r) { if (r.ok) { var c = r.clone(); caches.open(V).then(function (cc) { cc.put(key(req), c); }); } return r; });
  });
}
var trimming = false;
function trimTiles() {
  if (trimming) return; trimming = true;
  caches.open(TILES).then(function (c) {
    return c.keys().then(function (ks) { return Promise.all(ks.slice(0, Math.max(0, ks.length - 600)).map(function (k) { return c.delete(k); })); });
  }).then(function () { trimming = false; }, function () { trimming = false; });
}

self.addEventListener("fetch", function (e) {
  var req = e.request; if (req.method !== "GET") return;
  var u = new URL(req.url);
  if (u.hostname === "raw.githubusercontent.com") { e.respondWith(networkFirst(req)); return; }
  if (u.hostname.endsWith("tile.openstreetmap.org")) { e.respondWith(staleWhileRevalidate(req, TILES)); trimTiles(); return; }
  if (u.origin !== location.origin) return;                         // статистика та інше: без втручання
  if (req.mode === "navigate" || /\/(index\.html)?$/.test(u.pathname) || /schedule\.json$/.test(u.pathname)) { e.respondWith(networkFirst(req)); return; }
  if (/\/data\//.test(u.pathname)) { e.respondWith(staleWhileRevalidate(req, V)); return; }
  e.respondWith(cacheFirst(req));
});
