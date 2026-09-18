const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const chromiumPath = process.env.CHROMIUM_BIN || '/usr/bin/chromium';
const scriptPath = join(__dirname, '../../static/assets/js/advanced-search.js');

function operatorOptions() {
  return `<option value="contains">Contains words</option><option value="words" selected>All words</option>
    <option value="exact">Equals text</option>
    <option value="eq">Equals number</option><option value="gt">Greater than</option>
    <option value="gte">Greater than or equal to</option><option value="lt">Less than</option>
    <option value="lte">Less than or equal to</option><option value="between">Between</option>
    <option value="is">Is</option>`;
}

function conditionRow() {
  return `<fieldset data-condition-row>
    <legend data-condition-legend>Data field condition</legend>
    <label data-condition-label="field">Data field</label>
    <select name="condition_field">
      <option value="">Choose a field</option>
      <optgroup label="Microstructure">
        <option value="texture_type" data-field-type="text" data-default-operator="words">Texture type</option>
        <option value="grain_count" data-field-type="number" data-default-operator="eq">Grain number</option>
        <option value="lattice_structure" data-field-type="text" data-default-operator="words">Crystal structure</option>
        <option value="orientation_identifier" data-field-type="text" data-default-operator="words">Orientation identifier</option>
      </optgroup>
      <optgroup label="Discretization and boundaries">
        <option value="discretization_type" data-field-type="text" data-default-operator="words">Discretization type</option>
        <option value="discretization_count" data-field-type="number" data-default-operator="eq">Discretization count</option>
        <option value="RVE_continuity" data-field-type="boolean" data-default-operator="is">RVE continuity</option>
      </optgroup>
      <optgroup label="Material models">
        <option value="elastic_model_name" data-field-type="text" data-default-operator="words">Elastic model</option>
        <option value="plastic_model_name" data-field-type="text" data-default-operator="words">Plastic model</option>
      </optgroup>
      <optgroup label="Loading and temperature">
        <option value="loading_type" data-field-type="text" data-default-operator="words">Loading type</option>
        <option value="loading_mode" data-field-type="text" data-default-operator="words">Loading mode</option>
        <option value="global_temperature" data-field-type="number" data-default-operator="eq" data-unit="K">Global temperature (K)</option>
      </optgroup>
      <optgroup label="Saved filters">
      <option value="Grain_Number" data-field-type="number">Grain_Number</option>
      <option value="Youngs_Modulus" data-field-type="number">Youngs_Modulus</option>
      <option value="Load_Type" data-field-type="text">Load_Type</option>
      <option value="Software" data-field-type="text">Software</option>
      <option value="Stress" data-field-type="array">Stress</option>
      <option value="elastic_parameters" data-field-type="parameters">Elastic parameters</option>
      <option value="plastic_parameters" data-field-type="parameters">Plastic parameters</option>
      <option value="Legacy_Field">Legacy_Field</option>
      </optgroup>
    </select>
    <div data-condition-match>
      <label data-condition-label="operator">Match</label>
      <select name="condition_operator">
        ${operatorOptions()}
      </select>
    </div>
    <label data-condition-label="value">Value</label><input name="condition_value">
    <div data-condition-upper>
      <label data-condition-label="value_to">Maximum (Between only)</label>
      <input name="condition_value_to">
    </div>
    <button type="button" data-remove-condition hidden>Remove</button>
    <span data-condition-hint hidden>Matches one number in the array.</span>
    <p data-condition-error hidden></p>
  </fieldset>`;
}

function connect(socket) {
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  return (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
}

describe('advanced search controls in Chromium', {skip: !existsSync(chromiumPath), timeout: 30000}, () => {
  let browser;
  let profile;
  let socket;
  let send;

  before(async () => {
    profile = mkdtempSync(join(tmpdir(), 'advanced-search-test-'));
    browser = spawn(chromiumPath, [
      '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
      '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
    ], {stdio: ['ignore', 'ignore', 'pipe']});
    const address = await new Promise((resolve, reject) => {
      let output = '';
      browser.on('error', reject);
      browser.on('exit', code => reject(new Error(`Chromium exited: ${code}`)));
      browser.stderr.on('data', chunk => {
        output += chunk;
        const match = output.match(/DevTools listening on (ws:\/\/\S+)/);
        if (match) resolve(match[1]);
      });
    });
    socket = new WebSocket(address);
    await once(socket, 'open');
    send = connect(socket);
  });

  after(async () => {
    if (socket) socket.close();
    if (browser && browser.exitCode === null) {
      const exited = once(browser, 'exit');
      browser.kill('SIGTERM');
      await exited;
    }
    if (profile) rmSync(profile, {recursive: true, force: true});
  });

  async function page(t, setup = '', width = 1440) {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    await send('Emulation.setDeviceMetricsOverride', {
      width, height: 900, deviceScaleFactor: 1, mobile: false,
    }, sessionId);
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', {expression, returnByValue: true}, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
      return response.result.value;
    };
    const html = `<form id="advancedSearchForm">
      <button type="button" aria-controls="advancedSearchPanel" aria-expanded="false">Advanced Search</button>
      <a href="https://search.test/search/" data-clear-search>Clear</a>
      <div id="advancedSearchPanel" class="collapse">
        <div id="dataFieldConditions" data-max-conditions="10">${conditionRow()}</div>
        <button type="button" id="addConditionButton" hidden>Add condition</button>
        <p id="conditionStatus" role="status"></p>
        <a href="https://search.test/search/" data-clear-search>Clear</a>
        <template id="conditionRowTemplate">${conditionRow()}</template>
        <template id="conditionOperatorTemplate">${operatorOptions()}</template>
      </div>
    </form>`;
    await evaluate(`document.body.innerHTML = ${JSON.stringify(html)}; ${setup}`);
    const source = existsSync(scriptPath) ? readFileSync(scriptPath, 'utf8') : '';
    await evaluate(source);
    return evaluate;
  }

  test('an untouched row remains optional and keeps all four submitted values aligned', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`({
      optional: [...document.querySelectorAll('input, select')].every(input => !input.required),
      upperHidden: document.querySelector('[data-condition-upper]').hidden,
      values: [...new FormData(document.querySelector('form')).entries()]
    })`);
    assert.equal(state.optional, true);
    assert.equal(state.upperHidden, true);
    assert.deepEqual(state.values, [
      ['condition_field', ''], ['condition_operator', 'words'],
      ['condition_value', ''], ['condition_value_to', ''],
    ]);
  });

  test('choosing a numeric field offers numeric matches and keeps the entered value', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const value = document.querySelector('[name="condition_value"]');
      value.value = '42';
      field.value = 'Grain_Number';
      field.dispatchEvent(new Event('change'));
      const operator = document.querySelector('[name="condition_operator"]');
      return {options: [...operator.options].map(option => option.value),
        selected: operator.value, mode: value.inputMode, placeholder: value.placeholder,
        required: [field.required, value.required],
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(state.options, ['eq', 'gt', 'gte', 'lt', 'lte', 'between']);
    assert.equal(state.selected, 'eq');
    assert.equal(state.mode, 'decimal');
    assert.equal(state.placeholder, 'Number');
    assert.deepEqual(state.required, [true, true]);
    assert.deepEqual(state.submitted, ['Grain_Number', 'eq', '42', '']);
  });

  test('text presets use whole words without a visible Match or missing query slot', async t => {
    const evaluate = await page(t);
    const states = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      document.querySelector('[name="condition_value"]').value = 'orientation-123';
      return [...field.options].filter(option => option.dataset.defaultOperator === 'words').map(option => {
        field.value = option.value;
        field.dispatchEvent(new Event('change'));
        const operator = document.querySelector('[name="condition_operator"]');
        const hint = document.querySelector('[data-condition-hint]');
        return {field: field.value, operator: operator.value,
          options: [...operator.options].map(option => option.value),
          hidden: document.querySelector('[data-condition-match]').hidden,
          disabled: operator.disabled, compact: operator.closest('[data-condition-row]').classList.contains('condition-row-text'),
          hint: hint.hidden ? '' : hint.textContent,
          submitted: [...new FormData(document.querySelector('form')).values()]};
      });
    })()`);
    assert.equal(states.length, 8);
    for (const state of states) {
      assert.deepEqual(state, {field: state.field, operator: 'words', options: ['words'],
        hidden: true, disabled: false, compact: true,
        hint: '',
        submitted: [state.field, 'words', 'orientation-123', '']});
    }
  });

  test('saved text comparisons remain visible until explicitly changed to whole words', async t => {
    for (const saved of ['contains', 'exact']) {
      const evaluate = await page(t, `
        document.querySelector('[name="condition_field"]').value = 'elastic_model_name';
        document.querySelector('[name="condition_operator"]').value = ${JSON.stringify(saved)};
        document.querySelector('[name="condition_value"]').value = 'isotropic';
      `);
      const state = await evaluate(`(() => {
        window.dispatchEvent(new Event('pageshow'));
        window.dispatchEvent(new Event('pageshow'));
        const operator = document.querySelector('[name="condition_operator"]');
        return {options: [...operator.options].map(option => option.value),
          hidden: document.querySelector('[data-condition-match]').hidden,
          compact: operator.closest('[data-condition-row]').classList.contains('condition-row-text'),
          hintHidden: document.querySelector('[data-condition-hint]').hidden,
          submitted: [...new FormData(document.querySelector('form')).values()]};
      })()`);
      assert.deepEqual(state, {options: saved === 'contains' ? ['contains', 'words'] : ['words', 'exact'], hidden: false, compact: false,
        hintHidden: true, submitted: ['elastic_model_name', saved, 'isotropic', '']});
      const changed = await evaluate(`(() => {
        const operator = document.querySelector('[name="condition_operator"]');
        operator.value = 'words';
        operator.dispatchEvent(new Event('change'));
        window.dispatchEvent(new Event('pageshow'));
        return {options: [...operator.options].map(option => option.value),
          hidden: document.querySelector('[data-condition-match]').hidden,
          disabled: operator.disabled,
          submitted: [...new FormData(document.querySelector('form')).values()]};
      })()`);
      assert.deepEqual(changed, {options: ['words'], hidden: true, disabled: false,
        submitted: ['elastic_model_name', 'words', 'isotropic', '']});
    }
  });

  test('invalid text operators and upper bounds remain visible through restoration', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'texture_type';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '10';
      document.querySelector('[name="condition_value_to"]').value = '20';
      document.querySelector('[data-condition-error]').textContent = 'Choose a text match.';
    `);
    const restored = await evaluate(`(() => {
      window.dispatchEvent(new Event('pageshow'));
      window.dispatchEvent(new Event('pageshow'));
      const operator = document.querySelector('[name="condition_operator"]');
      return {options: [...operator.options].map(option => option.value),
        label: operator.selectedOptions[0].textContent,
        hidden: document.querySelector('[data-condition-match]').hidden,
        upperHidden: document.querySelector('[data-condition-upper]').hidden,
        invalid: operator.getAttribute('aria-invalid'),
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(restored.options, ['words', 'between']);
    assert.match(restored.label, /unsupported/i);
    assert.equal(restored.hidden, false);
    assert.equal(restored.upperHidden, false);
    assert.equal(restored.invalid, 'true');
    assert.deepEqual(restored.submitted, ['texture_type', 'between', '10', '20']);
    const corrected = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'words';
      operator.dispatchEvent(new Event('change'));
      return {hidden: document.querySelector('[data-condition-match]').hidden,
        upperHidden: document.querySelector('[data-condition-upper]').hidden,
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(corrected, {hidden: true, upperHidden: true,
      submitted: ['texture_type', 'words', '10', '']});
  });

  test('switching text presets resets saved comparisons while preserving the entered value', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'elastic_model_name';
      document.querySelector('[name="condition_operator"]').value = 'exact';
      document.querySelector('[name="condition_value"]').value = 'Crystal Plasticity';
    `);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      field.value = 'plastic_model_name';
      field.dispatchEvent(new Event('change'));
      return {hidden: document.querySelector('[data-condition-match]').hidden,
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(state, {hidden: true,
      submitted: ['plastic_model_name', 'words', 'Crystal Plasticity', '']});
  });

  test('mixed text numeric and boolean rows retain ordered query slots after removal', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const add = document.getElementById('addConditionButton');
      const entries = [['elastic_model_name', 'isotropic elasticity'],
        ['grain_count', '50'], ['RVE_continuity', 'false']];
      entries.forEach(([name, value], index) => {
        if (index) add.click();
        const row = document.querySelectorAll('[data-condition-row]')[index];
        const field = row.querySelector('[name="condition_field"]');
        field.value = name;
        field.dispatchEvent(new Event('change'));
        const input = row.querySelector('[name="condition_value"]');
        input.value = value;
        input.dispatchEvent(new Event('input'));
      });
      const form = document.querySelector('form');
      const before = [...new FormData(form).entries()];
      const disabled = [...form.querySelectorAll('[name="condition_operator"]')].some(input => input.disabled);
      document.querySelectorAll('[data-remove-condition]')[1].click();
      window.dispatchEvent(new Event('pageshow'));
      return {before, disabled, after: [...new FormData(form).entries()], valid: form.checkValidity()};
    })()`);
    const textEntries = [['condition_field', 'elastic_model_name'], ['condition_operator', 'words'],
      ['condition_value', 'isotropic elasticity'], ['condition_value_to', '']];
    const booleanEntries = [['condition_field', 'RVE_continuity'], ['condition_operator', 'is'],
      ['condition_value', 'false'], ['condition_value_to', '']];
    assert.deepEqual(state.before, [...textEntries,
      ['condition_field', 'grain_count'], ['condition_operator', 'eq'],
      ['condition_value', '50'], ['condition_value_to', ''], ...booleanEntries]);
    assert.deepEqual(state.after, [...textEntries, ...booleanEntries]);
    assert.equal(state.disabled, false);
    assert.equal(state.valid, true);
  });

  test('number text and boolean transitions restore Match visibility and clear only range bounds', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'grain_count';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '10';
      document.querySelector('[name="condition_value_to"]').value = '20';
    `);
    const states = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      return ['texture_type', 'grain_count', 'texture_type', 'RVE_continuity', 'texture_type'].map(name => {
        field.value = name;
        field.dispatchEvent(new Event('change'));
        const value = document.querySelector('[name="condition_value"]');
        const operator = document.querySelector('[name="condition_operator"]');
        return {hidden: document.querySelector('[data-condition-match]').hidden,
          disabled: operator.disabled, tag: value.tagName,
          submitted: [...new FormData(document.querySelector('form')).values()]};
      });
    })()`);
    assert.deepEqual(states, [
      {hidden: true, disabled: false, tag: 'INPUT', submitted: ['texture_type', 'words', '10', '']},
      {hidden: false, disabled: false, tag: 'INPUT', submitted: ['grain_count', 'eq', '10', '']},
      {hidden: true, disabled: false, tag: 'INPUT', submitted: ['texture_type', 'words', '10', '']},
      {hidden: false, disabled: false, tag: 'SELECT', submitted: ['RVE_continuity', 'is', '10', '']},
      {hidden: true, disabled: false, tag: 'INPUT', submitted: ['texture_type', 'words', '10', '']},
    ]);
  });

  test('boolean choices preserve false and the ordered condition slots after a numeric range', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'grain_count';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '10';
      document.querySelector('[name="condition_value_to"]').value = '20';
    `);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      field.value = 'RVE_continuity';
      field.dispatchEvent(new Event('change'));
      let value = document.querySelector('[name="condition_value"]');
      const initial = {tag: value.tagName, value: value.value,
        label: value.selectedOptions?.[0]?.textContent,
        options: [...document.querySelector('[name="condition_operator"]').options].map(option => option.value)};
      value.value = 'false';
      value.dispatchEvent(new Event('change'));
      document.getElementById('addConditionButton').click();
      const second = document.querySelectorAll('[data-condition-row]')[1];
      second.querySelector('[name="condition_field"]').value = 'grain_count';
      second.querySelector('[name="condition_field"]').dispatchEvent(new Event('change'));
      second.querySelector('[name="condition_value"]').value = '30';
      return {initial, options: value.options ? [...value.options].map(option => [option.value, option.textContent]) : [],
        labeled: value.labels.length === 1, required: value.required,
        upperHidden: document.querySelector('[data-condition-upper]').hidden,
        submitted: [...new FormData(document.querySelector('form')).entries()]};
    })()`);
    assert.equal(state.initial.tag, 'SELECT');
    assert.equal(state.initial.value, '10');
    assert.match(state.initial.label, /unsupported/i);
    assert.deepEqual(state.initial.options, ['is']);
    assert.deepEqual(state.options, [['', 'Choose continuity'], ['true', 'Periodic'], ['false', 'Non-periodic']]);
    assert.equal(state.labeled, true);
    assert.equal(state.required, true);
    assert.equal(state.upperHidden, true);
    assert.deepEqual(state.submitted, [
      ['condition_field', 'RVE_continuity'], ['condition_operator', 'is'],
      ['condition_value', 'false'], ['condition_value_to', ''],
      ['condition_field', 'grain_count'], ['condition_operator', 'eq'],
      ['condition_value', '30'], ['condition_value_to', ''],
    ]);
  });

  test('boolean controls switch to text and back without stale or duplicate submitted values', async t => {
    const evaluate = await page(t);
    const states = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const states = [];
      for (const [name, entered] of [['RVE_continuity', 'false'], ['texture_type', 'random'],
        ['RVE_continuity', 'true'], ['Legacy_Field', 'legacy']]) {
        field.value = name;
        field.dispatchEvent(new Event('change'));
        const value = document.querySelector('[name="condition_value"]');
        const before = value.value;
        value.value = entered;
        value.dispatchEvent(new Event('input'));
        value.dispatchEvent(new Event('change'));
        const operator = document.querySelector('[name="condition_operator"]');
        states.push({tag: value.tagName, before, value: value.value,
          options: [...operator.options].map(option => option.value),
          submitted: [...new FormData(document.querySelector('form')).values()]});
      }
      return states;
    })()`);
    assert.deepEqual(states.map(state => [state.tag, state.before, state.value]), [
      ['SELECT', '', 'false'], ['INPUT', 'false', 'random'],
      ['SELECT', 'random', 'true'], ['INPUT', 'true', 'legacy'],
    ]);
    assert.deepEqual(states.map(state => state.submitted), [
      ['RVE_continuity', 'is', 'false', ''], ['texture_type', 'words', 'random', ''],
      ['RVE_continuity', 'is', 'true', ''], ['Legacy_Field', 'contains', 'legacy', ''],
    ]);
    assert.deepEqual(states[3].options, ['contains', 'exact', 'eq', 'gt', 'gte', 'lt', 'lte', 'between']);
  });

  test('restored invalid boolean values and operators stay visible through pageshow until corrected', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'RVE_continuity';
      document.querySelector('[name="condition_operator"]').value = 'contains';
      document.querySelector('[name="condition_value"]').value = 'False';
      document.querySelector('[data-condition-error]').textContent = 'Choose Periodic or Non-periodic.';
    `);
    const initial = await evaluate(`(() => {
      window.dispatchEvent(new Event('pageshow'));
      window.dispatchEvent(new Event('pageshow'));
      const value = document.querySelector('[name="condition_value"]');
      const operator = document.querySelector('[name="condition_operator"]');
      return {tag: value.tagName, valueLabel: value.selectedOptions?.[0]?.textContent,
        operatorLabel: operator.selectedOptions[0].textContent,
        error: value.getAttribute('aria-invalid'),
        described: value.getAttribute('aria-describedby'),
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.equal(initial.tag, 'SELECT');
    assert.match(initial.valueLabel, /False.*unsupported/i);
    assert.match(initial.operatorLabel, /unsupported/i);
    assert.equal(initial.error, 'true');
    assert.match(initial.described, /error/);
    assert.deepEqual(initial.submitted, ['RVE_continuity', 'contains', 'False', '']);
    const corrected = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'is';
      operator.dispatchEvent(new Event('change'));
      const value = document.querySelector('[name="condition_value"]');
      value.value = 'false';
      value.dispatchEvent(new Event('change'));
      window.dispatchEvent(new Event('pageshow'));
      return {count: document.querySelectorAll('[name="condition_value"]').length,
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(corrected, {count: 1, submitted: ['RVE_continuity', 'is', 'false', '']});
  });

  test('temperature range labels and guidance use kelvin without changing the numeric query', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'global_temperature';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '273.15';
      document.querySelector('[name="condition_value_to"]').value = '300';
    `);
    const state = await evaluate(`(() => {
      const value = document.querySelector('[name="condition_value"]');
      const hint = document.querySelector('[data-condition-hint]');
      return {labels: ['value', 'value_to'].map(name =>
          document.querySelector('[data-condition-label="' + name + '"]').textContent),
        hint: hint.textContent, hintHidden: hint.hidden,
        described: (value.getAttribute('aria-describedby') || '').split(' ').includes(hint.id),
        options: [...document.querySelector('[name="condition_operator"]').options].map(option => option.value),
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(state.labels, ['Minimum (K)', 'Maximum (K)']);
    assert.match(state.hint, /K.*kelvin/i);
    assert.equal(state.hintHidden, false);
    assert.equal(state.described, true);
    assert.deepEqual(state.options, ['eq', 'gt', 'gte', 'lt', 'lte', 'between']);
    assert.deepEqual(state.submitted, ['global_temperature', 'between', '273.15', '300']);
  });

  test('parameter objects offer only word matching and clear an obsolete numeric upper bound', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Grain_Number';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '170000';
      document.querySelector('[name="condition_value_to"]').value = '180000';
    `);
    const states = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const operator = document.querySelector('[name="condition_operator"]');
      const value = document.querySelector('[name="condition_value"]');
      return ['elastic_parameters', 'plastic_parameters'].map(name => {
        field.value = name;
        field.dispatchEvent(new Event('change'));
        return {options: [...operator.options].map(option => option.value),
          submitted: [...new FormData(document.querySelector('form')).values()],
          placeholder: value.placeholder, inputMode: value.inputMode};
      });
    })()`);
    for (const [index, state] of states.entries()) {
      assert.deepEqual(state.options, ['contains']);
      assert.deepEqual(state.submitted,
        [index ? 'plastic_parameters' : 'elastic_parameters', 'contains', '170000', '']);
      assert.equal(state.placeholder, 'Parameter name or value');
      assert.equal(state.inputMode, 'text');
    }
  });

  test('restored parameter equality remains an explicit error until corrected', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'elastic_parameters';
      document.querySelector('[name="condition_operator"]').value = 'exact';
      document.querySelector('[name="condition_value"]').value = 'C11';
    `);
    const initial = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      return {options: [...operator.options].map(option => option.value),
        label: operator.selectedOptions[0].textContent};
    })()`);
    assert.deepEqual(initial.options, ['contains', 'exact']);
    assert.match(initial.label, /unsupported/i);
    const corrected = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'contains';
      operator.dispatchEvent(new Event('change'));
      return [...operator.options].map(option => option.value);
    })()`);
    assert.deepEqual(corrected, ['contains']);
  });

  test('switching a numeric range to text clears only the upper bound', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Grain_Number';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '10';
      document.querySelector('[name="condition_value_to"]').value = '20';
    `);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      field.value = 'Load_Type';
      field.dispatchEvent(new Event('change'));
      const operator = document.querySelector('[name="condition_operator"]');
      const value = document.querySelector('[name="condition_value"]');
      const upper = document.querySelector('[name="condition_value_to"]');
      return {options: [...operator.options].map(option => option.value),
        selected: operator.value, mode: value.inputMode, placeholder: value.placeholder,
        upperHidden: document.querySelector('[data-condition-upper]').hidden,
        upperRequired: upper.required, upperDisabled: upper.disabled,
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(state.options, ['contains', 'exact']);
    assert.equal(state.selected, 'contains');
    assert.equal(state.mode, 'text');
    assert.equal(state.placeholder, 'Text to match');
    assert.equal(state.upperHidden, true);
    assert.equal(state.upperRequired, false);
    assert.equal(state.upperDisabled, false);
    assert.deepEqual(state.submitted, ['Load_Type', 'contains', '10', '']);
  });

  test('a compatible match is preserved when selecting another typed or legacy field', async t => {
    const evaluate = await page(t);
    const states = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const operator = document.querySelector('[name="condition_operator"]');
      const states = [];
      for (const [first, match, second] of [
        ['Grain_Number', 'gte', 'Youngs_Modulus'], ['Load_Type', 'exact', 'Software'],
        ['Grain_Number', 'gte', 'Legacy_Field']
      ]) {
        field.value = first;
        field.dispatchEvent(new Event('change'));
        operator.value = match;
        operator.dispatchEvent(new Event('change'));
        field.value = second;
        field.dispatchEvent(new Event('change'));
        states.push({selected: operator.value,
          options: [...operator.options].map(option => option.value)});
      }
      return states;
    })()`);
    assert.deepEqual(states, [
      {selected: 'gte', options: ['eq', 'gt', 'gte', 'lt', 'lte', 'between']},
      {selected: 'exact', options: ['contains', 'exact']},
      {selected: 'gte', options: ['contains', 'exact', 'eq', 'gt', 'gte', 'lt', 'lte', 'between']},
    ]);
  });

  test('numeric array matches explain that one element is tested without hiding other matches', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const operator = document.querySelector('[name="condition_operator"]');
      const value = document.querySelector('[name="condition_value"]');
      const upper = document.querySelector('[name="condition_value_to"]');
      const hint = document.querySelector('[data-condition-hint]');
      field.value = 'Stress';
      field.dispatchEvent(new Event('change'));
      const textHidden = hint.hidden;
      operator.value = 'between';
      operator.dispatchEvent(new Event('change'));
      const numeric = {hidden: hint.hidden, text: hint.textContent, mode: value.inputMode,
        described: [value, upper].every(input =>
          (input.getAttribute('aria-describedby') || '').split(' ').includes(hint.id)),
        options: [...operator.options].map(option => option.value)};
      operator.value = 'exact';
      operator.dispatchEvent(new Event('change'));
      return {textHidden, numeric, hiddenAgain: hint.hidden,
        descriptionCleared: !value.hasAttribute('aria-describedby')};
    })()`);
    assert.equal(state.textHidden, true);
    assert.equal(state.numeric.hidden, false);
    assert.match(state.numeric.text, /one number.*array/i);
    assert.equal(state.numeric.mode, 'decimal');
    assert.equal(state.numeric.described, true);
    assert.deepEqual(state.numeric.options, ['contains', 'exact', 'eq', 'gt', 'gte', 'lt', 'lte', 'between']);
    assert.equal(state.hiddenAgain, true);
    assert.equal(state.descriptionCleared, true);
  });

  test('an initial restricted operator list can expand when the field type changes', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Load_Type';
      const operator = document.querySelector('[name="condition_operator"]');
      [...operator.options].filter(option => !['contains', 'exact'].includes(option.value))
        .forEach(option => option.remove());
      operator.value = 'exact';
    `);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      field.value = 'Grain_Number';
      field.dispatchEvent(new Event('change'));
      const operator = document.querySelector('[name="condition_operator"]');
      return {selected: operator.value, options: [...operator.options].map(option => option.value)};
    })()`);
    assert.deepEqual(state, {selected: 'eq', options: ['eq', 'gt', 'gte', 'lt', 'lte', 'between']});
  });

  test('initial incompatible matches remain submitted and editable with server errors', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Load_Type';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '10';
      document.querySelector('[name="condition_value_to"]').value = '20';
      document.querySelector('[data-condition-error]').textContent = 'Choose a text match.';
    `);
    const initial = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      const error = document.querySelector('[data-condition-error]');
      return {submitted: [...new FormData(document.querySelector('form')).values()],
        options: [...operator.options].map(option => option.value),
        selectedLabel: operator.selectedOptions[0].textContent,
        error: error.textContent, upperHidden: document.querySelector('[data-condition-upper]').hidden,
        described: [...document.querySelectorAll('input, select')].every(input =>
          input.getAttribute('aria-describedby') === error.id)};
    })()`);
    assert.deepEqual(initial.submitted, ['Load_Type', 'between', '10', '20']);
    assert.deepEqual(initial.options, ['contains', 'exact', 'between']);
    assert.match(initial.selectedLabel, /unsupported/i);
    assert.equal(initial.error, 'Choose a text match.');
    assert.equal(initial.upperHidden, false);
    assert.equal(initial.described, true);

    const corrected = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'exact';
      operator.dispatchEvent(new Event('change'));
      return {options: [...operator.options].map(option => option.value),
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(corrected, {options: ['contains', 'exact'],
      submitted: ['Load_Type', 'exact', '10', '']});
  });

  test('pageshow refreshes field restrictions without changing restored invalid values', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const field = document.querySelector('[name="condition_field"]');
      const value = document.querySelector('[name="condition_value"]');
      field.value = 'Grain_Number';
      document.querySelector('[name="condition_operator"]').value = 'contains';
      value.value = 'steel';
      window.dispatchEvent(new Event('pageshow'));
      window.dispatchEvent(new Event('pageshow'));
      const operator = document.querySelector('[name="condition_operator"]');
      return {options: [...operator.options].map(option => option.value),
        label: operator.selectedOptions[0].textContent,
        submitted: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(state.options, ['eq', 'gt', 'gte', 'lt', 'lte', 'between', 'contains']);
    assert.match(state.label, /unsupported/i);
    assert.deepEqual(state.submitted, ['Grain_Number', 'contains', 'steel', '']);
  });

  test('added rows filter their matches while preserving the four parallel submitted fields', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      document.getElementById('addConditionButton').click();
      const row = document.querySelectorAll('[data-condition-row]')[1];
      const field = row.querySelector('[name="condition_field"]');
      field.value = 'Grain_Number';
      field.dispatchEvent(new Event('change'));
      const data = new FormData(document.querySelector('form'));
      return {options: [...row.querySelector('[name="condition_operator"]').options].map(option => option.value),
        fields: data.getAll('condition_field'), operators: data.getAll('condition_operator'),
        values: data.getAll('condition_value'), upperValues: data.getAll('condition_value_to')};
    })()`);
    assert.deepEqual(state, {options: ['eq', 'gt', 'gte', 'lt', 'lte', 'between'],
      fields: ['', 'Grain_Number'], operators: ['words', 'eq'],
      values: ['', ''], upperValues: ['', '']});
  });

  test('adding stops at the limit and removing a row enables adding again', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const add = document.getElementById('addConditionButton');
      for (let count = 0; count < 12; count++) add.click();
      const limited = [document.querySelectorAll('[data-condition-row]').length, add.disabled];
      document.querySelector('[data-remove-condition]').click();
      return {limited, remaining: document.querySelectorAll('[data-condition-row]').length,
        disabled: add.disabled, status: document.getElementById('conditionStatus').textContent};
    })()`);
    assert.deepEqual(state.limited, [10, true]);
    assert.equal(state.remaining, 9);
    assert.equal(state.disabled, false);
    assert.match(state.status, /removed/i);
  });

  test('new rows have unique labeled controls and move focus to the new field', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      document.getElementById('addConditionButton').click();
      const rows = [...document.querySelectorAll('[data-condition-row]')];
      const controls = [...document.querySelectorAll('input, select')];
      return {ids: controls.map(control => control.id),
        labeled: controls.every(control => control.labels.length === 1),
        focused: rows.length === 2 && document.activeElement === rows[1].querySelector('select'),
        removeLabel: rows.length === 2 ? rows[1].querySelector('button').getAttribute('aria-label') : ''};
    })()`);
    assert.equal(new Set(state.ids).size, 8);
    assert.equal(state.ids.includes(''), false);
    assert.equal(state.labeled, true);
    assert.equal(state.focused, true);
    assert.match(state.removeLabel, /remove.*condition 2/i);
  });

  test('between exposes and requires both bounds only after the row is used', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'between';
      operator.dispatchEvent(new Event('change'));
      return {hidden: document.querySelector('[data-condition-upper]').hidden,
        required: [...document.querySelectorAll('input, select')].map(input => input.required),
        mode: document.querySelector('[name="condition_value"]').inputMode,
        placeholder: document.querySelector('[name="condition_value"]').placeholder};
    })()`);
    assert.equal(state.hidden, false);
    assert.deepEqual(state.required, [true, false, true, true]);
    assert.equal(state.mode, 'decimal');
    assert.match(state.placeholder, /min/i);
  });

  test('leaving between clears its upper bound without dropping its submitted position', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value_to"]').value = '50';
    `);
    const state = await evaluate(`(() => {
      const operator = document.querySelector('[name="condition_operator"]');
      operator.value = 'eq';
      operator.dispatchEvent(new Event('change'));
      const upper = document.querySelector('[name="condition_value_to"]');
      return {value: upper.value, required: upper.required, disabled: upper.disabled,
        submitted: new FormData(document.querySelector('form')).getAll('condition_value_to')};
    })()`);
    assert.deepEqual(state, {value: '', required: false, disabled: false, submitted: ['']});
  });

  test('typing in a row requires its field and value, and clearing it makes it optional', async t => {
    const evaluate = await page(t);
    const states = await evaluate(`(() => {
      const value = document.querySelector('[name="condition_value"]');
      const field = document.querySelector('[name="condition_field"]');
      value.value = 'steel';
      value.dispatchEvent(new Event('input'));
      const used = [field.required, value.required];
      value.value = '';
      value.dispatchEvent(new Event('input'));
      return [used, [field.required, value.required]];
    })()`);
    assert.deepEqual(states, [[true, true], [false, false]]);
  });

  test('removing the final condition leaves one clean optional row', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Grain_Number';
      document.querySelector('[name="condition_value"]').value = '20';
      document.querySelector('[data-condition-error]').textContent = 'Invalid value';
    `);
    const state = await evaluate(`(() => {
      document.querySelector('[data-remove-condition]').click();
      return {count: document.querySelectorAll('[data-condition-row]').length,
        values: [...new FormData(document.querySelector('form')).values()],
        valid: document.querySelector('form').checkValidity(),
        error: document.querySelector('[data-condition-error]').textContent,
        focused: document.activeElement.name};
    })()`);
    assert.deepEqual(state, {count: 1, values: ['', 'words', '', ''],
      valid: true, error: '', focused: 'condition_field'});
  });

  test('restored numeric bounds and server errors survive initialization with array guidance', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Stress';
      document.querySelector('[name="condition_operator"]').value = 'between';
      document.querySelector('[name="condition_value"]').value = '80';
      document.querySelector('[name="condition_value_to"]').value = '10';
      const error = document.querySelector('[data-condition-error]');
      error.hidden = false;
      error.textContent = 'Maximum must be at least the minimum.';
    `);
    const state = await evaluate(`({
      values: [...new FormData(document.querySelector('form')).values()],
      error: document.querySelector('[data-condition-error]').textContent,
      described: [...document.querySelectorAll('input, select')].every(input =>
        input.getAttribute('aria-describedby').split(' ').includes(document.querySelector('[data-condition-error]').id))
    })`);
    assert.deepEqual(state.values, ['Stress', 'between', '80', '10']);
    assert.match(state.error, /Maximum/);
    assert.equal(state.described, true);
  });

  test('an unexpected upper bound stays editable until the user clears it', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Load_Type';
      document.querySelector('[name="condition_operator"]').value = 'contains';
      document.querySelector('[name="condition_value"]').value = 'steel';
      document.querySelector('[name="condition_value_to"]').value = '10';
      const error = document.querySelector('[data-condition-error]');
      error.hidden = false;
      error.textContent = 'An upper bound is only valid for Between.';
    `);
    const initial = await evaluate(`({
      hidden: document.querySelector('[data-condition-upper]').hidden,
      value: document.querySelector('[name="condition_value_to"]').value,
      label: document.querySelector('[data-condition-label="value_to"]').textContent,
      required: document.querySelector('[name="condition_value_to"]').required
    })`);
    assert.equal(initial.hidden, false);
    assert.equal(initial.value, '10');
    assert.match(initial.label, /between only/i);
    assert.equal(initial.required, false);

    const cleared = await evaluate(`(() => {
      const upper = document.querySelector('[name="condition_value_to"]');
      upper.value = '';
      upper.dispatchEvent(new Event('input'));
      return {hidden: document.querySelector('[data-condition-upper]').hidden,
        values: [...new FormData(document.querySelector('form')).values()]};
    })()`);
    assert.deepEqual(cleared, {hidden: true,
      values: ['Load_Type', 'contains', 'steel', '']});
  });

  test('browser validation opens collapsed controls so an incomplete row can be corrected', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const value = document.querySelector('[name="condition_value"]');
      value.value = 'steel';
      value.dispatchEvent(new Event('input'));
      document.querySelector('form').checkValidity();
      return {open: document.getElementById('advancedSearchPanel').classList.contains('show'),
        expanded: document.querySelector('[aria-controls]').getAttribute('aria-expanded')};
    })()`);
    assert.deepEqual(state, {open: true, expanded: 'true'});
  });

  test('both Clear links keep the current panel state and discard search parameters', async t => {
    for (const width of [1440, 390]) {
      const evaluate = await page(t, '', width);
      const state = await evaluate(`(() => {
        const panel = document.getElementById('advancedSearchPanel');
        const toggle = document.querySelector('[aria-controls="advancedSearchPanel"]');
        const links = [...document.querySelectorAll('[data-clear-search]')];
        const urls = () => links.map(link => link.href);
        const initial = urls();
        toggle.setAttribute('aria-expanded', 'true');
        panel.classList.add('show');
        panel.dispatchEvent(new Event('show.bs.collapse'));
        const opened = urls();
        links.forEach(link => {
          link.href = 'https://search.test/search/?keyword=copper&condition_value=50#old';
          link.addEventListener('click', event => event.preventDefault());
          link.click();
        });
        const clicked = urls();
        const stillOpen = panel.classList.contains('show');
        toggle.setAttribute('aria-expanded', 'false');
        panel.classList.remove('show');
        panel.dispatchEvent(new Event('hide.bs.collapse'));
        return {initial, opened, clicked, stillOpen, closed: urls()};
      })()`);
      const closed = Array(2).fill('https://search.test/search/');
      const opened = Array(2).fill('https://search.test/search/?advanced=1');
      assert.deepEqual(state, {initial: closed, opened, clicked: opened, stillOpen: true, closed});
    }
  });

  test('Clear uses restored and transitioning panel states without validating incomplete conditions', async t => {
    const evaluate = await page(t);
    const state = await evaluate(`(() => {
      const panel = document.getElementById('advancedSearchPanel');
      const toggle = document.querySelector('[aria-controls="advancedSearchPanel"]');
      const links = [...document.querySelectorAll('[data-clear-search]')];
      toggle.setAttribute('aria-expanded', 'true');
      window.dispatchEvent(new Event('pageshow'));
      const restored = links.map(link => link.href);
      panel.className = 'collapsing';
      const value = document.querySelector('[name="condition_value"]');
      value.value = 'unfinished';
      value.dispatchEvent(new Event('input'));
      let validations = 0;
      document.querySelector('form').addEventListener('invalid', () => validations++, true);
      links[0].addEventListener('click', event => event.preventDefault());
      links[0].click();
      const opening = links[0].href;
      toggle.setAttribute('aria-expanded', 'false');
      links[0].click();
      return {restored, opening, closing: links[0].href, validations};
    })()`);
    assert.deepEqual(state, {
      restored: Array(2).fill('https://search.test/search/?advanced=1'),
      opening: 'https://search.test/search/?advanced=1',
      closing: 'https://search.test/search/', validations: 0,
    });
  });

  test('advanced footer actions stay usable inside their form at desktop and mobile widths', async t => {
    const template = readFileSync(join(__dirname, '../../templates/pages/search.html'), 'utf8');
    const styles = template.match(/<style>([\s\S]*?)<\/style>/)[1];
    const footer = template.match(/<div class="advanced-search-actions">[\s\S]*?<\/div>/)?.[0] || '';
    const bootstrap = readFileSync(join(__dirname, '../../static/assets/css/plugins/bootstrap.min.css'), 'utf8');
    for (const width of [1440, 390, 320]) {
      const evaluate = await page(t, '', width);
      const html = `<style>${bootstrap}${styles}</style>
        <form id="search" style="margin:20px;max-width:980px">${footer}</form>`;
      const state = await evaluate(`(() => {
        document.body.innerHTML = ${JSON.stringify(html)};
        const form = document.getElementById('search');
        const search = form.querySelector('button[type="submit"]');
        const clear = form.querySelector('a');
        if (!search || !clear) return {actionsPresent: false};
        const bounds = element => {
          const rect = element.getBoundingClientRect();
          return {width: rect.width, height: rect.height, left: rect.left, right: rect.right};
        };
        return {actionsPresent: true, belongsToForm: search.form === form,
          search: bounds(search), clear: bounds(clear),
          pageOverflow: document.documentElement.scrollWidth > innerWidth};
      })()`);
      assert.equal(state.actionsPresent, true, `${width}px: missing footer controls`);
      assert.equal(state.belongsToForm, true);
      for (const button of [state.search, state.clear]) {
        assert.ok(button.height >= 44 && button.width >= 70, `${width}px: ${JSON.stringify(button)}`);
        assert.ok(button.left >= 0 && button.right <= width);
      }
      assert.equal(state.pageOverflow, false);
    }
  });

  test('common filters preserve reading order and fit desktop rows or a mobile stack', async t => {
    const template = readFileSync(join(__dirname, '../../templates/pages/search.html'), 'utf8');
    const styles = template.match(/<style>([\s\S]*?)<\/style>/)[1];
    const section = template.match(/<section[^>]*aria-labelledby="commonFiltersTitle"[\s\S]*?<\/section>/)[0]
      .replace(/\{% if [^%]* %\}selected\{% endif %\}/g, '')
      .replace(/\{\{[^}]*\}\}/g, '');
    const bootstrap = readFileSync(join(__dirname, '../../static/assets/css/plugins/bootstrap.min.css'), 'utf8');
    const names = ['identifier', 'access', 'owner', 'creator', 'software', 'phase', 'title'];
    const populated = {identifier: 'a'.repeat(64), access: 'shared_with_me',
      owner: 'researcher.with.a.long.username', creator: 'Materials Research Group',
      software: 'DAMASK 3.0', phase: 'Ferrite', title: 'A long materials simulation title'};
    for (const width of [1440, 1024, 768, 390, 320]) {
      const evaluate = await page(t, '', width);
      for (const values of [{}, populated]) {
        const html = `<style>${bootstrap}${styles}</style>
          <form class="advanced-panel" style="margin:20px;max-width:980px">${section}</form>`;
        const state = await evaluate(`(() => {
          document.body.innerHTML = ${JSON.stringify(html)};
          const form = document.querySelector('form');
          const values = ${JSON.stringify(values)};
          const bounds = element => {
            const rect = element.getBoundingClientRect();
            return {left: rect.left, right: rect.right, top: rect.top,
              bottom: rect.bottom, width: rect.width, height: rect.height};
          };
          const fields = [...form.querySelectorAll('input, select')].map(control => {
            control.value = values[control.name] || '';
            return {name: control.name, id: control.id,
              label: control.labels[0]?.textContent.trim(), labelCount: control.labels.length,
              labelBounds: bounds(control.labels[0]), control: bounds(control),
              column: bounds(control.parentElement)};
          });
          return {fields, values: Object.fromEntries(new FormData(form)),
            row: bounds(form.querySelector('.row')),
            pageOverflow: document.documentElement.scrollWidth > innerWidth};
        })()`);
        const context = `${width}px/${values.identifier ? 'populated' : 'empty'}`;
        assert.deepEqual(state.fields.map(field => field.name), names, context);
        assert.deepEqual(state.fields.map(field => field.id), names.map(name => `id_${name}`), context);
        assert.deepEqual(state.fields.map(field => field.label),
          ['Identifier', 'Access', 'Owner (uploaded by)', 'Creator', 'Software', 'Phase', 'Title'], context);
        assert.deepEqual(state.values, Object.fromEntries(names.map(name => [name, values[name] || ''])), context);
        assert.equal(state.pageOverflow, false, context);
        for (const [index, field] of state.fields.entries()) {
          assert.equal(field.labelCount, 1, `${context}/${field.name}: associated label`);
          assert.ok(field.control.height >= 44, `${context}/${field.name}: usable control height`);
          assert.ok(field.control.left >= 0 && field.control.right <= width,
            `${context}/${field.name}: control fits viewport`);
          assert.ok(field.labelBounds.bottom <= field.control.top,
            `${context}/${field.name}: label does not overlap control`);
          assert.ok(field.labelBounds.right <= field.column.right,
            `${context}/${field.name}: label fits column`);
          const fraction = width < 768 ? 1 : field.name === 'title' ? 0.5 : 0.25;
          assert.ok(Math.abs(field.column.width - state.row.width * fraction) < 1,
            `${context}/${field.name}: column width ${field.column.width}`);
          const rowStart = width < 768 ? index : index < 4 ? 0 : 4;
          assert.ok(Math.abs(field.control.top - state.fields[rowStart].control.top) < 1,
            `${context}/${field.name}: aligned row`);
          if (index > 0) {
            const previous = state.fields[index - 1];
            if (width < 768 || index === 4) {
              assert.ok(field.labelBounds.top > previous.control.bottom,
                `${context}/${field.name}: follows previous row`);
            } else {
              assert.ok(field.control.left > previous.control.right,
                `${context}/${field.name}: follows previous column`);
            }
          }
        }
      }
    }
  });

  test('long identifier errors wrap inside the upload page on mobile', async t => {
    const template = readFileSync(join(__dirname, '../../templates/pages/upload.html'), 'utf8');
    const styles = [...template.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(match => match[1]).join('\n');
    const bootstrap = readFileSync(join(__dirname, '../../static/assets/css/plugins/bootstrap.min.css'), 'utf8');
    const evaluate = await page(t, '', 390);
    const html = `<style>${bootstrap}${styles}</style><div class="pc-content" style="margin:15px">
      <div id="upload-results">
      <div class="alert alert-danger">file.json data object 2: identifier "${'a'.repeat(64)}"
      already exists. Please remove the duplicate.</div></div></div>`;
    const layout = await evaluate(`(() => {
      document.body.innerHTML = ${JSON.stringify(html)};
      const alert = document.querySelector('.alert');
      return {page: document.documentElement.scrollWidth, viewport: innerWidth,
        content: alert.scrollWidth, available: alert.clientWidth};
    })()`);
    assert.ok(layout.page <= layout.viewport, JSON.stringify(layout));
    assert.ok(layout.content <= layout.available, JSON.stringify(layout));
  });

  test('record names remain visible beside long upload metadata on desktop and mobile', async t => {
    const bootstrap = readFileSync(join(__dirname, '../../static/assets/css/plugins/bootstrap.min.css'), 'utf8');
    for (const [filename, selector] of [['data_list.html', 'summary-value'], ['search.html', 'summary-title-row']]) {
      const template = readFileSync(join(__dirname, '../../templates/pages', filename), 'utf8');
      const styles = [...template.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(match => match[1]).join('\n');
      for (const width of [1440, 390]) {
        const evaluate = await page(t, '', width);
        const owner = filename === 'search.html' ? 'researcher'.repeat(16) : 'browser-qa-viewer';
        const html = `<style>${bootstrap}${styles}</style>
          <div style="width:min(700px, calc(100vw - 160px));margin:20px">
            <div class="${selector}"><span class="main">${'a'.repeat(64)}</span>
              <span class="summary-separator">&nbsp;|&nbsp;</span>
              <span class="time">${owner} | 2026-09-17 10:20</span>
            </div></div>`;
        const layout = await evaluate(`(() => {
          document.body.innerHTML = ${JSON.stringify(html)};
          const row = document.querySelector('.${selector}');
          const main = row.querySelector('.main').getBoundingClientRect();
          const time = row.querySelector('.time').getBoundingClientRect();
          return {nameWidth: main.width, timeRight: time.right, rowRight: row.getBoundingClientRect().right,
            sameLine: Math.abs(main.y - time.y) < 2,
            pageOverflow: document.documentElement.scrollWidth > innerWidth};
        })()`);
        assert.ok(layout.nameWidth > 100, `${filename}/${width}: ${JSON.stringify(layout)}`);
        assert.ok(layout.timeRight <= layout.rowRight + 1, `${filename}/${width}: ${JSON.stringify(layout)}`);
        assert.equal(layout.sameLine, width > 768, `${filename}/${width}: ${JSON.stringify(layout)}`);
        assert.equal(layout.pageOverflow, false);
      }
    }
  });

  test('live feed shows the full public total and updates it independently of its limited list', async t => {
    const template = readFileSync(join(__dirname, '../../templates/pages/search.html'), 'utf8');
    const source = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)]
      .map(match => match[1]).find(script => script.includes('refreshLiveDataObjects'));
    const evaluate = await page(t);
    await evaluate(`
      document.body.innerHTML = '<div id="liveDataCount" hidden></div>' +
        '<div id="liveDataSubtitle"></div><div id="liveDataStatus"></div><div id="liveDataList"></div>';
      window.livePayload = {total_count: 25, objects: Array.from({length: 20}, (_, id) => ({
        id, display_name: 'Public dataset ' + id, identifier: 'dataset-' + id,
        owner: 'researcher', uploaded_at: '2026-09-17 10:20', detail_url: '#data-' + id,
        access: 'Public', access_badges: ['Public']
      }))};
      window.fetch = async () => ({ok: true, json: async () => window.livePayload});
      window.setInterval = callback => { window.pollLiveData = callback; };
      ${source}
      document.dispatchEvent(new Event('DOMContentLoaded'));
    `);
    let state = await evaluate(`({count: document.getElementById('liveDataCount').textContent,
      hidden: document.getElementById('liveDataCount').hidden,
      rows: document.querySelectorAll('.live-data-item').length,
      accessLabels: [...document.querySelectorAll('.live-data-item')]
        .some(row => row.querySelector('.live-data-badge')),
      subtitle: document.getElementById('liveDataSubtitle').textContent})`);
    assert.equal(state.count, '25 total');
    assert.equal(state.hidden, false);
    assert.equal(state.rows, 20);
    assert.equal(state.accessLabels, false);
    assert.equal(state.subtitle, 'Latest 20 public uploads');

    await evaluate('window.livePayload = {total_count: 0, objects: []}; window.pollLiveData();');
    state = await evaluate(`({count: document.getElementById('liveDataCount').textContent,
      rows: document.querySelectorAll('.live-data-item').length,
      empty: document.querySelector('.live-data-empty')?.textContent})`);
    assert.equal(state.count, '0 total');
    assert.equal(state.rows, 0);
    assert.equal(state.empty, 'No public data objects yet');
  });

  test('live data rows stay compact and long lists scroll at desktop and mobile widths', async t => {
    const searchTemplate = readFileSync(join(__dirname, '../../templates/pages/search.html'), 'utf8');
    const searchStyles = searchTemplate.match(/<style>([\s\S]*?)<\/style>/)[1];
    const bootstrapStyles = readFileSync(join(__dirname, '../../static/assets/css/plugins/bootstrap.min.css'), 'utf8');
    for (const width of [1440, 390]) {
      const evaluate = await page(t, '', width);
      for (const count of [2, 20]) {
        const item = `<a class="live-data-item" href="#data">
          <div class="live-data-main">
            <div class="live-data-name">Example materials simulation dataset with a long descriptive title</div>
            <div class="live-data-meta">Uploaded by a researcher · 2026-09-16 · JSON simulation data</div>
          </div>
        </a>`;
        const html = `<style>${bootstrapStyles}${searchStyles}</style>
          <div class="card search-bar-card search-live-expanded"><div class="card-body">
            <div class="search-hero-wrap"><div class="live-data-panel">
              <div class="live-data-list">${item.repeat(count)}</div>
            </div></div>
          </div></div>`;
        const layout = await evaluate(`(() => {
          document.body.innerHTML = ${JSON.stringify(html)};
          const list = document.querySelector('.live-data-list');
          return {rowHeights: [...document.querySelectorAll('.live-data-item')]
              .map(row => row.getBoundingClientRect().height),
            listHeight: list.getBoundingClientRect().height,
            scrolls: list.scrollHeight > list.clientHeight,
            widths: [document.documentElement, list, list.firstElementChild]
              .map(element => ({client: element.clientWidth, scroll: element.scrollWidth})),
            horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth ||
              list.scrollWidth > list.clientWidth};
        })()`);
        assert.equal(layout.rowHeights.every(height => height <= 100), true,
          `${width}px/${count} rows: row heights ${layout.rowHeights}`);
        assert.ok(layout.listHeight <= (count === 2 ? 220 : 320),
          `${width}px/${count} rows: list height ${layout.listHeight}`);
        assert.equal(layout.scrolls, count === 20, `${width}px/${count} rows: list scrolling`);
        assert.equal(layout.horizontalOverflow, false,
          `${width}px/${count} rows: horizontal overflow ${JSON.stringify(layout.widths)}`);
      }
    }
  });
});
