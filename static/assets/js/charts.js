(() => {
  document.querySelectorAll('[data-chart-switch]').forEach(group => {
    const controls = group.querySelector('.charts-switch');
    if (!controls) return;
    const buttons = [...controls.querySelectorAll('[data-chart-target]')];
    const panels = [...group.querySelectorAll('[data-chart-panel]')];
    if (!buttons.length || buttons.some(button => !panels.some(panel => panel.id === button.dataset.chartTarget))) return;

    function activate(button) {
      buttons.forEach(item => {
        item.setAttribute('aria-pressed', String(item === button));
      });
      panels.forEach(panel => {
        panel.hidden = panel.id !== button.dataset.chartTarget;
      });
    }

    controls.hidden = false;
    group.classList.add('charts-enhanced');
    buttons.forEach(button => {
      button.setAttribute('aria-controls', button.dataset.chartTarget);
      button.addEventListener('click', () => activate(button));
    });
    activate(buttons.find(button => button.dataset.chartTarget === group.dataset.activePanel) || buttons[0]);
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
