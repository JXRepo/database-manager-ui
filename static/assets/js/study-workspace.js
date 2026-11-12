(() => {
  'use strict';

  const workspace = document.getElementById('study-workspace');
  if (!workspace) return;
  const browser = document.getElementById('study-member-browser');
  const toggle = document.getElementById('study-browser-toggle');
  const query = document.getElementById('study-member-query');
  if (!browser || !toggle || !query) return;
  const storageKey = `study-browser:${location.pathname}`;

  const showBrowser = (open, remember = true) => {
    browser.hidden = !open;
    workspace.classList.toggle('is-browser-collapsed', !open);
    toggle.setAttribute('aria-expanded', String(open));
    if (remember) {
      try { sessionStorage.setItem(storageKey, open ? 'open' : 'closed'); } catch { /* Presentation remains usable without storage */ }
    }
  };
  let open = Boolean(query.value) || (workspace.dataset.panel === 'compare' && Number(workspace.dataset.selectionCount) < 2);
  try {
    const previous = sessionStorage.getItem(storageKey);
    if (previous) open = previous === 'open';
  } catch { /* Use the current view's default when browser storage is unavailable */ }
  showBrowser(open, false);
  toggle.hidden = false;
  toggle.addEventListener('click', () => showBrowser(browser.hidden));
  document.getElementById('study-compare-link').addEventListener('click', event => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || Number(workspace.dataset.selectionCount) < 2) return;
    try { sessionStorage.setItem(storageKey, 'closed'); } catch { /* The comparison remains available with its browser open */ }
  });
  for (const link of workspace.querySelectorAll('.study-browse-link')) {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      showBrowser(true);
      query.focus();
      query.scrollIntoView({block: 'nearest'});
    });
  }

  const columnNavigation = document.getElementById('study-column-navigation');
  const matrix = workspace.querySelector('.study-comparison-scroll');
  if (columnNavigation && matrix) {
    const left = document.getElementById('study-columns-left');
    const right = document.getElementById('study-columns-right');
    const refreshColumns = () => {
      const maximum = matrix.scrollWidth - matrix.clientWidth;
      columnNavigation.hidden = maximum < 2;
      left.disabled = matrix.scrollLeft <= 1;
      right.disabled = matrix.scrollLeft >= maximum - 1;
    };
    left.hidden = right.hidden = false;
    left.addEventListener('click', () => { matrix.scrollLeft -= 200; });
    right.addEventListener('click', () => { matrix.scrollLeft += 200; });
    matrix.addEventListener('scroll', refreshColumns, {passive: true});
    if ('ResizeObserver' in window) new ResizeObserver(refreshColumns).observe(matrix);
    else window.addEventListener('resize', refreshColumns);
    refreshColumns();
  }
})();
