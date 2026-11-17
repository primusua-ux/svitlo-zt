/* Старий домен більше не обслуговується: цей service worker замінює попередній,
   прибирає збережені кеші і знімає себе, щоб встановлений застосунок не показував застарілі дані. */
self.addEventListener("install", function () { self.skipWaiting(); });
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (ks) { return Promise.all(ks.map(function (k) { return caches.delete(k); })); })
    .then(function () { return self.registration.unregister(); })
    .then(function () { return self.clients.matchAll({ type: "window" }); })
    .then(function (cs) { cs.forEach(function (c) { c.navigate(c.url); }); }));
});
