(() => {
  'use strict';

  const saveSelection = document.getElementById('collection-save-for-relationships');
  saveSelection?.addEventListener('click', () => {
    const panel = document.getElementById('collection-save-panel');
    if (panel) panel.open = true;
  });

  const panel = document.getElementById('manual-relationships');
  const form = document.getElementById('manual-relationship-form');
  if (!panel || !form) return;
  const editor = document.getElementById('manual-relationship-editor');
  const heading = document.getElementById('manual-relationship-editor-heading');
  const status = document.getElementById('manual-relationship-status');
  const reload = document.getElementById('manual-relationship-reload');
  const removeForm = document.getElementById('manual-relationship-delete-form');
  const removeConfirm = document.getElementById('manual-relationship-delete-confirm');
  const cancel = document.getElementById('manual-relationship-cancel');
  const graph = document.getElementById('detail-relationships');
  const svg = graph?.querySelector('.relationship-svg');
  const drawButton = document.getElementById('graph-draw-connection');
  const nodeList = Array.from(svg?.querySelectorAll('.relationship-node[data-object-pk]') || []);
  const nodes = new Map(nodeList.map(node => [node.dataset.objectPk, node]));
  const ports = Array.from(svg?.querySelectorAll('.relationship-port') || []);
  const manualEdges = Array.from(svg?.querySelectorAll('.relationship-edge[data-manual-id]') || []);
  const rows = JSON.parse(document.getElementById('manual-relationship-data').textContent) || [];
  const relationships = new Map(rows.map(row => [String(row.id), row]));
  let drawing = false;
  let source = null;
  let pointer = null;
  let draft = null;
  let ignoreClickUntil = 0;
  let pending = false;
  let conflicted = false;

  const announce = message => {
    status.textContent = message;
    status.hidden = !message;
  };
  const graphAnnounce = message => {
    const output = document.getElementById('graph-status');
    if (!output) return;
    output.textContent = message;
    output.hidden = !message;
  };
  const clearDraft = () => {
    draft?.remove();
    draft = null;
  };
  const setDrawing = active => {
    drawing = active;
    source = null;
    pointer = null;
    clearDraft();
    graph?.classList.toggle('is-drawing', active);
    drawButton?.setAttribute('aria-pressed', String(active));
    for (const node of nodeList) node.classList.remove('is-connection-source');
    for (const port of ports) port.tabIndex = active ? 0 : -1;
  };
  const updateButtons = () => {
    form.querySelector('button[type="submit"]').disabled = pending || conflicted;
    removeForm.querySelector('button[type="submit"]').disabled = pending || conflicted;
    cancel.disabled = pending;
    if (drawButton) drawButton.disabled = pending;
  };
  const clearErrors = () => {
    for (const errors of form.querySelectorAll('.errorlist')) errors.remove();
    announce('');
    reload.hidden = true;
    conflicted = false;
    updateButtons();
  };
  const openEditor = focus => {
    editor.open = true;
    if (focus) {
      editor.scrollIntoView({block: 'nearest', behavior: 'instant'});
      form.elements[focus].focus({preventScroll: true});
    }
  };
  const newRelationship = (focus = 'source') => {
    if (pending) return;
    setDrawing(false);
    clearErrors();
    for (const name of ['relationship_id', 'revision', 'source', 'target', 'label']) form.elements[name].value = '';
    heading.textContent = 'Add relationship';
    reload.href = panel.dataset.membersUrl;
    removeConfirm.hidden = true;
    removeConfirm.open = false;
    openEditor(focus);
  };
  const editRelationship = row => {
    if (pending || !row) return;
    setDrawing(false);
    clearErrors();
    form.elements.relationship_id.value = row.id;
    form.elements.revision.value = row.revision;
    form.elements.source.value = row.source_id;
    form.elements.target.value = row.target_id;
    form.elements.label.value = row.label;
    heading.textContent = 'Edit relationship';
    removeConfirm.hidden = false;
    removeConfirm.open = false;
    removeForm.action = row.delete_url;
    removeForm.elements.revision.value = row.revision;
    reload.href = row.edit_url;
    openEditor('label');
  };
  const chooseSource = id => {
    source = String(id);
    for (const node of nodeList) node.classList.toggle('is-connection-source', node.dataset.objectPk === source);
    graphAnnounce('Choose a different data object as the destination. Escape cancels drawing.');
  };
  const chooseTarget = id => {
    if (source === String(id)) {
      graphAnnounce('Choose a different data object as the destination.');
      return;
    }
    form.elements.source.value = source;
    form.elements.target.value = id;
    setDrawing(false);
    graphAnnounce('Connection selected. Enter its relationship name and save.');
    openEditor('label');
  };

  document.getElementById('graph-add-relationship')?.addEventListener('click', event => {
    event.preventDefault();
    newRelationship();
  });
  cancel.hidden = false;
  cancel.addEventListener('click', () => {
    if (pending) return;
    newRelationship(null);
    editor.open = false;
    graphAnnounce('');
    document.getElementById('graph-add-relationship')?.focus();
  });
  if (drawButton) {
    drawButton.hidden = false;
    drawButton.addEventListener('click', () => {
      if (drawing) {
        setDrawing(false);
        graphAnnounce('Drawing cancelled.');
        return;
      }
      if (nodeList.length < 2) {
        newRelationship();
        announce('Choose objects in the form, or open Collection members to draw between visible object cards.');
        return;
      }
      newRelationship(null);
      setDrawing(true);
      graphAnnounce('Drag a purple connection point to another object, or select the source and destination with click or Enter. Escape cancels.');
      ports[0]?.focus({preventScroll: true});
    });
  }
  const objectAt = element => {
    const node = element?.closest('.relationship-node[data-object-pk]');
    if (node) return node.dataset.objectPk;
    return element?.closest('.relationship-port')?.dataset.sourceObject;
  };
  const screenPoint = event => new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
  const nearestManualEdge = (event, fallback) => {
    const point = screenPoint(event);
    const matrix = svg.getScreenCTM();
    const tolerance = 8 / Math.hypot(matrix.a, matrix.b);
    let nearest = fallback;
    let shortest = Infinity;
    for (const edge of manualEdges) {
      const bounds = edge.getBBox();
      if (point.x < bounds.x - tolerance || point.x > bounds.x + bounds.width + tolerance
          || point.y < bounds.y - tolerance || point.y > bounds.y + bounds.height + tolerance) continue;
      const length = edge.getTotalLength();
      const step = length / 32;
      const distance = position => {
        const candidate = edge.getPointAtLength(position);
        return (candidate.x - point.x) ** 2 + (candidate.y - point.y) ** 2;
      };
      let closestPosition = 0;
      let closestDistance = Infinity;
      for (let index = 0; index <= 32; index++) {
        const value = distance(index * step);
        if (value < closestDistance) {
          closestDistance = value;
          closestPosition = index * step;
        }
      }
      let left = Math.max(0, closestPosition - step);
      let right = Math.min(length, closestPosition + step);
      for (let iteration = 0; iteration < 16; iteration++) {
        const third = (right - left) / 3;
        if (distance(left + third) < distance(right - third)) right -= third;
        else left += third;
      }
      const value = distance((left + right) / 2);
      if (value < shortest) {
        shortest = value;
        nearest = edge;
      }
    }
    return nearest;
  };
  const moveDraft = event => {
    const startNode = nodes.get(source);
    if (!startNode) return;
    const transform = startNode.parentNode.transform.baseVal.getItem(0).matrix;
    const start = {x: transform.e + 232, y: transform.f + 40};
    const end = screenPoint(event);
    if (!draft) {
      draft = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      draft.setAttribute('class', 'relationship-draft');
      draft.setAttribute('aria-hidden', 'true');
      svg.append(draft);
    }
    const bend = Math.max(40, Math.abs(end.x - start.x) / 2);
    draft.setAttribute('d', `M ${start.x} ${start.y} C ${start.x + bend} ${start.y}, ${end.x - bend} ${end.y}, ${end.x} ${end.y}`);
  };
  svg?.addEventListener('pointerdown', event => {
    const port = event.target.closest('.relationship-port');
    if (!drawing || !port || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    chooseSource(port.dataset.sourceObject);
    pointer = {id: event.pointerId, x: event.clientX, y: event.clientY, port};
    port.setPointerCapture(event.pointerId);
    moveDraft(event);
  }, true);
  svg?.addEventListener('pointermove', event => {
    if (!pointer || pointer.id !== event.pointerId) return;
    moveDraft(event);
  });
  svg?.addEventListener('pointerup', event => {
    if (!pointer || pointer.id !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const drag = pointer;
    pointer = null;
    const id = objectAt(document.elementFromPoint(event.clientX, event.clientY));
    if (id && id !== source) chooseTarget(id);
    else if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 5) graphAnnounce('Drop on a different data object, or select its card to finish the connection.');
    clearDraft();
    if (drag.port.hasPointerCapture(event.pointerId)) drag.port.releasePointerCapture(event.pointerId);
    ignoreClickUntil = performance.now() + 250;
  }, true);
  const cancelPointer = () => {
    if (!pointer) return;
    setDrawing(false);
    graphAnnounce('Drawing cancelled.');
  };
  svg?.addEventListener('pointercancel', cancelPointer);
  svg?.addEventListener('lostpointercapture', cancelPointer);
  svg?.addEventListener('click', event => {
    if (event.detail && performance.now() < ignoreClickUntil) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    const id = objectAt(event.target);
    if (drawing && id) {
      event.preventDefault();
      event.stopPropagation();
      if (source) chooseTarget(id);
      else chooseSource(id);
      return;
    }
    const edge = event.target.closest('[data-manual-id]');
    if (edge) {
      event.preventDefault();
      event.stopPropagation();
      // Wide hit areas can overlap, so pointer clicks follow the nearest visible curve
      const selected = event.detail ? nearestManualEdge(event, edge) : edge;
      editRelationship(relationships.get(selected.dataset.manualId));
    }
  }, true);
  svg?.addEventListener('keydown', event => {
    if (!['Enter', ' '].includes(event.key)) return;
    const id = objectAt(event.target);
    const edge = event.target.closest('[data-manual-id]');
    if ((drawing && id) || edge) {
      event.preventDefault();
      event.stopPropagation();
      if (drawing && id) {
        if (source) chooseTarget(id);
        else chooseSource(id);
      } else editRelationship(relationships.get(edge.dataset.manualId));
    }
  }, true);
  for (const edge of manualEdges) {
    edge.setAttribute('tabindex', '0');
    edge.setAttribute('role', 'button');
    edge.setAttribute('aria-label', `Edit ${edge.querySelector('title').textContent}`);
    const hit = edge.cloneNode(true);
    hit.setAttribute('class', 'relationship-edge-hit');
    hit.removeAttribute('tabindex');
    hit.removeAttribute('role');
    hit.removeAttribute('marker-end');
    hit.setAttribute('aria-hidden', 'true');
    hit.querySelector('title')?.remove();
    edge.after(hit);
  }
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || pending) return;
    if (drawing) {
      event.preventDefault();
      setDrawing(false);
      graphAnnounce('Drawing cancelled.');
      drawButton?.focus();
    } else if (editor.open) {
      event.preventDefault();
      cancel.click();
    }
  });
  window.addEventListener('pagehide', () => setDrawing(false));

  const submit = async (event, submittedForm) => {
    event.preventDefault();
    if (pending || conflicted) return;
    const body = new FormData(submittedForm);
    pending = true;
    updateButtons();
    announce(submittedForm === form ? 'Saving relationship…' : 'Deleting relationship…');
    reload.hidden = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(submittedForm.action, {
        method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}, signal: controller.signal,
      });
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error('Unexpected response');
      }
      const result = await response.json();
      if (response.ok && result.ok && result.redirect_url) {
        const destination = new URL(result.redirect_url, location.href);
        if (destination.origin !== location.origin) throw new Error('Invalid destination');
        window.location.assign(destination.href);
        return;
      }
      const errors = [];
      for (const values of Object.values(result.errors || {})) {
        for (const value of Array.isArray(values) ? values : [values]) errors.push(typeof value === 'string' ? value : value.message);
      }
      announce([result.error, ...errors].filter(Boolean).join(' ') || 'The relationship could not be saved. Check the selected objects and relationship name.');
      conflicted = response.status === 409;
      reload.hidden = !conflicted;
    } catch {
      announce('The change could not be confirmed. Reload saved relationships to check before trying again. Your entered values are kept here.');
      reload.hidden = false;
    } finally {
      window.clearTimeout(timeout);
      pending = false;
      updateButtons();
    }
  };
  form.addEventListener('submit', event => submit(event, form));
  removeForm.addEventListener('submit', event => submit(event, removeForm));
  panel.classList.add('is-interactive');
})();
