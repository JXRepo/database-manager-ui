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

  const filterMenus = [...page.querySelectorAll('.charts-filter-menu')];
  filterMenus.forEach(menu => {
    menu.addEventListener('toggle', () => {
      if (!menu.open) return;
      for (const other of filterMenus) {
        if (other !== menu) other.open = false;
      }
    });
    menu.addEventListener('change', () => {
      const selected = [...menu.querySelectorAll('input:checked')];
      let label = 'All';
      if (selected.length === 1) {
        label = selected[0].closest('label').textContent.trim();
      } else if (selected.length) {
        label = `${selected.length} selected`;
      }
      menu.querySelector('[data-filter-summary]').textContent = label;
      menu.querySelector('summary').title = label;
      menu.classList.toggle('has-selection', selected.length > 0);
    });
  });
  document.addEventListener('click', event => {
    for (const menu of filterMenus) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });
  page.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const menu = event.target.closest('.charts-filter-menu');
    if (menu?.open) {
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });

  if (window.location.hash === '#objects') {
    const summary = document.getElementById('objects');
    const details = summary?.closest('details');
    if (details) {
      details.open = true;
      summary.scrollIntoView({block: 'start'});
    }
  }
})();
