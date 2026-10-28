import {TENSOR_COMPONENTS, isTensorNumber, formatTensorValue, tensorComponentMeaning, tensorComponentVisible} from './mechanical-bc-tensor.js';
import {tensorDeformation} from './mechanical-bc-deformation.js';

export function createTensorPanel(panel, items, units, onChange, onHighlight, context = {}) {
  const conditions = items.map((item, index) => ({item, index})).filter(({item}) => item.is_tensor_load);
  if (!panel || !conditions.length) return null;
  const conditionSelect = panel.querySelector('[data-tensor-condition]');
  const loadSelect = panel.querySelector('[data-tensor-load]');
  const matrix = panel.querySelector('[data-tensor-matrix]');
  const scaleInput = panel.querySelector('[data-tensor-scale]');
  const buttons = Array.from(panel.querySelectorAll('[data-tensor-filter]'));
  let current = conditions[0];
  let loadIndex = 0;
  let selected = null;
  let scale = 1;
  let preview = null;
  let mode = 'action';
  let cells = [];

  function highlight(components) {
    const keys = Array.isArray(components) ? components : [components];
    cells.forEach(cell => cell.classList.toggle('is-hovered', keys.includes(cell.dataset.component)));
  }
  function hover(component) {
    highlight(component);
    onHighlight(component);
  }
  function members(mode = 'all') {
    const magnitude = current.item.tensor_loads?.[loadIndex]?.magnitude;
    return TENSOR_COMPONENTS.filter(key => tensorComponentMeaning(key, magnitude?.[key])
      && tensorComponentVisible(key, magnitude[key], mode));
  }
  function precise(value) {
    return Number(value.toPrecision(7)).toString();
  }
  function render() {
    const load = current.item.tensor_loads?.[loadIndex];
    const magnitude = load?.magnitude;
    const isStrain = current.item.loading_type === 'strain';
    const rawUnit = units?.[isStrain ? 'Strain' : 'Stress'];
    const unit = isStrain && (rawUnit === 1 || rawUnit === '1') ? '-' : typeof rawUnit === 'string' ? rawUnit.trim() : '';
    panel.querySelector('[data-tensor-heading]').textContent = `Whole cube · ${isStrain ? 'Strain' : 'Stress'}${unit ? ` (${unit})` : ' · unit not supplied'}`;
    panel.querySelector('[data-tensor-kind]').textContent = mode === 'action'
      ? 'Combine actions or toggle components, then play the gripping motion.'
      : 'Numerical strain preview from the selected components.';
    loadSelect.value = String(loadIndex);
    matrix.replaceChildren();
    cells = [];
    for (const text of ['i / j', 'X face', 'Y face', 'Z face']) {
      const heading = document.createElement('span');
      heading.className = 'bc-tensor-axis';
      heading.textContent = text;
      heading.setAttribute('aria-hidden', 'true');
      matrix.appendChild(heading);
    }
    for (const key of TENSOR_COMPONENTS) {
      if (key[1] === 'x') {
        const heading = document.createElement('span');
        heading.className = 'bc-tensor-axis';
        heading.textContent = `${key[0].toUpperCase()} direction`;
        matrix.appendChild(heading);
      }
      const value = magnitude?.[key];
      const supplied = magnitude && Object.hasOwn(magnitude, key);
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'bc-tensor-cell';
      cell.dataset.component = key;
      cell.disabled = !isTensorNumber(value);
      cell.setAttribute('aria-pressed', String(selected.has(key)));
      cell.classList.toggle('is-filtered', !selected.has(key));
      const raw = typeof value === 'object' ? JSON.stringify(value) : String(value);
      cell.title = supplied ? `${key}: ${raw}${unit ? ` ${unit}` : ''}` : `${key}: not supplied`;
      const label = document.createElement('span');
      label.textContent = key;
      const number = document.createElement('strong');
      number.textContent = supplied ? formatTensorValue(value) : '—';
      cell.append(label, number);
      const meaning = tensorComponentMeaning(key, value, isStrain);
      if (meaning) {
        cell.dataset.effect = meaning.effect;
        cell.style.setProperty('--bc-component-color', meaning.color);
        const action = document.createElement('small');
        action.dataset.tensorAction = '';
        action.textContent = meaning.effect === 'shear' ? 'Shear' : meaning.action;
        cell.appendChild(action);
      }
      cell.setAttribute('aria-label', `${key}: ${supplied ? number.textContent : 'Not supplied'}${unit && supplied ? ` ${unit}` : ''}${meaning ? ` · ${meaning.action}` : ''}`);
      cell.addEventListener('click', () => {
        const reverse = key[1] + key[0];
        const keys = reverse !== key && isTensorNumber(magnitude?.[reverse]) && magnitude[reverse] === value ? [key, reverse] : [key];
        const remove = selected.has(key);
        keys.forEach(component => remove ? selected.delete(component) : selected.add(component));
        render();
        cells.find(button => button.dataset.component === key)?.focus({preventScroll: true});
      });
      cell.addEventListener('pointerenter', () => hover(key));
      cell.addEventListener('pointerleave', () => hover(''));
      cell.addEventListener('focus', () => hover(key));
      cell.addEventListener('blur', () => hover(''));
      matrix.appendChild(cell);
      cells.push(cell);
    }
    const labels = {all: 'Select all', pull: isStrain ? 'Extend' : 'Pull', push: isStrain ? 'Shorten' : 'Push', slide: 'Shear'};
    buttons.forEach(button => {
      const mode = button.dataset.tensorFilter;
      (button.querySelector('[data-tensor-filter-label]') || button).textContent = labels[mode];
      const available = members(mode);
      const included = available.filter(key => selected.has(key)).length;
      button.setAttribute('aria-pressed', String(available.length > 0 && included === available.length));
      button.classList.toggle('is-partial', included > 0 && included < available.length);
      if (mode !== 'all') {
        button.disabled = !available.length;
        button.querySelector('[data-tensor-action-count]').textContent = `(${included}/${available.length})`;
        button.title = available.length ? 'Toggle this group without changing the other selected actions' : 'No nonzero components';
      }
    });
    const active = TENSOR_COMPONENTS.filter(key => selected.has(key));
    const actions = ['pull','push','slide'].filter(mode => members(mode).some(key => selected.has(key))).map(mode => labels[mode]);
    panel.querySelector('[data-tensor-description]').textContent = actions.length ? `Combination: ${actions.join(' + ')}` : 'No nonzero components selected';
    panel.querySelector('[data-tensor-filter-note]').hidden = members().every(key => selected.has(key));
    const unavailable = active.filter(key => !isTensorNumber(magnitude?.[key]));
    const status = panel.querySelector('[data-tensor-status]');
    status.textContent = unavailable.length ? `Selected but missing or invalid in this record: ${unavailable.join(', ')}` : '';
    status.hidden = !status.textContent;
    preview = tensorDeformation(magnitude, selected, current.item.loading_type, units, context);
    let scaleNote = '';
    if (preview.matrix && scale > preview.maxScale) {
      scale = 1;
      scaleNote = ' Display amplification reset to ×1 for this selection.';
    }
    scaleInput.value = String(scale);
    scaleInput.max = String(preview.maxScale);
    scaleInput.disabled = !preview.matrix;
    scaleInput.setCustomValidity('');
    const details = panel.querySelector('[data-tensor-deformation-values]');
    details.replaceChildren();
    if (preview.matrix) {
      for (let i = 0; i < 3; i++) {
        const row = document.createElement('span');
        const axis = 'XYZ'[i];
        row.textContent = `${axis}: ${precise(preview.matrix[i][i] * 100)}%`;
        if (preview.extensions) row.textContent += ` · axial change ${precise(preview.extensions[i])} ${context.lengthUnit}`;
        details.appendChild(row);
      }
      for (const [i, j] of [[0, 1], [0, 2], [1, 2]]) {
        if (!preview.matrix[i][j]) continue;
        const row = document.createElement('span');
        row.textContent = `${'XYZ'[i]}${'XYZ'[j]}: ${precise(preview.matrix[i][j] * 100)}% (tensor shear)`;
        details.appendChild(row);
      }
    }
    panel.querySelector('[data-tensor-preview-note]').textContent = preview.error || `${preview.source}. Display ×${scale}.${scaleNote}`;
    panel.querySelectorAll('[data-tensor-mode]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.tensorMode === mode));
    });
    panel.querySelector('[data-tensor-calculated]').hidden = mode !== 'calculated';
    panel.querySelector('[data-tensor-action-note]').hidden = mode !== 'action';
    onHighlight('');
    onChange({item: current.item, itemIndex: current.index, load, filter: 'all', selected: new Set(selected), unit,
      deformation: preview, scale, mode, actionLabel: actions.join(' + ')});
  }
  function selectCondition(index, record = 0) {
    const next = conditions.find(entry => entry.index === Number(index)) || conditions[0];
    const fresh = selected === null || next.index !== current.index;
    current = next;
    conditionSelect.value = String(current.index);
    const loads = current.item.tensor_loads || [];
    loadIndex = Math.max(0, Math.min(record, loads.length - 1));
    if (fresh) { selected = new Set(members()); scale = 1; }
    loadSelect.replaceChildren();
    loads.forEach((load, index) => {
      const step = load.details?.find(detail => detail.key === 'step');
      loadSelect.add(new Option(`Record ${index + 1} of ${loads.length}${step ? ` · step ${step.display}` : ''}`, String(index)));
    });
    if (!loads.length) loadSelect.add(new Option('No load entries', '0'));
    loadSelect.disabled = loads.length < 2;
    loadSelect.closest('label').hidden = loads.length < 2;
    render();
  }
  conditions.forEach(({item, index}, order) => conditionSelect.add(new Option(`Whole cube ${order + 1} · ${item.loading_type}${item.loading_mode ? ` / ${item.loading_mode}` : ''}`, String(index))));
  conditionSelect.disabled = conditions.length === 1;
  conditionSelect.closest('label').hidden = conditions.length === 1;
  conditionSelect.addEventListener('change', () => selectCondition(conditionSelect.value));
  loadSelect.addEventListener('change', () => { loadIndex = Number(loadSelect.value); render(); });
  buttons.forEach(button => button.addEventListener('click', () => {
    const keys = members(button.dataset.tensorFilter);
    if (button.dataset.tensorFilter === 'all') selected = new Set(keys);
    else {
      const remove = keys.every(key => selected.has(key));
      keys.forEach(key => remove ? selected.delete(key) : selected.add(key));
    }
    render();
  }));
  panel.querySelectorAll('[data-tensor-mode]').forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.tensorMode;
    render();
  }));
  panel.querySelector('[data-tensor-clear]').addEventListener('click', () => { selected.clear(); render(); });
  scaleInput.addEventListener('change', () => {
    const next = Number(scaleInput.value);
    if (!Number.isFinite(next) || next < 1 || next > preview.maxScale) {
      scaleInput.setCustomValidity(`Choose a display amplification from 1 to ${preview.maxScale}.`);
      scaleInput.reportValidity();
      return;
    }
    scale = next;
    render();
  });
  document.querySelectorAll('[data-bc-show-tensor]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      selectCondition(button.dataset.bcShowTensor, Number(button.dataset.bcLoadIndex));
      panel.scrollIntoView({block:'nearest',behavior:'instant'});
    });
  });
  panel.hidden = false;
  selectCondition(current.index);
  return {highlight};
}
