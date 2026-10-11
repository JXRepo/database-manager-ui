const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const root = join(__dirname, '../..');
const chromiumPath = process.env.CHROMIUM_BIN || '/usr/bin/chromium';

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

describe('whole RVE tensor panel in Chromium', {timeout: 30000}, () => {
  let browser;
  let profile;
  let socket;
  let send;

  before(async () => {
    assert.ok(existsSync(chromiumPath), `Chromium is required: ${chromiumPath}`);
    profile = mkdtempSync(join(tmpdir(), 'getting-started-test-'));
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

  async function page(t, items, units = {Stress: 'MPa', Strain: 1}) {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}, sessionId);
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    const template = readFileSync(join(root, 'templates/pages/data_detail.html'), 'utf8');
    const panelHTML = template.match(/<section class="bc-tensor-panel"[\s\S]*?<\/section>/)[0];
    const pure = readFileSync(join(root, 'static/assets/js/mechanical-bc-tensor.js'), 'utf8').replaceAll('export ', '');
    const panel = readFileSync(join(root, 'static/assets/js/mechanical-bc-tensor-panel.js'), 'utf8')
      .replace(/^import .*;\n/, '').replaceAll('export ', '');
    await evaluate(`document.body.innerHTML = ${JSON.stringify(panelHTML)}; ${pure}\n${panel}
      window.supplied = ${JSON.stringify(items)};
      window.original = JSON.stringify(supplied);
      createTensorPanel(document.querySelector('[data-bc-tensor-panel]'), supplied, ${JSON.stringify(units)},
        view => { window.view = view; }, () => {});`);
    return evaluate;
  }

  function condition(type = 'stress', loads) {
    return {is_tensor_load: true, loading_type: type, loading_mode: 'cyclic', tensor_loads: loads || [
      {magnitude: {xx: 100, yy: -50, zz: 0, xy: 1.005, yx: -2, yz: 0, xz: 0}, step: 0,
        details: [{key: 'step', display: '0'}]},
      {magnitude: {xx: -10, yy: 0, zz: 0, xy: 0, yz: 0, xz: 0}, step: 10001,
        details: [{key: 'step', display: '10001'}]},
    ]};
  }

  test('loads, matrix selection, filters and clearing stay synchronized without changing data', async t => {
    const ev = await page(t, [condition()]);
    assert.equal(await ev('document.querySelector("[data-tensor-heading]").textContent'), 'Whole cube · Stress (MPa)');
    assert.equal(await ev('document.querySelector("[data-tensor-condition]").closest("label").hidden'), true);
    assert.equal(await ev('document.querySelector("[data-tensor-options]").open'), false);
    assert.equal(await ev('document.querySelector("[data-tensor-matrix]").checkVisibility()'), true);
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.filter'), 'all');
    assert.equal(await ev('document.querySelector("[data-tensor-filter=all]").getAttribute("aria-pressed")'), 'true');
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected).map(a => a.component)'),
      ['xx', 'xx', 'xy', 'xy', 'yx', 'yx', 'yy', 'yy']);
    assert.equal(await ev('document.querySelector("[data-tensor-description]").textContent'), 'All supplied components');
    assert.equal(await ev('document.querySelector("[data-tensor-load]").closest("details")'), null);
    assert.equal(await ev('document.querySelector("[data-component=xy] strong").textContent'), '1.01');
    assert.equal(await ev('document.querySelector("[data-component=xy]").title'), 'xy: 1.005 MPa');
    await ev('document.querySelector("[data-component=xy]").click()');
    assert.equal(await ev('view.selected'), 'xy');
    assert.equal(await ev('document.activeElement.dataset.component'), 'xy');
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected).map(a => a.component)'), ['xy', 'xy']);
    assert.match(await ev('document.querySelector("[data-tensor-status]").textContent'), /^xy:/);
    assert.equal(await ev('document.querySelector("[data-tensor-status]").title'), 'xy: 1.005 MPa');
    await ev('document.querySelector("[data-component=xy]").click()');
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.filter'), 'all');
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected).map(a => a.component)'),
      ['xx', 'xx', 'xy', 'xy', 'yx', 'yx', 'yy', 'yy']);
    await ev('document.querySelector("[data-tensor-options] > summary").click()');
    await ev('document.querySelector("[data-tensor-filter=normal]").click()');
    assert.equal(await ev('view.selected'), '');
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter).map(a => a.component)'), ['xx', 'xx', 'yy', 'yy']);
    await ev('document.querySelector("[data-tensor-slider]").value="1";document.querySelector("[data-tensor-slider]").dispatchEvent(new Event("input"))');
    assert.equal(await ev('view.load.step'), 10001);
    assert.equal(await ev('document.querySelector("[data-tensor-load]").value'), '1');
    assert.equal(await ev('document.querySelector("[data-component=yx] strong").textContent'), '—');
    assert.equal(await ev('document.querySelector("[data-component=yx]").disabled'), true);
    await ev('document.querySelector("[data-component=xx]").click();document.querySelector("[data-tensor-clear]").click()');
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('document.querySelector("[data-tensor-filter=normal]").getAttribute("aria-pressed")'), 'true');
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('strain shape is explicit, can be disabled, and cannot average conflicting reciprocal values', async t => {
    const strain = condition('strain');
    strain.tensor_loads[1].magnitude = {xx: -10, yy: 5, zz: 0, xy: 2, yx: 2, yz: 0, zy: 0, xz: 0, zx: 0};
    const ev = await page(t, [strain]);
    await ev('document.querySelector("[data-tensor-options] > summary").click()');
    assert.equal(await ev('document.querySelector("[data-tensor-shape]").disabled'), true);
    assert.equal(await ev('view.shapeMatrix'), null);
    await ev('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('document.querySelector("[data-tensor-shape]").disabled'), false);
    assert.equal(await ev('view.shapeMatrix'), null);
    await ev('document.querySelector("[data-tensor-shape]").click()');
    assert.ok(await ev('view.shapeMatrix[0][0] < 0'));
    assert.ok(await ev('view.shapeMatrix[1][1] > 0 && view.shapeMatrix[0][1] > 0'));
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.filter'), 'all');
    assert.match(await ev('document.querySelector("[data-tensor-kind]").textContent'), /^Normalized small-strain illustration/);
    await ev('document.querySelector("[data-tensor-options] > summary").click()');
    assert.ok(await ev('view.shapeMatrix[0][0] < 0'));
    assert.equal(await ev('document.querySelector("[data-tensor-shape]").checked'), true);
    assert.match(await ev('document.querySelector("[data-tensor-note]").textContent'), /Assumes tensor shear and symmetry/);
    await ev('document.querySelector("[data-component=yy]").click()');
    assert.equal(await ev('view.selected'), 'yy');
    assert.equal(await ev('view.shapeMatrix'), null);
    assert.equal(await ev('document.querySelector("[data-tensor-shape]").checked'), false);
    assert.match(await ev('document.querySelector("[data-tensor-kind]").textContent'), /^Strain direction guides/);
    await ev('document.querySelector("[data-tensor-options] > summary").click();document.querySelector("[data-tensor-shape]").click();document.querySelector("[data-tensor-shape]").click()');
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.filter'), 'all');
    await ev('document.querySelector("[data-tensor-shape]").click()');
    await ev('document.querySelector("[data-tensor-load]").value="0";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.shapeMatrix'), null);
    assert.equal(await ev('document.querySelector("[data-tensor-shape]").checked'), false);
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('multiple tensor conditions use their own load entries and units', async t => {
    const ev = await page(t, [{is_defined: true}, condition(), condition('strain', [])]);
    assert.equal(await ev('document.querySelector("[data-tensor-condition]").closest("label").hidden'), false);
    await ev('document.querySelector("[data-tensor-options] > summary").click()');
    await ev('document.querySelector("[data-component=xx]").click();document.querySelector("[data-tensor-condition]").value="2";document.querySelector("[data-tensor-condition]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.itemIndex'), 2);
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('document.querySelector("[data-tensor-heading]").textContent'), 'Whole cube · Strain (-)');
    assert.equal(await ev('document.querySelector("[data-tensor-slider]").disabled'), true);
    assert.equal(await ev('document.querySelector("[data-tensor-position]").textContent'), 'No load entries supplied');
  });

  test('all components follow supplied load order while explicit selection persists across absent or invalid values', async t => {
    const loads = [
      {magnitude: {yy: 0, yx: -2.345, xx: 10, zz: 0}, step: 7, details: [{key: 'step', display: '7'}]},
      {magnitude: {xx: -10, zz: 0}, step: 3, details: [{key: 'step', display: '3'}]},
      {magnitude: {xx: 10, yx: null}, step: 123456789012345, details: [{key: 'step', display: '123456789012345'}]},
    ];
    const ev = await page(t, [condition('stress', loads), condition('stress', [{magnitude: {zz: 0, xx: 0}}])]);
    assert.equal(await ev('view.selected'), '');
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected).map(a => a.component)'), ['xx', 'xx', 'yx', 'yx']);
    await ev('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.load.step'), 3);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected).map(a => a.component)'), ['xx', 'xx']);
    await ev('document.querySelector("[data-tensor-load]").value="0";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"));document.querySelector("[data-component=yx]").click()');
    assert.equal(await ev('view.selected'), 'yx');
    assert.equal(await ev('document.querySelector("[data-tensor-description]").textContent'), 'yx · Shear · Y direction on ±X faces');
    assert.equal(await ev('document.querySelector("[data-tensor-status]").title'), 'yx: -2.345 MPa');
    await ev('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.selected'), 'yx');
    assert.equal(await ev('view.load.step'), 3);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected)'), []);
    assert.equal(await ev('document.querySelector("[data-component=yx]").getAttribute("aria-pressed")'), 'true');
    assert.match(await ev('document.querySelector("[data-tensor-status]").textContent'), /Not supplied in this load entry/);
    await ev('document.querySelector("[data-tensor-load]").value="2";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.selected'), 'yx');
    assert.match(await ev('document.querySelector("[data-tensor-status]").textContent'), /Invalid value/);
    assert.match(await ev('document.querySelector("[data-tensor-position]").textContent'), /123456789012345$/);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected)'), []);
    await ev('document.querySelector("[data-tensor-condition]").value="1";document.querySelector("[data-tensor-condition]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.selected'), '');
    assert.equal(await ev('view.filter'), 'all');
    assert.match(await ev('document.querySelector("[data-tensor-status]").textContent'), /no nonzero components/);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude, view.filter, view.selected)'), []);
    assert.equal(await ev('document.querySelector("[data-tensor-load]").closest("label").hidden'), true);
    assert.equal(await ev('document.querySelector("[data-tensor-slider]").closest(".bc-tensor-progress").hidden'), true);
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('invalid uploaded objects and markup stay harmless and never become arrows', async t => {
    const bad = {toString: {nested: true}};
    const ev = await page(t, [condition('strain', [{magnitude: {xx: bad, xy: '<img src=x onerror=alert(1)>', yy: true, zz: null}, details: []}])], {Strain: bad});
    assert.equal(await ev('document.querySelector("[data-tensor-matrix] img")'), null);
    assert.equal(await ev('document.querySelectorAll("[data-tensor-matrix] button:disabled").length'), 9);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude)'), []);
    assert.match(await ev('document.querySelector("[data-tensor-heading]").textContent'), /unit not supplied/);
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });
});
