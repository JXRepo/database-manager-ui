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
    async function downloaded(extension, graphPath = cases.sample) {
      const object = new URL(graphPath, process.env.RELATIONSHIP_BASE_URL).searchParams.get('object');
      const path = join(artifacts, `data-${object}-relationships.${extension}`);
      for (let attempt = 0; attempt < 100; attempt++) {
        if (existsSync(path) && !existsSync(path + '.crdownload')) return readFileSync(path);
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Download missing: ${path}`);
    }
    async function layout(label) {
      const metrics = await evaluate(`(() => {
        const graph = document.querySelector('.graph-page');
        const viewport = graph.querySelector('.graph-canvas');
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
    await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: artifacts});
    for (const name of ['sample', 'large']) {
      const objectId = new URL(cases[name], process.env.RELATIONSHIP_BASE_URL).searchParams.get('object');
      for (const extension of ['png', 'svg']) rmSync(join(artifacts, `data-${objectId}-relationships.${extension}`), {force: true});
    }
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
      assert.ok(await evaluate(`document.querySelector('.graph-workspace').getBoundingClientRect().bottom <= innerHeight`),
        'The initial canvas and its navigation help fit the desktop viewport');
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

    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await navigate(cases.sample);
    const selectedId = `document.querySelector('.relationship-node[aria-current="true"]').dataset.node`;
    const selectedVisible = `(() => {
      const node = document.querySelector('.relationship-node[aria-current="true"]').getBoundingClientRect();
      const viewport = document.querySelector('.relationship-viewport').getBoundingClientRect();
      return node.left >= viewport.left && node.right <= viewport.right && node.top >= viewport.top && node.bottom <= viewport.bottom;
    })()`;
    await click('#graph-find-tab');
    await evaluate(`document.querySelector('#graph-node-query').value = '233000'; document.querySelector('#graph-node-query').dispatchEvent(new Event('input'))`);
    assert.match(await evaluate(`document.querySelector('#graph-node-count').innerText`), /^1 of /,
      'Node search includes individual parameter values');
    await evaluate(`document.querySelector('#graph-node-kind').value = 'phase'; document.querySelector('#graph-node-kind').dispatchEvent(new Event('change'))`);
    assert.equal(await evaluate(`document.querySelector('#graph-no-nodes').hidden`), false,
      'Type and text filters must match the same node');
    await click('#graph-clear-search');
    await evaluate(`document.querySelector('#graph-node-query').value = 'CUBIC elasticity'; document.querySelector('#graph-node-query').dispatchEvent(new Event('input')); document.querySelector('#graph-node-query').focus()`);
    await command('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    assert.equal(await evaluate(selectedId), 'relationship-phase-0-model-0-elastic');
    assert.ok(await evaluate(selectedVisible), 'Search results center a readable node');
    const bookmark = await evaluate('location.pathname + location.search + location.hash');
    await click('.relationship-info-item:not([hidden]) .graph-connections a');
    assert.equal(await evaluate(selectedId), 'relationship-phase-0');
    await evaluate('history.back()');
    await until(`${selectedId} === 'relationship-phase-0-model-0-elastic'`);
    await navigate(cases.empty);
    await navigate(bookmark);
    assert.equal(await evaluate(selectedId), 'relationship-phase-0-model-0-elastic', 'A direct link restores the chosen node');
    assert.ok(await evaluate(selectedVisible));
    await click('#graph-focus');
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node:not(.is-muted)').length`), 2,
      'Model focus includes only the model and its own phase');
    await click('#graph-focus');
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node.is-muted').length`), 0);
    await click('#graph-zoom-in');
    const zoom = await evaluate(`parseInt(document.querySelector('#graph-zoom-reset').innerText)`);
    await click('#graph-zoom-out');
    assert.ok(await evaluate(`parseInt(document.querySelector('#graph-zoom-reset').innerText)`) < zoom);
    await click('#graph-fit');
    assert.ok(await evaluate(`(() => {
      const area = document.querySelector('.relationship-viewport').getBoundingClientRect();
      return Array.from(document.querySelectorAll('[data-node]')).every(node => {
        const box = node.getBoundingClientRect();
        return box.left >= area.left && box.right <= area.right && box.top >= area.top && box.bottom <= area.bottom;
      });
    })()`), 'Fit shows every node without cropping');
    await evaluate(`Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async () => {throw new Error('Clipboard denied');}}})`);
    await click('#graph-copy-link');
    assert.equal(await evaluate(`document.querySelector('#graph-link-fallback').value`), process.env.RELATIONSHIP_BASE_URL + bookmark);
    assert.equal(await evaluate(`document.querySelector('#graph-link-fallback').hidden`), false);

    await click('#graph-focus');
    await click('.graph-download summary');
    await click('#graph-save-svg');
    const svgText = (await downloaded('svg')).toString('utf8');
    const exported = await evaluate(`(() => {
      const image = new DOMParser().parseFromString(${JSON.stringify(svgText)}, 'image/svg+xml');
      return {errors: image.querySelectorAll('parsererror').length, html: image.querySelectorAll('foreignObject').length,
        nodes: image.querySelectorAll('[data-node]').length, dimmed: image.querySelectorAll('.is-muted').length,
        labels: Array.from(image.querySelectorAll('[data-node]')).every(node => node.querySelector('title')?.textContent && node.querySelectorAll('text').length >= 2)};
    })()`);
    assert.deepEqual(exported, {errors: 0, html: 0, nodes: await evaluate(`document.querySelectorAll('[data-node]').length`), dimmed: 0, labels: true});
    await click('.graph-download summary');
    await click('#graph-save-png');
    const png = await downloaded('png');
    assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    const graphSize = await evaluate(`({width: document.querySelector('.relationship-svg').viewBox.baseVal.width, height: document.querySelector('.relationship-svg').viewBox.baseVal.height})`);
    assert.equal(png.readUInt32BE(16), graphSize.width * 2);
    assert.equal(png.readUInt32BE(20), graphSize.height * 2);
    await until(`document.querySelector('#graph-status').textContent.includes('downloaded as PNG')`);
    await screenshot('explorer-download');
    await click('.relationship-node-output');
    await click('.relationship-info-item:not([hidden]) .graph-source-link');
    await until(`location.hash === '#data-curves' && document.readyState === 'complete' && !!document.querySelector('#data-curves')`);
    await navigate(cases.sample);
    await click('.relationship-node-loading');
    await click('.relationship-info-item:not([hidden]) .graph-source-link');
    await until(`location.hash === '#data-loading' && document.readyState === 'complete' && !!document.querySelector('#data-loading')`);

    await navigate(cases.long);
    await click('#graph-zoom-reset');
    await evaluate(`const viewport = document.querySelector('.relationship-viewport'); viewport.scrollLeft = 150; viewport.scrollTop = 250`);
    const start = await evaluate(`(() => {const viewport = document.querySelector('.relationship-viewport'); const box = viewport.getBoundingClientRect(); return {x: box.left + 12, y: box.top + 12, left: viewport.scrollLeft, top: viewport.scrollTop};})()`);
    await command('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, x: start.x, y: start.y});
    await command('Input.dispatchMouseEvent', {type: 'mouseMoved', button: 'left', buttons: 1, x: start.x - 50, y: start.y - 70});
    await command('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, x: start.x - 50, y: start.y - 70});
    const after = await evaluate(`({left: document.querySelector('.relationship-viewport').scrollLeft, top: document.querySelector('.relationship-viewport').scrollTop})`);
    assert.ok(after.left > start.left + 20 && after.top > start.top + 20, 'Dragging the background pans both axes');
    await command('Input.dispatchMouseEvent', {type: 'mouseWheel', x: start.x + 50, y: start.y + 50, deltaY: -80, deltaX: 0, modifiers: 2});
    await until(`parseInt(document.querySelector('#graph-zoom-reset').innerText) > 100`);
    await click('#graph-find-tab');
    await evaluate(`document.querySelector('#graph-node-query').value = 'Phase 11'; document.querySelector('#graph-node-kind').value = 'phase'; document.querySelector('#graph-node-query').dispatchEvent(new Event('input'))`);
    assert.match(await evaluate(`document.querySelector('#graph-node-count').innerText`), /^1 of /);
    await click('.graph-node-results li:not([hidden]) a');
    assert.equal(await evaluate(selectedId), 'relationship-phase-11');
    assert.ok(await evaluate(selectedVisible), 'The last phase in a large graph is brought into view');
    await screenshot('explorer-long-selected');

    await navigate(cases.large);
    await click('#graph-find-tab');
    await evaluate(`document.querySelector('#graph-node-query').value = 'Phase 79'; document.querySelector('#graph-node-kind').value = 'phase'; document.querySelector('#graph-node-query').dispatchEvent(new Event('input'))`);
    await click('.graph-node-results li:not([hidden]) a');
    assert.equal(await evaluate(selectedId), 'relationship-phase-79');
    assert.ok(await evaluate(selectedVisible));
    await click('#graph-focus');
    assert.ok(await evaluate(`parseInt(document.querySelector('#graph-zoom-reset').innerText) >= 75`),
      'Focusing a late phase must preserve readable zoom even when the record node is far away');
    assert.ok(await evaluate(selectedVisible));
    await screenshot('explorer-eighty-phases');
    await click('.graph-download summary');
    await click('#graph-save-png');
    const largePNG = await downloaded('png', cases.large);
    assert.equal(largePNG.readUInt32BE(20), 8192, 'Tall graphs use the bounded full-image height');
    assert.ok(largePNG.readUInt32BE(16) * largePNG.readUInt32BE(20) <= 16000000);
    assert.ok(largePNG.readUInt32BE(16) > 1000, 'Full graph width survives focused-view export');

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
    console.log('Graph workspace browser checks passed: detail/sidebar entry, object search/switching, 3 desktop widths, node text/type search, parameters, keyboard selection, connection navigation, curve/loading links, stable bookmarks/back, fit/zoom/drag/focus, clipboard fallback, actual complete SVG/PNG downloads, 12 and 80 phases, bounded large PNG, long names, empty states, escaped HTML and native forms/links without JavaScript.');
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
