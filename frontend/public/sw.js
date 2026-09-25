// Bump RELEASE_VERSION with each frontend release. Activation removes every prior FamilyFin cache.
const RELEASE_VERSION = "t02-2026-09-25-2";
const CACHE_PREFIX = "familyfin-static-";
const CACHE_NAME = `${CACHE_PREFIX}${RELEASE_VERSION}`;
const INSTALL_ASSETS = ["/offline.html", "/icons/icon-192.svg", "/icons/icon-512.svg", "/manifest.webmanifest"];
const REFRESHABLE_STATIC = ["/icons/", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then(async (cache) => {
    await Promise.all(INSTALL_ASSETS.map(async (path) => {
      const response = await fetch(new Request(path, { cache: "reload" }));
      if (!response.ok) throw new Error(`Unable to precache static asset: ${path}`);
      await cache.put(path, response);
    }));
  }));
  // Let the current app finish using its versioned chunks; the waiting worker activates when tabs close.
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME).map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

async function networkFirstStatic(request, cache) {
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    if (response.ok) return response;
    return (await cache.match(request)) || response;
  } catch {
    return (await cache.match(request)) || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Financial API traffic, uploads, and all mutations always go directly to the online service.
  if (url.pathname.startsWith("/api/") || request.method !== "GET") return;

  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(request);
        if (cached) return cached;
        const response = await fetch(request);
        if (response.ok) await cache.put(request, response.clone());
        return response;
      }),
    );
    return;
  }

  if (REFRESHABLE_STATIC.some((path) => url.pathname.startsWith(path))) {
    event.respondWith(caches.open(CACHE_NAME).then((cache) => networkFirstStatic(request, cache)));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(async () => (await caches.open(CACHE_NAME).then((cache) => cache.match("/offline.html"))) || Response.error()));
  }
});
