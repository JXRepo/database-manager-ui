const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, readFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync} = require('node:fs');
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
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out: ${expression}`);
    }
    async function navigate(path = '/charts/', enhanced = true) {
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
    async function layout(label, width) {
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
        curveTop: document.querySelector('.charts-curve-svg')?.getBoundingClientRect().top,
        curveBottom: document.querySelector('.charts-curve-svg')?.getBoundingClientRect().bottom,
        graphCount: document.querySelectorAll('.charts-curve-svg, .charts-bar-svg, .charts-histogram-svg').length,
      })`);
      assert.ok(metrics.documentWidth <= width, `${label} overflows at ${width}: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.mainLeft >= metrics.sidebarRight - 1, `${label} under sidebar: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.titleVisible && metrics.titleTop >= metrics.headerBottom, `${label} title under navigation: ${JSON.stringify(metrics)}`);
      if (metrics.curveTop) {
        assert.ok(metrics.curveTop < 400 && metrics.curveBottom < 850, 'Curve must be visible on the first screen');
        assert.ok(metrics.graphCount >= 3);
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
    assert.ok(await evaluate('document.getElementById("response-line").getTotalLength() > 0'));
    assert.equal(await evaluate('document.querySelectorAll(".charts-curve-svg, .charts-bar-svg, .charts-histogram-svg").length'), 4);
    await evaluate('document.getElementById("response-plot").focus()');
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'ArrowRight', code: 'ArrowRight', windowsVirtualKeyCode: 39});
    assert.ok(await evaluate('document.getElementById("curve-tooltip").textContent.includes("Point 2")'));
    assert.equal(await evaluate('document.getElementById("curve-tooltip").hidden'), false);
    await evaluate('document.getElementById("response-plot").blur()');
    await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: profile});
    await evaluate('document.getElementById("download-curve").click()');
    for (let attempt = 0; attempt < 60 && !existsSync(join(profile, 'stress-strain.svg')); attempt++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const downloaded = readFileSync(join(profile, 'stress-strain.svg'), 'utf8');
    assert.match(downloaded, /id="response-line"/);
    assert.match(downloaded, /Equivalent stress/);
    assert.match(downloaded, /Supplied results/);
    assert.doesNotMatch(downloaded, /id="curve-focus"/);
    for (const width of [1280, 1440, 1920]) await layout('varied-data', width);

    await evaluate('document.getElementById("charts-group").value = "software"; document.getElementById("charts-group").dispatchEvent(new Event("change", {bubbles: true}))');
    await until('document.readyState === "complete" && !!document.querySelector("svg[data-category=software]")');
    await evaluate('document.querySelector(".charts-composition details").open = true');
    assert.equal(await evaluate('document.querySelectorAll(".charts-composition .charts-category-table a").length'), 14);
    await evaluate('document.getElementById("charts-group").value = "elastic_model"; document.getElementById("charts-group").dispatchEvent(new Event("change", {bubbles: true}))');
    await until('document.readyState === "complete" && !!document.querySelector("svg[data-category=elastic_model]")');
    assert.ok(await evaluate('document.querySelector(".charts-composition").textContent.includes("Anisotropic elasticity")'));
    await evaluate('document.getElementById("charts-measure").value = "grain_count"; document.getElementById("charts-measure").dispatchEvent(new Event("change", {bubbles: true}))');
    await until('new URLSearchParams(location.search).get("measure") === "grain_count" && document.readyState === "complete" && document.querySelector(".charts-histogram-svg").getAttribute("aria-label").includes("Grain number")');
    const specificObject = await evaluate('[...document.querySelectorAll("#curve-object option")].find(option => option.textContent.includes("charts-browser-0")).value');
    await evaluate('document.getElementById("curve-object").value = ' + JSON.stringify(specificObject) + '; document.getElementById("curve-object").dispatchEvent(new Event("change", {bubbles: true}))');
    await until('document.readyState === "complete" && document.querySelectorAll("#curve-component option").length === 2');
    await evaluate('document.getElementById("curve-component").value = "33"; document.getElementById("curve-component").dispatchEvent(new Event("change", {bubbles: true}))');
    await until('new URLSearchParams(location.search).get("component") === "33" && document.readyState === "complete" && document.querySelector("#curve-title").textContent.includes("σ₃₃")');
    assert.deepEqual(await evaluate('JSON.parse(document.getElementById("curve-points").textContent).map(point => point.y)'), [0, -60, -100]);
    const sampledObject = await evaluate('[...document.querySelectorAll("#curve-object option")].find(option => option.textContent.endsWith(" · charts-browser-23")).value');
    await navigate('/charts/?curve=' + sampledObject);
    assert.ok(await evaluate('JSON.parse(document.getElementById("curve-points").textContent).length <= 2400'));
    rmSync(join(profile, 'stress-strain.svg'));
    await evaluate('document.getElementById("download-curve").click()');
    for (let attempt = 0; attempt < 60 && !existsSync(join(profile, 'stress-strain.svg')); attempt++) {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const sampledExport = readFileSync(join(profile, 'stress-strain.svg'), 'utf8');
    assert.match(sampledExport, /charts-browser-23/);
    assert.match(sampledExport, /plotted points from 12000 paired samples/);
    assert.match(sampledExport, /Strain: 12002 points; stress: 12000/);
    assert.match(sampledExport, /Preview shows \d+ points, retaining local extrema/);
    await navigate();

    const phase = await evaluate(`(() => {
      const link = [...document.querySelectorAll('[data-category=phase] .charts-bar')].find(el => el.getAttribute('data-label') === 'Copper');
      return {path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bar-count').textContent)};
    })()`);
    await navigate(phase.path);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), phase.count);
    assert.equal(await evaluate('document.querySelector(".charts-objects").open'), true);
    assert.equal(await evaluate('document.querySelectorAll(".charts-table tbody tr").length'), phase.count);
    assert.ok(await evaluate('document.querySelector(".charts-filter").textContent.includes("Copper")'));
    const clear = await evaluate('document.querySelector(".charts-clear").getAttribute("href")');
    await navigate(clear);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '26');

    const bin = await evaluate(`(() => {
      const link = document.querySelector('.charts-histogram-svg .charts-bin[href]');
      return {path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bin-count').textContent)};
    })()`);
    await navigate(bin.path);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), bin.count);

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
    assert.equal(await evaluate('document.querySelectorAll(".charts-curve-svg, .charts-bar-svg, .charts-histogram-svg").length'), 4);
    assert.ok(await evaluate('getComputedStyle(document.querySelector(".charts-apply")).display !== "none"'));
    const visible = await evaluate('(() => {const svg = document.getElementById("response-plot"); const r = svg.getBoundingClientRect(); return svg.contains(document.elementFromPoint(r.left + 100, r.top + 60));})()');
    assert.ok(visible, 'The server-rendered curve remains visible without JavaScript');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await command('Emulation.setScriptExecutionDisabled', {value: false});

    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_EMPTY_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine');
    assert.equal(await evaluate('document.querySelectorAll(".charts-composition").length'), 0);
    assert.ok(await evaluate('document.querySelector(".charts-empty h2").textContent.includes("starts here")'));
    for (const width of [1280, 1440, 1920]) await layout('empty-data', width);
    assert.deepEqual(exceptions, []);
    console.log('Charts browser checks passed: four visible SVG plots, keyboard point inspection, SVG download, category/measure/object/component controls, exact drillthrough, pagination, permissions, no JavaScript, and 9 desktop layouts.');
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
