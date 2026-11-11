(() => {
  'use strict';

  const graph = document.getElementById('detail-relationships');
  if (!graph) return;
  const nodes = Array.from(graph.querySelectorAll('[data-node]'));
  const panels = Array.from(graph.querySelectorAll('.relationship-info-item'));
  const edges = Array.from(graph.querySelectorAll('.relationship-edge'));
  if (!nodes.length) return;

  const select = node => {
    for (const item of nodes) {
      if (item === node) item.setAttribute('aria-current', 'true');
      else item.removeAttribute('aria-current');
    }
    for (const panel of panels) panel.hidden = panel.id !== `${node.dataset.node}-info`;
    for (const edge of edges) {
      edge.classList.toggle('is-active',
        edge.dataset.source === node.dataset.node || edge.dataset.target === node.dataset.node);
    }
    graph.querySelector('.relationship-info').scrollTop = 0;
  };

  for (const node of nodes) {
    node.setAttribute('aria-controls', `${node.dataset.node}-info`);
    node.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      select(node);
    });
  }
  graph.classList.add('is-interactive');
  const linked = nodes.find(node => node.getAttribute('href') === window.location.hash);
  select(linked || nodes[0]);
  const initial = linked || nodes[0];
  const viewport = graph.querySelector('.relationship-viewport');
  const bounds = viewport.getBoundingClientRect();
  const nodeBounds = initial.getBoundingClientRect();
  viewport.scrollLeft += nodeBounds.left + nodeBounds.width / 2 - bounds.left - bounds.width / 2;
  viewport.scrollTop += nodeBounds.top + nodeBounds.height / 2 - bounds.top - bounds.height / 2;
})();
