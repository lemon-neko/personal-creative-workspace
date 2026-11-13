/* Editable application rows: small partial writes, serialized independently per row. */
(() => {
  function openTarget() {
    const target = document.getElementById(location.hash.slice(1));
    if (target instanceof HTMLDetailsElement) target.open = true;
    if (target) target.scrollIntoView({ block: 'start' });
  }
  window.addEventListener('hashchange', openTarget);
  openTarget();

  const table = document.querySelector('[data-career-table]');
  if (!table) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  const states = new Map();
  const template = document.getElementById('career-new-row-template');
  const bypass = new WeakSet();
  let navigating = false;

  function fields(row) {
    return [...row.querySelectorAll('[data-autosave-field]')];
  }
  function values(row) {
    return Object.fromEntries(fields(row).map(field => [field.name, field.value]));
  }
  function dirty(state) {
    return fields(state.row).some(field => field.value !== state.saved[field.name]);
  }
  function message(state, text, failed = false, retry = false) {
    const label = state.row.querySelector('[data-save-state]');
    label.textContent = text;
    label.toggleAttribute('data-failed', failed);
    state.row.querySelector('[data-retry]').hidden = !retry;
  }
  async function send(url, method, payload) {
    const isForm = payload instanceof FormData;
    let response;
    try {
      response = await fetch(url, {
        method, credentials: 'same-origin',
        headers: { Accept: 'application/json', 'X-CSRF-Token': csrf,
          ...(isForm ? {} : { 'Content-Type': 'application/json' }) },
        body: isForm ? payload : JSON.stringify(payload),
      });
    } catch {
      throw new Error('连接失败，请重试');
    }
    let data;
    try { data = await response.json(); }
    catch { throw new Error('服务未返回保存结果，请重试'); }
    if (!response.ok) {
      throw new Error(typeof data.error === 'string' ? data.error :
        typeof data.detail === 'string' ? data.detail : '保存失败，请刷新页面后重试');
    }
    return data;
  }
  function initialize(row) {
    const state = { row, id: row.dataset.jobId, saved: {}, pending: {}, running: null,
      recording: null, error: false, creationToken: crypto.randomUUID() };
    for (const field of fields(row)) state.saved[field.name] = field.dataset.savedValue;
    row.toggleAttribute('data-new-row', !state.id);
    states.set(row, state);
    return state;
  }
  function appendBlankRow() {
    const row = template.content.firstElementChild.cloneNode(true);
    table.appendChild(row);
    initialize(row);
  }
  function promote(state, job) {
    state.id = job.id;
    state.row.dataset.jobId = job.id;
    state.row.id = `job-${job.id}`;
    state.row.removeAttribute('data-new-row');
    state.row.dataset.patchUrl = `${table.dataset.jobsUrl}/${encodeURIComponent(job.id)}`;
    const detail = state.row.querySelector('[data-detail-link]');
    detail.href = state.row.dataset.patchUrl;
    detail.hidden = false;
    const tailor = state.row.querySelector('[data-tailor-link]');
    if (tailor) {
      tailor.href = table.dataset.matchTemplate.replace('__job__', encodeURIComponent(job.id));
      tailor.hidden = false;
    }
    const record = state.row.querySelector('[data-record-form]');
    if (record) {
      record.action = `${state.row.dataset.patchUrl}/submissions`;
      record.querySelectorAll('select,button').forEach(control => { control.disabled = false; });
    }
    appendBlankRow();
  }
  async function drain(state) {
    while (Object.keys(state.pending).length) {
      const creating = !state.id;
      const input = creating ? values(state.row) : state.pending;
      if (creating && (!input.company.trim() || !input.title.trim())) {
        message(state, '填完公司与岗位后保存');
        return false;
      }
      const sent = creating ? { ...input } : Object.fromEntries(
        Object.entries(input).filter(([key, value]) => value !== state.saved[key]));
      state.pending = {};
      if (!Object.keys(sent).length) continue;
      message(state, '保存中');
      try {
        const data = await send(creating ? table.dataset.jobsUrl : state.row.dataset.patchUrl,
          creating ? 'POST' : 'PATCH', creating ? { ...sent, creation_token: state.creationToken } : sent);
        if (!data.job?.id) throw new Error('未收到记录标识，请重试');
        if (creating) promote(state, data.job);
        for (const field of fields(state.row)) {
          const key = field.name;
          if (!creating && !Object.hasOwn(sent, key)) continue;
          state.saved[key] = data.job[key];
          if (creating) {
            // A creation retry may return an already saved row: keep newer local input.
            if (field.value === sent[key] && field.value !== data.job[key]) state.pending[key] = field.value;
          } else if (Object.hasOwn(sent, key) && field.value === sent[key]) {
            field.value = data.job[key];
          }
        }
        state.error = false;
      } catch (error) {
        state.pending = { ...sent, ...state.pending };
        state.error = true;
        message(state, `保存失败：${error.message}`, true, true);
        return false;
      }
    }
    message(state, dirty(state) ? '' : '已保存');
    return true;
  }
  function save(state) {
    if (state.running) return state.running;
    state.running = drain(state).finally(() => { state.running = null; });
    return state.running;
  }
  function queue(state, field) {
    if (field.value === state.saved[field.name] && !state.running && !state.error) return;
    state.pending[field.name] = field.value;
    state.error = false;
    void save(state);
  }
  async function flushRow(state) {
    // Capture an active text field as well as changes waiting behind the current write.
    for (const field of fields(state.row)) {
      if (field.value !== state.saved[field.name]) state.pending[field.name] = field.value;
    }
    if (!Object.keys(state.pending).length && !state.running) return true;
    if (state.error) return false;
    if (!state.id) {
      const input = values(state.row);
      if (!input.company.trim() || !input.title.trim()) {
        message(state, '请填写公司与岗位后再离开', true);
        return false;
      }
    }
    const ok = await save(state);
    return ok && !dirty(state);
  }
  async function flushAll() {
    const results = await Promise.all([...states.values()].map(async state => {
      const ok = await flushRow(state);
      if (state.recording) await state.recording;
      return ok;
    }));
    if (results.every(Boolean)) return true;
    const failed = [...states.values()].find(state => state.error || dirty(state));
    failed?.row.querySelector('[data-autosave-field]')?.focus();
    return false;
  }
  async function recordSnapshot(state, form) {
    if (state.recording) return;
    const button = form.querySelector('button');
    button.disabled = true;
    state.recording = (async () => {
      if (!await flushRow(state)) return;
      message(state, '记录中');
      try {
        const data = await send(form.action, 'POST', new FormData(form));
        const area = state.row.querySelector('[data-snapshot-link]');
        const link = document.createElement('a');
        link.href = data.snapshot.url;
        link.textContent = data.snapshot.title;
        const revision = document.createElement('small');
        revision.textContent = `r${data.snapshot.revision} · 只读快照`;
        area.replaceChildren(link, revision);
        message(state, '已保存');
      } catch (error) {
        message(state, `记录失败：${error.message}`, true);
      }
    })();
    try { await state.recording; }
    finally { state.recording = null; button.disabled = false; }
  }

  table.querySelectorAll('[data-career-row]').forEach(initialize);
  table.addEventListener('focusout', event => {
    const field = event.target.closest('[data-autosave-field]');
    if (field && !field.matches('select,[type="date"]')) queue(states.get(field.closest('[data-career-row]')), field);
  });
  table.addEventListener('change', event => {
    const field = event.target.closest('[data-autosave-field]');
    if (field?.matches('select,[type="date"]')) queue(states.get(field.closest('[data-career-row]')), field);
  });
  table.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.isComposing && event.target.matches('input[data-autosave-field]')) {
      event.preventDefault();
      event.target.blur();
    }
  });
  table.addEventListener('click', event => {
    const button = event.target.closest('[data-retry]');
    if (button) {
      const state = states.get(button.closest('[data-career-row]'));
      state.error = false;
      for (const field of fields(state.row)) {
        if (field.value !== state.saved[field.name]) state.pending[field.name] = field.value;
      }
      void save(state);
    }
  });
  document.addEventListener('submit', event => {
    const form = event.target;
    if (bypass.delete(form)) return;
    const record = form.closest('[data-record-form]');
    if (record) {
      event.preventDefault();
      void recordSnapshot(states.get(record.closest('[data-career-row]')), record);
      return;
    }
    if (![...states.values()].some(state => dirty(state) || state.running || state.recording || state.error)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (navigating) return;
    navigating = true;
    const submitter = event.submitter;
    void flushAll().then(ok => {
      navigating = false;
      if (ok) {
        bypass.add(form);
        form.requestSubmit(submitter);
      }
    });
  }, true);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
        event.shiftKey || event.altKey || link.target === '_blank') return;
    if (link.getAttribute('href').startsWith('#')) {
      if (link.hash === location.hash) openTarget();
      return;
    }
    if (![...states.values()].some(state => dirty(state) || state.running || state.recording || state.error)) return;
    event.preventDefault();
    if (navigating) return;
    navigating = true;
    void flushAll().then(ok => {
      navigating = false;
      if (ok) location.assign(link.href);
    });
  });
  const editId = new URLSearchParams(location.search).get('edit');
  if (editId) document.getElementById(`job-${editId}`)?.querySelector('[data-autosave-field]')?.focus();
})();
