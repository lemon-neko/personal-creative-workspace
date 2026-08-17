(() => {
  "use strict";
  const DB_NAME = "yubai-mobile-captures";
  const STORE = "captures";
  let csrfToken = "";

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "idempotencyKey" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function transact(mode, operation) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const store = transaction.objectStore(STORE);
      const request = operation(store);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => db.close();
    });
  }

  const allCaptures = () => transact("readonly", store => store.getAll());
  const saveCapture = capture => transact("readwrite", store => store.put(capture));
  const removeCapture = key => transact("readwrite", store => store.delete(key));
  const message = text => { const target = document.querySelector("#sync-message"); if (target) target.textContent = text; };

  async function updateQueueCount() {
    const captures = await allCaptures();
    const target = document.querySelector("#queue-count");
    if (target) target.textContent = String(captures.length);
    return captures;
  }

  async function requestBackgroundSync() {
    if (!("serviceWorker" in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.ready;
      if ("sync" in registration) await registration.sync.register("sync-captures");
    } catch (_) { /* foreground retry remains available */ }
  }

  function updateNetwork() {
    const target = document.querySelector("#network-state");
    if (!target) return;
    target.textContent = navigator.onLine ? "网络可用" : "离线排队中";
    target.className = navigator.onLine ? "online" : "offline";
  }

  async function session() {
    const response = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("手机会话已失效，请重新配对。");
    const data = await response.json();
    csrfToken = data.csrf_token;
    return data;
  }

  function formDataFor(capture) {
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

  async function syncQueue() {
    if (!navigator.onLine) { message("Mac 暂时不可达，内容已安全留在手机队列。"); return; }
    const captures = await updateQueueCount();
    if (!captures.length) { message("没有待同步内容。"); return; }
    try {
      if (!csrfToken) await session();
      let synced = 0;
      for (const capture of captures) {
        const response = await fetch("/api/captures", {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { "X-CSRF-Token": csrfToken }, body: formDataFor(capture),
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({ detail: "同步失败" }));
          throw new Error(error.detail || "同步失败");
        }
        await removeCapture(capture.idempotencyKey);
        synced += 1;
      }
      await updateQueueCount();
      message(`已将 ${synced} 条记录同步回 Mac。`);
      await loadRecent();
    } catch (error) {
      message(`${error.message} 未同步内容仍保留在手机。`);
    }
  }

  async function loadRecent() {
    const target = document.querySelector("#recent-list");
    if (!target || !navigator.onLine) return;
    try {
      const response = await fetch("/api/recent", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      const { items } = await response.json();
      target.replaceChildren();
      if (!items.length) { target.innerHTML = '<p class="quiet-note">Mac 上还没有待整理记录。</p>'; return; }
      items.forEach(item => {
        const article = document.createElement("article"); article.className = "recent-item";
        const title = document.createElement("strong"); title.textContent = item.title;
        const summary = document.createElement("div"); summary.textContent = item.summary;
        const meta = document.createElement("small"); meta.textContent = new Date(item.created_at).toLocaleString("zh-CN");
        article.append(title, summary, meta);
        item.tags.forEach(value => { const tag = document.createElement("span"); tag.className = "tag"; tag.textContent = value; article.append(tag); });
        target.append(article);
      });
    } catch (_) { target.innerHTML = '<p class="quiet-note">暂时读不到 Mac，离线记录仍然可用。</p>'; }
  }

  async function queueForm(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const files = [...form.elements.images.files];
    const total = files.reduce((sum, file) => sum + file.size, 0);
    if (files.length > 5 || files.some(file => file.size > 10 * 1024 * 1024) || total > 25 * 1024 * 1024) {
      message("图片限制：最多 5 张、单张 10 MB、合计 25 MB。"); return;
    }
    const capture = {
      idempotencyKey: crypto.randomUUID(), body: String(data.get("body") || "").trim(),
      title: String(data.get("title") || ""), tags: String(data.get("tags") || ""),
      category: String(data.get("category") || ""), createdAt: new Date().toISOString(),
      images: files.map(file => ({ name: file.name, type: file.type, blob: file })),
    };
    if (!capture.body) return;
    await saveCapture(capture);
    await requestBackgroundSync();
    form.reset();
    document.querySelector("#image-summary").textContent = "";
    await updateQueueCount();
    message("想法已先保存在手机，正在尝试送回 Mac……");
    await syncQueue();
  }

  async function revoke() {
    if (!confirm("解除后需要新的配对码才能再次连接。确定吗？")) return;
    if (!csrfToken) await session();
    const response = await fetch("/api/session/revoke", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": csrfToken } });
    if (response.ok) location.reload();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    updateNetwork();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/service-worker.js");
    const captureForm = document.querySelector("#capture-form");
    captureForm?.addEventListener("submit", queueForm);
    document.querySelector("#sync-now")?.addEventListener("click", syncQueue);
    document.querySelector("#refresh-recent")?.addEventListener("click", loadRecent);
    document.querySelector("#revoke-session")?.addEventListener("click", revoke);
    document.querySelector('input[name="images"]')?.addEventListener("change", event => {
      const files = [...event.target.files]; document.querySelector("#image-summary").textContent = files.length ? `已选择 ${files.length} 张，共 ${(files.reduce((s,f)=>s+f.size,0)/1024/1024).toFixed(1)} MB` : "";
    });
    if (captureForm) {
      await updateQueueCount();
      try { await session(); } catch (error) { message(error.message); }
      await syncQueue();
      await loadRecent();
    }
  });
  window.addEventListener("online", () => {
    updateNetwork();
    if (document.querySelector("#capture-form")) syncQueue();
  });
  window.addEventListener("offline", updateNetwork);
  navigator.serviceWorker?.addEventListener("message", event => {
    if (event.data?.type === "SYNC_COMPLETE" && document.querySelector("#capture-form")) {
      updateQueueCount(); loadRecent(); message("后台同步已完成。");
    }
  });
})();
