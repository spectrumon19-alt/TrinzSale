// Unregister stub — PWA has been removed.
// Browsers that still have the old SW registered will receive this, unregister it,
// and stop requesting this file after the next page reload.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => {
    e.waitUntil(
        self.registration.unregister()
            .then(() => self.clients.matchAll({ type: 'window' }))
            .then(clients => clients.forEach(c => c.navigate(c.url)))
    );
});
