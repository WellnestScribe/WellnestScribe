{% load static %}
const CACHE_NAME = "wellnest-shell-v{{ ui_asset_version|default:'1' }}";
const APP_SHELL = [
  "/",
  "{% url 'manifest' %}?v={{ ui_asset_version|default:'1' }}",
  "{% static 'images/favicon.ico' %}",
  "{% static 'images/wellnest-logo.png' %}",
  "{% static 'images/pwa/icon-192x192.png' %}",
  "{% static 'images/pwa/icon-512x512.png' %}",
  "{% static 'css/wellnest.css' %}?v={{ ui_asset_version|default:'1' }}",
  "{% static 'js/wellnest.js' %}?v={{ ui_asset_version|default:'1' }}"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(async () => {
          return (
            (await caches.match(request)) ||
            caches.match("/") ||
            Response.error()
          );
        })
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            return response;
          })
          .catch(() => cached);
        return cached || networkFetch;
      })
    );
  }
});
