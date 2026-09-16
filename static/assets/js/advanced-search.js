(() => {
  'use strict';

  const form = document.getElementById('advancedSearchForm');
  const container = document.getElementById('dataFieldConditions');
  const template = document.getElementById('conditionRowTemplate');
  const operatorTemplate = document.getElementById('conditionOperatorTemplate');
  const addButton = document.getElementById('addConditionButton');
  const status = document.getElementById('conditionStatus');
  if (!form || !container || !template || !operatorTemplate || !addButton) return;

  const maxConditions = Number(container.dataset.maxConditions) || 10;
  const operatorOptions = Array.from(operatorTemplate.content.querySelectorAll('option'));
  const numericOperators = ['eq', 'gt', 'gte', 'lt', 'lte', 'between'];
  let nextId = 0;

  function rows() {
    return Array.from(container.querySelectorAll('[data-condition-row]'));
  }

  function updateOperators(row, preserveInvalid = false) {
    const field = row.querySelector('[name="condition_field"]');
    const operator = row.querySelector('[name="condition_operator"]');
    const fieldType = field.selectedOptions[0]?.dataset.fieldType;
    const selected = operator.value;
    const allowed = operatorOptions.filter(option => {
      if (fieldType === 'number') return numericOperators.includes(option.value);
      if (fieldType === 'text') return ['contains', 'exact'].includes(option.value);
      return true;
    });
    const compatible = allowed.some(option => option.value === selected);
    operator.replaceChildren(...allowed.map(option => option.cloneNode(true)));
    if (!compatible && preserveInvalid) {
      const original = operatorOptions.find(option => option.value === selected);
      const label = original ? original.textContent : selected || 'Empty match';
      operator.add(new Option(`${label} (unsupported for this field)`, selected));
    }
    if (compatible || preserveInvalid) {
      operator.value = selected;
    } else {
      operator.value = fieldType === 'number' ? 'eq' : 'contains';
    }
  }

  function updateRow(row) {
    const field = row.querySelector('[name="condition_field"]');
    const operator = row.querySelector('[name="condition_operator"]');
    const value = row.querySelector('[name="condition_value"]');
    const upper = row.querySelector('[name="condition_value_to"]');
    const between = operator.value === 'between';
    const numeric = numericOperators.includes(operator.value);
    const active = Boolean(field.value || value.value.trim() || upper.value.trim() ||
      operator.value !== 'contains');

    row.querySelector('[data-condition-upper]').hidden = !between && !upper.value;
    row.querySelector('[data-condition-label="value"]').textContent = between ? 'Minimum' : 'Value';
    row.querySelector('[data-condition-label="value_to"]').textContent = between ? 'Maximum' : 'Maximum (Between only)';
    value.inputMode = numeric ? 'decimal' : 'text';
    value.placeholder = between ? 'Minimum' : numeric ? 'Number' : 'Text to match';
    upper.inputMode = 'decimal';
    field.required = active;
    value.required = active;
    upper.required = active && between;

    const hint = row.querySelector('[data-condition-hint]');
    if (hint) {
      hint.hidden = field.selectedOptions[0]?.dataset.fieldType !== 'array' || !numeric;
      for (const input of [value, upper]) {
        const descriptions = (input.getAttribute('aria-describedby') || '').split(' ')
          .filter(id => id && id !== hint.id);
        if (!hint.hidden) descriptions.push(hint.id);
        if (descriptions.length) input.setAttribute('aria-describedby', descriptions.join(' '));
        else input.removeAttribute('aria-describedby');
      }
    }
  }

  function updateCount() {
    const currentRows = rows();
    addButton.disabled = currentRows.length >= maxConditions;
    currentRows.forEach((row, index) => {
      row.querySelector('[data-condition-legend]').textContent = `Data field condition ${index + 1}`;
      row.querySelector('[data-remove-condition]').setAttribute('aria-label', `Remove condition ${index + 1}`);
    });
  }

  function prepareRow(row) {
    const prefix = `condition-${++nextId}`;
    const error = row.querySelector('[data-condition-error]');
    error.id = `${prefix}-error`;
    const hint = row.querySelector('[data-condition-hint]');
    if (hint) hint.id = `${prefix}-hint`;
    for (const name of ['field', 'operator', 'value', 'value_to']) {
      const input = row.querySelector(`[name="condition_${name}"]`);
      input.id = `${prefix}-${name}`;
      row.querySelector(`[data-condition-label="${name}"]`).htmlFor = input.id;
      if (error.textContent.trim()) {
        input.setAttribute('aria-describedby', error.id);
        input.setAttribute('aria-invalid', 'true');
      }
      input.addEventListener('input', () => updateRow(row));
      input.addEventListener('change', () => {
        if (name === 'field' || name === 'operator') {
          updateOperators(row);
          if (row.querySelector('[name="condition_operator"]').value !== 'between') {
            row.querySelector('[name="condition_value_to"]').value = '';
          }
        }
        updateRow(row);
      });
    }

    const removeButton = row.querySelector('[data-remove-condition]');
    removeButton.hidden = false;
    removeButton.addEventListener('click', () => {
      const index = rows().indexOf(row);
      row.remove();
      if (rows().length === 0) addRow();
      updateCount();
      const remainingRows = rows();
      const focusRow = remainingRows[Math.min(index, remainingRows.length - 1)];
      focusRow.querySelector('[name="condition_field"]').focus();
      status.textContent = 'Condition removed.';
    });
    updateOperators(row, true);
    updateRow(row);
  }

  function addRow() {
    if (rows().length >= maxConditions) return;
    const row = template.content.firstElementChild.cloneNode(true);
    container.appendChild(row);
    prepareRow(row);
    updateCount();
    row.querySelector('[name="condition_field"]').focus();
    status.textContent = addButton.disabled ? `Maximum of ${maxConditions} conditions reached.` : 'Condition added.';
  }

  rows().forEach(prepareRow);
  updateCount();
  addButton.hidden = false;
  addButton.addEventListener('click', addRow);

  form.addEventListener('invalid', () => {
    document.getElementById('advancedSearchPanel').classList.add('show');
    form.querySelector('[aria-controls="advancedSearchPanel"]').setAttribute('aria-expanded', 'true');
  }, true);

  window.addEventListener('pageshow', () => {
    rows().forEach(row => {
      updateOperators(row, true);
      updateRow(row);
    });
    updateCount();
  });
})();
