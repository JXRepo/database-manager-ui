import {TENSOR_COMPONENTS, isTensorNumber, formatTensorValue, tensorComponentLabel, createTensorComponentLabel, tensorComponentMeaning} from './mechanical-bc-tensor.js';

export function createTensorPanel(panel, items, units, onChange, onHighlight) {
  const conditions = items.map((item, index) => ({item, index})).filter(({item}) => item.is_tensor_load);
  if (!panel || !conditions.length) return null;
  const conditionSelect = panel.querySelector('[data-tensor-condition]');
  const loadSelect = panel.querySelector('[data-tensor-load]');
  const matrix = panel.querySelector('[data-tensor-matrix]');
  const selectAll = panel.querySelector('[data-tensor-filter="all"]');
  let current = conditions[0];
  let loadIndex = 0;
  let selected = null;
  let cells = [];

  function highlight(components) {
    const keys = Array.isArray(components) ? components : [components];
    const linked = new Set();
    cells.forEach(cell => {
      const members = cell.dataset.components.split(',');
      const matching = members.some(key => keys.includes(key));
      cell.classList.toggle('is-hovered', matching);
      if (matching) members.forEach(key => linked.add(key));
    });
    return [...linked];
  }
  function hover(component) {
    highlight(component);
    onHighlight(component);
  }
  function members() {
    const magnitude = current.item.tensor_loads?.[loadIndex]?.magnitude;
    return TENSOR_COMPONENTS.filter(key => tensorComponentMeaning(key, magnitude?.[key]));
  }
  function render() {
    const load = current.item.tensor_loads?.[loadIndex];
    const magnitude = load?.magnitude;
    const isStrain = current.item.loading_type === 'strain';
    const rawUnit = units?.[isStrain ? 'Strain' : 'Stress'];
    const unit = isStrain && (rawUnit === 1 || rawUnit === '1') ? '-' : typeof rawUnit === 'string' ? rawUnit.trim() : '';
    panel.querySelector('[data-tensor-heading]').textContent = `Whole cube · ${isStrain ? 'Strain' : 'Stress'}${unit ? ` (${unit})` : ' · unit not supplied'}${current.item.loading_mode ? ` / ${current.item.loading_mode}` : ''}`;
    loadSelect.value = String(loadIndex);
    matrix.replaceChildren();
    cells = [];
    for (const text of ['Direction / Face', 'X face', 'Y face', 'Z face']) {
      const heading = document.createElement('span');
      heading.className = 'bc-tensor-axis';
      heading.textContent = text;
      if (text === 'Direction / Face') heading.title = 'The first subscript is the direction; the second is the face normal.';
      heading.setAttribute('aria-hidden', 'true');
      matrix.appendChild(heading);
    }
    for (const key of TENSOR_COMPONENTS) {
      if (key[1] === 'x') {
        const heading = document.createElement('span');
        heading.className = 'bc-tensor-axis';
        heading.textContent = `${key[0]} direction`;
        matrix.appendChild(heading);
      }
      const value = magnitude?.[key];
      const supplied = magnitude && Object.hasOwn(magnitude, key);
      const reverse = key[1] + key[0];
      const paired = reverse !== key && isTensorNumber(value) && isTensorNumber(magnitude?.[reverse]) && magnitude[reverse] === value;
      if (paired && key > reverse) {
        const space = document.createElement('span');
        space.setAttribute('aria-hidden', 'true');
        matrix.appendChild(space);
        continue;
      }
      const keys = paired ? [key, reverse] : [key];
      const selectedCount = keys.filter(component => selected.has(component)).length;
      const fullySelected = selectedCount === keys.length;
      const componentLabel = tensorComponentLabel(key, isStrain);
      const symmetry = paired ? ` · ${componentLabel} = ${tensorComponentLabel(reverse, isStrain)}` : '';
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = 'bc-tensor-cell';
      cell.dataset.component = key;
      cell.dataset.components = keys.join(',');
      cell.disabled = !isTensorNumber(value);
      cell.setAttribute('aria-pressed', selectedCount && !fullySelected ? 'mixed' : String(fullySelected));
      cell.classList.toggle('is-filtered', !selectedCount);
      const raw = typeof value === 'object' ? JSON.stringify(value) : String(value);
      cell.title = (supplied ? `${componentLabel}: ${raw}${unit ? ` ${unit}` : ''}` : `${componentLabel}: not supplied`)
        + (fullySelected ? ' · Selected' : selectedCount ? ' · Partly selected' : ' · Not selected') + symmetry;
      const label = createTensorComponentLabel(key, isStrain);
      const number = document.createElement('strong');
      number.textContent = supplied ? formatTensorValue(value) : '—';
      cell.append(label, number);
      const meaning = tensorComponentMeaning(key, value, isStrain);
      if (meaning) {
        cell.dataset.effect = meaning.effect;
        cell.style.setProperty('--bc-component-color', meaning.color);
      }
      const directions = keys.map(component => `${component[0]} direction on ${component[1].toUpperCase()} faces`).join('; ');
      cell.setAttribute('aria-label', `${componentLabel}, ${directions}: ${supplied ? number.textContent : 'Not supplied'}${unit && supplied ? ` ${unit}` : ''}${symmetry}`);
      cell.addEventListener('click', () => {
        keys.forEach(component => fullySelected ? selected.delete(component) : selected.add(component));
        render();
        cells.find(button => button.dataset.component === key)?.focus({preventScroll: true});
      });
      cell.addEventListener('pointerenter', () => hover(keys));
      cell.addEventListener('pointerleave', () => hover(''));
      cell.addEventListener('focus', () => hover(keys));
      cell.addEventListener('blur', () => hover(''));
      matrix.appendChild(cell);
      cells.push(cell);
    }
    const available = members();
    const included = available.filter(key => selected.has(key)).length;
    selectAll.setAttribute('aria-pressed', String(available.length > 0 && included === available.length));
    selectAll.classList.toggle('is-partial', included > 0 && included < available.length);
    const active = TENSOR_COMPONENTS.filter(key => selected.has(key));
    const unavailable = active.filter(key => !isTensorNumber(magnitude?.[key]));
    const status = panel.querySelector('[data-tensor-status]');
    status.replaceChildren();
    if (unavailable.length) {
      status.append('Selected but missing or invalid in this record: ');
      unavailable.forEach((key, index) => {
        if (index) status.append(', ');
        status.appendChild(createTensorComponentLabel(key, isStrain));
      });
    } else if (!included) {
      status.textContent = 'Select a nonzero component to animate.';
    }
    status.hidden = !status.textContent;
    onHighlight('');
    onChange({item: current.item, itemIndex: current.index, load, filter: 'all', selected: new Set(selected), unit});
  }
  function selectCondition(index, record = 0) {
    const next = conditions.find(entry => entry.index === Number(index)) || conditions[0];
    const fresh = selected === null || next.index !== current.index;
    current = next;
    conditionSelect.value = String(current.index);
    const loads = current.item.tensor_loads || [];
    loadIndex = Math.max(0, Math.min(record, loads.length - 1));
    if (fresh) selected = new Set(members());
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
  loadSelect.addEventListener('change', () => {
    loadIndex = Number(loadSelect.value);
    render();
  });
  selectAll.addEventListener('click', () => {
    selected = new Set(members());
    render();
  });
  panel.querySelector('[data-tensor-clear]').addEventListener('click', () => { selected.clear(); render(); });
  selectCondition(current.index);
  panel.hidden = false;
  const fallback = document.querySelector('[data-bc-tensor-fallback]');
  if (fallback) fallback.hidden = true;
  return {highlight};
}
