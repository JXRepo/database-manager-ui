(() => {
  const page = document.querySelector('.charts-page');
  if (!page) return;
  page.querySelectorAll('form[data-auto-submit]').forEach(form => {
    form.addEventListener('change', () => {
      const scope = form.elements.namedItem('scope');
      const privateOption = form.elements.namedItem('include_private');
      if (scope && privateOption) privateOption.disabled = scope.value !== 'mine';
      form.requestSubmit();
    });
  });
  page.classList.add('charts-js');

  if (window.location.hash === '#objects') {
    const summary = document.getElementById('objects');
    const details = summary?.closest('details');
    if (details) {
      details.open = true;
      summary.scrollIntoView({block: 'start'});
    }
  }
})();
