(() => {
  const page = document.querySelector('.charts-page');
  if (!page) return;

  const scopeForm = page.querySelector('.charts-scope-form');
  scopeForm?.addEventListener('change', () => {
    const scope = scopeForm.elements.namedItem('scope');
    const privateOption = scopeForm.elements.namedItem('include_private');
    if (privateOption) privateOption.disabled = scope.value !== 'mine';
    scopeForm.requestSubmit();
  });
  page.classList.add('charts-js');

  const openRecords = () => {
    const summary = document.getElementById('objects');
    const details = summary?.closest('details');
    if (details) {
      details.open = true;
      summary.scrollIntoView({block: 'start'});
    }
  };
  page.addEventListener('click', event => {
    if (event.target.closest('a[href="#objects"]')) openRecords();
  });
  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#objects') openRecords();
  });
  if (window.location.hash === '#objects') openRecords();
})();
