import {TENSOR_COMPONENTS, isTensorNumber, formatTensorValue, strainIllustration, tensorArrows, tensorComponentMeaning, tensorComponentVisible} from './mechanical-bc-tensor.js';

export function createTensorPanel(panel, items, units, onChange, onHighlight) {
  const conditions = items.map((item, index) => ({item, index})).filter(({item}) => item.is_tensor_load);
  if (!panel || !conditions.length) return null;

  const conditionSelect = panel.querySelector('[data-tensor-condition]');
  const loadSelect = panel.querySelector('[data-tensor-load]');
  const matrix = panel.querySelector('[data-tensor-matrix]');
  const shape = panel.querySelector('[data-tensor-shape]');
  const shapeLabel = panel.querySelector('[data-tensor-shape-label]');
  const filterButtons = Array.from(panel.querySelectorAll('[data-tensor-filter]'));
  let current = conditions[0];
  let loadIndex = 0;
  let filter = 'all';
  let selected = null;
  let cells = [];

  function componentDescription(key, value, isStrain) {
    if (key[0] !== key[1]) {
      return `Slide (${isStrain ? 'shear strain' : 'shear'}) · ${key[0].toUpperCase()} direction on ±${key[1].toUpperCase()} faces`;
    }
    let kind = 'Normal component';
    const meaning = tensorComponentMeaning(key, value, isStrain);
    if (meaning) {
      const action = isStrain ? meaning.action : value > 0 ? 'Pull apart' : 'Push together';
      kind = `${action} (${meaning.name.toLowerCase()})`;
    }
    return `${kind} · ${key[0].toUpperCase()} direction on ±${key[1].toUpperCase()} faces`;
  }

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
    if (selected && isTensorNumber(magnitude?.[selected])
      && !tensorComponentVisible(selected, magnitude[selected], filter)) filter = 'all';
    const isStrain = current.item.loading_type === 'strain';
    const rawUnit = units?.[isStrain ? 'Strain' : 'Stress'];
    const unit = isStrain && (rawUnit === 1 || (typeof rawUnit === 'string' && rawUnit.trim() === '1'))
      ? '-' : (typeof rawUnit === 'string' ? rawUnit.trim() : '');
    panel.querySelector('[data-tensor-heading]').textContent =
      `Whole cube · ${isStrain ? 'Strain' : 'Stress'}${unit ? ` (${unit})` : ' · unit not supplied'}`;
    loadSelect.value = String(loadIndex);
    shapeLabel.hidden = !isStrain;
    const preview = strainIllustration(magnitude, filter, selected);
    shape.disabled = !!preview.error;
    if (!isStrain || preview.error) {
      if (shape.checked) {
        selected = '';
        filter = 'all';
      }
      shape.checked = false;
    }
    panel.querySelector('[data-tensor-kind]').textContent = shape.checked
      ? 'Normalized small-strain illustration · all supplied components'
      : (isStrain ? 'Strain direction guides · fixed arrow lengths' : 'Stress on opposing faces · fixed arrow lengths');
    shape.title = preview.error;
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
        heading.setAttribute('aria-hidden', 'true');
        matrix.appendChild(heading);
      }
      const cell = document.createElement('button');
      const supplied = magnitude && Object.hasOwn(magnitude, key);
      const value = magnitude?.[key];
      cell.type = 'button';
      cell.className = 'bc-tensor-cell';
      cell.dataset.component = key;
      cell.disabled = !isTensorNumber(value);
      cell.setAttribute('aria-pressed', String(selected === key));
      cell.classList.toggle('is-filtered', !tensorComponentVisible(key, value, filter, selected));
      const rawValue = typeof value === 'object' ? JSON.stringify(value) : String(value);
      cell.title = supplied ? `${key}: ${rawValue}${unit ? ` ${unit}` : ''}` : `${key}: not supplied`;
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
        action.textContent = meaning.action;
        cell.appendChild(action);
      }
      cell.setAttribute('aria-label', `${key}: ${supplied ? number.textContent : 'Not supplied'}${unit && supplied ? ` ${unit}` : ''}${meaning ? ` · ${meaning.action} (${meaning.name.toLowerCase()})` : ''}`);
      cell.addEventListener('click', () => {
        shape.checked = false;
        selected = selected === key ? '' : key;
        if (!selected || !tensorComponentVisible(key, value, filter)) filter = 'all';
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
    const actionLabels = {all: 'Show all', pull: isStrain ? 'Extend' : 'Pull', push: isStrain ? 'Shorten' : 'Push', slide: 'Slide'};
    filterButtons.forEach(button => {
      button.textContent = actionLabels[button.dataset.tensorFilter];
      button.setAttribute('aria-pressed', String(!selected && !shape.checked && button.dataset.tensorFilter === filter));
    });
    panel.querySelector('[data-tensor-filter-note]').hidden = !selected && filter === 'all';
    const valid = TENSOR_COMPONENTS.filter(key => isTensorNumber(magnitude?.[key]));
    const invalid = TENSOR_COMPONENTS.filter(key => magnitude && Object.hasOwn(magnitude, key) && !isTensorNumber(magnitude[key]));
    let status = '';
    const description = panel.querySelector('[data-tensor-description]');
    const statusElement = panel.querySelector('[data-tensor-status]');
    statusElement.removeAttribute('title');
    if (selected) {
      const value = magnitude?.[selected];
      description.textContent = `${selected} · ${componentDescription(selected, value, isStrain)}`;
      const supplied = magnitude && Object.hasOwn(magnitude, selected);
      if (!supplied) status = `${selected}: Not supplied in this load entry · no arrows`;
      else if (!isTensorNumber(value)) status = `${selected}: Invalid value · no arrows`;
      else status = `${selected}: ${formatTensorValue(value)}${unit ? ` ${unit}` : ''}${value === 0 ? ' · zero value, no arrows' : ''}`;
      statusElement.title = cells.find(cell => cell.dataset.component === selected).title;
    } else {
      description.textContent = shape.checked ? 'Cube: Strain shape illustration'
        : `Cube arrows: ${filter === 'all' ? 'All' : actionLabels[filter]}`;
      if (!valid.length) status = 'No numeric tensor components to visualize. See supplied load details in the table.';
      else if (!tensorArrows(magnitude, filter).length) status = 'No nonzero components in this view';
    }
    if (invalid.length) status += `${status ? ' · ' : ''}Invalid components omitted: ${invalid.join(', ')}`;
    statusElement.textContent = status;
    statusElement.hidden = !status;
    const note = panel.querySelector('[data-tensor-note]');
    note.textContent = shape.checked
      ? 'Normalized small-strain illustration, not a simulated shape. Assumes tensor shear and symmetry; all nine components must be supplied and reciprocal values must agree. Blue: original, purple: illustration.'
      : '';
    note.parentElement.hidden = !shape.checked;
    panel.querySelector('[data-tensor-preview-note]').textContent = isStrain && preview.error ? preview.error : '';
    onHighlight('');
    onChange({item: current.item, itemIndex: current.index, load, filter, selected, unit,
      shapeMatrix: shape.checked ? preview.matrix : null});
  }

  function selectCondition(index, step = 0) {
    const next = conditions.find(entry => entry.index === Number(index)) || conditions[0];
    const fresh = selected === null || next.index !== current.index;
    current = next;
    conditionSelect.value = String(current.index);
    const loads = current.item.tensor_loads || [];
    loadIndex = Math.max(0, Math.min(step, loads.length - 1));
    if (fresh) {
      selected = '';
      filter = 'all';
      shape.checked = false;
    }
    loadSelect.replaceChildren();
    loads.forEach((load, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      const stepDetail = load.details?.find(detail => detail.key === 'step');
      option.textContent = `Record ${index + 1} of ${loads.length}${stepDetail ? ` · step ${stepDetail.display}` : ''}`;
      loadSelect.appendChild(option);
    });
    if (!loads.length) loadSelect.add(new Option('No load entries', '0'));
    loadSelect.disabled = loads.length < 2;
    loadSelect.closest('label').hidden = loads.length < 2;
    render();
  }

  conditions.forEach(({item, index}, order) => {
    conditionSelect.add(new Option(`Whole cube ${order + 1} · ${item.loading_type}${item.loading_mode ? ` / ${item.loading_mode}` : ''}`, String(index)));
  });
  conditionSelect.disabled = conditions.length === 1;
  conditionSelect.closest('label').hidden = conditions.length === 1;
  conditionSelect.addEventListener('change', () => selectCondition(conditionSelect.value));
  function selectLoad(index) {
    loadIndex = Number(index);
    render();
  }
  loadSelect.addEventListener('change', () => selectLoad(loadSelect.value));
  filterButtons.forEach(button => button.addEventListener('click', () => {
    shape.checked = false;
    filter = button.dataset.tensorFilter;
    selected = '';
    render();
  }));
  shape.addEventListener('change', () => {
    filter = 'all';
    selected = '';
    render();
  });
  panel.querySelector('[data-tensor-clear]').addEventListener('click', () => {
    shape.checked = false;
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
