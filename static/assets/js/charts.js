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

  const tooltip = document.createElement('div');
  tooltip.id = 'charts-tooltip';
  tooltip.className = 'charts-tooltip';
  tooltip.setAttribute('role', 'tooltip');
  tooltip.hidden = true;
  document.body.append(tooltip);

  const targets = page.querySelectorAll('.charts-dashboard-grid [role="img"], .charts-box-svg, '
    + '.charts-dashboard-grid .charts-svg-label[title], .charts-coverage-link[title], .charts-context-label[title]');
  for (const target of targets) {
    const svgTitle = target.querySelector(':scope > title');
    const description = target.getAttribute('title') || svgTitle?.textContent || target.getAttribute('aria-label');
    if (!description?.trim()) continue;
    target.dataset.chartTooltip = description.trim();
    target.removeAttribute('title');
    svgTitle?.remove();
  }

  let activeTarget = null;
  const tooltipTarget = element => element instanceof Element ? element.closest('[data-chart-tooltip]') : null;

  function hideTooltip() {
    tooltip.hidden = true;
    activeTarget?.removeAttribute('aria-describedby');
    activeTarget = null;
  }

  function showTooltip(target, x, y) {
    if (activeTarget !== target) {
      hideTooltip();
      activeTarget = target;
      tooltip.textContent = target.dataset.chartTooltip;
      target.setAttribute('aria-describedby', tooltip.id);
    }
    tooltip.hidden = false;
    const bounds = tooltip.getBoundingClientRect();
    const left = Math.max(12, Math.min(x + 14, innerWidth - bounds.width - 12));
    const top = y + bounds.height + 14 <= innerHeight - 12 ? y + 14 : y - bounds.height - 14;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(12, top)}px`;
  }

  function showPointerTooltip(event) {
    const target = tooltipTarget(event.target);
    if (target) showTooltip(target, event.clientX, event.clientY);
    else hideTooltip();
  }

  page.addEventListener('pointerover', showPointerTooltip);
  page.addEventListener('pointermove', showPointerTooltip);
  page.addEventListener('pointerout', event => {
    if (tooltipTarget(event.relatedTarget) !== activeTarget) hideTooltip();
  });
  page.addEventListener('focusin', event => {
    const target = tooltipTarget(event.target);
    if (!target) return;
    const bounds = target.getBoundingClientRect();
    showTooltip(target, bounds.left + bounds.width / 2, bounds.bottom);
  });
  page.addEventListener('focusout', hideTooltip);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') hideTooltip();
  });
  window.addEventListener('scroll', hideTooltip, true);
  window.addEventListener('resize', hideTooltip);
  window.addEventListener('blur', hideTooltip);
  page.classList.add('charts-js');
})();
