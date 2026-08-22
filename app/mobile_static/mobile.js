(() => {
  "use strict";

  const DB_NAME = "yubai-mobile-captures";
  const DB_VERSION = 2;
  const STORES = {
    captures: "captures",
    ideas: "ideas",
    edits: "ideaEdits",
    conflicts: "ideaConflicts",
    meta: "meta",
  };
  let csrfToken = "";

  function openDb() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORES.captures)) {
          db.createObjectStore(STORES.captures, { keyPath: "idempotencyKey" });
        }
        if (!db.objectStoreNames.contains(STORES.ideas)) {
          db.createObjectStore(STORES.ideas, { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains(STORES.edits)) {
          db.createObjectStore(STORES.edits, { keyPath: "itemId" });
        }
        if (!db.objectStoreNames.contains(STORES.conflicts)) {
          db.createObjectStore(STORES.conflicts, { keyPath: "itemId" });
        }
        if (!db.objectStoreNames.contains(STORES.meta)) {
          db.createObjectStore(STORES.meta, { keyPath: "key" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function transact(storeName, mode, operation) {
    const db = await openDb();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, mode);
      const request = operation(transaction.objectStore(storeName));
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.oncomplete = () => db.close();
      transaction.onerror = () => {
        db.close();
        reject(transaction.error);
      };
    });
  }

  const all = store => transact(store, "readonly", target => target.getAll());
  const get = (store, key) => transact(store, "readonly", target => target.get(key));
  const put = (store, value) => transact(store, "readwrite", target => target.put(value));
  const remove = (store, key) => transact(store, "readwrite", target => target.delete(key));
  const clear = store => transact(store, "readwrite", target => target.clear());

  function setMessage(selector, text) {
    const target = document.querySelector(selector);
    if (target) target.textContent = text;
  }

  function updateNetwork() {
    const target = document.querySelector("#network-state");
    if (!target) return;
    target.textContent = navigator.onLine ? "网络可用" : "离线模式";
    target.className = navigator.onLine ? "online" : "offline";
  }

  async function serviceWorkerTarget() {
    if (!("serviceWorker" in navigator)) return null;
    const registration = await navigator.serviceWorker.ready;
    return navigator.serviceWorker.controller || registration.active || registration.waiting;
  }

  async function sendToServiceWorker(payload) {
    try {
      const target = await serviceWorkerTarget();
      target?.postMessage(payload);
    } catch (_) {
      // Online use remains available without the service worker.
    }
  }

  async function clearOfflineKnowledge() {
    await sendToServiceWorker({ type: "CLEAR_KNOWLEDGE_CACHE" });
  }

  async function clearPrivateLocalData() {
    await Promise.all(Object.values(STORES).map(store => clear(store)));
    await clearOfflineKnowledge();
  }

  async function session() {
    let response;
    try {
      response = await fetch("/api/session", {
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch (error) {
      throw new Error("Mac 暂时不可达，本机内容仍然保留。");
    }
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        await clearPrivateLocalData();
      }
      throw new Error("手机会话已失效，请重新配对。");
    }
    const data = await response.json();
    csrfToken = data.csrf_token;
    return data;
  }

  async function requestBackgroundSync() {
    if (!("serviceWorker" in navigator)) return;
    try {
      const registration = await navigator.serviceWorker.ready;
      if ("sync" in registration) await registration.sync.register("sync-workspace");
    } catch (_) {
      // Foreground retries remain available.
    }
  }

  function validateImages(files) {
    const total = files.reduce((sum, file) => sum + file.size, 0);
    if (
      files.length > 5
      || files.some(file => file.size > 10 * 1024 * 1024)
      || total > 25 * 1024 * 1024
    ) {
      throw new Error("图片限制：最多 5 张、单张 10 MB、合计 25 MB。");
    }
  }

  function serializeImages(files) {
    return files.map(file => ({ name: file.name, type: file.type, blob: file }));
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

  async function updateQueueCount() {
    const captures = await all(STORES.captures);
    const target = document.querySelector("#queue-count");
    if (target) target.textContent = String(captures.length);
    return captures;
  }

  async function syncCaptureQueue() {
    if (!navigator.onLine) {
      setMessage("#sync-message", "Mac 暂时不可达，内容已安全留在手机队列。");
      return;
    }
    const captures = await updateQueueCount();
    if (!captures.length) {
      setMessage("#sync-message", "没有待同步内容。");
      return;
    }
    try {
      if (!csrfToken) await session();
      let synced = 0;
      for (const capture of captures) {
        const response = await fetch("/api/captures", {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: { "X-CSRF-Token": csrfToken },
          body: captureFormData(capture),
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({ detail: "同步失败" }));
          throw new Error(error.detail || "同步失败");
        }
        const receipt = await response.json();
        await remove(STORES.captures, capture.idempotencyKey);
        synced += 1;
        if (currentIdeaId() === `local--${capture.idempotencyKey}`) {
          location.replace(`/ideas/${encodeURIComponent(receipt.content_id)}`);
          return;
        }
      }
      await updateQueueCount();
      setMessage("#sync-message", `已将 ${synced} 条记录同步回 Mac。`);
      await refreshIdeasSnapshot();
      await loadRecent();
    } catch (error) {
      setMessage("#sync-message", `${error.message} 未同步内容仍保留在手机。`);
    }
  }

  async function queueCapture(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const files = [...form.elements.images.files];
    try {
      validateImages(files);
    } catch (error) {
      setMessage("#sync-message", error.message);
      return;
    }
    const capture = {
      idempotencyKey: crypto.randomUUID(),
      body: String(data.get("body") || "").trim(),
      title: String(data.get("title") || ""),
      tags: String(data.get("tags") || ""),
      category: String(data.get("category") || ""),
      createdAt: new Date().toISOString(),
      images: serializeImages(files),
    };
    if (!capture.body) return;
    await put(STORES.captures, capture);
    await requestBackgroundSync();
    form.reset();
    setMessage("#image-summary", "");
    await updateQueueCount();
    setMessage("#sync-message", "想法已先保存在手机，正在尝试送回 Mac……");
    await syncCaptureQueue();
  }

  async function loadRecent() {
    const target = document.querySelector("#recent-list");
    if (!target || !navigator.onLine) return;
    try {
      const response = await fetch("/api/recent", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      const { items } = await response.json();
      target.replaceChildren();
      if (!items.length) {
        target.innerHTML = '<p class="quiet-note">Mac 上还没有待整理记录。</p>';
        return;
      }
      items.forEach(item => {
        const article = document.createElement("article");
        article.className = "recent-item";
        const title = document.createElement("strong");
        title.textContent = item.title;
        const summary = document.createElement("div");
        summary.textContent = item.summary;
        const meta = document.createElement("small");
        meta.textContent = new Date(item.created_at).toLocaleString("zh-CN");
        article.append(title, summary, meta);
        item.tags.forEach(value => {
          const tag = document.createElement("span");
          tag.className = "tag";
          tag.textContent = value;
          article.append(tag);
        });
        target.append(article);
      });
    } catch (_) {
      target.innerHTML = '<p class="quiet-note">暂时读不到 Mac，离线记录仍然可用。</p>';
    }
  }

  function editFormData(edit) {
    const data = new FormData();
    data.append("operation_key", edit.operationKey);
    data.append("expected_revision", edit.baseRevision);
    data.append("body", edit.body);
    data.append("title", edit.title);
    data.append("tags", edit.tags);
    data.append("category", edit.category);
    edit.images.forEach(image => data.append("images", image.blob, image.name));
    return data;
  }

  async function refreshIdeasSnapshot() {
    if (!navigator.onLine) {
      await renderIdeaList();
      return;
    }
    try {
      if (!csrfToken) await session();
      const response = await fetch("/api/ideas/snapshot", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error("无法读取随想快照");
      const payload = await response.json();
      const edits = new Map((await all(STORES.edits)).map(edit => [edit.itemId, edit]));
      const current = await all(STORES.ideas);
      const received = new Set(payload.items.map(item => item.id));
      for (const item of payload.items) {
        if (!edits.has(item.id)) await put(STORES.ideas, item);
      }
      for (const item of current) {
        if (!received.has(item.id) && !edits.has(item.id)) await remove(STORES.ideas, item.id);
      }
      await put(STORES.meta, { key: "topics", value: payload.topics || [] });
      setMessage("#idea-list-message", `已更新 ${payload.items.length} 条随想快照。`);
    } catch (error) {
      setMessage("#idea-list-message", `${error.message} 使用手机上的最近快照。`);
    }
    await renderIdeaList();
  }

  async function renderIdeaList() {
    const target = document.querySelector("#mobile-idea-list");
    if (!target) return;
    const edits = new Set((await all(STORES.edits)).map(edit => edit.itemId));
    const conflicts = new Set((await all(STORES.conflicts)).map(item => item.itemId));
    const serverIdeas = (await all(STORES.ideas)).map(item => ({
      ...item,
      hrefId: item.id,
      pending: edits.has(item.id),
      conflict: conflicts.has(item.id),
      sortTime: item.updated_at,
    }));
    const localIdeas = (await all(STORES.captures)).map(item => ({
      id: `local--${item.idempotencyKey}`,
      hrefId: `local--${item.idempotencyKey}`,
      title: item.title || item.body.slice(0, 36) || "未命名想法",
      summary: item.body.slice(0, 90),
      pending: true,
      conflict: false,
      sortTime: item.createdAt,
    }));
    const items = [...serverIdeas, ...localIdeas].sort(
      (left, right) => String(right.sortTime).localeCompare(String(left.sortTime)),
    );
    target.replaceChildren();
    if (!items.length) {
      target.innerHTML = '<p class="quiet-note">还没有随想快照。联网刷新，或先去“随手记”写一条。</p>';
      return;
    }
    items.forEach(item => {
      const link = document.createElement("a");
      link.className = `idea-list-item${item.pending ? " pending" : ""}`;
      link.href = `/ideas/${encodeURIComponent(item.hrefId)}`;
      const title = document.createElement("strong");
      title.textContent = item.title || "未命名想法";
      const summary = document.createElement("p");
      summary.textContent = item.summary || "";
      const state = document.createElement("small");
      state.textContent = item.conflict
        ? "存在版本冲突，等待合并"
        : item.pending
          ? "手机修改待同步"
          : "已与 Mac 同步";
      link.append(title, summary, state);
      target.append(link);
    });
    const count = document.querySelector("#idea-edit-count");
    if (count) count.textContent = String(edits.size + localIdeas.length);
  }

  async function syncIdeaEdits() {
    if (!navigator.onLine) {
      setMessage("#idea-list-message", "当前离线，修改仍保留在手机。");
      return;
    }
    const edits = await all(STORES.edits);
    if (!edits.length) {
      await renderIdeaList();
      return;
    }
    try {
      if (!csrfToken) await session();
      let synced = 0;
      for (const edit of edits) {
        const suffix = edit.resolve ? "/resolve" : "";
        const response = await fetch(`/api/ideas/${encodeURIComponent(edit.itemId)}${suffix}`, {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          headers: { "X-CSRF-Token": csrfToken },
          body: editFormData(edit),
        });
        const payload = await response.json().catch(() => ({ detail: "同步失败" }));
        if (response.status === 409) {
          await put(STORES.conflicts, { itemId: edit.itemId, server: payload.current, local: edit });
          continue;
        }
        if (!response.ok) throw new Error(payload.detail || "同步失败");
        await put(STORES.ideas, payload.item);
        await remove(STORES.edits, edit.itemId);
        await remove(STORES.conflicts, edit.itemId);
        synced += 1;
      }
      setMessage(
        "#idea-list-message",
        synced ? `已同步 ${synced} 条修改。` : "有修改需要先处理版本冲突。",
      );
    } catch (error) {
      setMessage("#idea-list-message", `${error.message} 修改仍保留在手机。`);
    }
    await renderIdeaList();
    await loadIdeaEditor();
  }

  function currentIdeaId() {
    const editor = document.querySelector("#idea-editor");
    if (!editor) return "";
    if (editor.dataset.ideaId) return editor.dataset.ideaId;
    const match = location.pathname.match(/^\/ideas\/([^/]+)$/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function fillIdeaForm(item) {
    const form = document.querySelector("#idea-edit-form");
    if (!form || !item) return;
    form.elements.title.value = item.title || "";
    form.elements.body.value = item.body || "";
    form.elements.tags.value = Array.isArray(item.tags) ? item.tags.join("，") : item.tags || "";
    form.elements.category.value = item.category || "";
    const heading = document.querySelector("#idea-heading");
    if (heading) heading.textContent = item.title || "未命名想法";
  }

  async function renderTopics() {
    const target = document.querySelector("#mobile-topic-options");
    if (!target) return;
    const meta = await get(STORES.meta, "topics");
    const topics = meta?.value || [];
    target.replaceChildren();
    if (!topics.length) {
      target.innerHTML = '<p class="quiet-note">还没有可用主题地图，请先在桌面或 Obsidian 创建主题。</p>';
      return;
    }
    topics.forEach(topic => {
      const label = document.createElement("label");
      label.className = "topic-option";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.name = "map_ids";
      input.value = topic.id;
      const copy = document.createElement("span");
      const title = document.createElement("b");
      title.textContent = topic.title;
      const summary = document.createElement("small");
      summary.textContent = topic.summary || "";
      copy.append(title, summary);
      label.append(input, copy);
      target.append(label);
    });
  }

  async function renderConflict(itemId) {
    const panel = document.querySelector("#idea-conflict");
    if (!panel) return;
    const conflict = await get(STORES.conflicts, itemId);
    panel.hidden = !conflict;
    if (!conflict) return;
    document.querySelector("#conflict-server-body").value = conflict.server.body || "";
    document.querySelector("#conflict-local-body").value = conflict.local.body || "";
    setMessage("#idea-edit-message", "检测到冲突：两边内容都保留了，请人工决定。");
  }

  async function loadIdeaEditor() {
    const itemId = currentIdeaId();
    if (!itemId) return;
    if (itemId.startsWith("local--")) {
      const capture = await get(STORES.captures, itemId.slice(7));
      if (!capture) {
        setMessage("#idea-edit-message", "这条本地想法已经同步或不存在。");
        return;
      }
      fillIdeaForm(capture);
      document.querySelector(".distill-card")?.setAttribute("hidden", "");
      return;
    }
    if (navigator.onLine && !(await get(STORES.edits, itemId))) await refreshIdeasSnapshot();
    const item = await get(STORES.ideas, itemId);
    if (!item) {
      setMessage("#idea-edit-message", "手机上没有这条随想快照，请联网后返回列表刷新。");
      return;
    }
    fillIdeaForm(item);
    await renderTopics();
    await renderConflict(itemId);
  }

  async function saveIdeaEdit(event) {
    event.preventDefault();
    const itemId = currentIdeaId();
    const form = event.currentTarget;
    const data = new FormData(form);
    const files = [...form.elements.images.files];
    try {
      validateImages(files);
      if (itemId.startsWith("local--")) {
        const key = itemId.slice(7);
        const capture = await get(STORES.captures, key);
        if (!capture) throw new Error("本地想法不存在");
        const combinedImages = [...capture.images, ...serializeImages(files)];
        validateImages(combinedImages.map(image => image.blob));
        await put(STORES.captures, {
          ...capture,
          title: String(data.get("title") || ""),
          body: String(data.get("body") || "").trim(),
          tags: String(data.get("tags") || ""),
          category: String(data.get("category") || ""),
          images: combinedImages,
        });
        setMessage("#idea-edit-message", "本地想法已更新，联网后会作为一条记录同步。");
        await requestBackgroundSync();
        if (navigator.onLine) await syncCaptureQueue();
        return;
      }
      const snapshot = await get(STORES.ideas, itemId);
      if (!snapshot) throw new Error("缺少随想快照，请返回列表刷新");
      const existing = await get(STORES.edits, itemId);
      const images = [...(existing?.images || []), ...serializeImages(files)];
      validateImages(images.map(image => image.blob));
      const edit = {
        itemId,
        operationKey: existing?.operationKey || crypto.randomUUID(),
        baseRevision: existing?.baseRevision || snapshot.revision,
        title: String(data.get("title") || ""),
        body: String(data.get("body") || "").trim(),
        tags: String(data.get("tags") || ""),
        category: String(data.get("category") || ""),
        images,
      };
      await put(STORES.edits, edit);
      await put(STORES.ideas, {
        ...snapshot,
        title: edit.title || snapshot.title,
        body: edit.body,
        summary: edit.body.slice(0, 180),
        tags: edit.tags.split(/[,，]/).map(value => value.trim()).filter(Boolean),
        category: edit.category || null,
        updated_at: new Date().toISOString(),
      });
      setMessage("#idea-edit-message", "修改已保存在手机，正在尝试同步……");
      await requestBackgroundSync();
      await syncIdeaEdits();
    } catch (error) {
      setMessage("#idea-edit-message", error.message);
    }
  }

  async function discardMobileEdit() {
    const itemId = currentIdeaId();
    const conflict = await get(STORES.conflicts, itemId);
    if (!conflict) return;
    await put(STORES.ideas, conflict.server);
    await remove(STORES.edits, itemId);
    await remove(STORES.conflicts, itemId);
    fillIdeaForm(conflict.server);
    await renderConflict(itemId);
    setMessage("#idea-edit-message", "已丢弃手机修改，保留 Mac / Obsidian 最新版本。");
  }

  async function saveMergedEdit() {
    const itemId = currentIdeaId();
    const conflict = await get(STORES.conflicts, itemId);
    if (!conflict) return;
    const form = document.querySelector("#idea-edit-form");
    const edit = {
      ...conflict.local,
      operationKey: crypto.randomUUID(),
      baseRevision: conflict.server.revision,
      resolve: true,
      title: form.elements.title.value,
      body: document.querySelector("#conflict-local-body").value.trim(),
      tags: form.elements.tags.value,
      category: form.elements.category.value,
    };
    await put(STORES.edits, edit);
    await remove(STORES.conflicts, itemId);
    fillIdeaForm({ ...conflict.server, ...edit });
    await syncIdeaEdits();
  }

  async function createKnowledgeCard(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const itemId = currentIdeaId();
    if (!navigator.onLine) {
      setMessage("#distill-message", "知识卡只在联网时创建；随想编辑仍可离线保存。");
      return;
    }
    if (itemId.startsWith("local--")) {
      setMessage("#distill-message", "请先把这条新随想同步到 Mac，再整理为知识。");
      return;
    }
    await syncIdeaEdits();
    if (await get(STORES.edits, itemId)) {
      setMessage("#distill-message", "请先解决随想同步或版本冲突，再创建知识卡。");
      return;
    }
    try {
      if (!csrfToken) await session();
      const response = await fetch(`/api/ideas/${encodeURIComponent(itemId)}/knowledge/cards`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "X-CSRF-Token": csrfToken },
        body: new FormData(form),
      });
      const payload = await response.json().catch(() => ({ detail: "创建失败" }));
      if (!response.ok) throw new Error(payload.detail || "创建失败");
      form.reset();
      setMessage("#distill-message", `已创建知识卡「${payload.title}」，原始随想没有改变。`);
    } catch (error) {
      setMessage("#distill-message", error.message);
    }
  }

  function offlineKnowledgePaths() {
    const manifest = document.querySelector("#knowledge-offline-manifest");
    if (!manifest) return [];
    try {
      const paths = JSON.parse(manifest.textContent || "[]");
      return Array.isArray(paths) ? paths.filter(path => typeof path === "string") : [];
    } catch (_) {
      return [];
    }
  }

  function renderKnowledgeCacheStatus({ count = 0, updatedAt = null } = {}) {
    const target = document.querySelector("#knowledge-cache-status");
    if (!target) return;
    if (!count) {
      target.textContent = "尚未保存离线知识";
      return;
    }
    const suffix = updatedAt
      ? ` · ${new Date(updatedAt).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })}`
      : "";
    target.textContent = `已缓存 ${count} 个知识页面${suffix}`;
  }

  async function refreshOfflineKnowledge() {
    const paths = offlineKnowledgePaths();
    if (paths.length && navigator.onLine) {
      setMessage("#knowledge-cache-status", "正在更新离线知识……");
      await sendToServiceWorker({ type: "CACHE_KNOWLEDGE_PATHS", paths });
      return;
    }
    await sendToServiceWorker({ type: "GET_KNOWLEDGE_CACHE_STATUS" });
  }

  async function revoke() {
    if (!confirm("解除后会清除本机快照和待同步内容，并需要新配对码。确定吗？")) return;
    if (!csrfToken) await session();
    const response = await fetch("/api/session/revoke", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken },
    });
    if (response.ok) {
      await clearPrivateLocalData();
      location.reload();
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    updateNetwork();
    if ("serviceWorker" in navigator) {
      try {
        await navigator.serviceWorker.register("/service-worker.js");
      } catch (_) {
        // Online use remains available if registration fails.
      }
    }
    const captureForm = document.querySelector("#capture-form");
    captureForm?.addEventListener("submit", queueCapture);
    document.querySelector("#sync-now")?.addEventListener("click", syncCaptureQueue);
    document.querySelector("#refresh-recent")?.addEventListener("click", loadRecent);
    document.querySelector("#revoke-session")?.addEventListener("click", revoke);
    document.querySelector("#refresh-ideas")?.addEventListener("click", refreshIdeasSnapshot);
    document.querySelector("#sync-idea-edits")?.addEventListener("click", syncIdeaEdits);
    document.querySelector("#idea-edit-form")?.addEventListener("submit", saveIdeaEdit);
    document.querySelector("#discard-mobile-edit")?.addEventListener("click", discardMobileEdit);
    document.querySelector("#save-merged-edit")?.addEventListener("click", saveMergedEdit);
    document.querySelector("#mobile-distill-form")?.addEventListener("submit", createKnowledgeCard);
    document.querySelector("#clear-mobile-data")?.addEventListener("click", async () => {
      if (confirm("清除离线随想、待同步修改、图片和知识副本？此操作无法撤销。")) {
        await clearPrivateLocalData();
        await renderIdeaList();
        setMessage("#idea-list-message", "手机本地副本已清除。");
      }
    });
    document.querySelector("#clear-knowledge-cache")?.addEventListener("click", async () => {
      if (confirm("清除这台手机保存的离线知识副本？联网后可以重新生成。")) {
        await clearOfflineKnowledge();
      }
    });
    document.querySelector('input[name="images"]')?.addEventListener("change", event => {
      const files = [...event.target.files];
      setMessage(
        "#image-summary",
        files.length
          ? `已选择 ${files.length} 张，共 ${(files.reduce((sum, file) => sum + file.size, 0) / 1024 / 1024).toFixed(1)} MB`
          : "",
      );
    });
    if (captureForm) {
      await updateQueueCount();
      try {
        await session();
      } catch (error) {
        setMessage("#sync-message", error.message);
      }
      await syncCaptureQueue();
      await loadRecent();
    }
    if (document.querySelector("#mobile-idea-list")) await refreshIdeasSnapshot();
    if (document.querySelector("#idea-editor")) await loadIdeaEditor();
    if (document.querySelector("#knowledge-offline-manifest")) await refreshOfflineKnowledge();
  });

  window.addEventListener("online", async () => {
    updateNetwork();
    await syncCaptureQueue();
    await syncIdeaEdits();
    if (document.querySelector("#mobile-idea-list")) await refreshIdeasSnapshot();
    if (document.querySelector("#knowledge-offline-manifest")) await refreshOfflineKnowledge();
  });
  window.addEventListener("offline", updateNetwork);
  navigator.serviceWorker?.addEventListener("message", event => {
    if (event.data?.type === "SYNC_COMPLETE") {
      updateQueueCount();
      renderIdeaList();
      loadRecent();
      setMessage("#sync-message", "后台同步已完成。");
    } else if (event.data?.type === "KNOWLEDGE_CACHE_STATUS") {
      renderKnowledgeCacheStatus(event.data);
    }
  });
})();
