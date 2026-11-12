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
    function verifyAxisSegments(metrics, label) {
      const {area, axes, arrows} = metrics.plotLayout;
      const segments = {
        x: [{x: area.left - (metrics.xMin < 0 ? 24 : 0), y: axes.y}, {x: arrows.x[0].x, y: axes.y}],
        y: [{x: axes.x, y: area.bottom + (metrics.yMin < 0 ? 24 : 0)}, {x: axes.x, y: arrows.y[0].y}],
      };
      for (const axis of ['x', 'y']) {
        const expected = segments[axis];
        const matches = points => points.length === 2 && points.every((point, index) =>
          Math.hypot(point.x - expected[index].x, point.y - expected[index].y) < .15);
        const actual = metrics.strokePaths.find(path => path.color === '#111111' && path.points.length === 2
          && Math.hypot(path.points[1].x - expected[1].x, path.points[1].y - expected[1].y) < .15);
        assert.ok(actual, `${label}: ${axis} axis has a real stroke ending at its arrow tip`);
        const gap = axis === 'x' ? area.left - actual.points[0].x : actual.points[0].y - area.bottom;
        const expectedGap = metrics[axis + 'Min'] < 0 ? 24 : 0;
        assert.ok(Math.abs(gap - expectedGap) < .15,
          `${label}: ${axis} minimum-to-axis-end gap is ${gap}px; expected ${expectedGap}px`);
        assert.ok(matches(actual.points), `${label}: ${axis} axis remains aligned with its true zero coordinate`);
        if (metrics.plotLayout.axisSegments) {
          assert.ok(matches(metrics.plotLayout.axisSegments[axis]), `${label}: ${axis} measured segment matches its actual stroke`);
        }
        assert.ok(expected.every(point => point.x >= .75 && point.y >= .75
          && point.x <= metrics.width - .75 && point.y <= metrics.height - .75),
        `${label}: ${axis} axis stroke remains inside the canvas`);
      }
      return segments;
    }
    function verifyTextLayout(metrics, label) {
      const planned = metrics.plotLayout;
      assert.ok(planned && planned.ticks.length && planned.titles.x && planned.titles.y,
        `${label}: the drawing exposes its measured text layout`);
      const axisSegments = verifyAxisSegments(metrics, label);
      const fontSize = font => Number(font.match(/([\d.]+)px/)[1]);
      const close = (actual, expected, message) => assert.ok(Math.abs(actual - expected) <= .15,
        `${label}: ${message}: ${actual} instead of ${expected}`);
      const overlap = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > .5
        && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > .5;
      const union = boxes => ({
        left: Math.min(...boxes.map(box => box.left)), top: Math.min(...boxes.map(box => box.top)),
        right: Math.max(...boxes.map(box => box.right)), bottom: Math.max(...boxes.map(box => box.bottom)),
      });
      const used = new Set();
      assert.ok(Array.isArray(planned.multipliers), `${label}: scientific multipliers participate in measured layout`);
      const groups = [...planned.ticks, ...planned.multipliers, planned.titles.x, planned.titles.y];
      for (const position of groups) {
        const bounds = position.group.bounds;
        const drawnRuns = [];
        for (const run of position.group.runs) {
          const local = run.bounds;
          const rotated = Math.abs((position.rotation || 0) + Math.PI / 2) < 1e-6;
          const expected = rotated ? {
            left: position.left + local.top - bounds.top,
            right: position.left + local.bottom - bounds.top,
            top: position.top - local.right + bounds.right,
            bottom: position.top - local.left + bounds.right,
          } : {
            left: position.left + local.left - bounds.left,
            right: position.left + local.right - bounds.left,
            top: position.top + local.top - bounds.top,
            bottom: position.top + local.bottom - bounds.top,
          };
          // Canvas serializes fractional glyph sizes (22.9090909px becomes 22.9091px).
          const index = metrics.texts.findIndex((text, index) => !used.has(index)
            && text.text === run.text && Math.abs(fontSize(text.font) - fontSize(run.font)) < .0001
            && ['left', 'top', 'right', 'bottom'].every(edge => Math.abs(text[edge] - expected[edge]) <= .15));
          assert.ok(index >= 0, `${label}: fillText does not match the measured run ${JSON.stringify({
            run, expected, drawn: metrics.texts.filter(text => text.text === run.text),
          })}`);
          used.add(index);
          drawnRuns.push(metrics.texts[index]);
          const printedSize = fontSize(metrics.texts[index].font) * 85 / 25.4 * 72 / (metrics.width + 48);
          assert.ok(printedSize >= 5, `${label}: ${run.text} remains at least 5pt in an 85mm PNG, got ${printedSize}pt`);
        }
        const actual = union(drawnRuns);
        for (const edge of ['left', 'top', 'right', 'bottom']) {
          close(actual[edge], position[edge], `${position.axis || 'title'} group ${edge}`);
        }
        assert.ok(position.left >= 0 && position.top >= 0
          && position.right <= metrics.width && position.bottom <= metrics.height,
        `${label}: text group is clipped: ${JSON.stringify(position)}`);
      }
      for (let first = 0; first < groups.length; first++) {
        for (let second = first + 1; second < groups.length; second++) {
          assert.equal(overlap(groups[first], groups[second]), false,
            `${label}: measured labels overlap: ${JSON.stringify([groups[first], groups[second]])}`);
        }
      }
      for (const axis of ['x', 'y']) {
        const ticks = planned.ticks.filter(tick => tick.axis === axis);
        const exponent = metrics.exponents[axis];
        const multipliers = planned.multipliers.filter(multiplier => multiplier.axis === axis);
        assert.equal(multipliers.length, exponent === null ? 0 : 1,
          `${label}: ${axis} shows exactly one shared multiplier only when needed`);
        if (multipliers.length) {
          const multiplier = multipliers[0];
          assert.equal(multiplier.exponent, exponent, `${label}: ${axis} multiplier matches its scale`);
          assert.ok(multiplier.group.runs.some(run => run.text === '× 10'), `${label}: shared multiplier has a multiplication sign`);
          assert.ok(multiplier.group.runs.some(run => run.text === String(exponent)), `${label}: shared exponent is drawn`);
        }
        for (const endpoint of [metrics[axis + 'Min'], metrics[axis + 'Max']]) {
          assert.ok(ticks.some(tick => tick.value === endpoint), `${label}: ${axis} endpoint remains labelled: ${endpoint}`);
        }
        const labels = metrics.tickLabels.filter(tick => tick.axis === axis);
        const visibleLabels = labels.map(({value, label: tickLabel}) => {
          if (value === 0) {
            assert.deepEqual(tickLabel, {type: 'plain', text: '0'}, `${label}: true zero remains plain`);
            return '0';
          }
          if (tickLabel.type === 'plain') {
            assert.match(tickLabel.text, /^-?\d+\.\d{2}$/, `${label}: ordinary ticks use exactly two decimals`);
            assert.notEqual(Number(tickLabel.text), 0, `${label}: a nonzero tick must not round to a false zero`);
            return tickLabel.text;
          }
          assert.match(tickLabel.mantissa, /^-?\d+\.\d{2}$/, `${label}: scientific mantissas use two decimals`);
          assert.match(tickLabel.exponent, /^-?\d+$/, `${label}: scientific exponents remain integers`);
          return `${tickLabel.mantissa}e${tickLabel.exponent}`;
        });
        assert.equal(new Set(visibleLabels).size, visibleLabels.length, `${label}: ${axis} tick labels remain distinct`);
        for (const tick of ticks) {
          const formatted = labels.find(item => item.value === tick.value).label;
          const main = formatted.type === 'plain' ? formatted.text : `${formatted.mantissa} × 10`;
          assert.ok(tick.group.runs.some(run => run.text === main),
            `${label}: ${axis} tick draws the expected coefficient: ${main}`);
          if (formatted.type === 'scientific') {
            assert.ok(tick.group.runs.some(run => run.text === formatted.exponent),
              `${label}: ${axis} exceptional coefficient exponent is drawn`);
          }
        }
        const arrow = planned.arrows[axis];
        assert.equal(arrow.length, 3, `${label}: ${axis} arrow has three vertices`);
        assert.ok(metrics.filledPaths.some(path => path.length === arrow.length
          && path.every((point, index) => Math.hypot(point.x - arrow[index].x, point.y - arrow[index].y) < .15)),
        `${label}: ${axis} arrow's actual filled vertices match the layout`);
        const arrowBox = union(arrow.map(point => ({left: point.x, right: point.x, top: point.y, bottom: point.y})));
        assert.ok(arrowBox.left >= 0 && arrowBox.top >= 0
          && arrowBox.right <= metrics.width && arrowBox.bottom <= metrics.height,
        `${label}: ${axis} arrow remains inside the canvas`);
        const rangeEnd = axis === 'x' ? metrics.area.right : metrics.area.top;
        const baseGap = axis === 'x' ? arrowBox.left - rangeEnd : rangeEnd - arrowBox.bottom;
        assert.ok(baseGap >= 24 - .15, `${label}: ${axis} arrow base stays 24px beyond the range endpoint`);
        close(axis === 'x' ? arrowBox.right - arrowBox.left : arrowBox.bottom - arrowBox.top, 8,
          `${axis} arrow length`);
        for (const group of groups) {
          assert.equal(overlap(group, arrowBox), false,
            `${label}: ${axis} arrow overlaps text: ${JSON.stringify({group, arrowBox})}`);
        }
      }
      const arrowPoints = [...planned.arrows.x, ...planned.arrows.y, ...axisSegments.x, ...axisSegments.y];
      const axisText = [...planned.ticks, ...planned.multipliers];
      const xTitleGap = planned.xSide < 0
        ? Math.min(metrics.area.top, ...axisText.map(tick => tick.top), ...arrowPoints.map(point => point.y)) - planned.titles.x.bottom
        : planned.titles.x.top - Math.max(metrics.area.bottom, ...axisText.map(tick => tick.bottom), ...arrowPoints.map(point => point.y));
      const yTitleGap = planned.ySide < 0
        ? Math.min(metrics.area.left, ...axisText.map(tick => tick.left), ...arrowPoints.map(point => point.x)) - planned.titles.y.right
        : planned.titles.y.left - Math.max(metrics.area.right, ...axisText.map(tick => tick.right), ...arrowPoints.map(point => point.x));
      close(xTitleGap, 16, 'X title gap includes shared multipliers and the complete axis envelope');
      close(yTitleGap, 16, 'Y title gap includes shared multipliers and the complete axis envelope');
      const sigma = metrics.texts.find(text => text.text === 'σ');
      const epsilon = metrics.texts.find(text => text.text === 'ε');
      assert.ok(sigma && epsilon && Math.abs(sigma.glyphHeight - epsilon.glyphHeight) <= 1,
        `${label}: sigma and epsilon have matching visible glyph heights`);
    }
    async function layout(label, width, expected = null) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
      await evaluate(`new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      const metrics = await evaluate(`(() => {
        const chart = Chart.getChart('mechanical-plot');
        chart.resize();
        window.plotTexts = [];
        window.plotFilledPaths = [];
        window.plotStrokePaths = [];
        chart.update('none');
        const {x, y} = chart.scales;
        const area = chart.chartArea;
        const rect = chart.canvas.getBoundingClientRect();
        const sign = scale => (scale.min < 0 ? '-' : '') + (scale.max > 0 ? '+' : '');
        const ctx = chart.ctx;
        function hasAxis(px, py) {
          const pixels = ctx.getImageData(Math.floor(px) - 2, Math.floor(py) - 2, 5, 5).data;
          for (let i = 0; i < pixels.length; i += 4) {
            if (pixels[i] < 225 && Math.abs(pixels[i + 1] - pixels[i]) < 4
              && Math.abs(pixels[i + 2] - pixels[i]) < 4) return true;
          }
          return false;
        }
        const data = chart.data.datasets[0].data;
        const originX = x.getPixelForValue(0), originY = y.getPixelForValue(0);
        const insideText = (px, py) => window.plotTexts.some(text => px >= text.left - 3
          && px <= text.right + 3 && py >= text.top - 3 && py <= text.bottom + 3);
        const framePixels = [];
        for (const fraction of [.25, .5, .75]) {
          const px = area.left + area.width * fraction, py = area.top + area.height * fraction;
          for (const edge of [area.top, area.bottom]) {
            if (Math.abs(edge - originY) > 5 && Math.abs(px - originX) > 5
              && !insideText(px, edge) && hasAxis(px, edge)) framePixels.push({px, py: edge});
          }
          for (const edge of [area.left, area.right]) {
            if (Math.abs(edge - originX) > 5 && Math.abs(py - originY) > 5
              && !insideText(edge, py) && hasAxis(edge, py)) framePixels.push({px: edge, py});
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
          radii: chart.getDatasetMeta(0).data.map(point => point.options.radius), gaps,
          xGrid: x.options.grid.display, yGrid: y.options.grid.display,
          data, texts: window.plotTexts, filledPaths: window.plotFilledPaths, strokePaths: window.plotStrokePaths,
          plotLayout: chart.$mechanicalPlotLayout,
          exponents: {x: x.options.customExponent, y: y.options.customExponent},
          tickLabels: chart.$mechanicalPlotLayout.ticks.map(tick => ({
            axis: tick.axis, value: tick.value,
            label: formatPlotTickLabel(tick.value - Number(chart.scales[tick.axis].options.customOffset || 0),
              chart.scales[tick.axis].options.customTickFormat,
              chart.scales[tick.axis].options.customExponent),
          })),
          overflow: document.documentElement.scrollWidth > innerWidth};
      })()`);
      if (process.env.PLOT_SCREENSHOT_DIR) {
        mkdirSync(process.env.PLOT_SCREENSHOT_DIR, {recursive: true});
        await evaluate(`document.querySelector('.plot-panel').scrollIntoView({block: 'start', behavior: 'instant'});
          scrollBy({top: -88, behavior: 'instant'});
          new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
        const shot = await command('Page.captureScreenshot', {format: 'png'});
        const filename = width === 1440 ? `${label}.png` : `${label}-${width}.png`;
        writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, filename), Buffer.from(shot.data, 'base64'));
        assert.ok(await evaluate(`(() => {const r = document.getElementById('mechanical-plot').getBoundingClientRect();
          return r.top >= 0 && r.bottom <= innerHeight;})()`), `${label}: canvas is visible in the screenshot`);
      }
      if (expected) {
        assert.equal(metrics.xSigns, expected.xSigns, `${label}: X quadrants`);
        assert.equal(metrics.ySigns, expected.ySigns, `${label}: Y quadrants`);
        assert.deepEqual(metrics.data, expected.x.map((x, i) => ({x, y: expected.y[i]})), `${label}: original point order`);
        if (expected.exponents) assert.deepEqual(metrics.exponents, expected.exponents, `${label}: independently selected axis multipliers`);
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
      assert.equal(metrics.width, 720, `${label}: fixed desktop chart width`);
      assert.equal(metrics.height, 480, `${label}: fixed desktop chart height`);
      assert.ok(Math.abs(metrics.displayWidth - metrics.width) < 1
        && Math.abs(metrics.displayHeight - metrics.height) < 1,
        `${label}: displayed canvas and pointer coordinates share the same size`);
      assert.deepEqual(metrics.framePixels, [], `${label}: no additional rectangular frame`);
      assert.ok(metrics.radii.every(radius => radius === 0), `${label}: no endpoint circles`);
      assert.deepEqual(metrics.gaps, [], `${label}: labels never erase curve segments`);
      assert.equal(metrics.xGrid, false);
      assert.equal(metrics.yGrid, false);
      assert.equal(metrics.overflow, false, `${label}: desktop width`);
      assert.ok(metrics.texts.length > 5, `${label}: visible ticks and titles`);
      verifyTextLayout(metrics, label);
      if (label === 'long-decimal-upper' || label === 'sample-33') {
        for (const axis of ['x', 'y']) {
          const count = metrics.tickLabels.filter(tick => tick.axis === axis).length;
          assert.ok(count >= 6, `${label}: ${axis} has at least six readable ticks, got ${count}`);
        }
      }
      const zeros = metrics.texts.filter(text => text.text === '0');
      assert.equal(zeros.length, 2, `${label}: separate zero labels for X and Y`);
      assert.ok(zeros.every(text => Math.abs((text.left + text.right) / 2 - metrics.originX) < 25
        && Math.abs((text.top + text.bottom) / 2 - metrics.originY) < 30), `${label}: zeros sit beside the origin`);
      for (const text of metrics.texts) {
        assert.ok(text.left >= -1 && text.right <= metrics.width + 1
          && text.top >= -1 && text.bottom <= metrics.height + 1, `${label}: clipped ${JSON.stringify(text)}`);
      }
      assert.ok(metrics.texts.some(item => item.text === 'σ' && Math.abs(item.rotation + Math.PI / 2) < 1e-6),
        `${label}: stress title is vertical`);
      for (const symbol of ['σ', 'ε']) {
        assert.ok(metrics.texts.some(item => item.text === symbol && item.font.includes('italic')), `${label}: italic ${symbol}`);
      }
      assert.ok(metrics.texts.some(item => item.text === '(MPa)' && !item.font.includes('italic')));
      assert.ok(metrics.texts.some(item => item.text === '(-)' && !item.font.includes('italic')));
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
        const ratio = chart.currentDevicePixelRatio;
        const pixels = chart.ctx.getImageData(Math.floor(center.x * ratio) - 8 * ratio,
          Math.floor(center.y * ratio) - 8 * ratio, 17 * ratio, 17 * ratio).data;
        let bluePixels = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 2] > 120 && pixels[i + 2] - pixels[i] > 55) bluePixels++;
        }
        return {radius: point.options.radius, border: point.options.borderColor, bluePixels: bluePixels / ratio ** 2,
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
    async function exportedLayout() {
      return evaluate(`({...window.plotExportGeometry,
        strokePaths: window.plotExportStrokePaths,
        filledPaths: window.plotExportFilledPaths,
        texts: window.plotExportTexts.map(text => ({...text, glyphHeight: text.glyphHeight / 3,
          left: text.left / 3, right: text.right / 3, top: text.top / 3, bottom: text.bottom / 3}))})`);
    }
    async function downloadMeasuredPNG(label) {
      const directory = mkdtempSync(join(profile, 'plot-download-'));
      await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: directory});
      try {
        await evaluate('window.capturePlotExport = true; window.plotExportTexts = []; window.plotExportFilledPaths = []; window.plotExportStrokePaths = []; window.plotExportGeometry = null; document.getElementById("download-plot-btn").click(); window.capturePlotExport = false');
        let name;
        for (let attempt = 0; attempt < 100; attempt++) {
          name = readdirSync(directory).find(file => file.endsWith('.png'));
          if (name) break;
          await new Promise(resolve => setTimeout(resolve, 50));
        }
        assert.ok(name, `${label}: PNG downloads`);
        verifyTextLayout(await exportedLayout(), `${label} PNG`);
        const png = readFileSync(join(directory, name));
        assert.equal(png.readUInt32BE(16), 2304);
        assert.equal(png.readUInt32BE(20), 1584);
        if (process.env.PLOT_SCREENSHOT_DIR) {
          mkdirSync(process.env.PLOT_SCREENSHOT_DIR, {recursive: true});
          writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, `${label}-download.png`), png);
        }
      } finally {
        await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: profile});
      }
    }
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: library});
    await command('Page.addScriptToEvaluateOnNewDocument', {source: `
      window.plotTexts = [];
      window.plotExportTexts = [];
      window.plotFilledPaths = [];
      window.plotExportFilledPaths = [];
      window.plotStrokePaths = [];
      window.plotExportStrokePaths = [];
      const isPlotExport = context => window.capturePlotExport && context.canvas.width === 2160 && context.canvas.height === 1440;
      const drawText = CanvasRenderingContext2D.prototype.fillText;
      CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...args) {
        const exporting = isPlotExport(this);
        if (this.canvas.id === 'mechanical-plot' || exporting) {
          const m = this.measureText(text);
          const matrix = this.getTransform();
          const corners = [[x - m.actualBoundingBoxLeft, y - m.actualBoundingBoxAscent],
            [x + m.actualBoundingBoxRight, y - m.actualBoundingBoxAscent],
            [x - m.actualBoundingBoxLeft, y + m.actualBoundingBoxDescent],
            [x + m.actualBoundingBoxRight, y + m.actualBoundingBoxDescent]]
            .map(([px, py]) => ({x: matrix.a * px + matrix.c * py + matrix.e,
              y: matrix.b * px + matrix.d * py + matrix.f}));
          const record = {text, font: this.font, rotation: Math.atan2(matrix.b, matrix.a),
            scaleX: Math.hypot(matrix.a, matrix.b), scaleY: Math.hypot(matrix.c, matrix.d),
            glyphHeight: (m.actualBoundingBoxAscent + m.actualBoundingBoxDescent) * Math.hypot(matrix.c, matrix.d),
            left: Math.min(...corners.map(point => point.x)), right: Math.max(...corners.map(point => point.x)),
            top: Math.min(...corners.map(point => point.y)), bottom: Math.max(...corners.map(point => point.y))};
          (exporting ? window.plotExportTexts : window.plotTexts).push(record);
        }
        return drawText.call(this, text, x, y, ...args);
      };
      const beginPath = CanvasRenderingContext2D.prototype.beginPath;
      CanvasRenderingContext2D.prototype.beginPath = function(...args) {
        if (this.canvas.id === 'mechanical-plot' || isPlotExport(this)) this.plotTestPath = [];
        return beginPath.apply(this, args);
      };
      for (const method of ['moveTo', 'lineTo']) {
        const original = CanvasRenderingContext2D.prototype[method];
        CanvasRenderingContext2D.prototype[method] = function(x, y, ...args) {
          if ((this.canvas.id === 'mechanical-plot' || isPlotExport(this)) && this.plotTestPath) {
            const matrix = this.getTransform();
            this.plotTestPath.push({x: matrix.a * x + matrix.c * y + matrix.e,
              y: matrix.b * x + matrix.d * y + matrix.f, move: method === 'moveTo'});
          }
          return original.call(this, x, y, ...args);
        };
      }
      const fill = CanvasRenderingContext2D.prototype.fill;
      CanvasRenderingContext2D.prototype.fill = function(...args) {
        const exporting = isPlotExport(this);
        if ((this.canvas.id === 'mechanical-plot' || exporting) && this.plotTestPath?.length === 3) {
          const paths = exporting ? window.plotExportFilledPaths : window.plotFilledPaths;
          const ratio = exporting ? 3 : 1;
          paths.push(this.plotTestPath.map(point => ({x: point.x / ratio, y: point.y / ratio})));
        }
        return fill.apply(this, args);
      };
      const stroke = CanvasRenderingContext2D.prototype.stroke;
      CanvasRenderingContext2D.prototype.stroke = function(...args) {
        const exporting = isPlotExport(this);
        if ((this.canvas.id === 'mechanical-plot' || exporting) && this.plotTestPath) {
          const paths = exporting ? window.plotExportStrokePaths : window.plotStrokePaths;
          const ratio = exporting ? 3 : 1;
          let points = [];
          for (const point of this.plotTestPath) {
            if (point.move && points.length) {
              paths.push({points, color: this.strokeStyle});
              points = [];
            }
            points.push({x: point.x / ratio, y: point.y / ratio});
          }
          if (points.length) paths.push({points, color: this.strokeStyle});
          if (exporting) {
            const chart = Chart.getChart(this.canvas);
            if (chart?.$mechanicalPlotLayout) window.plotExportGeometry = {
              plotLayout: chart.$mechanicalPlotLayout, width: chart.width, height: chart.height,
              area: chart.chartArea,
              xMin: chart.scales.x.min, xMax: chart.scales.x.max,
              yMin: chart.scales.y.min, yMax: chart.scales.y.max,
              exponents: {x: chart.scales.x.options.customExponent, y: chart.scales.y.options.customExponent},
              tickLabels: chart.$mechanicalPlotLayout.ticks.map(tick => ({
                axis: tick.axis, value: tick.value,
                label: formatPlotTickLabel(tick.value - Number(chart.scales[tick.axis].options.customOffset || 0),
                  chart.scales[tick.axis].options.customTickFormat,
                  chart.scales[tick.axis].options.customExponent),
              })),
            };
          }
        }
        return stroke.apply(this, args);
      };`});
    await command('Network.setCookie', {name: process.env.PLOT_COOKIE_NAME, value: process.env.PLOT_SESSION,
      url: process.env.PLOT_BASE_URL, path: '/'});
    await send('Browser.setDownloadBehavior', {behavior: 'allow', downloadPath: profile});
    const cases = JSON.parse(process.env.PLOT_CASES);
    for (const item of cases) {
      await navigate(item.path);
      assert.equal(await evaluate('document.querySelector("#plot-full-view, #plot-initial-view, #plot-initial-count")'), null,
        'The detail page shows the complete curve without sample-range controls');
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
    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 900, deviceScaleFactor: 2, mobile: false});
    await evaluate('Chart.getChart("mechanical-plot").resize()');
    await until('canvas.width === 1440');
    await hover('PNG excludes the active sample marker', 0, .7, 1);
    await evaluate('window.capturePlotExport = true; window.plotExportTexts = []; window.plotExportFilledPaths = []; window.plotExportStrokePaths = []; window.plotExportGeometry = null; document.getElementById("download-plot-btn").click(); window.capturePlotExport = false');
    await evaluate('document.getElementById("download-xy-csv-btn").click()');
    for (let attempt = 0; attempt < 100; attempt++) {
      if (readdirSync(profile).some(name => name.endsWith('.png')) && readdirSync(profile).some(name => name.endsWith('.csv'))) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    const pngName = readdirSync(profile).find(name => name.endsWith('.png'));
    const csvName = readdirSync(profile).find(name => name.endsWith('.csv'));
    assert.ok(pngName && csvName, 'PNG and selected X/Y CSV both download');
    const png = readFileSync(join(profile, pngName));
    assert.equal(png.readUInt32BE(16), (720 + 48) * 3, 'PNG uses three pixels per CSS pixel with equal margins');
    assert.equal(png.readUInt32BE(20), (480 + 48) * 3);
    const exportTexts = await evaluate('window.plotExportTexts');
    verifyTextLayout(await exportedLayout(), 'positive PNG');
    assert.ok(exportTexts.length > 5, 'PNG redraws its labels on the full resolution canvas');
    assert.ok(exportTexts.every(text => Math.abs(text.scaleX - 3) < 1e-6 && Math.abs(text.scaleY - 3) < 1e-6),
      'PNG uses a genuine threefold text transform rather than scaling an existing bitmap');
    assert.ok(exportTexts.every(text => text.left >= 0 && text.top >= 0 && text.right <= 2160 && text.bottom <= 1440),
      'PNG text remains inside its drawing canvas before the equal margins are added');
    assert.ok(exportTexts.some(text => text.text === 'σ') && exportTexts.some(text => text.text === 'ε'),
      'PNG includes both mathematical axis titles');
    assert.equal(await evaluate('Chart.getChart("mechanical-plot").width'), 720, 'export preserves the interactive chart size');
    const exportedHoverEdge = await evaluate(`new Promise(resolve => {
      const image = new Image();
      image.onload = () => {
        const check = document.createElement('canvas');
        check.width = image.width; check.height = image.height;
        const ctx = check.getContext('2d');
        ctx.drawImage(image, 0, 0);
        const chart = Chart.getChart('mechanical-plot');
        const point = chart.data.datasets[0].data[1];
        const x = (chart.scales.x.getPixelForValue(point.x) + 24) * 3;
        const y = (chart.scales.y.getPixelForValue(point.y) + 24 + 6) * 3;
        resolve(Array.from(ctx.getImageData(Math.round(x), Math.round(y), 1, 1).data));
      };
      image.src = ${JSON.stringify('data:image/png;base64,' + png.toString('base64'))};
    })`);
    assert.ok(exportedHoverEdge.slice(0, 3).every(channel => channel > 245), 'PNG omits the enlarged hover marker');
    const csv = readFileSync(join(profile, csvName), 'utf8');
    assert.match(csv, /total_strain.strain_11/);
    assert.match(csv, /stress.stress_11/);
    assert.match(csv, /1,0.01,40/);
    if (process.env.PLOT_SCREENSHOT_DIR) writeFileSync(join(process.env.PLOT_SCREENSHOT_DIR, 'download.png'), png);
    await navigate(cases.find(item => item.name === 'third').path);
    await select('plot-x-select', 'total_strain.strain_11');
    await layout('negative-axis-png', 1440);
    await downloadMeasuredPNG('negative-axis');
    if (process.env.PLOT_SAMPLE_PATH) {
      await navigate(process.env.PLOT_SAMPLE_PATH);
      for (const component of ['33', '22', '13', '23']) {
        await select('plot-x-select', `total_strain.strain_${component}`);
        await layout(`sample-${component}`, 1440);
        if (component === '33') await downloadMeasuredPNG('sample-33');
      }
      assert.equal(await evaluate('Chart.getChart("mechanical-plot").data.datasets[0].data.length'), 242);
    }
    const initialSample = JSON.parse(process.env.PLOT_INITIAL_SAMPLE);
    await navigate(initialSample.path);
    await select('plot-x-select', 'total_strain.strain_33');
    const initialMetrics = await layout('sample-initial-25', 1440, initialSample);
    assert.equal(initialMetrics.data.length, 25, 'The offline initial fixture preserves all 25 original samples');
    assert.equal(initialMetrics.plotLayout.multipliers.length, 1, 'The initial fixture needs only one X-axis multiplier');
    assert.ok(initialMetrics.tickLabels.every(tick => tick.label.type === 'plain'),
      'The initial fixture uses plain coefficients without repeated powers of ten');
    await downloadMeasuredPNG('sample-initial-25');
    await navigate(process.env.PLOT_EMPTY_PATH, false);
    assert.match(await evaluate('document.querySelector(".plot-empty").textContent'), /No plot-ready mechanical variables/);
    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
      assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'), false);
    }
    assert.deepEqual(exceptions, []);
    console.log(`Mechanical plot browser checks passed: ${cases.length} cases at 3 desktop widths; measured Canvas text and per-axis multipliers match their layout without overlaps or clipping, titles have equal 16px gaps, arrow bases stay 24px beyond range endpoints, two-place ticks remain distinct, and all text is at least 5pt at 85mm PNG width. The original 25-sample fixture, curve hover, linked selectors, raw values, full resolution PNG without hover markers, CSV downloads and empty data remain intact.`);
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
