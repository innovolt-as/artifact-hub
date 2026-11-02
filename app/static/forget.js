// Forget the copies on this phone (static/sw.js). They are the caches whose names start with "hub-", and only those
// go: an app's localStorage, IndexedDB and own caches are never touched.
//   window.hubForget() -> Promise<void>  never fails; settings-account.js calls it after «Slett mine data»
// With data-run on its tag it runs at once: base.html loads it so on every page for someone not logged in, so logging
// out, or a login that has run out, leaves no copy behind. The worker is told too, so an answer it is still storing
// does not bring a cache back.
(function () {
  const me = document.currentScript;
  window.hubForget = async () => {
    try { navigator.serviceWorker?.controller?.postMessage({ type: "hub:forget" }); } catch { /* no worker */ }
    try {
      const names = await window.caches.keys();
      await Promise.all(names.filter((n) => n.startsWith("hub-")).map((n) => window.caches.delete(n)));
    } catch { /* no Cache API (not a secure page): nothing was kept */ }
  };
  if (me && me.hasAttribute("data-run")) window.hubForget();
})();
