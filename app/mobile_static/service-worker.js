const SHELL_CACHE = "yubai-mobile-shell-v5";
const KNOWLEDGE_CACHE = "yubai-mobile-knowledge-v1";
const KNOWLEDGE_META_PATH = "/__pcw-offline-knowledge-meta";
const SHELL = [
  "/offline",
  "/mobile-assets/styles/base.css?v=5",
  "/mobile-assets/styles/knowledge.css?v=5",
  "/mobile-assets/mobile.js?v=5",
  "/mobile-assets/icon.svg",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys
        .filter(key => key !== SHELL_CACHE && key !== KNOWLEDGE_CACHE)
        .map(key => caches.delete(key)),
    )).then(() => self.clients.claim()),
  );
});

function isKnowledgePath(pathname) {
  return pathname === "/knowledge" || pathname.startsWith("/knowledge/");
}

async function clearKnowledgeCache() {
  await caches.delete(KNOWLEDGE_CACHE);
}

async function knowledgeCacheStatus() {
  const cache = await caches.open(KNOWLEDGE_CACHE);
  const entries = await cache.keys();
  const metaResponse = await cache.match(KNOWLEDGE_META_PATH);
  let updatedAt = null;
  if (metaResponse) {
    try {
      updatedAt = (await metaResponse.json()).updatedAt || null;
    } catch (_) {
      updatedAt = null;
    }
  }
  return {
    count: entries.filter(entry => new URL(entry.url).pathname !== KNOWLEDGE_META_PATH).length,
    updatedAt,
  };
}

async function notifyKnowledgeStatus() {
  const status = await knowledgeCacheStatus();
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  clients.forEach(client => client.postMessage({ type: "KNOWLEDGE_CACHE_STATUS", ...status }));
}

function isCacheableKnowledgeResponse(response) {
  return response.ok
    && !response.redirected
    && response.headers.get("x-pcw-offline-knowledge") === "1";
}

async function cacheKnowledgePaths(paths) {
  const cache = await caches.open(KNOWLEDGE_CACHE);
  let cached = 0;
  let failed = false;
  const acceptedPaths = [...new Set(paths.filter(rawPath => {
    const url = new URL(rawPath, self.location.origin);
    return url.origin === self.location.origin && isKnowledgePath(url.pathname);
  }).map(rawPath => new URL(rawPath, self.location.origin).pathname))];
  for (const path of acceptedPaths) {
    try {
      const request = new Request(path, { credentials: "same-origin", cache: "no-store" });
      const response = await fetch(request);
      if (response.status === 401 || response.status === 403 || response.redirected) {
        await clearKnowledgeCache();
        throw new Error("mobile session unavailable");
      }
      if (!isCacheableKnowledgeResponse(response)) continue;
      await cache.put(request, response.clone());
      cached += 1;
    } catch (_) {
      failed = true;
      // Existing verified snapshot remains available when an individual refresh fails.
    }
  }
  if (!failed && cached === acceptedPaths.length && cached > 0) {
    const accepted = new Set(acceptedPaths);
    for (const entry of await cache.keys()) {
      const pathname = new URL(entry.url).pathname;
      if (pathname !== KNOWLEDGE_META_PATH && !accepted.has(pathname)) {
        await cache.delete(entry);
      }
    }
    await cache.put(
      KNOWLEDGE_META_PATH,
      new Response(JSON.stringify({ updatedAt: new Date().toISOString() }), {
        headers: { "Content-Type": "application/json" },
      }),
    );
  }
  await notifyKnowledgeStatus();
}

async function knowledgeResponse(request) {
  try {
    const response = await fetch(request);
    if (response.status === 401 || response.status === 403 || response.redirected) {
      await clearKnowledgeCache();
      return response;
    }
    if (isCacheableKnowledgeResponse(response)) {
      const cache = await caches.open(KNOWLEDGE_CACHE);
      await cache.put(request, response.clone());
    }
    return response;
  } catch (_) {
    const cached = await caches.match(request, { cacheName: KNOWLEDGE_CACHE });
    return cached || caches.match("/offline");
  }
}

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (isKnowledgePath(url.pathname)) {
    event.respondWith(knowledgeResponse(event.request));
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/offline")));
    return;
  }
  if (url.pathname.startsWith("/mobile-assets/")) {
    event.respondWith(caches.match(event.request).then(found => found || fetch(event.request)));
  }
});

self.addEventListener("message", event => {
  const data = event.data || {};
  if (data.type === "CACHE_KNOWLEDGE_PATHS" && Array.isArray(data.paths)) {
    event.waitUntil(cacheKnowledgePaths(data.paths));
  } else if (data.type === "CLEAR_KNOWLEDGE_CACHE") {
    event.waitUntil(clearKnowledgeCache().then(notifyKnowledgeStatus));
  } else if (data.type === "GET_KNOWLEDGE_CACHE_STATUS") {
    event.waitUntil(notifyKnowledgeStatus());
  }
});

self.addEventListener("sync", event => {
  if (event.tag === "sync-captures") event.waitUntil(syncCaptures());
});

function openCaptureDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("yubai-mobile-captures", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("captures", { keyPath: "idempotencyKey" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function allCaptures(db) {
  return new Promise((resolve, reject) => {
    const request = db.transaction("captures", "readonly").objectStore("captures").getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function removeCapture(db, key) {
  return new Promise((resolve, reject) => {
    const request = db.transaction("captures", "readwrite").objectStore("captures").delete(key);
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

function captureFormData(capture) {
  const data = new FormData();
  data.append("idempotency_key", capture.idempotencyKey);
  data.append("body", capture.body);
  data.append("title", capture.title);
  data.append("tags", capture.tags);
  data.append("category", capture.category);
  data.append("created_at", capture.createdAt);
  capture.images.forEach(image => data.append("images", image.blob, image.name));
  return data;
}

async function syncCaptures() {
  const sessionResponse = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
  if (!sessionResponse.ok) {
    await clearKnowledgeCache();
    throw new Error("mobile session unavailable");
  }
  const session = await sessionResponse.json();
  const db = await openCaptureDb();
  try {
    for (const capture of await allCaptures(db)) {
      const response = await fetch("/api/captures", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-CSRF-Token": session.csrf_token },
        body: captureFormData(capture),
      });
      if (!response.ok) throw new Error("capture sync failed");
      await removeCapture(db, capture.idempotencyKey);
    }
  } finally {
    db.close();
  }
  const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  clients.forEach(client => client.postMessage({ type: "SYNC_COMPLETE" }));
}
