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
    await send('Emulation.setEmulatedMedia', {features: [{name: 'prefers-reduced-motion', value: 'reduce'}]}, sessionId);
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
      .replace(/^import .*;\n/gm, '').replaceAll('export ', '');
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

  test('combines arbitrary action groups and shear pairs instead of replacing one selection', async t => {
    const ev = await page(t, [condition()]);
    assert.deepEqual(await ev('Array.from(view.selected)'), ['xx','xy','yx','yy']);
    await ev('document.querySelector("[data-tensor-clear]").click();document.querySelector("[data-tensor-filter=push]").click()');
    assert.deepEqual(await ev('Array.from(view.selected)'), ['yy']);
    await ev('document.querySelector("[data-tensor-filter=slide]").click()');
    assert.deepEqual(await ev('Array.from(view.selected).sort()'), ['xy','yx','yy']);
    await ev('document.querySelector("[data-tensor-filter=pull]").click()');
    assert.deepEqual(await ev('Array.from(view.selected).sort()'), ['xx','xy','yx','yy']);
    await ev('document.querySelector("[data-tensor-filter=push]").click()');
    assert.deepEqual(await ev('Array.from(view.selected).sort()'), ['xx','xy','yx']);
    assert.equal(await ev('document.querySelector("[data-component=yy] strong").textContent'), '-50.00');
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('compact controls omit the numerical preview and keep the complete matrix', async t => {
    const ev = await page(t, [condition()]);
    assert.equal(await ev('document.querySelectorAll("[data-tensor-mode],[data-tensor-calculated],[data-tensor-scale]").length'), 0);
    assert.equal(await ev('document.querySelectorAll("[data-component]").length'), 9);
    assert.equal(await ev('document.querySelector("[data-tensor-description]")'), null);
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  const complete = {xx: .02, yy: -.01, zz: 0, xy: .003, yx: .003, xz: 0, zx: 0, yz: 0, zy: 0};

  test('matrix cells independently combine normal strains and toggle reciprocal shear together', async t => {
    const ev = await page(t, [condition('strain', [{magnitude: complete}])]);
    assert.equal(await ev('document.querySelectorAll("svg,canvas,[data-tensor-example-host]").length'), 0);
    await ev('document.querySelector("[data-component=xy]").click()');
    assert.deepEqual(await ev('Array.from(view.selected)'), ['xx','yy']);
    assert.equal(await ev('document.activeElement.dataset.component'), 'xy');
    await ev('document.querySelector("[data-component=xx]").click();document.querySelector("[data-component=yx]").click()');
    assert.deepEqual(await ev('Array.from(view.selected).sort()'), ['xy','yx','yy']);
    assert.equal(await ev('document.querySelector("[data-component=xx] strong").textContent'), '0.02');
    assert.equal(await ev('document.querySelector("[data-component=yx]").title'), 'yx: 0.003 - · Selected');
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('only supplementary fields appear in collapsed load details and uploaded text stays escaped', async t => {
    const ev = await page(t, [condition('stress', [{magnitude: {xx: 15}, details: [
      {key: 'magnitude', display: '{xx: 15.00}'},
      {key: 'step', display: '0.0123456789'},
      {key: 'frequency', display: '2.00'},
      {key: '<img src=x>', display: '<b>raw text</b>'},
    ]}])]);
    assert.equal(await ev('document.querySelector("[data-tensor-details]").open'), false);
    assert.equal(await ev('document.querySelector("[data-tensor-details]").hidden'), false);
    assert.deepEqual(await ev('Array.from(document.querySelectorAll("[data-tensor-details-list] dt")).map(n=>n.textContent)'), ['step','frequency','<img src=x>']);
    assert.equal(await ev('document.querySelector("[data-tensor-details-list] dd").textContent'), '0.0123456789');
    assert.equal(await ev('document.querySelectorAll("[data-tensor-details-list] img,[data-tensor-details-list] b").length'), 0);
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('load details retain magnitude content that the nine matrix cells cannot represent', async t => {
    const ev = await page(t, [condition('stress', [
      {magnitude: {xx: 15, extra: 9}, details: [{key: 'magnitude', display: '{xx: 15.00, extra: 9.00}'}]},
      {magnitude: [1, 2], details: [{key: 'magnitude', display: '[1.00, 2.00]'}]},
    ])]);
    assert.match(await ev('document.querySelector("[data-tensor-details-list]").textContent'), /extra: 9.00/);
    await ev('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('document.querySelector("[data-tensor-details-list] dd").textContent'), '[1.00, 2.00]');
    assert.equal(await ev('JSON.stringify(supplied) === original'), true);
  });

  test('records retain selected keys, exact supplied order and missing values without inventing components', async t => {
    const loads = [
      {magnitude: {xx:10,yx:-2.345},details:[{key:'step',display:'7'}]},
      {magnitude: {xx:-10},details:[{key:'step',display:'3'}]},
      {magnitude: {xx:10,yx:null},details:[{key:'step',display:'123456789012345'}]},
      {magnitude: {xx:0}},
    ];
    const ev = await page(t,[condition('stress',loads)]);
    assert.deepEqual(await ev('Array.from(document.querySelector("[data-tensor-load]").options).map(o=>o.textContent)'),
      ['Record 1 of 4 · step 7','Record 2 of 4 · step 3','Record 3 of 4 · step 123456789012345','Record 4 of 4']);
    assert.equal(await ev('document.querySelector("[data-component=yx] strong").textContent'),'-2.35');
    await ev('document.querySelector("[data-tensor-load]").value="1";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.deepEqual(await ev('Array.from(view.selected)'),['xx','yx']);
    assert.match(await ev('document.querySelector("[data-tensor-status]").textContent'),/missing or invalid.*yx/);
    assert.deepEqual(await ev('tensorArrows(view.load.magnitude,view.filter,view.selected).map(a=>[a.component,a.value])'),[['xx',-10],['xx',-10]]);
    assert.equal(await ev('view.actionLabel'), 'Push');
    assert.equal(await ev('document.querySelector("[data-component=yx]").disabled'),true);
    await ev('document.querySelector("[data-tensor-load]").value="2";document.querySelector("[data-tensor-load]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('JSON.stringify(supplied) === original'),true);
  });

  test('different reciprocal values remain independently selectable', async t => {
    const ev = await page(t,[condition('strain',[{magnitude:{...complete, yx:-.001}}])]);
    await ev('document.querySelector("[data-tensor-clear]").click();document.querySelector("[data-component=xy]").click()');
    assert.deepEqual(await ev('Array.from(view.selected)'),['xy']);
    assert.equal(await ev('document.querySelector("[data-component=yx] strong").textContent'),'0.00');
    assert.equal(await ev('document.querySelector("[data-component=yx]").title'),'yx: -0.001 - · Not selected');
    assert.equal(await ev('view.actionLabel'), 'Shear');
  });

  test('multiple conditions reset selection and use their own units; one record has no navigation', async t => {
    const ev = await page(t,[{is_defined:true},condition(),condition('strain',[{magnitude:complete}])]);
    await ev('document.querySelector("[data-tensor-clear]").click();document.querySelector("[data-tensor-condition]").value="2";document.querySelector("[data-tensor-condition]").dispatchEvent(new Event("change"))');
    assert.equal(await ev('view.itemIndex'),2);
    assert.deepEqual(await ev('Array.from(view.selected)'),['xx','xy','yx','yy']);
    assert.equal(await ev('document.querySelector("[data-tensor-heading]").textContent'),'Whole cube · Strain (-) / cyclic');
    assert.equal(await ev('document.querySelector("[data-tensor-load]").closest("label").hidden'),true);
    assert.deepEqual(await ev('Array.from(document.querySelectorAll("[data-tensor-filter]")).map(b=>(b.querySelector("[data-tensor-filter-label]")||b).textContent)'),['Extend','Shorten','Shear','Select all']);
    assert.equal(await ev('document.querySelector("[data-tensor-status]").hidden'),true);
    assert.equal(await ev('document.querySelectorAll("[data-tensor-slider]").length'),0);
  });

  test('invalid uploaded containers and markup remain harmless and unselected', async t => {
    const bad = {toString:{nested:true}};
    const ev = await page(t,[condition('strain',[{magnitude:{xx:bad,xy:'<img src=x onerror=alert(1)>',yy:true,zz:null}}])],{Strain:bad});
    assert.equal(await ev('document.querySelector("[data-tensor-matrix] img")'),null);
    assert.equal(await ev('document.querySelectorAll("[data-tensor-matrix] button:disabled").length'),9);
    assert.match(await ev('document.querySelector("[data-tensor-heading]").textContent'),/unit not supplied/);
    assert.deepEqual(await ev('Array.from(view.selected)'), []);
    assert.equal(await ev('JSON.stringify(supplied) === original'),true);
  });
});
