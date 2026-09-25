import {TENSOR_COMPONENTS, TENSOR_COLORS, isTensorNumber, formatTensorValue, strainIllustration, tensorArrows} from './mechanical-bc-tensor.js';

export function createTensorPanel(panel, items, units, onChange, onHighlight) {
  const conditions = items.map((item, index) => ({item, index})).filter(({item}) => item.is_tensor_load);
  if (!panel || !conditions.length) return null;

  const conditionSelect = panel.querySelector('[data-tensor-condition]');
  const loadSelect = panel.querySelector('[data-tensor-load]');
  const slider = panel.querySelector('[data-tensor-slider]');
  const matrix = panel.querySelector('[data-tensor-matrix]');
  const shape = panel.querySelector('[data-tensor-shape]');
  const shapeLabel = panel.querySelector('[data-tensor-shape-label]');
  const filterButtons = Array.from(panel.querySelectorAll('[data-tensor-filter]'));
  let current = conditions[0];
  let loadIndex = 0;
  let filter = 'all';
  let selected = '';
  let cells = [];

  function highlight(component) {
    cells.forEach(cell => cell.classList.toggle('is-hovered', cell.dataset.component === component));
  }

  function hover(component) {
    highlight(component);
    onHighlight(component);
  }

  function render() {
    const loads = current.item.tensor_loads || [];
    const load = loads[loadIndex];
    const magnitude = load?.magnitude;
    const isStrain = current.item.loading_type === 'strain';
    const rawUnit = units?.[isStrain ? 'Strain' : 'Stress'];
    const unit = isStrain && (rawUnit === 1 || (typeof rawUnit === 'string' && rawUnit.trim() === '1'))
      ? '-' : (typeof rawUnit === 'string' ? rawUnit.trim() : '');
    panel.querySelector('[data-tensor-heading]').textContent =
      `Whole RVE · ${isStrain ? 'Strain' : 'Stress'}${unit ? ` (${unit})` : ' · unit not supplied'}`;
    panel.querySelector('[data-tensor-metadata]').textContent = (load?.details || [])
      .filter(detail => detail.key !== 'magnitude')
      .map(detail => `${detail.key}: ${detail.display}`).join(' · ');
    panel.querySelector('[data-tensor-position]').textContent = loads.length
      ? `Load ${loadIndex + 1} of ${loads.length}` : 'No load entries supplied';
    loadSelect.value = String(loadIndex);
    slider.value = String(loadIndex);
    slider.setAttribute('aria-valuetext', loadSelect.selectedOptions[0]?.textContent || 'No loads');
    shapeLabel.hidden = !isStrain;
    const preview = strainIllustration(magnitude, filter, selected);
    shape.disabled = !!preview.error;
    if (!isStrain || preview.error) shape.checked = false;
    shape.title = preview.error;
    matrix.replaceChildren();
    cells = [];
    for (const key of TENSOR_COMPONENTS) {
      const cell = document.createElement('button');
      const supplied = magnitude && Object.hasOwn(magnitude, key);
      const value = magnitude?.[key];
      cell.type = 'button';
      cell.className = 'bc-tensor-cell';
      cell.dataset.component = key;
      cell.style.setProperty('--component-color', TENSOR_COLORS[key[0]]);
      cell.disabled = !isTensorNumber(value);
      cell.setAttribute('aria-pressed', String(selected === key));
      cell.classList.toggle('is-filtered', filter !== 'all' && ((key[0] === key[1]) !== (filter === 'normal')));
      const rawValue = typeof value === 'object' ? JSON.stringify(value) : String(value);
      cell.title = supplied ? `${key}: ${rawValue}${unit ? ` ${unit}` : ''}` : `${key}: not supplied`;
      const label = document.createElement('span');
      label.textContent = key;
      const number = document.createElement('strong');
      number.textContent = supplied ? formatTensorValue(value) : 'Not supplied';
      cell.setAttribute('aria-label', `${key}: ${number.textContent}${unit && supplied ? ` ${unit}` : ''}`);
      cell.append(label, number);
      cell.addEventListener('click', () => {
        selected = selected === key ? '' : key;
        if (filter !== 'all' && ((key[0] === key[1]) !== (filter === 'normal'))) filter = 'all';
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
    filterButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.tensorFilter === filter)));
    const valid = TENSOR_COMPONENTS.filter(key => isTensorNumber(magnitude?.[key]));
    const invalid = TENSOR_COMPONENTS.filter(key => magnitude && Object.hasOwn(magnitude, key) && !isTensorNumber(magnitude[key]));
    let status = selected ? `${selected}: ${String(magnitude[selected])}${unit ? ` ${unit}` : ''}`
      : filter === 'all' ? 'All supplied components' : `Supplied ${filter} components`;
    if (!valid.length) status = 'No numeric tensor components to visualize. See supplied load details below.';
    else if (!tensorArrows(magnitude, filter, selected).length) status += ' · no nonzero components in this view';
    if (invalid.length) status += ` · invalid components omitted: ${invalid.join(', ')}`;
    panel.querySelector('[data-tensor-status]').textContent = status;
    panel.querySelector('[data-tensor-note]').textContent = shape.checked
      ? 'Normalized small-strain illustration, not a simulated shape. Assumes tensor shear and symmetry; missing reciprocal entries are mirrored for this preview only. Blue: original, purple: illustration.'
      : `${isStrain ? 'Strain direction guides, not forces or a predicted shape.' : 'Stress component schematic, not reconstructed boundary tractions.'} ij means direction i on faces normal to j. Positive normal values point outward. Arrow lengths are fixed; use the values for magnitude. Missing components are not inferred.`;
    panel.querySelector('[data-tensor-preview-note]').textContent = isStrain && preview.error ? preview.error : '';
    onHighlight('');
    onChange({item: current.item, itemIndex: current.index, load, filter, selected, unit,
      shapeMatrix: shape.checked ? preview.matrix : null});
  }

  function selectCondition(index, step = 0) {
    current = conditions.find(entry => entry.index === Number(index)) || conditions[0];
    conditionSelect.value = String(current.index);
    const loads = current.item.tensor_loads || [];
    loadIndex = Math.max(0, Math.min(step, loads.length - 1));
    selected = '';
    filter = 'all';
    shape.checked = false;
    loadSelect.replaceChildren();
    loads.forEach((load, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      const stepDetail = load.details?.find(detail => detail.key === 'step');
      option.textContent = `Load ${index + 1}${stepDetail ? ` · step ${stepDetail.display}` : ''}`;
      loadSelect.appendChild(option);
    });
    if (!loads.length) loadSelect.add(new Option('No load entries', '0'));
    loadSelect.disabled = loads.length < 2;
    slider.max = String(Math.max(0, loads.length - 1));
    slider.disabled = loads.length < 2;
    render();
  }

  conditions.forEach(({item, index}, order) => {
    conditionSelect.add(new Option(`Whole RVE ${order + 1} · ${item.loading_type}${item.loading_mode ? ` / ${item.loading_mode}` : ''}`, String(index)));
  });
  conditionSelect.disabled = conditions.length === 1;
  conditionSelect.addEventListener('change', () => selectCondition(conditionSelect.value));
  function selectLoad(index) {
    loadIndex = Number(index);
    selected = '';
    render();
  }
  loadSelect.addEventListener('change', () => selectLoad(loadSelect.value));
  slider.addEventListener('input', () => selectLoad(slider.value));
  filterButtons.forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.tensorFilter;
    selected = '';
    render();
  }));
  shape.addEventListener('change', render);
  panel.querySelector('[data-tensor-clear]').addEventListener('click', () => {
    selected = '';
    render();
  });
  document.querySelectorAll('[data-bc-show-tensor]').forEach(button => {
    button.hidden = false;
    button.addEventListener('click', () => {
      selectCondition(button.dataset.bcShowTensor, Number(button.dataset.bcLoadIndex));
      panel.scrollIntoView({block: 'nearest', behavior: 'instant'});
    });
  });
  panel.hidden = false;
  selectCondition(current.index);
  return {highlight};
}
