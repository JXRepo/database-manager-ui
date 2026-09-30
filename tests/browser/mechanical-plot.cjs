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
        chart.resize();
        window.plotTexts = [];
        chart.update('none');
        const {x, y} = chart.scales;
        const area = chart.chartArea;
        const rect = chart.canvas.getBoundingClientRect();
        const sign = scale => (scale.min < 0 ? '-' : '') + (scale.max > 0 ? '+' : '');
        const ctx = chart.ctx;
        function hasAxis(px, py) {
          const pixels = ctx.getImageData(Math.floor(px) - 2, Math.floor(py) - 2, 5, 5).data;
          for (let i = 0; i < pixels.length; i += 4) {
            const coverage = (255 - pixels[i]) / 108;
            if (coverage > .1 && Math.abs(pixels[i + 1] - (255 - coverage * 88)) < 4
              && Math.abs(pixels[i + 2] - (255 - coverage * 71)) < 4) return true;
          }
          return false;
        }
        const data = chart.data.datasets[0].data;
        const originX = x.getPixelForValue(0), originY = y.getPixelForValue(0);
        const framePixels = [];
        for (const fraction of [.25, .5, .75]) {
          const px = area.left + area.width * fraction, py = area.top + area.height * fraction;
          for (const edge of [area.top, area.bottom]) {
            if (Math.abs(edge - originY) > 5 && Math.abs(px - originX) > 5 && hasAxis(px, edge)) framePixels.push({px, py: edge});
          }
          for (const edge of [area.left, area.right]) {
            if (Math.abs(edge - originX) > 5 && Math.abs(py - originY) > 5 && hasAxis(edge, py)) framePixels.push({px: edge, py});
          }
        }
        const gaps = [];
        for (let i = 1; i < data.length; i++) {
          const start = data[i - 1], end = data[i];
          if (start.x === end.x && start.y === end.y) continue;
          for (const fraction of [0, .25, .5, .75, 1]) {
            const px = x.getPixelForValue(start.x) * (1 - fraction) + x.getPixelForValue(end.x) * fraction;
            const py = y.getPixelForValue(start.y) * (1 - fraction) + y.getPixelForValue(end.y) * fraction;
            const pixels = ctx.getImageData(Math.floor(px) - 2, Math.floor(py) - 2, 5, 5).data;
            let blue = false;
            for (let j = 0; j < pixels.length; j += 4) {
              if (pixels[j + 2] > 120 && pixels[j + 2] - pixels[j] > 55) {blue = true; break;}
            }
            if (!blue) gaps.push({i, fraction, px, py});
          }
        }
        return {xSigns: sign(x), ySigns: sign(y), width: chart.width, height: chart.height,
          displayWidth: rect.width, displayHeight: rect.height,
          xMin: x.min, xMax: x.max, yMin: y.min, yMax: y.max, area,
          originX, originY, framePixels,
          horizontal: hasAxis(area.left + area.width * .25, originY),
          vertical: hasAxis(originX, area.top + area.height * .25),
          xArrow: hasAxis(area.right + 8, originY + 2),
          yArrow: hasAxis(originX + 2, area.top - 8),
          radii: chart.getDatasetMeta(0).data.map(point => point.options.radius), gaps,
          xGrid: x.options.grid.display, yGrid: y.options.grid.display,
          data, texts: window.plotTexts,
          overflow: document.documentElement.scrollWidth > innerWidth};
      })()`);
      if (expected) {
        assert.equal(metrics.xSigns, expected.xSigns, `${label}: X quadrants`);
        assert.equal(metrics.ySigns, expected.ySigns, `${label}: Y quadrants`);
        assert.deepEqual(metrics.data, expected.x.map((x, i) => ({x, y: expected.y[i]})), `${label}: original point order`);
      }
      for (const coordinate of ['x', 'y']) {
        const values = metrics.data.map(point => point[coordinate]);
        const low = Math.min(...values), high = Math.max(...values);
        if (low !== high) {
          assert.equal(metrics[coordinate + 'Min'], Math.min(0, low), `${label}: ${coordinate} minimum includes zero`);
          assert.equal(metrics[coordinate + 'Max'], Math.max(0, high), `${label}: ${coordinate} maximum includes zero`);
        }
      }
      assert.ok(metrics.horizontal && metrics.vertical, `${label}: two axes through the true origin`);
      assert.ok(Math.abs(metrics.displayWidth - metrics.width) < 1
        && Math.abs(metrics.displayHeight - metrics.height) < 1,
        `${label}: displayed canvas and pointer coordinates share the same size`);
      assert.ok(metrics.xArrow && metrics.yArrow, `${label}: positive-direction arrowheads`);
      assert.deepEqual(metrics.framePixels, [], `${label}: no additional rectangular frame`);
      assert.ok(metrics.radii.every(radius => radius === 0), `${label}: no endpoint circles`);
      assert.deepEqual(metrics.gaps, [], `${label}: labels never erase curve segments`);
      assert.equal(metrics.xGrid, false);
      assert.equal(metrics.yGrid, false);
      assert.equal(metrics.overflow, false, `${label}: desktop width`);
      assert.ok(metrics.texts.length > 5, `${label}: visible ticks and titles`);
      const zeros = metrics.texts.filter(text => text.text === '0');
      assert.equal(zeros.length, 2, `${label}: separate zero labels for X and Y`);
      assert.ok(zeros.every(text => Math.abs((text.left + text.right) / 2 - metrics.originX) < 25
        && Math.abs((text.top + text.bottom) / 2 - metrics.originY) < 30), `${label}: zeros sit beside the origin`);
      for (const text of metrics.texts) {
        assert.ok(text.left >= -1 && text.right <= metrics.width + 1
          && text.top >= -1 && text.bottom <= metrics.height + 1, `${label}: clipped ${JSON.stringify(text)}`);
        const outside = text.right <= metrics.area.left || text.left >= metrics.area.right
          || text.bottom <= metrics.area.top || text.top >= metrics.area.bottom;
        const besideAxis = Math.abs((text.left + text.right) / 2 - metrics.originX) < 96
          || Math.abs((text.top + text.bottom) / 2 - metrics.originY) < 30;
        assert.ok(outside || besideAxis, `${label}: labels sit beside the axes: ${JSON.stringify(text)}`);
      }
      assert.ok(metrics.texts.some(item => item.text === 'σ' && Math.abs(item.rotation + Math.PI / 2) < 1e-6),
        `${label}: stress title is vertical`);
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
    async function hover(label, segment, fraction, expectedIndex, offset = 0) {
      await evaluate(`document.querySelector('.plot-panel').scrollIntoView({block: 'start', behavior: 'instant'});
        scrollBy({top: -88, behavior: 'instant'});
        new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      const position = await evaluate(`(() => {
        const chart = Chart.getChart('mechanical-plot'), points = chart.getDatasetMeta(0).data;
        const a = points[${segment}].getCenterPoint(true), b = (points[${segment + 1}] || points[${segment}]).getCenterPoint(true);
        const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
        const x = a.x + dx * ${fraction} - dy / length * ${offset};
        const y = a.y + dy * ${fraction} + dx / length * ${offset};
        const rect = chart.canvas.getBoundingClientRect();
        return {x: rect.left + x * rect.width / chart.width, y: rect.top + y * rect.height / chart.height};
      })()`);
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: position.x, y: position.y});
      try {
        await until(`(() => {const chart = Chart.getChart('mechanical-plot');
          return chart.getActiveElements().length === 1 && chart.getActiveElements()[0].index === ${expectedIndex}
            && chart.tooltip.opacity > .99;})()`);
      } catch (error) {
        throw new Error(`${label}: pointer on segment ${segment} at ${fraction}, expected sample ${expectedIndex}. ${error.message}`);
      }
      const state = await evaluate(`(() => {
        const chart = Chart.getChart('mechanical-plot'), active = chart.getActiveElements()[0];
        const point = active.element, center = point.getCenterPoint(true);
        const pixels = chart.ctx.getImageData(Math.floor(center.x) - 8, Math.floor(center.y) - 8, 17, 17).data;
        let bluePixels = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 2] > 120 && pixels[i + 2] - pixels[i] > 55) bluePixels++;
        }
        return {radius: point.options.radius, border: point.options.borderColor, bluePixels,
          title: chart.tooltip.title, body: chart.tooltip.body.flatMap(row => row.lines),
          raw: chart.data.datasets[0].data[active.index], tooltipIndex: chart.tooltip.getActiveElements()[0].index};
      })()`);
      assert.ok(state.radius >= 7 && state.bluePixels > 80, `${label}: visibly enlarged hover dot`);
      assert.equal(state.border, '#ffffff', `${label}: contrasting hover edge`);
      assert.equal(state.tooltipIndex, expectedIndex, `${label}: marker and tooltip show the same sample`);
      assert.deepEqual(state.title, [`Sample index ${expectedIndex}`]);
      assert.ok(state.body.some(line => line.startsWith('X: ') && line.endsWith(String(state.raw.x))), `${label}: exact X value`);
      assert.ok(state.body.some(line => line.startsWith('Y: ') && line.endsWith(String(state.raw.y))), `${label}: exact Y value`);
      assert.ok(state.body.some(line => line.includes('MPa')) && state.body.some(line => line.includes('(-)')),
        `${label}: selected units`);
      return position;
    }
    async function clearHover() {
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 300, y: 35});
      await until(`(() => {const chart = Chart.getChart('mechanical-plot');
        return chart.getActiveElements().length === 0 && chart.tooltip.opacity === 0;})()`);
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
          const matrix = this.getTransform();
          const corners = [[x - m.actualBoundingBoxLeft, y - m.actualBoundingBoxAscent],
            [x + m.actualBoundingBoxRight, y - m.actualBoundingBoxAscent],
            [x - m.actualBoundingBoxLeft, y + m.actualBoundingBoxDescent],
            [x + m.actualBoundingBoxRight, y + m.actualBoundingBoxDescent]]
            .map(([px, py]) => ({x: matrix.a * px + matrix.c * py + matrix.e,
              y: matrix.b * px + matrix.d * py + matrix.f}));
          window.plotTexts.push({text, font: this.font, rotation: Math.atan2(matrix.b, matrix.a),
            left: Math.min(...corners.map(point => point.x)), right: Math.max(...corners.map(point => point.x)),
            top: Math.min(...corners.map(point => point.y)), bottom: Math.max(...corners.map(point => point.y))});
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
    for (const width of [1280, 1440, 1920]) {
      await navigate(cases[0].path);
      await select('plot-x-select', 'total_strain.strain_11');
      await layout('hover-sparse', width, cases[0]);
      for (const fraction of [.1, .3, .49, .51, .7, .9]) {
        await hover('sparse segment', 0, fraction, fraction < .5 ? 0 : 1, 7);
      }
      const nearLine = await hover('line proximity', 0, .3, 0, 7);
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: nearLine.x, y: nearLine.y - 48});
      await until(`(() => {const chart = Chart.getChart('mechanical-plot');
        return chart.getActiveElements().length === 0 && chart.tooltip.opacity === 0;})()`);
      await hover('line re-entry', 0, .3, 0);
      const margin = await evaluate(`(() => {const rect = canvas.getBoundingClientRect();
        return {x: rect.left + 5, y: rect.top + 5};})()`);
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: margin.x, y: margin.y});
      await until(`(() => {const chart = Chart.getChart('mechanical-plot');
        return chart.getActiveElements().length === 0 && chart.tooltip.opacity === 0;})()`);
      await hover('leave canvas', 0, .3, 0);
      await clearHover();
    }
    for (const name of ['small', 'zero']) {
      await navigate(cases.find(item => item.name === name).path);
      await select('plot-x-select', 'total_strain.strain_11');
      await layout(`hover-${name}`, 1440);
      await hover(name, 0, name === 'small' ? .7 : 0, name === 'small' ? 1 : 0);
      await clearHover();
    }
    await navigate(cases.find(item => item.name === 'cycle').path);
    await select('plot-x-select', 'total_strain.strain_11');
    await layout('hover-cycle', 1440);
    await hover('cycle reversal', 3, .7, 4);
    if (process.env.PLOT_SCREENSHOT_DIR) {
      const shot = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, 'hover-tooltip.png'), Buffer.from(shot.data, 'base64'));
    }
    await clearHover();
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
    console.log(`Mechanical plot browser checks passed: ${cases.length} cases at 3 desktop widths, consistent canvas sizing, continuous sparse-line hover, enlarged sample markers, precise X/Y readouts, tiny values, a single point, reversals and hover clearing; two Cartesian axes, arrowheads, separate origin labels, no frame, asymmetric data ranges including zero, vertical stress title, uninterrupted curves, original samples, linked selectors, raw values, PNG/CSV downloads and empty data.`);
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
