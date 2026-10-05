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
})();
