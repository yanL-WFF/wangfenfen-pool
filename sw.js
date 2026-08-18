// 王粉粉选题池 Service Worker —— 让手机「添加到主屏幕」后像原生 App 一样离线可用
const CACHE = 'wf-pool-v2';
const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // 动态接口（数据/AI/同步）走网络优先，失败回退缓存
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // 静态资源：缓存优先，同时后台更新
  e.respondWith(
    caches.match(e.request).then(hit => {
      const net = fetch(e.request).then(resp => {
        if (resp && resp.status === 200) caches.open(CACHE).then(c => c.put(e.request, resp.clone()));
        return resp;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
