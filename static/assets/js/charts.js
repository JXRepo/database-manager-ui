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

  page.addEventListener('click', event => {
    page.querySelectorAll('.charts-metrics details[open]').forEach(details => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  page.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const details = event.target.closest('.charts-metrics details[open]');
    if (!details) return;
    details.open = false;
    details.querySelector('summary').focus();
    event.preventDefault();
  });
})();
