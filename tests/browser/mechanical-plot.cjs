const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync, mkdirSync, readFileSync, readdirSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  // Use the page's existing Chart.js library; a cached bundle allows offline checks.
  const library = process.env.CHARTJS_TEST_BUNDLE
    ? readFileSync(process.env.CHARTJS_TEST_BUNDLE, 'utf8')
    : await (await fetch('https://cdn.jsdelivr.net/npm/chart.js', {signal: AbortSignal.timeout(30000)})).text();
  const profile = mkdtempSync(join(tmpdir(), 'mechanical-plot-browser-'));
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
    async function navigate(path, hasCurve = true) {
      const url = process.env.PLOT_BASE_URL + path;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'
        && !!document.querySelector('.plot-panel') ${hasCurve ? '&& !!Chart.getChart("mechanical-plot")' : ''}`);
      if (hasCurve) await evaluate('Chart.getChart("mechanical-plot").stop(); Chart.getChart("mechanical-plot").update("none")');
    }
    async function select(id, value) {
      await evaluate(`document.getElementById(${JSON.stringify(id)}).value = ${JSON.stringify(value)};
        document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('change', {bubbles: true}));
        Chart.getChart('mechanical-plot').stop(); Chart.getChart('mechanical-plot').update('none')`);
    }
    async function layout(label, width, expected = null) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
      await evaluate(`new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      const metrics = await evaluate(`(() => {
        const chart = Chart.getChart('mechanical-plot');
        window.plotTexts = [];
        chart.resize(); chart.update('none');
        const {x, y} = chart.scales;
        const area = chart.chartArea;
        const sign = scale => (scale.min < 0 ? '-' : '') + (scale.max > 0 ? '+' : '');
        const ctx = chart.ctx;
        function hasAxis(px, py) {
          const pixels = ctx.getImageData(Math.floor(px) - 2, Math.floor(py) - 2, 5, 5).data;
          for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i] < 225 && pixels[i + 2] - pixels[i] > 8) return true;
          }
          return false;
        }
        return {xSigns: sign(x), ySigns: sign(y), width: chart.width, height: chart.height,
          xZero: x.getPixelForValue(0), yZero: y.getPixelForValue(0), area,
          horizontal: hasAxis(area.left + area.width * .25, y.getPixelForValue(0)),
          vertical: hasAxis(x.getPixelForValue(0), area.top + area.height * .25),
          xGrid: x.options.grid.display, yGrid: y.options.grid.display,
          data: chart.data.datasets[0].data, texts: window.plotTexts,
          overflow: document.documentElement.scrollWidth > innerWidth};
      })()`);
      if (expected) {
        assert.equal(metrics.xSigns, expected.xSigns, `${label}: X quadrants`);
        assert.equal(metrics.ySigns, expected.ySigns, `${label}: Y quadrants`);
        assert.deepEqual(metrics.data, expected.x.map((x, i) => ({x, y: expected.y[i]})), `${label}: original point order`);
      }
      assert.ok(metrics.horizontal && metrics.vertical, `${label}: both zero axes are drawn`);
      assert.equal(metrics.xGrid, false);
      assert.equal(metrics.yGrid, false);
      assert.equal(metrics.overflow, false, `${label}: desktop width`);
      assert.ok(metrics.texts.length > 5, `${label}: visible ticks and titles`);
      for (const text of metrics.texts) {
        assert.ok(text.left >= -1 && text.right <= metrics.width + 1
          && text.top >= -1 && text.bottom <= metrics.height + 1, `${label}: clipped ${JSON.stringify(text)}`);
      }
      for (const symbol of ['σ', 'ε']) {
        assert.ok(metrics.texts.some(item => item.text === symbol && item.font.includes('italic')), `${label}: italic ${symbol}`);
      }
      assert.ok(metrics.texts.some(item => item.text === '(MPa)' && !item.font.includes('italic')));
      assert.ok(metrics.texts.some(item => item.text === '(-)' && !item.font.includes('italic')));
      if (process.env.PLOT_SCREENSHOT_DIR && width === 1440) {
        mkdirSync(process.env.PLOT_SCREENSHOT_DIR, {recursive: true});
        await evaluate(`document.querySelector('.plot-panel').scrollIntoView({block: 'start', behavior: 'instant'});
          scrollBy({top: -88, behavior: 'instant'});
          new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
        assert.ok(await evaluate(`(() => {const r = document.getElementById('mechanical-plot').getBoundingClientRect();
          return r.top >= 0 && r.bottom <= innerHeight;})()`), `${label}: canvas is visible in the screenshot`);
        const shot = await command('Page.captureScreenshot', {format: 'png'});
        writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, `${label}.png`), Buffer.from(shot.data, 'base64'));
      }
      return metrics;
    }
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: library});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: `
      window.plotTexts = [];
      const drawText = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...args) {
        if (this.canvas.id === 'mechanical-plot') {
          const m = this.measureText(text);
          window.plotTexts.push({text, font: this.font, left: x - m.actualBoundingBoxLeft,
            right: x + m.actualBoundingBoxRight, top: y - m.actualBoundingBoxAscent,
            bottom: y + m.actualBoundingBoxDescent});
        }
        return drawText.call(this, text, x, y, ...args);
      };`});
    await command('Network.setCookie', {name: process.env.PLOT_COOKIE_NAME, value: process.env.PLOT_SESSION,
      url: process.env.PLOT_BASE_URL, path: '/'});
    await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: profile});
    const cases = JSON.parse(process.env.PLOT_CASES);
    for (const item of cases) {
      await navigate(item.path);
      await select('plot-x-select', 'total_strain.strain_11');
      for (const width of [1280, 1440, 1920]) await layout(item.name, width, item);
    }
    await navigate(cases[0].path);
    await select('plot-x-select', 'total_strain.strain_22');
    assert.equal(await evaluate('ySelect.value'), 'stress.stress_22');
    await select('plot-y-select', 'stress.stress_11');
    assert.equal(await evaluate('xSelect.value'), 'total_strain.strain_11');
    await select('plot-x-select', 'plastic_strain.plastic_strain_11');
    assert.equal(await evaluate('ySelect.value'), 'stress.stress_11');
    await select('plot-x-select', 'total_strain.strain_11');
    assert.equal(await evaluate('document.getElementById("x-raw-pre").textContent'), '0: 0\n1: 0.01\n2: 0.02');
    await evaluate('document.getElementById("csv-clear-all").click()');
    assert.equal(await evaluate('document.getElementById("download-selected-csv").disabled'), true);
    await evaluate('document.getElementById("csv-select-all").click()');
    assert.equal(await evaluate('document.getElementById("download-selected-csv").disabled'), false);
    await evaluate('document.getElementById("download-plot-btn").click()');
    await evaluate('document.getElementById("download-xy-csv-btn").click()');
    for (let attempt = 0; attempt < 100; attempt++) {
      if (readdirSync(profile).some(name => name.endsWith('.png')) && readdirSync(profile).some(name => name.endsWith('.csv'))) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const pngName = readdirSync(profile).find(name => name.endsWith('.png'));
    const csvName = readdirSync(profile).find(name => name.endsWith('.csv'));
    assert.ok(pngName && csvName, 'PNG and selected X/Y CSV both download');
    const png = readFileSync(join(profile, pngName));
    const size = await evaluate('({width: canvas.width, height: canvas.height})');
    assert.equal(png.readUInt32BE(16), size.width + 96);
    assert.equal(png.readUInt32BE(20), size.height + 96);
    const csv = readFileSync(join(profile, csvName), 'utf8');
    assert.match(csv, /total_strain.strain_11/);
    assert.match(csv, /stress.stress_11/);
    assert.match(csv, /1,0.01,40/);
    if (process.env.PLOT_SCREENSHOT_DIR) writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, 'download.png'), png);
    if (process.env.PLOT_SAMPLE_PATH) {
      await navigate(process.env.PLOT_SAMPLE_PATH);
      for (const component of ['33', '22', '13', '23']) {
        await select('plot-x-select', `total_strain.strain_${component}`);
        await layout(`sample-${component}`, 1440);
      }
      assert.equal(await evaluate('Chart.getChart("mechanical-plot").data.datasets[0].data.length'), 242);
    }
    await navigate(process.env.PLOT_EMPTY_PATH, false);
    assert.match(await evaluate('document.querySelector(".plot-empty").textContent'), /No plot-ready mechanical variables/);
    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
      assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
    }
    assert.deepEqual(exceptions, []);
    console.log('Mechanical plot browser checks passed: 14 quadrant cases at 3 desktop widths, zero axes, no grid, unclipped labels, original samples, linked selectors, raw values, CSV selection, PNG/CSV downloads and empty data.');
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
