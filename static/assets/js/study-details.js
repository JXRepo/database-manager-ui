(() => {
  'use strict';

  const section = document.getElementById('study-parameters');
  const form = document.getElementById('study-detail-search');
  const fieldTable = document.getElementById('study-parameter-fields');
  if (!section || !form || !fieldTable) return;

  const query = document.getElementById('study-detail-query');
  const rows = [...section.querySelectorAll('[data-parameter-row]')];
  const groups = [...section.querySelectorAll('[data-parameter-group]')];
  const filters = [...section.querySelectorAll('a[data-detail-status]')];
  const visibleCount = document.getElementById('study-detail-visible-count');
  const clear = document.getElementById('study-detail-clear');
  const empty = document.getElementById('study-detail-empty');
  const missingFocus = document.getElementById('study-detail-focus-missing');
  let status = section.dataset.detailStatus || 'all';

  function plainClick(event) {
    return event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
  }

  function publish(focus = null) {
    const changes = {
      detail_status: status === 'all' ? null : status,
      detail_q: query.value.trim() || null,
      detail_focus: focus,
    };
    window.dispatchEvent(new CustomEvent('study:state-change', {detail: changes}));
    const url = new URL(location.href);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    }
    url.hash = focus ? `study-parameter-${focus}` : 'study-parameter-fields';
    history.replaceState(history.state, '', url);
    for (const link of filters) {
      const destination = new URL(url);
      destination.searchParams.set('detail_status', link.dataset.detailStatus);
      destination.searchParams.delete('detail_focus');
      destination.hash = 'study-parameter-fields';
      link.href = destination.href;
    }
    for (const link of section.querySelectorAll('[data-detail-jump]')) {
      const destination = new URL(url);
      destination.searchParams.delete('detail_status');
      destination.searchParams.delete('detail_q');
      destination.searchParams.set('detail_focus', link.dataset.detailJump.replace('study-parameter-', ''));
      destination.hash = link.dataset.detailJump;
      link.href = destination.href;
    }
  }

  function filterRows({notify = true, focus = null} = {}) {
    const terms = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const visibleGroups = new Set();
    let count = 0;
    for (const row of rows) {
      const matches = (status === 'all' || row.dataset.state === status)
        && terms.every(term => row.dataset.parameterSearch.includes(term));
      row.hidden = !matches;
      row.classList.toggle('is-field-focused', row.dataset.parameterRow === focus);
      if (matches) {
        count += 1;
        visibleGroups.add(row.dataset.parameterGroupKey);
      }
    }
    for (const group of groups) group.hidden = !visibleGroups.has(group.dataset.parameterGroup);
    for (const link of filters) {
      if (link.dataset.detailStatus === status) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
    form.elements.detail_status.value = status;
    section.dataset.detailStatus = status;
    clear.hidden = status === 'all' && !query.value.trim();
    empty.hidden = count > 0;
    visibleCount.textContent = `${count} of ${rows.length} fields shown`;
    if (missingFocus && notify) missingFocus.hidden = true;
    if (notify) {
      fieldTable.open = true;
      publish(focus);
    }
  }

  function clearFilters(event) {
    if (event && !plainClick(event)) return;
    event?.preventDefault();
    status = 'all';
    query.value = '';
    filterRows();
    query.focus({preventScroll: true});
  }

  function revealField(id, notify = true) {
    const row = rows.find(item => item.id === id);
    if (!row) return;
    status = 'all';
    query.value = '';
    fieldTable.open = true;
    filterRows({notify, focus: row.dataset.parameterRow});
    requestAnimationFrame(() => {
      row.scrollIntoView({block: 'center', inline: 'nearest'});
      row.focus({preventScroll: true});
    });
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    query.value = query.value.trim();
    filterRows();
  });
  query.addEventListener('input', () => filterRows());
  for (const link of filters) {
    link.addEventListener('click', event => {
      if (!plainClick(event)) return;
      event.preventDefault();
      status = link.dataset.detailStatus;
      filterRows();
    });
  }
  clear.addEventListener('click', clearFilters);
  for (const link of section.querySelectorAll('[data-detail-clear]')) link.addEventListener('click', clearFilters);
  for (const link of section.querySelectorAll('[data-detail-jump]')) {
    link.addEventListener('click', event => {
      if (!plainClick(event)) return;
      event.preventDefault();
      revealField(link.dataset.detailJump);
    });
  }
  if (section.dataset.detailFocus) revealField(section.dataset.detailFocus, false);
})();
