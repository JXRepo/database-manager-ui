(() => {
  'use strict';

  const graph = document.getElementById('detail-relationships');
  if (!graph) return;
  const svg = graph.querySelector('.relationship-svg');
  if (!svg) return;
  const viewport = graph.querySelector('.relationship-viewport');
  const nodes = Array.from(svg.querySelectorAll('[data-node]'));
  const byId = new Map(nodes.map(node => [node.dataset.node, node]));
  const panels = Array.from(graph.querySelectorAll('.relationship-info-item'));
  const edges = Array.from(svg.querySelectorAll('.relationship-edge'));
  const results = Array.from(graph.querySelectorAll('[data-result]'));
  const info = graph.querySelector('.relationship-info');
  const query = graph.querySelector('#graph-node-query');
  const kind = graph.querySelector('#graph-node-kind');
  const status = graph.querySelector('#graph-status');
  const tabs = Array.from(graph.querySelectorAll('[role="tab"]'));
  const layouts = JSON.parse(document.getElementById('graph-layouts').textContent);
  let view = graph.dataset.view;
  let width = svg.viewBox.baseVal.width;
  let height = svg.viewBox.baseVal.height;
  let selected = nodes[0];
  let zoom = 1;
  let focused = false;
  let fitted = false;

  const announce = message => {
    status.hidden = !message;
    status.textContent = message;
  };
  const showTab = index => {
    tabs.forEach((tab, position) => {
      tab.setAttribute('aria-selected', String(position === index));
      tab.tabIndex = position === index ? 0 : -1;
      graph.querySelector(`#${tab.getAttribute('aria-controls')}`).hidden = position !== index;
    });
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => showTab(index));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index;
      showTab(next);
      tabs[next].focus();
    });
  });

  const connectedIds = () => {
    const ids = new Set([selected.dataset.node]);
    edges.forEach(edge => {
      if (edge.dataset.source === selected.dataset.node) ids.add(edge.dataset.target);
      if (edge.dataset.target === selected.dataset.node) ids.add(edge.dataset.source);
    });
    return ids;
  };
  const emphasize = () => {
    const connected = connectedIds();
    for (const node of nodes) node.classList.toggle('is-muted', focused && !connected.has(node.dataset.node));
    for (const edge of edges) {
      const active = edge.dataset.source === selected.dataset.node || edge.dataset.target === selected.dataset.node;
      edge.classList.toggle('is-active', active);
      edge.classList.toggle('is-muted', focused && !active);
    }
  };
  const minimumZoom = () => Math.min(.1, (viewport.clientWidth - 48) / width, (viewport.clientHeight - 48) / height);
  const setZoom = (value, anchor) => {
    const old = svg.getBoundingClientRect();
    const area = viewport.getBoundingClientRect();
    const point = anchor || {x: area.left + viewport.clientWidth / 2, y: area.top + viewport.clientHeight / 2};
    const x = (point.x - old.left) / zoom;
    const y = (point.y - old.top) / zoom;
    zoom = Math.min(2, Math.max(minimumZoom(), value));
    svg.style.width = `${width * zoom}px`;
    svg.style.height = `${height * zoom}px`;
    const next = svg.getBoundingClientRect();
    viewport.scrollLeft += next.left + x * zoom - point.x;
    viewport.scrollTop += next.top + y * zoom - point.y;
    graph.querySelector('#graph-zoom-reset').textContent = `${Math.round(zoom * 100)}%`;
    graph.querySelector('#graph-zoom-in').disabled = zoom >= 2;
    graph.querySelector('#graph-zoom-out').disabled = zoom <= minimumZoom();
    fitted = false;
  };
  const center = (x, y) => {
    const box = svg.getBoundingClientRect();
    const area = viewport.getBoundingClientRect();
    viewport.scrollLeft += box.left + x * zoom - area.left - viewport.clientWidth / 2;
    viewport.scrollTop += box.top + y * zoom - area.top - viewport.clientHeight / 2;
  };
  const nodePosition = node => {
    const transform = node.parentNode.transform.baseVal.getItem(0).matrix;
    const rect = node.querySelector('rect');
    return {x: transform.e, y: transform.f, width: rect.width.baseVal.value, height: rect.height.baseVal.value};
  };
  const centerSelected = (readable = true) => {
    const readableZoom = view === 'detailed' ? 1 : .75;
    if (readable && zoom < readableZoom) setZoom(readableZoom);
    const point = nodePosition(selected);
    center(point.x + point.width / 2, point.y + point.height / 2);
    fitted = false;
  };
  const fit = () => {
    let box = {x: 0, y: 0, width, height};
    if (focused) {
      const ids = connectedIds();
      const points = nodes.filter(node => ids.has(node.dataset.node)).map(nodePosition);
      const left = Math.min(...points.map(point => point.x));
      const top = Math.min(...points.map(point => point.y));
      box = {x: left, y: top, width: Math.max(...points.map(point => point.x + point.width)) - left,
        height: Math.max(...points.map(point => point.y + point.height)) - top};
    }
    setZoom(Math.min(1, (viewport.clientWidth - 48) / box.width, (viewport.clientHeight - 48) / box.height));
    center(box.x + box.width / 2, box.y + box.height / 2);
    fitted = true;
  };

  const setURLView = (url, mode) => {
    if (mode === 'detailed') url.searchParams.set('view', mode);
    else url.searchParams.delete('view');
  };
  const updateNavigation = () => {
    for (const link of document.querySelectorAll('[data-graph-url]')) {
      const url = new URL(link.href);
      setURLView(url, view);
      if (link.hasAttribute('data-keep-node') && url.searchParams.get('object') === graph.dataset.object) {
        url.hash = selected.getAttribute('href');
      }
      link.href = url.pathname + url.search + url.hash;
    }
    for (const link of graph.querySelectorAll('[data-graph-view]')) {
      const url = new URL(location.href);
      setURLView(url, link.dataset.graphView);
      url.hash = selected.getAttribute('href');
      link.href = url.pathname + url.search + url.hash;
      link.setAttribute('aria-pressed', String(view === link.dataset.graphView));
    }
    const form = document.querySelector('.graph-find-form');
    if (form) {
      form.elements.view.value = view;
      const action = new URL(form.action);
      action.hash = selected.getAttribute('href');
      form.action = action.pathname + action.hash;
    }
  };
  const showView = (mode, bookmark = true) => {
    const layout = layouts[mode];
    view = mode;
    graph.dataset.view = mode;
    graph.querySelector('#graph-link-fallback').hidden = true;
    width = layout.width;
    height = layout.height;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    for (const node of nodes) {
      const position = layout.positions[node.dataset.node];
      node.parentNode.setAttribute('transform', `translate(${position.x} ${position.y})`);
      node.querySelector('rect').setAttribute('height', position.height);
    }
    edges.forEach((edge, index) => edge.setAttribute('d', layout.paths[index]));
    if (bookmark) {
      const url = new URL(location.href);
      setURLView(url, mode);
      url.hash = selected.getAttribute('href');
      if (url.href !== location.href) history.pushState(null, '', url.pathname + url.search + url.hash);
    }
    setZoom(Math.max(.75, zoom));
    centerSelected();
    updateNavigation();
  };
  for (const link of graph.querySelectorAll('[data-graph-view]')) {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      if (view !== link.dataset.graphView) showView(link.dataset.graphView);
    });
    link.addEventListener('keydown', event => {
      if (event.key === ' ') { event.preventDefault(); link.click(); }
    });
  }

  const select = (node, {bookmark = true, move = true} = {}) => {
    selected = node;
    for (const item of nodes) {
      if (item === node) item.setAttribute('aria-current', 'true');
      else item.removeAttribute('aria-current');
    }
    for (const panel of panels) panel.hidden = panel.id !== `${node.dataset.node}-info`;
    for (const result of results) {
      const link = result.querySelector('a');
      if (result.dataset.result === node.dataset.node) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
    emphasize();
    showTab(0);
    info.scrollTop = 0;
    graph.querySelector('#graph-link-fallback').hidden = true;
    if (bookmark && location.hash !== node.getAttribute('href')) {
      history.pushState(null, '', node.getAttribute('href'));
    }
    updateNavigation();
    if (move) centerSelected();
  };
  const nodeFromHash = () => nodes.find(node => [node.getAttribute('href'), `#${node.dataset.legacyNode}-info`].includes(location.hash));
  for (const node of nodes) node.setAttribute('aria-controls', `${node.dataset.node}-info`);
  graph.addEventListener('click', event => {
    const link = event.target.closest('.relationship-node, .graph-node-link');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const node = byId.get(link.getAttribute('href').slice(1, -5));
    if (!node) return;
    event.preventDefault();
    select(node);
    node.focus({preventScroll: true});
  });
  const restore = () => {
    const requestedViews = new URL(location.href).searchParams.getAll('view');
    const mode = requestedViews.length === 1 && requestedViews[0] === 'detailed' ? 'detailed' : 'compact';
    if (view !== mode) showView(mode, false);
    const node = nodeFromHash() || nodes[0];
    if (selected !== node) select(node, {bookmark: false});
  };
  window.addEventListener('popstate', restore);
  window.addEventListener('hashchange', restore);

  const words = text => text.normalize('NFKC').toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || [];
  const searchWords = new Map(nodes.map((node, index) => [node.dataset.node, new Set(words(
    `${node.getAttribute('aria-label')} ${Array.from(panels[index].querySelectorAll('dt, dd')).map(item => item.textContent).join(' ')}`,
  ))]));
  const search = () => {
    const terms = words(query.value);
    let count = 0;
    for (const result of results) {
      const id = result.dataset.result;
      const match = (!kind.value || byId.get(id).dataset.kind === kind.value)
        && terms.every(term => searchWords.get(id).has(term));
      result.hidden = !match;
      if (match) count++;
    }
    graph.querySelector('#graph-node-count').textContent = `${count} of ${nodes.length} nodes`;
    graph.querySelector('#graph-no-nodes').hidden = count > 0;
  };
  query.addEventListener('input', search);
  kind.addEventListener('change', search);
  graph.querySelector('#graph-clear-search').addEventListener('click', () => {
    query.value = '';
    kind.value = '';
    search();
    query.focus();
  });
  query.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      results.find(result => !result.hidden)?.querySelector('a').click();
    }
  });

  graph.querySelector('#graph-zoom-in').addEventListener('click', () => setZoom(zoom * 1.25));
  graph.querySelector('#graph-zoom-out').addEventListener('click', () => setZoom(zoom / 1.25));
  graph.querySelector('#graph-zoom-reset').addEventListener('click', () => setZoom(1));
  graph.querySelector('#graph-fit').addEventListener('click', fit);
  graph.querySelector('#graph-center').addEventListener('click', () => centerSelected());
  graph.querySelector('#graph-focus').addEventListener('click', event => {
    focused = !focused;
    event.currentTarget.setAttribute('aria-pressed', String(focused));
    emphasize();
    centerSelected();
  });
  viewport.addEventListener('wheel', event => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    setZoom(zoom * Math.exp(-Math.max(-100, Math.min(100, event.deltaY)) * .005), {x: event.clientX, y: event.clientY});
  }, {passive: false});
  viewport.addEventListener('keydown', event => {
    if (event.target !== viewport) return;
    if (['+', '=', '-', '0', '/'].includes(event.key)) event.preventDefault();
    if (['+', '='].includes(event.key)) setZoom(zoom * 1.25);
    if (event.key === '-') setZoom(zoom / 1.25);
    if (event.key === '0') fit();
    if (event.key === '/') { showTab(1); query.focus(); }
  });
  let drag = null;
  viewport.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('[data-node]')) return;
    drag = {x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop};
    viewport.setPointerCapture(event.pointerId);
    viewport.focus({preventScroll: true});
    viewport.classList.add('is-dragging');
  });
  viewport.addEventListener('pointermove', event => {
    if (!drag) return;
    viewport.scrollLeft = drag.left + drag.x - event.clientX;
    viewport.scrollTop = drag.top + drag.y - event.clientY;
    fitted = false;
  });
  const stopDragging = () => { drag = null; viewport.classList.remove('is-dragging'); };
  viewport.addEventListener('pointerup', stopDragging);
  viewport.addEventListener('pointercancel', stopDragging);
  viewport.addEventListener('lostpointercapture', stopDragging);

  graph.querySelector('#graph-copy-link').addEventListener('click', async () => {
    const url = new URL(location.href);
    if (graph.dataset.object) {
      url.search = new URLSearchParams(url.searchParams.get('tab') === 'graph'
        ? {tab: 'graph'} : {object: graph.dataset.object}).toString();
    }
    setURLView(url, view);
    url.hash = selected.getAttribute('href');
    const accessNotice = graph.dataset.temporary
      ? 'Save this selection as a collection to keep a lasting link.'
      : graph.dataset.collection
        ? 'This collection is private to your account.'
        : 'The recipient must have access to this data object.';
    try {
      await navigator.clipboard.writeText(url.href);
      announce(`Node link copied. ${accessNotice}`);
    } catch {
      const fallback = graph.querySelector('#graph-link-fallback');
      fallback.value = url.href;
      fallback.hidden = false;
      fallback.focus();
      fallback.select();
      announce(`Copy the selected link. ${accessNotice}`);
    }
  });

  // Export plain SVG text instead of HTML foreignObject labels so PNG and standalone SVG render consistently.
  const exportSVG = () => {
    const clone = svg.cloneNode(true);
    const ns = 'http://www.w3.org/2000/svg';
    clone.setAttribute('xmlns', ns);
    clone.removeAttribute('style');
    clone.removeAttribute('class');
    clone.removeAttribute('aria-labelledby');
    clone.style.fontFamily = 'Arial, sans-serif';
    const background = document.createElementNS(ns, 'rect');
    background.setAttribute('width', width);
    background.setAttribute('height', height);
    background.setAttribute('fill', '#fff');
    clone.prepend(background);
    const title = document.createElementNS(ns, 'title');
    title.textContent = `Relationships: ${nodes[0].querySelector('.relationship-label').textContent}`;
    clone.prepend(title);
    clone.querySelectorAll('.relationship-edge').forEach(edge => {
      edge.removeAttribute('class');
      edge.setAttribute('fill', 'none');
      edge.setAttribute('stroke', '#a3afc2');
      edge.setAttribute('stroke-width', '1.5');
    });
    const colors = {record: ['#edf3ff', '#90ace0'], collection: ['#edf3ff', '#90ace0'],
      reference: ['#f8f4fc', '#d6c8e4'], missing: ['#f5f6f8', '#c9d1dc'], phase: ['#f2f8f5', '#bbd9c9'],
      model: ['#f8f4fc', '#d6c8e4'], output: ['#fff8ee', '#e8d6b9'], loading: ['#eef8fa', '#b8dbe0']};
    const measure = document.createElement('canvas').getContext('2d');
    const prefix = (text, suffix = '') => {
      const characters = Array.from(text.slice(0, 1024));
      let low = 0;
      let high = Math.min(characters.length, 256);
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (measure.measureText(characters.slice(0, middle).join('') + suffix).width <= 204) low = middle;
        else high = middle - 1;
      }
      return characters.slice(0, low).join('');
    };
    for (const node of clone.querySelectorAll('[data-node]')) {
      const [fill, stroke] = colors[node.dataset.kind] || ['#fff', '#d8e1ec'];
      node.removeAttribute('class');
      node.removeAttribute('href');
      node.removeAttribute('aria-current');
      node.querySelector('rect').setAttribute('fill', fill);
      node.querySelector('rect').setAttribute('stroke', stroke);
      node.querySelector('rect').setAttribute('stroke-width', '1.5');
      const category = node.querySelector('text');
      category.setAttribute('fill', '#68778d');
      category.setAttribute('font-size', '11');
      node.querySelector('.relationship-divider').setAttribute('stroke', '#d8e1ec');
      node.querySelector('.relationship-divider').setAttribute('stroke-width', '1');
      const label = node.querySelector('.relationship-title-box');
      let remaining = label.textContent.trim().replace(/\s+/g, ' ');
      measure.font = '600 15px Arial';
      for (let line = 0; line < 2 && remaining; line++) {
        let part = prefix(remaining, line === 1 ? '…' : '');
        if (part.length < remaining.length && line === 0 && part.lastIndexOf(' ') > 0) part = part.slice(0, part.lastIndexOf(' '));
        remaining = remaining.slice(part.length).trimStart();
        const text = document.createElementNS(ns, 'text');
        text.setAttribute('x', '14');
        text.setAttribute('y', String(47 + line * 17));
        text.setAttribute('font-size', '15');
        text.setAttribute('font-weight', '600');
        text.setAttribute('fill', '#2b3d58');
        text.textContent = part + (remaining && line === 1 ? '…' : '');
        node.append(text);
      }
      label.remove();
      const preview = node.querySelector('.relationship-preview');
      if (preview && view === 'detailed') {
        Array.from(preview.querySelectorAll('.relationship-preview-item')).forEach((item, index) => {
          for (const [selector, size, y, color] of [['span', 10, 91, '#68778d'], ['strong', 12, 105, '#354665']]) {
            const full = item.querySelector(selector).textContent.trim().replace(/\s+/g, ' ');
            measure.font = `${size}px Arial`;
            const visible = measure.measureText(full.slice(0, 1024)).width <= 204 && full.length <= 1024 ? full : prefix(full, '…') + '…';
            const text = document.createElementNS(ns, 'text');
            text.setAttribute('x', '14');
            text.setAttribute('y', String(y + index * 28));
            text.setAttribute('font-size', size);
            text.setAttribute('fill', color);
            text.setAttribute('class', 'relationship-export-detail');
            text.textContent = visible;
            const title = document.createElementNS(ns, 'title');
            title.textContent = full;
            text.append(title);
            node.append(text);
          }
        });
      }
      preview?.remove();
    }
    return new Blob([new XMLSerializer().serializeToString(clone)], {type: 'image/svg+xml;charset=utf-8'});
  };
  const download = (blob, extension, mode = view) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const name = graph.dataset.exportName || `data-${graph.dataset.object}-relationships`;
    link.download = `${name}-${mode}.${extension}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  };
  graph.querySelector('#graph-save-svg').addEventListener('click', () => {
    download(exportSVG(), 'svg');
    graph.querySelector('.graph-download').open = false;
    announce(`${graph.dataset.collection ? 'Current graph view' : 'Complete graph'} downloaded as SVG. Full node names are included in the SVG titles.`);
  });
  graph.querySelector('#graph-save-png').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    announce('Preparing the complete graph image…');
    const exportWidth = width;
    const exportHeight = height;
    const exportView = view;
    let url;
    try {
      url = URL.createObjectURL(exportSVG());
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = reject;
        image.src = url;
      });
      const scale = Math.min(2, 8192 / exportWidth, 8192 / exportHeight, Math.sqrt(16000000 / (exportWidth * exportHeight)));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.floor(exportWidth * scale));
      canvas.height = Math.max(1, Math.floor(exportHeight * scale));
      canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
      if (!blob) throw new Error('Empty image');
      download(blob, 'png', exportView);
      graph.querySelector('.graph-download').open = false;
      announce(`${graph.dataset.collection ? 'Current graph view' : 'Complete graph'} downloaded as PNG (${canvas.width} × ${canvas.height}). SVG retains vector detail at any size.`);
    } catch {
      announce('PNG could not be created. Download SVG to save the complete graph.');
    } finally {
      if (url) URL.revokeObjectURL(url);
      button.disabled = false;
    }
  });
  graph.addEventListener('keydown', event => {
    const menu = graph.querySelector('.graph-download');
    if (event.key === 'Escape' && menu.open) {
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.graph-download')) graph.querySelector('.graph-download').open = false;
  });

  graph.classList.add('is-interactive');
  for (const selector of ['.graph-controls', '.graph-inspector-tabs', '#graph-copy-link', '.graph-interactive-help']) {
    graph.querySelector(selector).hidden = false;
  }
  graph.querySelector('.graph-native-help').hidden = true;
  select(nodeFromHash() || nodes[0], {bookmark: false, move: false});
  search();
  fit();
  if (nodeFromHash() || zoom < (view === 'detailed' ? 1 : .75)) centerSelected();
  let lastSize = '';
  new ResizeObserver(() => {
    const size = `${viewport.clientWidth},${viewport.clientHeight}`;
    if (lastSize && lastSize !== size) {
      if (fitted) fit();
      else centerSelected(false);
    }
    lastSize = size;
  }).observe(viewport);
})();
