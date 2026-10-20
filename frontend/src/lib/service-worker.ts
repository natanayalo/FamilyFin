/** Keep production PWA caches out of hot-reload sessions on the same origin. */
export async function configureServiceWorker(hotReload: boolean): Promise<void> {
  if (!("serviceWorker" in navigator)) return;
  if (!hotReload) {
    await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    return;
  }
  const registrations = await navigator.serviceWorker.getRegistrations();
  const isFamilyFin = (worker: ServiceWorker | null) => worker &&
    new URL(worker.scriptURL).origin === location.origin &&
    new URL(worker.scriptURL).pathname === "/sw.js";
  await Promise.all(registrations.filter((registration) =>
    isFamilyFin(registration.active) || isFamilyFin(registration.waiting) || isFamilyFin(registration.installing)
  ).map((registration) => registration.unregister()));
  if ("caches" in window) {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith("familyfin-static-")).map((name) => caches.delete(name)));
  }
  // An unregistered worker still controls this document until its next navigation.
  if (isFamilyFin(navigator.serviceWorker.controller)) location.reload();
}
