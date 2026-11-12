const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync, mkdirSync, readFileSync, writeFileSync, existsSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const library = process.env.CHARTJS_TEST_BUNDLE
    ? readFileSync(process.env.CHARTJS_TEST_BUNDLE, 'utf8')
    : await (await fetch('https://cdn.jsdelivr.net/npm/chart.js', {signal: AbortSignal.timeout(30000)})).text();
  const profile = mkdtempSync(join(tmpdir(), 'collection-browser-'));
  const artifacts = process.env.COLLECTION_ARTIFACT_DIR || join(tmpdir(), 'research-collections-qa');
  mkdirSync(artifacts, {recursive: true});
  const browser = spawn(process.env.CHROMIUM_BIN || '/usr/bin/chromium', [
    '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio: ['ignore', 'ignore', 'pipe']});
  let socket;
  try {
    const address = await new Promise((resolve, reject) => {
      let logs = '';
      browser.on('error', reject);
      browser.on('exit', code => reject(new Error(`Chromium exited: ${code}`)));
      browser.stderr.on('data', chunk => {
        logs += chunk;
        const match = logs.match(/DevTools listening on (ws:\/\/\S+)/);
        if (match) resolve(match[1]);
      });
    });
    socket = new WebSocket(address);
    await once(socket, 'open');
    let nextId = 0;
    const pending = new Map();
    const exceptions = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(JSON.stringify(message.error)));
      else request.resolve(message.result);
    });
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params, sessionId}));
    });
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    const command = (method, params = {}) => send(method, params, sessionId);
    const evaluate = async expression => {
      const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    async function until(expression) {
      for (let attempt = 0; attempt < 120; attempt++) {
        try {
          if (await evaluate(expression)) return;
        } catch (error) {
          if (!/context|navigation/i.test(error.message)) throw error;
        }
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      const state = await evaluate(`({url: location.href, selected: document.querySelector('.relationship-node[aria-current="true"]')?.dataset.node,
        details: document.querySelector('.relationship-info-item:not([hidden])')?.innerText})`);
      const capture = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(artifacts, 'failure.png'), Buffer.from(capture.data, 'base64'));
      throw new Error(`Timed out: ${expression}; state=${JSON.stringify(state)}`);
    }
    async function navigate(path) {
      const url = process.env.COLLECTION_BASE_URL + path;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'
        && !!document.querySelector('.pc-content')`);
    }
    async function click(selector) {
      await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) throw new Error('Missing control: ' + ${JSON.stringify(selector)});
        element.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
      })()`);
      await new Promise(resolve => setTimeout(resolve, 40));
      const point = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        const box = element.getBoundingClientRect();
        const x = box.left + box.width / 2;
        const y = box.top + box.height / 2;
        const target = document.elementFromPoint(x, y);
        if (!box.width || !box.height || !element.contains(target)) {
          throw new Error('Covered control: ' + ${JSON.stringify(selector)} + ' by ' + target?.outerHTML.slice(0, 200));
        }
        return {x, y};
      })()`);
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', ...point});
      await command('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...point});
      await command('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...point});
    }
    async function fill(selector, value) {
      await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        element.value = ${JSON.stringify(value)};
        element.dispatchEvent(new Event('input', {bubbles: true}));
        element.dispatchEvent(new Event('change', {bubbles: true}));
      })()`);
    }
    async function screenshot(name) {
      await evaluate('window.scrollTo(0, 0)');
      const capture = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }
    async function layout(label) {
      const metrics = await evaluate(`(() => {
        const canvas = document.querySelector('.graph-canvas')?.getBoundingClientRect();
        const inspector = document.querySelector('.relationship-inspector')?.getBoundingClientRect();
        return {width: innerWidth, documentWidth: document.documentElement.scrollWidth,
          canvasHeight: canvas?.height || 0,
          sideBySide: !canvas || (inspector.left >= canvas.right - 1 && Math.abs(inspector.top - canvas.top) < 1),
          injection: !!window.collectionInjection,
          secretText: document.body.textContent.includes('SECRET'),
          nodes: document.querySelectorAll('.relationship-node').length};
      })()`);
      assert.ok(metrics.documentWidth <= metrics.width, `${label}: page overflow ${JSON.stringify(metrics)}`);
      assert.ok(metrics.sideBySide, `${label}: inspector must remain beside the graph`);
      assert.ok(metrics.canvasHeight === 0 || metrics.canvasHeight >= 400, `${label}: graph has a useful canvas`);
      assert.equal(metrics.injection, false, `${label}: uploaded text must stay escaped`);
      assert.equal(metrics.secretText, false, `${label}: private records and collections must not leak`);
      assert.ok(metrics.nodes <= 27, `${label}: only one bounded page is drawn`);
    }
    async function download(name) {
      const path = join(artifacts, name);
      for (let attempt = 0; attempt < 120; attempt++) {
        if (existsSync(path) && !existsSync(path + '.crdownload')) return readFileSync(path);
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      const state = await evaluate(`({url: location.href, menu: document.querySelector('.graph-download')?.open,
        status: document.querySelector('#graph-status')?.textContent, view: document.querySelector('#detail-relationships')?.dataset.view})`);
      const capture = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(artifacts, 'failure.png'), Buffer.from(capture.data, 'base64'));
      throw new Error(`Download missing: ${path}; state=${JSON.stringify(state)}; exceptions=${JSON.stringify(exceptions)}`);
    }

    const cases = JSON.parse(process.env.COLLECTION_CASES);
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: library});
    await command('Network.setCookie', {name: process.env.COLLECTION_COOKIE_NAME,
      value: process.env.COLLECTION_SESSION, url: process.env.COLLECTION_BASE_URL, path: '/'});
    await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: artifacts});
    for (const extension of ['svg', 'png']) {
      rmSync(join(artifacts, `collection-relationships-detailed.${extension}`), {force: true});
    }

    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await navigate(cases.home);
      await layout(`home-${width}`);
      assert.equal(await evaluate(`document.querySelector('.collection-list-link[href="${cases.reference}"] .collection-list-count').textContent`), '100 accessible objects');
      await screenshot(`collections-${width}`);
      await navigate(cases.reference);
      assert.equal(await evaluate(`document.querySelector('.collection-total').textContent`), '100 accessible data objects');
      assert.equal(await evaluate(`document.querySelectorAll('.collection-table tbody tr').length`), 25);
      await layout(`reference-${width}`);
      await screenshot(`reference-${width}`);
      await click('[data-graph-view="detailed"]');
      await layout(`reference-detailed-${width}`);
      await navigate(cases.reference + '?links=members&page=4');
      await layout(`long-object-titles-${width}`);
      assert.ok(await evaluate(`document.querySelector('.collection-table').textContent.includes('<script>window.collectionInjection')`));
      await screenshot(`long-object-titles-${width}`);
      await navigate(cases.empty);
      assert.match(await evaluate(`document.querySelector('.collection-empty').textContent`), /No accessible data objects/);
      await layout(`empty-${width}`);
      await screenshot(`empty-${width}`);
    }
    console.log('Desktop layout passed at 1280, 1440 and 1920 pixels, including 100 accessible objects and empty collections.');

    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await navigate(cases.reference);
    await click('.collection-group-list > summary');
    assert.equal(await evaluate(`document.querySelectorAll('.collection-group-list li').length`), 25);
    await click('.collection-pagination[aria-label="Group pages"] a');
    await until(`location.search.includes('groups_page=2') && document.readyState === 'complete'`);
    assert.ok(await evaluate(`document.querySelectorAll('.collection-group-list li').length < 25`));
    assert.match(await evaluate(`document.querySelector('.collection-pagination[aria-label="Group pages"]').textContent`), /Page 2 of 2/);
    await navigate(cases.reference + '?links=software');
    await click('.relationship-node-software');
    await click('.relationship-info-item:not([hidden]) .graph-source-link');
    await until(`location.search.includes('group=') && document.readyState === 'complete'`);
    assert.match(await evaluate(`document.querySelector('.collection-group-current').textContent`), /41 objects/);
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-record').length`), 25);
    const groupPath = await evaluate('location.pathname + location.search');
    await click('.collection-pagination[aria-label="Object pages"] a');
    await until(`new URL(location.href).searchParams.get('page') === '2' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`document.querySelectorAll('.collection-table tbody tr').length`), 16);
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-record').length`), 16);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('group')`), new URL(groupPath, process.env.COLLECTION_BASE_URL).searchParams.get('group'));
    await click('[data-graph-view="detailed"]');
    assert.ok(await evaluate(`document.querySelector('.relationship-preview').getBoundingClientRect().height > 0`));
    await screenshot('group-page-detailed');
    await click('.graph-download summary');
    await click('#graph-save-svg');
    const svg = (await download('collection-relationships-detailed.svg')).toString();
    assert.ok(svg.includes('Research collection'));
    assert.equal(svg.includes('<foreignObject'), false);
    assert.equal((svg.match(/data-node="/g) || []).length, 18);
    await click('.graph-download summary');
    await click('#graph-save-png');
    const png = await download('collection-relationships-detailed.png');
    assert.equal(png.subarray(1, 4).toString(), 'PNG');
    assert.ok(png.readUInt32BE(16) <= 8192 && png.readUInt32BE(20) <= 8192);
    const referenceExport = await evaluate(`fetch(document.querySelector('#collection-export').href).then(response => response.json())`);
    assert.equal(referenceExport.length, 100);
    assert.equal(referenceExport.some(record => record.identifier === 'secret-inaccessible'), false);
    await navigate(cases.reference + '?links=relations&group=missing');
    assert.match(await evaluate(`document.querySelector('.collection-group-current').textContent`), /No declared relation/);
    assert.ok(await evaluate(`document.querySelectorAll('.collection-table tbody tr').length > 0`));
    await navigate(cases.reference + '?links=members');
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-record').length`), 25);
    const forbiddenStatus = await evaluate(`fetch(${JSON.stringify(cases.forbidden)}).then(response => response.status)`);
    assert.equal(forbiddenStatus, 404);
    console.log('Group and member pagination, missing metadata, exact access counts, original JSON and actual SVG/PNG downloads passed.');

    await navigate(cases.search + '?keyword=workflow');
    assert.equal(await evaluate(`document.querySelector('#graphSelectedButton').disabled`), true);
    assert.equal(await evaluate(`!!document.querySelector('.result-checkbox[value="${cases.hidden}"]')`), false);
    assert.equal(await evaluate(`!!document.querySelector('.result-checkbox[value="${cases.shared}"]')`), true);
    await click(`.result-checkbox[value="${cases.first}"]`);
    await click(`.result-checkbox[value="${cases.public}"]`);
    assert.equal(await evaluate(`document.querySelector('#selectedResultCount').textContent`), '2 selected');
    await click('#graphSelectedButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-save-form') && document.readyState === 'complete'`);
    assert.equal(await evaluate(`document.querySelector('.collection-total').textContent`), '2 accessible data objects');
    await screenshot('selected-two-objects');
    await fill('#collection-save-form [name="title"]', 'Workflow collection');
    await click('#collection-save-form button[type="submit"]');
    await until(`location.pathname.includes('/graph/collections/') && !!document.querySelector('#collection-edit-form') && document.readyState === 'complete'`);
    const savedPath = await evaluate('location.pathname');
    const savedId = savedPath.split('/').filter(Boolean).at(-1);
    await screenshot('saved-collection');
    await navigate(cases.home);
    assert.match(await evaluate(`document.querySelector('.collection-list-link[href="${savedPath}"]').textContent`), /Workflow collection.*2 accessible objects/s);
    await click(`.collection-list-link[href="${savedPath}"]`);
    await until(`location.pathname === ${JSON.stringify(savedPath)} && document.readyState === 'complete'`);
    await click('.collection-dimensions a[href*="links=software"]');
    await until(`location.search.includes('links=software') && document.readyState === 'complete'`);
    assert.match(await evaluate(`document.querySelector('.collection-explanation').textContent`), /names.*version/s);
    await click('.collection-dimensions a[href*="links=relations"]');
    await until(`location.search.includes('links=relations') && document.readyState === 'complete'`);
    await click(`.collection-object-graph[href="${cases.detail}?tab=graph"]`);
    await until(`location.pathname === ${JSON.stringify(cases.detail)} && location.search === '?tab=graph' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('#plot-variables-data')`), false);
    await click('.relationship-node-software');
    await evaluate(`Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async value => {window.copiedCollectionLink = value;}}})`);
    await click('#graph-copy-link');
    await until(`typeof window.copiedCollectionLink === 'string'`);
    const copied = new URL(await evaluate('window.copiedCollectionLink'));
    assert.equal(copied.pathname, cases.detail);
    assert.equal(copied.searchParams.get('tab'), 'graph');
    assert.equal(copied.hash, '#relationship-software-info');
    await navigate(copied.pathname + copied.search + copied.hash);
    assert.equal(await evaluate(`document.querySelector('.relationship-node[aria-current="true"]').dataset.node`), 'relationship-software');
    await screenshot('object-graph-tab');

    await navigate(cases.myData + '?software=Append%20Solver');
    assert.equal(await evaluate(`document.querySelectorAll('.my-data-checkbox').length`), 1);
    await click(`.my-data-checkbox[value="${cases.second}"]`);
    await click('#graphMyDataButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-add-form') && document.readyState === 'complete'`);
    await fill('#target-collection', savedId);
    await click('#collection-add-form button');
    await until(`location.pathname === ${JSON.stringify(savedPath)} && document.querySelector('.collection-total')?.textContent === '3 accessible data objects' && document.readyState === 'complete'`);
    await click('.collection-manage > summary');
    await fill('#collection-edit-form [name="title"]', 'Edited workflow collection');
    await fill('#collection-edit-form [name="description"]', 'A named research group, independent of upload batches.');
    await click('#collection-edit-form button');
    await until(`document.querySelector('#collection-title')?.textContent === 'Edited workflow collection' && document.readyState === 'complete'`);
    await click(`.collection-member-checkbox[value="${cases.first}"]`);
    assert.equal(await evaluate(`document.querySelector('#collection-selection-count').textContent`), '1 selected');
    await click('#collection-remove-button');
    await until(`document.querySelector('.collection-total')?.textContent === '2 accessible data objects' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('.collection-member-checkbox[value="${cases.first}"]')`), false);
    await click('.collection-manage > summary');
    await click('.collection-delete > summary');
    await click('#collection-delete-form button');
    await until(`location.pathname === ${JSON.stringify(cases.home)} && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('.collection-list-link[href="${savedPath}"]')`), false);
    await navigate(cases.detail);
    assert.equal(await evaluate(`!!document.querySelector('#data-metadata')`), true);
    console.log('Real Search/My Data selection, save, reopen, object graph, copy link, append, edit, remove and delete workflows passed.');

    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate(cases.myData + '?software=Append%20Solver');
    assert.equal(await evaluate(`document.querySelector('#graphMyDataButton').disabled`), false);
    await click(`.my-data-checkbox[value="${cases.second}"]`);
    await click('#graphMyDataButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-save-form') && document.readyState === 'complete'`);
    await fill('#collection-save-form [name="title"]', 'Native browser collection');
    await click('#collection-save-form button[type="submit"]');
    await until(`location.pathname.includes('/graph/collections/') && document.querySelector('#collection-title')?.textContent === 'Native browser collection' && document.readyState === 'complete'`);
    const nativePath = await evaluate('location.pathname');
    const nativeId = nativePath.split('/').filter(Boolean).at(-1);
    await navigate(cases.search + '?keyword=workflow');
    assert.equal(await evaluate(`document.querySelector('#graphSelectedButton').disabled`), false);
    await click(`.result-checkbox[value="${cases.public}"]`);
    await click('#graphSelectedButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-add-form') && document.readyState === 'complete'`);
    await fill('#target-collection', nativeId);
    await click('#collection-add-form button');
    await until(`location.pathname === ${JSON.stringify(nativePath)} && document.querySelector('.collection-total')?.textContent === '2 accessible data objects' && document.readyState === 'complete'`);
    await click('.collection-group-list > summary');
    await click('.collection-group-list li a');
    await until(`location.search.includes('group=') && document.readyState === 'complete'`);
    await click('[data-graph-view="detailed"]');
    await until(`location.search.includes('view=detailed') && document.readyState === 'complete'`);
    await click('.relationship-node-record');
    assert.match(await evaluate('location.hash'), /^#collection-object-\d+-info$/);
    assert.ok(await evaluate(`document.querySelector(location.hash).getBoundingClientRect().height > 0`));
    await layout('native-collection');
    await screenshot('without-javascript');
    assert.deepEqual(exceptions, []);
    console.log('Native forms, saved collections, group links, detail anchors and detailed cards passed without JavaScript.');
    console.log(`Screenshots and graph downloads: ${artifacts}`);
  } finally {
    socket?.close();
    if (browser.exitCode === null) {
      const exited = once(browser, 'exit');
      browser.kill('SIGTERM');
      await exited;
    }
    rmSync(profile, {recursive: true, force: true});
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
