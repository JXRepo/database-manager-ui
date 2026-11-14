(() => {
  'use strict';

  const configuration = document.getElementById('study-state-data');
  if (!configuration) return;
  const config = JSON.parse(configuration.textContent);
  const allowed = new Set(config.allowed);
  const dynamic = new Set(['detail_status', 'detail_q', 'detail_focus', 'curve_component', 'curve_strain', 'curve_view', 'curve_open']);
  let state = {...config.state};
  let generation = 0;
  let signedGeneration = 0;
  let pending = null;
  let controller = null;
  let lastError = null;
  const errorBox = document.getElementById('study-state-error');
  const linkIntents = new WeakMap();
  const formIntents = new WeakMap();
  const knownTokens = new Map([[config.token, 'current']]);
  for (const [view, token] of Object.entries(config.variants || {})) knownTokens.set(token, view);

  function intentFor(values) {
    const intent = {};
    for (const key of allowed) {
      const value = values.get(key);
      if (value !== (config.state[key] ?? null)) intent[key] = value;
    }
    return intent;
  }

  for (const link of document.querySelectorAll('a[href]')) {
    const url = new URL(link.href, location.href);
    if (url.origin === location.origin && url.pathname === config.workspace) linkIntents.set(link, intentFor(url.searchParams));
  }
  for (const form of document.querySelectorAll('form[method="get"]')) {
    const url = new URL(form.action, location.href);
    if (url.origin !== location.origin || url.pathname !== config.workspace) continue;
    const values = new URLSearchParams();
    for (const input of form.querySelectorAll('input[type="hidden"][name]')) values.set(input.name, input.value);
    formIntents.set(form, intentFor(values));
  }

  function announceError() {
    if (!errorBox) return;
    errorBox.replaceChildren(document.createTextNode('The current view could not be preserved. Your entries are still here. '));
    const retry = document.createElement('button');
    retry.type = 'button'; retry.className = 'btn btn-outline-secondary btn-sm'; retry.textContent = 'Retry view links';
    retry.addEventListener('click', () => { lastError = null; sync().catch(() => {}); });
    errorBox.append(retry);
    errorBox.hidden = false;
  }

  function patchViews() {
    const current = new URL(location.href);
    current.pathname = config.workspace;
    for (const key of allowed) current.searchParams.delete(key);
    for (const [key, value] of Object.entries(state)) current.searchParams.set(key, value);
    history.replaceState(history.state, '', current);
    const saved = {...state};
    delete saved.analysis; delete saved.analyses_page;
    for (const input of document.querySelectorAll('input[name="workspace_state"]')) input.value = JSON.stringify(saved);
    for (const link of document.querySelectorAll('a[href]')) {
      const intent = linkIntents.get(link);
      if (!intent) continue;
      const url = new URL(link.href, location.href);
      for (const key of allowed) url.searchParams.delete(key);
      for (const [key, value] of Object.entries({...state, ...intent})) {
        if (value !== null && value !== undefined) url.searchParams.set(key, value);
      }
      link.href = url.href;
    }
    for (const form of document.querySelectorAll('form[method="get"]')) {
      const intent = formIntents.get(form);
      if (!intent) continue;
      const values = {...state, ...intent};
      for (const key of dynamic) {
        const fields = [...form.elements].filter(input => input.name === key);
        if (fields.some(input => input.type !== 'hidden')) continue;
        const value = key === 'detail_status' && fields.length ? (values[key] || 'all') : values[key];
        if (value === null || value === undefined) { fields.forEach(input => input.remove()); continue; }
        let field = fields[0];
        if (!field) { field = document.createElement('input'); field.type = 'hidden'; field.name = key; form.append(field); }
        field.value = value;
      }
    }
  }

  function applyToken(result) {
    const tokens = {current: result.graph_context, ...result.variants};
    for (const link of document.querySelectorAll('a[href]')) {
      const url = new URL(link.href, location.href);
      if (url.origin !== location.origin || !url.searchParams.has('graph_context')) continue;
      const kind = knownTokens.get(url.searchParams.get('graph_context')) || 'current';
      url.searchParams.set('graph_context', tokens[kind]);
      link.href = url.href;
    }
    for (const input of document.querySelectorAll('input[name="graph_context"]')) {
      input.value = tokens[knownTokens.get(input.value) || 'current'];
    }
    for (const [kind, token] of Object.entries(tokens)) knownTokens.set(token, kind);
    window.dispatchEvent(new CustomEvent('study:state-synced', {detail: {...state}}));
  }

  function sync() {
    if (signedGeneration === generation) return Promise.resolve();
    if (pending) return pending;
    const requestedGeneration = generation;
    const url = new URL(config.endpoint, location.href);
    url.search = new URLSearchParams(state).toString();
    const requestController = new AbortController();
    controller = requestController;
    const signal = requestController.signal;
    const timeout = setTimeout(() => requestController.abort(), 15000);
    const task = fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}, signal})
      .then(async response => {
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('View links unavailable');
        const result = await response.json();
        if (!result.graph_context || !result.variants) throw new Error('View links unavailable');
        if (requestedGeneration !== generation) return;
        applyToken(result);
        signedGeneration = requestedGeneration;
        lastError = null;
        if (errorBox) errorBox.hidden = true;
      }).catch(error => {
        if (requestedGeneration === generation) { lastError = error; announceError(); throw error; }
      }).finally(() => {
        clearTimeout(timeout);
        if (pending === task) { pending = null; controller = null; }
      });
    pending = task;
    return task;
  }

  async function flush() {
    while (signedGeneration !== generation) {
      if (lastError && !pending) throw lastError;
      await sync();
    }
  }

  function update(changes) {
    let changed = false;
    for (const [key, value] of Object.entries(changes || {})) {
      if (!dynamic.has(key)) continue;
      const next = value === null || value === undefined || value === '' ? undefined : String(value);
      if (state[key] === next) continue;
      if (next === undefined) delete state[key]; else state[key] = next;
      changed = true;
    }
    if (!changed) return;
    generation += 1;
    lastError = null;
    controller?.abort(); pending = null;
    patchViews();
    sync().catch(() => {});
  }

  window.StudyState = {get: () => ({...state}), flush, update};
  window.addEventListener('study:state-change', event => update(event.detail));
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (!new URL(link.href, location.href).searchParams.has('graph_context') || signedGeneration === generation) return;
    event.preventDefault(); event.stopImmediatePropagation();
    flush().then(() => location.assign(link.href)).catch(() => announceError());
  }, true);
  const resubmitting = new WeakSet();
  document.addEventListener('submit', event => {
    const form = event.target;
    if (resubmitting.has(form)) { resubmitting.delete(form); return; }
    if (form.matches('[data-study-analysis-mutation]') || !form.querySelector('[name="graph_context"]') || signedGeneration === generation) return;
    event.preventDefault(); event.stopImmediatePropagation();
    const submitter = event.submitter;
    flush().then(() => { resubmitting.add(form); form.requestSubmit(submitter); }).catch(() => announceError());
  }, true);
  window.addEventListener('pagehide', () => controller?.abort());
})();
