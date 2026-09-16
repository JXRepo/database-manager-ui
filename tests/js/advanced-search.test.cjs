const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const chromiumPath = process.env.CHROMIUM_BIN || '/usr/bin/chromium';
const scriptPath = join(__dirname, '../../static/assets/js/advanced-search.js');

function conditionRow() {
  return `<fieldset data-condition-row>
    <legend data-condition-legend>Data field condition</legend>
    <label data-condition-label="field">Data field</label>
    <select name="condition_field">
      <option value="">Choose a field</option>
      <option value="Grain_Number">Grain_Number</option>
      <option value="Load_Type">Load_Type</option>
    </select>
    <label data-condition-label="operator">Match</label>
    <select name="condition_operator">
      <option value="contains">Contains words</option><option value="exact">Equals text</option>
      <option value="eq">Equals number</option><option value="gt">Greater than</option>
      <option value="gte">At least</option><option value="lt">Less than</option>
      <option value="lte">At most</option><option value="between">Between</option>
    </select>
    <label data-condition-label="value">Value</label><input name="condition_value">
    <div data-condition-upper>
      <label data-condition-label="value_to">Maximum (Between only)</label>
      <input name="condition_value_to">
    </div>
    <button type="button" data-remove-condition hidden>Remove</button>
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

  async function page(t, setup = '') {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', {expression, returnByValue: true}, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
      return response.result.value;
    };
    const html = `<form id="advancedSearchForm">
      <button type="button" aria-controls="advancedSearchPanel" aria-expanded="false">Advanced Search</button>
      <div id="advancedSearchPanel" class="collapse">
        <div id="dataFieldConditions" data-max-conditions="10">${conditionRow()}</div>
        <button type="button" id="addConditionButton" hidden>Add condition</button>
        <p id="conditionStatus" role="status"></p>
        <template id="conditionRowTemplate">${conditionRow()}</template>
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
      ['condition_field', ''], ['condition_operator', 'contains'],
      ['condition_value', ''], ['condition_value_to', ''],
    ]);
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
    assert.deepEqual(state, {count: 1, values: ['', 'contains', '', ''],
      valid: true, error: '', focused: 'condition_field'});
  });

  test('restored numeric bounds and server errors survive initialization', async t => {
    const evaluate = await page(t, `
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
        input.getAttribute('aria-describedby') === document.querySelector('[data-condition-error]').id)
    })`);
    assert.deepEqual(state.values, ['', 'between', '80', '10']);
    assert.match(state.error, /Maximum/);
    assert.equal(state.described, true);
  });

  test('an unexpected upper bound stays editable until the user clears it', async t => {
    const evaluate = await page(t, `
      document.querySelector('[name="condition_field"]').value = 'Load_Type';
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
});
