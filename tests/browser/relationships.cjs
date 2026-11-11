const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync, mkdirSync, readFileSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const library = process.env.CHARTJS_TEST_BUNDLE
    ? readFileSync(process.env.CHARTJS_TEST_BUNDLE, 'utf8')
    : await (await fetch('https://cdn.jsdelivr.net/npm/chart.js', {signal: AbortSignal.timeout(30000)})).text();
  const profile = mkdtempSync(join(tmpdir(), 'relationship-browser-'));
  const artifacts = process.env.RELATIONSHIP_ARTIFACT_DIR || join(tmpdir(), 'graph-workspace-qa');
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
      for (let attempt = 0; attempt < 100; attempt++) {
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out: ${expression}`);
    }
    async function navigate(path) {
      const url = process.env.RELATIONSHIP_BASE_URL + path;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'
        && !!document.querySelector('.pc-content')`);
    }
    async function click(selector) {
      const point = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        element.scrollIntoView({block: 'center', inline: 'center'});
        const box = element.getBoundingClientRect();
        return {x: box.left + box.width / 2, y: box.top + box.height / 2};
      })()`);
      await command('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...point});
      await command('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...point});
    }
    async function screenshot(name) {
      await evaluate(`window.scrollTo(0, 0)`);
      const capture = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }
    async function layout(label) {
      const metrics = await evaluate(`(() => {
        const graph = document.querySelector('.graph-page');
        const viewport = graph.querySelector('.relationship-viewport');
        const inspector = graph.querySelector('.relationship-inspector');
        const canvas = viewport?.getBoundingClientRect();
        const side = inspector?.getBoundingClientRect();
        return {
          documentWidth: document.documentElement.scrollWidth, width: innerWidth,
          viewportHeight: canvas?.height || 0,
          inspectorBesideGraph: !canvas || (side.left >= canvas.right - 1
            && Math.abs(side.top - canvas.top) < 1 && Math.abs(side.height - canvas.height) < 1),
          nodes: Array.from(graph.querySelectorAll('[data-node]')).map(node => {
            const rect = node.querySelector('rect').getBoundingClientRect();
            const text = node.querySelector('.relationship-label').getBoundingClientRect();
            return {id: node.dataset.node, inside: text.left >= rect.left && text.right <= rect.right
              && text.top >= rect.top && text.bottom <= rect.bottom};
          }),
        };
      })()`);
      assert.ok(metrics.documentWidth <= metrics.width, `${label}: the page must not overflow horizontally`);
      assert.ok(metrics.viewportHeight === 0 || (metrics.viewportHeight >= 480 && metrics.viewportHeight <= 880),
        `${label}: the workspace gives the graph a large bounded canvas`);
      assert.ok(metrics.inspectorBesideGraph, `${label}: node details must remain beside the canvas`);
      assert.ok(metrics.nodes.every(node => node.inside), `${label}: labels must stay inside their nodes: ${JSON.stringify(metrics.nodes)}`);
    }

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: library});
    await command('Network.setCookie', {name: process.env.RELATIONSHIP_COOKIE_NAME,
      value: process.env.RELATIONSHIP_SESSION, url: process.env.RELATIONSHIP_BASE_URL, path: '/'});
    const cases = JSON.parse(process.env.RELATIONSHIP_CASES);
    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await navigate(cases.detail);
      assert.equal(await evaluate(`!!document.querySelector('#detail-relationships')`), false,
        'The detail page links to the workspace instead of embedding it');
      await click('a[href="' + cases.sample + '"]');
      await until(`location.pathname === '/graph/' && document.readyState === 'complete'
        && !!document.querySelector('.graph-workspace')`);
      assert.equal(await evaluate('location.search'), new URL(cases.sample, process.env.RELATIONSHIP_BASE_URL).search);
      assert.equal(await evaluate(`document.querySelector('.pc-sidebar a[href="/graph/"]').getAttribute('aria-current')`), 'page');
      assert.equal(await evaluate(`document.querySelector('#detail-relationships').tagName`), 'SECTION');
      await layout(`sample-${width}`);
      await click('.relationship-node-model');
      assert.equal(await evaluate(`document.querySelectorAll('.relationship-info-item:not([hidden])').length`), 1);
      assert.match(await evaluate(`document.querySelector('.relationship-info-item:not([hidden])').innerText`), /Ferrite.*Uses elastic model/s);
      assert.equal(await evaluate(`document.querySelector('.relationship-node-model').getAttribute('aria-current')`), 'true');
      await evaluate(`document.querySelector('.relationship-node-software').focus()`);
      await command('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
      await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
      assert.match(await evaluate(`document.querySelector('.relationship-info-item:not([hidden])').innerText`), /DAMASK.*3\.0/s);
      await click('.relationship-node-output');
      assert.match(await evaluate(`document.querySelector('.relationship-info-item:not([hidden])').innerText`), /3 samples.*MPa.*Supplied/s);
      await screenshot(`sample-${width}`);
      await click('#graph-view-details');
      await until(`location.pathname === ${JSON.stringify(cases.detail)} && document.readyState === 'complete'`);
      assert.equal(await evaluate(`!!document.querySelector('#detail-relationships')`), false);
    }

    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await navigate(cases.long);
      await layout(`long-labels-${width}`);
      assert.equal(await evaluate('window.graphInjection'), undefined);
      assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-phase').length`), 12);
      await click('.relationship-node-creator');
      assert.ok(await evaluate(`document.querySelector('.relationship-info-item:not([hidden])').textContent.includes('WWW'.repeat(100))`));
      await screenshot(`long-labels-${width}`);
      await navigate(cases.empty);
      assert.match(await evaluate(`document.querySelector('.relationship-empty').innerText`), /No related metadata/);
      await layout(`empty-${width}`);
      await screenshot(`empty-${width}`);
    }

    await click('.pc-sidebar a[href="/graph/"]');
    await until(`location.pathname === '/graph/' && location.search === '' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('#detail-relationships')`), false);
    await evaluate(`document.querySelector('#graph-query').value = 'steel uniaxial'`);
    await click('.graph-find-form button');
    await until(`location.search.includes('q=steel') && document.readyState === 'complete'`);
    assert.equal(await evaluate(`document.querySelectorAll('#graph-object option[value]:not([value=""])').length`), 1);
    await evaluate(`document.querySelector('#graph-object').value = ${JSON.stringify(new URL(cases.sample, process.env.RELATIONSHIP_BASE_URL).searchParams.get('object'))}`);
    await click('.graph-select-form button');
    await until(`location.search === ${JSON.stringify(new URL(cases.sample, process.env.RELATIONSHIP_BASE_URL).search)} && document.readyState === 'complete'`);
    await click('#graph-change-data');
    await until(`location.search.includes('choose=1') && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('.graph-workspace')`), true,
      'Choosing another object must retain the current graph until submission');
    await screenshot('change-data');
    await evaluate(`document.querySelector('#graph-object').value = ${JSON.stringify(new URL(cases.long, process.env.RELATIONSHIP_BASE_URL).searchParams.get('object'))}`);
    await click('.graph-select-form button');
    await until(`location.search === ${JSON.stringify(new URL(cases.long, process.env.RELATIONSHIP_BASE_URL).search)} && document.readyState === 'complete'`);
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-phase').length`), 12);
    await navigate(cases.picker + '?q=unmatched');
    assert.match(await evaluate(`document.querySelector('.graph-picker-empty').innerText`), /No data objects match/);
    assert.equal(await evaluate(`!!document.querySelector('#graph-query')`), true);
    await screenshot('empty-picker');

    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate(cases.picker);
    await evaluate(`document.querySelector('#graph-object').value = ${JSON.stringify(new URL(cases.sample, process.env.RELATIONSHIP_BASE_URL).searchParams.get('object'))}`);
    await click('.graph-select-form button');
    await until(`location.search === ${JSON.stringify(new URL(cases.sample, process.env.RELATIONSHIP_BASE_URL).search)} && document.readyState === 'complete'`);
    await click('.relationship-node-model');
    assert.ok(await evaluate(`location.hash.endsWith('-info')`), 'Native links must reach relationship details without JavaScript');
    assert.match(await evaluate(`document.querySelector(location.hash).innerText`), /Cubic elasticity.*Ferrite/s);
    assert.ok(await evaluate(`document.querySelector(location.hash).getBoundingClientRect().height > 0`));
    await screenshot('without-javascript');
    assert.deepEqual(exceptions, []);
    console.log('Graph workspace browser checks passed: detail/sidebar entry, current object context, object search/switching, large canvas with a right inspector at 3 desktop widths, node selection, keyboard activation, long names, 12 phases, empty states, escaped HTML and native forms/links without JavaScript.');
    console.log(`Screenshots: ${artifacts}`);
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
