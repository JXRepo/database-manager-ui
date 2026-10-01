const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdirSync, mkdtempSync, rmSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const profile = mkdtempSync(join(tmpdir(), 'charts-browser-'));
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
    let stage = 'browser startup';
    const pending = new Map();
    const exceptions = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(`${request.stage}: ${request.method}: ${JSON.stringify(message.error)}${request.expression ? '\n' + request.expression : ''}`));
      else request.resolve(message.result);
    });
    const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, {resolve, reject, method, stage, expression: params.expression});
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
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out: ${expression}`);
    }
    async function navigate(path = '/charts/', enhanced = true) {
      stage = `navigate ${path}${enhanced ? '' : ' without JavaScript'}`;
      const url = process.env.CHARTS_BASE_URL + path;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === "complete" && !!document.querySelector(".charts-page")`);
      if (enhanced) await until('document.querySelector(".charts-page").classList.contains("charts-js")');
    }
    async function settleLayout() {
      await evaluate(`(async () => {
        window.scrollTo(0, 0);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        await Promise.all(document.getAnimations().filter(animation => animation.effect.getComputedTiming().endTime !== Infinity)
          .map(animation => animation.finished.catch(() => {})));
      })()`);
    }
    async function choose(id, value, parameter) {
      stage = `choose ${id} = ${value}`;
      await evaluate(`(() => {
        const select = document.getElementById(${JSON.stringify(id)});
        select.value = ${JSON.stringify(value)};
        select.dispatchEvent(new Event('change', {bubbles: true}));
      })()`);
      await until(`document.readyState === 'complete' && document.querySelector('.charts-page').classList.contains('charts-js')
        && new URLSearchParams(location.search).get(${JSON.stringify(parameter)}) === ${JSON.stringify(value)}
        && document.getElementById(${JSON.stringify(id)}).value === ${JSON.stringify(value)}`);
    }
    async function selections() {
      return evaluate(`({
        material: document.getElementById('charts-material-group').value,
        setup: document.getElementById('charts-group').value,
        measure: document.getElementById('charts-measure').value,
      })`);
    }
    async function categoryLink(panel, label) {
      return evaluate(`(() => {
        const link = [...document.querySelectorAll(${JSON.stringify(panel + ' .charts-bar')})]
          .find(element => element.getAttribute('data-label') === ${JSON.stringify(label)});
        return {path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bar-count').textContent)};
      })()`);
    }
    async function assertLinkedCount(link) {
      await navigate(link.path);
      assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), link.count);
      assert.equal(await evaluate('document.querySelector(".charts-objects").open'), true);
      const pagination = await evaluate('document.querySelector(".charts-pagination").textContent');
      assert.match(pagination, new RegExp(`of ${link.count} objects?`));
    }
    async function layout(label, width) {
      stage = `layout ${label} at ${width}`;
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await settleLayout();
      const metrics = await evaluate(`({
        documentWidth: document.documentElement.scrollWidth,
        viewport: innerWidth,
        mainLeft: document.querySelector('.charts-page').getBoundingClientRect().left,
        sidebarRight: document.querySelector('.pc-sidebar').getBoundingClientRect().right,
        titleTop: document.querySelector('.charts-heading h1').getBoundingClientRect().top,
        headerBottom: document.querySelector('.pc-header').getBoundingClientRect().bottom,
        titleVisible: (() => {
          const title = document.querySelector('.charts-heading h1');
          const rect = title.getBoundingClientRect();
          return title.contains(document.elementFromPoint(rect.left + 10, rect.top + 10));
        })(),
        titleLeft: document.querySelector('.charts-heading h1').getBoundingClientRect().left,
        height: document.documentElement.scrollHeight,
        primary: [...document.querySelectorAll('.charts-primary-grid .charts-bar-svg')]
          .map(svg => ({top: svg.getBoundingClientRect().top, bottom: svg.getBoundingClientRect().bottom})),
        graphCount: document.querySelectorAll('.charts-bar-svg, .charts-histogram-svg').length,
        numericLabels: [...document.querySelectorAll('.charts-histogram-svg text')].map(text => {
          const svg = text.ownerSVGElement, box = text.getBBox(), bounds = svg.viewBox.baseVal;
          return {label: text.textContent, fontSize: parseFloat(getComputedStyle(text).fontSize) * svg.getScreenCTM().a,
            clipped: box.x < -1 || box.y < -1 || box.x + box.width > bounds.width + 1 || box.y + box.height > bounds.height + 1};
        }),
      })`);
      assert.ok(metrics.documentWidth <= width, `${label} overflows at ${width}: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.mainLeft >= metrics.sidebarRight - 1, `${label} under sidebar: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.titleVisible && metrics.titleTop >= metrics.headerBottom, `${label} title under navigation: ${JSON.stringify(metrics)}`);
      for (const text of metrics.numericLabels) {
        assert.ok(text.fontSize >= 9.5 && !text.clipped, `${label}: readable numeric label at ${width}: ${JSON.stringify(text)}`);
      }
      if (metrics.primary.length) {
        assert.equal(metrics.primary.length, 2);
        for (const chart of metrics.primary) {
          assert.ok(chart.top < 500 && chart.bottom < 1000, `Primary aggregate chart must be visible on the first screen: ${JSON.stringify(metrics)}`);
        }
        assert.equal(metrics.graphCount, 4);
      }
      if (process.env.CHARTS_SCREENSHOT_DIR && width === 1440) {
        mkdirSync(process.env.CHARTS_SCREENSHOT_DIR, {recursive: true});
        const viewport = await command('Page.captureScreenshot', {format: 'png'});
        writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '-viewport.png'), Buffer.from(viewport.data, 'base64'));
        await command('Emulation.setDeviceMetricsOverride', {width, height: Math.min(metrics.height, 4500), deviceScaleFactor: 1, mobile: false});
        await settleLayout();
        const shot = await command('Page.captureScreenshot', {format: 'png'});
        writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '.png'), Buffer.from(shot.data, 'base64'));
        await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
        await settleLayout();
      }
      return metrics;
    }
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await navigate();
    assert.equal(await evaluate('document.querySelector("h1").textContent'), 'Charts');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '26');
    assert.equal(await evaluate('document.body.textContent.includes("hidden-private-marker")'), false);
    assert.deepEqual(await selections(), {material: 'phase', setup: 'software', measure: 'temperature'});
    assert.equal(await evaluate('document.querySelectorAll(".charts-bar-svg, .charts-histogram-svg").length'), 4);
    assert.deepEqual(await evaluate('[...document.querySelectorAll(".charts-panel h2")].map(heading => heading.textContent)'),
      ['Materials & microstructure', 'Simulation setup', 'Simulation conditions', 'Available results']);
    assert.equal(await evaluate('document.querySelectorAll(".charts-curve-svg, #curve-object, #curve-component, #download-curve").length'), 0);
    for (const width of [1280, 1440, 1920]) await layout('varied-data', width);

    const matchingResults = await evaluate(`(() => {
      const link = document.querySelector('.charts-metric[href*="matching_response"]');
      return {path: link.getAttribute('href'), count: Number(link.querySelector('strong').textContent)};
    })()`);
    await assertLinkedCount(matchingResults);
    assert.ok(await evaluate('document.querySelector(".charts-filter").textContent.includes("Matching stress")'));
    await navigate();
    await evaluate('document.querySelector(".charts-composition details").open = true');
    assert.equal(await evaluate('document.querySelectorAll(".charts-composition .charts-category-table a").length'), 14);
    await choose('charts-material-group', 'texture', 'material_group');
    await choose('charts-group', 'elastic_model', 'group');
    assert.ok(await evaluate('document.querySelector(".charts-composition").textContent.includes("Anisotropic elasticity")'));
    await choose('charts-measure', 'grain_count', 'measure');
    assert.ok(await evaluate('document.querySelector(".charts-histogram-svg").getAttribute("aria-label").includes("Grain number")'));
    assert.deepEqual(await selections(), {material: 'texture', setup: 'elastic_model', measure: 'grain_count'});
    await choose('charts-group', 'loading_mode', 'group');
    const texture = await categoryLink('.charts-materials', 'Goss');
    await assertLinkedCount(texture);
    assert.deepEqual(await selections(), {material: 'texture', setup: 'loading_mode', measure: 'grain_count'});
    const cyclic = await categoryLink('.charts-composition', 'cyclic');
    await assertLinkedCount(cyclic);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    assert.deepEqual(await selections(), {material: 'texture', setup: 'loading_mode', measure: 'grain_count'});
    assert.ok(await evaluate('[...document.querySelectorAll(".charts-object-id")].every(element => /^charts-browser-\\d+$/.test(element.textContent))'));
    const grainBin = await evaluate(`(() => {
      const link = document.querySelector('.charts-histogram-svg .charts-bin[href]');
      return {path: link.getAttribute('href'), count: Number(link.getAttribute('aria-label').match(/View (\\d+) objects/)[1])};
    })()`);
    await assertLinkedCount(grainBin);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 3);
    assert.deepEqual(await selections(), {material: 'texture', setup: 'loading_mode', measure: 'grain_count'});

    await navigate();
    const phase = await categoryLink('.charts-materials', 'Copper');
    await evaluate(`document.querySelector('.charts-materials .charts-bar[data-label="Copper"]').focus()`);
    assert.equal(await evaluate('document.activeElement.getAttribute("data-label")'), 'Copper');
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await command('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13});
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + phase.path)} && document.readyState === 'complete'
      && document.querySelector('.charts-page').classList.contains('charts-js')`);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), phase.count);
    assert.equal(await evaluate('document.querySelectorAll(".charts-table tbody tr").length'), phase.count);
    assert.ok(await evaluate('document.querySelector(".charts-filter").textContent.includes("Copper")'));
    const software = await categoryLink('.charts-composition', 'Software 1');
    await assertLinkedCount(software);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    assert.ok(await evaluate('[...document.querySelectorAll(".charts-table tbody tr")].every(row => row.textContent.includes("Copper") && row.textContent.includes("Software 1"))'));
    const clear = await evaluate('document.querySelector(".charts-clear").getAttribute("href")');
    await navigate(clear);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '26');

    const bin = await evaluate(`(() => {
      const link = document.querySelector('.charts-histogram-svg .charts-bin[href]');
      return {path: link.getAttribute('href'), count: Number(link.getAttribute('aria-label').match(/View (\\d+) objects/)[1])};
    })()`);
    await assertLinkedCount(bin);

    await navigate('/charts/?scope=mine&show=objects');
    const firstIds = await evaluate('[...document.querySelectorAll(".charts-object-id")].map(el => el.textContent)');
    const next = await evaluate('document.querySelector("a[rel=next]").getAttribute("href")');
    await navigate(next);
    assert.ok(await evaluate('document.querySelector(".charts-pagination").textContent.includes("Page 2")'));
    const secondIds = await evaluate('[...document.querySelectorAll(".charts-object-id")].map(el => el.textContent)');
    assert.equal(firstIds.filter(id => secondIds.includes(id)).length, 0);
    await navigate('/charts/?scope=public&show=objects');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    for (const width of [1280, 1440, 1920]) await layout('long-singleton', width);
    await evaluate('document.getElementById("charts-scope").value = "shared"; document.querySelector(".charts-scope-form").requestSubmit()');
    await until('location.search === "?scope=shared" && document.readyState === "complete" && !!document.querySelector(".charts-page")');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');

    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate('/charts/?scope=mine', false);
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.equal(await evaluate('document.querySelectorAll(".charts-bar-svg, .charts-histogram-svg").length'), 4);
    assert.ok(await evaluate('getComputedStyle(document.querySelector(".charts-apply")).display !== "none"'));
    await evaluate('window.scrollTo(0, 0)');
    const visible = await evaluate(`(() => {
      return [...document.querySelectorAll('.charts-primary-grid .charts-bar-svg')].every(svg => {
        const rect = svg.getBoundingClientRect();
        return svg.contains(document.elementFromPoint(rect.left + 15, rect.top + 30));
      });
    })()`);
    assert.ok(visible, 'Both server-rendered aggregate charts remain visible without JavaScript');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await evaluate(`(() => {
      const select = document.getElementById('charts-material-group');
      select.value = 'texture';
      select.closest('form').requestSubmit();
    })()`);
    await until(`new URLSearchParams(location.search).get('material_group') === 'texture' && document.readyState === 'complete'
      && !!document.querySelector('.charts-materials svg[data-category=texture]')`);
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.equal(await evaluate('new URLSearchParams(location.search).get("scope")'), 'mine');
    const noScriptLink = await categoryLink('.charts-materials', 'Goss');
    await navigate(noScriptLink.path, false);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), noScriptLink.count);
    assert.equal(await evaluate('document.querySelector(".charts-objects").open'), true);
    await command('Emulation.setScriptExecutionDisabled', {value: false});

    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_EMPTY_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine');
    assert.equal(await evaluate('document.querySelectorAll(".charts-composition").length'), 0);
    assert.ok(await evaluate('document.querySelector(".charts-empty h2").textContent.includes("starts here")'));
    for (const width of [1280, 1440, 1920]) await layout('empty-data', width);
    if (process.env.CHARTS_SAMPLE_SESSION) {
      await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SAMPLE_SESSION,
        url: process.env.CHARTS_BASE_URL, path: '/'});
      await navigate('/charts/?scope=mine');
      assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
      assert.equal((await categoryLink('.charts-materials', 'Copper')).count, 1);
      assert.equal((await categoryLink('.charts-composition', 'Abaqus CAE')).count, 1);
      assert.match(await evaluate('document.querySelector(".charts-distribution-summary").textContent'), /Median\s+298\s+K/);
      assert.ok(await evaluate('document.querySelector(".charts-data-notes").textContent.includes("Different curve lengths")'));
      assert.equal(await evaluate('document.querySelectorAll(".charts-curve-svg, #curve-object, #curve-component").length'), 0);
      for (const width of [1280, 1440, 1920]) await layout('sample-copper', width);
      await assertLinkedCount(await categoryLink('.charts-materials', 'Copper'));
      await assertLinkedCount(await categoryLink('.charts-composition', 'Abaqus CAE'));
      for (const [measure, value, formatted] of [
        ['temperature', '298', '298 K'], ['grain_count', '343', '343'], ['discretization_count', '2744', '2,744'],
      ]) {
        if (measure !== 'temperature') await choose('charts-measure', measure, 'measure');
        assert.ok((await evaluate('document.querySelector(".charts-distribution-summary").textContent')).includes(formatted));
        const sampleBin = await evaluate(`(() => {
          const link = document.querySelector('.charts-histogram-svg .charts-bin[href]');
          return {path: link.getAttribute('href'), count: Number(link.getAttribute('aria-label').match(/View (\\d+) objects/)[1])};
        })()`);
        assert.ok(new URL(process.env.CHARTS_BASE_URL + sampleBin.path).searchParams.getAll('range')
          .includes(`${measure}:${value}:${value}:1`));
        await assertLinkedCount(sampleBin);
      }
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 5);
      assert.equal(await evaluate('document.querySelector(".charts-object-id").textContent'), 'a46fde6c');
      assert.equal(await evaluate('document.querySelector(".charts-object-title").getAttribute("href")'),
        process.env.CHARTS_SAMPLE_DETAIL_URL);
      await choose('charts-material-group', 'texture', 'material_group');
      assert.equal((await categoryLink('.charts-materials', 'Goss')).count, 1);
      console.log('Charts local sample checks passed: Copper, Abaqus CAE, Goss, 298 K, 343 grains, 2,744 cells, exact combined links, detail navigation, and 3 desktop layouts.');
    }
    assert.deepEqual(exceptions, []);
    console.log('Charts browser checks passed: four aggregate SVG plots, keyboard category links, independent material/setup/condition controls, exact combined drillthrough, pagination, permissions, no JavaScript, and 9 desktop layouts.');
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
