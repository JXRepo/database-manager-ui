(() => {
  'use strict';

  const temporaryLink = document.getElementById('study-analysis-save-collection');
  temporaryLink?.addEventListener('click', () => {
    const panel = document.getElementById('collection-save-panel');
    if (panel) panel.open = true;
  });

  const section = document.getElementById('study-analyses');
  const form = document.getElementById('study-analysis-form');
  if (!section || !form) return;
  const feedback = document.getElementById('study-analysis-feedback');
  const recovery = document.getElementById('study-analysis-recovery');
  const acknowledge = document.getElementById('study-analysis-acknowledge');
  const dirty = document.getElementById('study-analysis-dirty');
  const initialText = {
    title: JSON.parse(document.getElementById('study-analysis-saved-title').textContent),
    notes: JSON.parse(document.getElementById('study-analysis-saved-notes').textContent),
  };
  let baseline = null;
  try {
    baseline = JSON.parse(document.getElementById('study-analysis-baseline').textContent);
    if (typeof baseline === 'string') baseline = JSON.parse(baseline);
  } catch { /* Unavailable source records intentionally have no baseline */ }
  let pending = false;
  let conflicted = false;
  let unconfirmed = false;
  let confirmedNavigation = false;
  let controller;
  const mutations = [...section.querySelectorAll('[data-study-analysis-mutation]')];
  const buttons = mutations.flatMap(item => [...item.querySelectorAll('button[type="submit"]')]);
  const initiallyDisabled = new Set(buttons.filter(button => button.disabled));
  const stableState = value => JSON.stringify(Object.fromEntries(Object.entries(value || {})
    .filter(([key]) => key !== 'analysis' && key !== 'analyses_page').sort(([a], [b]) => a.localeCompare(b))));

  const refreshDirty = () => {
    if (!dirty) return;
    let changed = form.elements.title.value !== initialText.title || form.elements.notes.value !== initialText.notes;
    if (section.dataset.activeId && baseline && typeof baseline === 'object') {
      try { changed = changed || stableState(JSON.parse(form.elements.workspace_state.value)) !== stableState(baseline); }
      catch { changed = true; }
    } else if (section.dataset.activeId) changed = changed || !dirty.hidden;
    dirty.hidden = !changed;
  };
  const refreshButtons = () => {
    for (const button of buttons) {
      const staleAction = conflicted && (button.value === 'update' || button.closest('[data-study-analysis-mutation="delete"]'));
      button.disabled = initiallyDisabled.has(button) || pending || confirmedNavigation || unconfirmed || Boolean(staleAction);
    }
  };
  const announce = (message, warning = false) => {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.classList.toggle('is-warning', warning);
  };
  form.addEventListener('input', refreshDirty);
  window.addEventListener('study:state-change', () => queueMicrotask(refreshDirty));
  window.addEventListener('study:state-synced', refreshDirty);
  acknowledge.addEventListener('click', () => {
    unconfirmed = false;
    acknowledge.hidden = true;
    announce('Your entered values are still here. Save only if the earlier change was not applied.');
    refreshButtons();
  });
  if (location.hash === '#study-analyses') section.open = true;
  window.addEventListener('hashchange', () => { if (location.hash === '#study-analyses') section.open = true; });

  for (const submittedForm of mutations) submittedForm.addEventListener('submit', async event => {
    event.preventDefault();
    const intent = event.submitter?.value || (section.dataset.activeId ? 'update' : 'create');
    if (pending || unconfirmed || (conflicted && (intent === 'update' || submittedForm.dataset.studyAnalysisMutation === 'delete'))) return;
    pending = true;
    refreshButtons();
    section.open = true;
    announce(submittedForm === form ? 'Saving analysis…' : 'Deleting saved analysis…');
    recovery.hidden = true;
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    let sent = false;
    try {
      if (window.StudyState) await window.StudyState.flush();
      const body = new FormData(submittedForm);
      if (submittedForm === form) body.set('intent', intent);
      sent = true;
      const response = await fetch(submittedForm.action, {
        method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}, signal: controller.signal,
      });
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Unexpected response');
      const result = await response.json();
      if (response.ok && result.ok && result.redirect_url) {
        const destination = new URL(result.redirect_url, location.href);
        if (destination.origin !== location.origin) throw new Error('Invalid destination');
        confirmedNavigation = true;
        location.assign(destination.href);
        return;
      }
      const errors = [];
      for (const values of Object.values(result.errors || {})) {
        for (const value of Array.isArray(values) ? values : [values]) errors.push(typeof value === 'string' ? value : value.message);
      }
      announce([...new Set([result.error, ...errors].filter(Boolean))].join(' ') || 'The analysis could not be saved. Check your entries and selected records.', true);
      if (response.status === 409) {
        conflicted = true;
        recovery.hidden = false;
        acknowledge.hidden = true;
      }
    } catch {
      if (sent) {
        unconfirmed = true;
        announce('The change could not be confirmed. Check saved analyses before another save. Your entered name and notes are kept here.', true);
        recovery.hidden = false;
        acknowledge.hidden = false;
      } else {
        announce('The current view could not be confirmed, so this analysis was not submitted. Your entries are kept. Try saving again when the connection is available.', true);
      }
    } finally {
      clearTimeout(timeout);
      pending = false;
      controller = null;
      refreshButtons();
    }
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    confirmedNavigation = false;
    pending = false;
    refreshButtons();
    refreshDirty();
  });
  window.addEventListener('beforeunload', event => {
    if (confirmedNavigation || (form.elements.title.value === initialText.title && form.elements.notes.value === initialText.notes)) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('pagehide', () => controller?.abort());
  refreshDirty();
})();
