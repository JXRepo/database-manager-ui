const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdirSync, mkdtempSync, rmSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

function exactEighths(value) {
  const match = value.replaceAll(',', '').trim().match(/^([+-]?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i);
  assert.ok(match, `Expected an exact decimal, received ${value}`);
  const fraction = match[3] || '';
  const coefficient = BigInt(match[1] + match[2] + fraction) * 8n;
  const exponent = Number(match[4] || 0) - fraction.length;
  if (exponent >= 0) return coefficient * 10n ** BigInt(exponent);
  const divisor = 10n ** BigInt(-exponent);
  assert.equal(coefficient % divisor, 0n);
  return coefficient / divisor;
}

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
      const state = await evaluate(`({url: location.href, ready: document.readyState,
        recordCount: document.querySelector('.charts-metric-total strong')?.textContent,
        focused: document.activeElement?.outerHTML?.slice(0, 300),
        errors: document.querySelector('.charts-errors')?.textContent})`);
      throw new Error(`Timed out: ${expression}\n${JSON.stringify(state)}`);
    }
    async function navigate(path = '/charts/', enhanced = true, expectedPath = path) {
      stage = `navigate ${path}${enhanced ? '' : ' without JavaScript'}`;
      const url = process.env.CHARTS_BASE_URL + path;
      await evaluate(`document.querySelector('.charts-page')?.setAttribute('data-browser-navigation', 'pending')`);
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + expectedPath)} && document.readyState === "complete"
        && !!document.querySelector(".charts-page") && !document.querySelector('.charts-page').hasAttribute('data-browser-navigation')`);
      if (enhanced) await until('document.querySelector(".charts-page").classList.contains("charts-js")');
    }
    async function settleLayout() {
      await evaluate(`(async () => {
        window.scrollTo({top: 0, left: 0, behavior: 'instant'});
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        await Promise.all(document.getAnimations().filter(animation => animation.effect.getComputedTiming().endTime !== Infinity)
          .map(animation => animation.finished.catch(() => {})));
        window.scrollTo({top: 0, left: 0, behavior: 'instant'});
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      })()`);
    }
    async function headingMetrics() {
      await settleLayout();
      return evaluate(`(() => {
        const title = document.querySelector('.page-header-title > h1, .page-header-title > h5');
        const breadcrumb = document.querySelector('.page-header .breadcrumb');
        const titleRect = title.getBoundingClientRect(), breadcrumbRect = breadcrumb.getBoundingClientRect();
        const font = element => {
          const style = getComputedStyle(element);
          return {size: style.fontSize, weight: style.fontWeight, lineHeight: style.lineHeight,
            family: style.fontFamily, color: style.color};
        };
        return {left: titleRect.left, top: titleRect.top, height: titleRect.height, font: font(title),
          breadcrumbTop: breadcrumbRect.top, breadcrumbGap: breadcrumbRect.left - titleRect.right,
          breadcrumbFont: font(breadcrumb)};
      })()`);
    }
    async function comparePageHeadings(width) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      const charts = await headingMetrics();
      for (const path of ['/data-list/', '/share/']) {
        stage = `compare Charts heading with ${path} at ${width}`;
        await command('Page.navigate', {url: process.env.CHARTS_BASE_URL + path});
        await until(`location.pathname === ${JSON.stringify(path)} && document.readyState === 'complete'
          && !!document.querySelector('.page-header-title > h5')`);
        const reference = await headingMetrics();
        assert.deepEqual(charts, reference, `Charts heading must match ${path} at ${width}`);
        console.log(`${width}px: Charts matches ${path} at (${charts.left}, ${charts.top}), ${charts.font.size}.`);
        if (process.env.CHARTS_SCREENSHOT_DIR && width === 1440) {
          const shot = await command('Page.captureScreenshot', {format: 'png'});
          writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, 'heading-' + path.replaceAll('/', '') + '.png'),
            Buffer.from(shot.data, 'base64'));
        }
      }
      await navigate();
    }
    async function chooseScope(value, enhanced = true) {
      stage = `choose scope = ${value}${enhanced ? '' : ' without JavaScript'}`;
      const path = await evaluate(`(() => {
        const select = document.getElementById('charts-scope');
        select.value = ${JSON.stringify(value)};
        const form = select.closest('form');
        form.dataset.browserSubmitting = 'true';
        ${enhanced ? "select.dispatchEvent(new Event('change', {bubbles: true}));" : ""}
        const action = new URL(form.action);
        const path = action.pathname + '?' + new URLSearchParams(new FormData(form)).toString() + action.hash;
        ${enhanced ? "" : "form.requestSubmit();"}
        return path;
      })()`);
      assert.equal(new URL(process.env.CHARTS_BASE_URL + path).hash, '', 'Changing scope returns to the overview');
      await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL)} + ${JSON.stringify(path)}
        && document.readyState === 'complete' && document.querySelector('.charts-scope-form')?.dataset.browserSubmitting !== 'true'
        && document.getElementById('charts-scope').value === ${JSON.stringify(value)}`);
      if (enhanced) await until('document.querySelector(".charts-page").classList.contains("charts-js")');
    }
    async function setPrivate(checked, enhanced = true) {
      stage = `include private = ${checked}${enhanced ? '' : ' without JavaScript'}`;
      await evaluate(`(() => {
        const checkbox = document.getElementById('charts-include-private');
        checkbox.checked = ${checked};
        checkbox.closest('form').dataset.browserSubmitting = 'true';
        ${enhanced ? "checkbox.dispatchEvent(new Event('change', {bubbles: true}));" : "checkbox.closest('form').requestSubmit();"}
      })()`);
      await until(`document.readyState === 'complete' && !!document.querySelector('.charts-page')
        && document.querySelector('.charts-scope-form')?.dataset.browserSubmitting !== 'true'
        && new URLSearchParams(location.search).get('scope') === 'mine'
        && new URLSearchParams(location.search).get('include_private') === ${checked ? "'1'" : 'null'}
        && document.getElementById('charts-include-private').checked === ${checked}`);
      if (enhanced) await until('document.querySelector(".charts-page").classList.contains("charts-js")');
    }
    async function coverageLink(value) {
      return evaluate(`(() => {
        const link = [...document.querySelectorAll('.charts-coverage-link')]
          .find(element => element.dataset.coverage === ${JSON.stringify(value)});
        return {path: link.getAttribute('href'), count: Number(link.dataset.count)};
      })()`);
    }
    async function assertPrivate() {
      assert.equal(await evaluate('new URLSearchParams(location.search).get("include_private")'), '1');
      if (await evaluate('!!document.querySelector(".charts-records")')) {
        assert.equal(await evaluate('new URLSearchParams(location.search).get("scope")'), 'mine');
      } else {
        assert.equal(await evaluate('document.getElementById("charts-include-private").checked'), true);
      }
    }
    async function categoryLink(key, label) {
      return evaluate(`(() => {
        const panel = document.querySelector('[data-statistic="' + ${JSON.stringify(key)} + '"]');
        const bar = [...panel.querySelectorAll('.charts-bar, .charts-bubble, .charts-column')]
          .find(element => element.dataset.label === ${JSON.stringify(label)});
        if (bar) return {path: bar.getAttribute('href'), count: Number(bar.dataset.count ?? bar.querySelector('.charts-bar-count').textContent)};
        throw new Error('Missing chart category: ' + ${JSON.stringify(key + ': ' + label)});
      })()`);
    }
    async function histogramLink(measure) {
      if (measure === 'grain_count') return boxLink();
      return evaluate(`(() => {
        const link = document.querySelector('svg[data-measure="' + ${JSON.stringify(measure)} + '"] .charts-bin[href]');
        return {path: link.getAttribute('href'), count: Number(link.dataset.objectCount)};
      })()`);
    }
    async function loadingLink(type, mode) {
      return evaluate(`(() => {
        const link = [...document.querySelectorAll('.charts-heatmap-cell')]
          .find(cell => cell.dataset.type === ${JSON.stringify(type)} && cell.dataset.mode === ${JSON.stringify(mode)});
        return {path: link.getAttribute('href'), count: Number(link.dataset.count)};
      })()`);
    }
    async function boxLink() {
      return evaluate(`(() => {
        const link = document.querySelector('.charts-box-selection');
        return {path: link.getAttribute('href'), count: Number(link.dataset.objectCount)};
      })()`);
    }
    async function viewRecords(enhanced = true) {
      await navigate(await evaluate('document.querySelector(".charts-record-link").getAttribute("href")'), enhanced);
      assert.ok(await evaluate('!!document.querySelector(".charts-records") && !document.querySelector(".charts-dashboard-grid")'));
      assert.equal(await evaluate('document.querySelector("h1").textContent'), 'Data objects');
      return evaluate(`[...document.querySelectorAll('.charts-table tbody tr')].map(row => ({
        identifier: row.querySelector('.charts-object-id').textContent,
        href: row.querySelector('.charts-object-title').getAttribute('href'),
        text: row.textContent,
      }))`);
    }
    async function assertLinkedCount(link, enhanced = true) {
      await navigate(link.path, enhanced);
      if (!link.count) {
        assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
        assert.equal(await evaluate('document.querySelectorAll(".charts-object-id").length'), 0);
        return [];
      }
      assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), link.count);
      assert.equal(await evaluate('document.querySelectorAll(".charts-objects, .charts-records").length'), 0);
      assert.equal(new URL(process.env.CHARTS_BASE_URL + link.path).searchParams.has('show'), false);
      const rows = await viewRecords(enhanced);
      assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), link.count);
      assert.equal(await evaluate('document.querySelectorAll(".charts-table tbody tr").length'), Math.min(link.count, 10));
      const pagination = await evaluate('document.querySelector(".charts-pagination").textContent');
      assert.match(pagination, new RegExp(`of ${link.count} (objects?|records?)`));
      await navigate(await evaluate('document.querySelector(".charts-heading-actions a").getAttribute("href")'), enhanced);
      assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), link.count);
      return rows;
    }
    async function pressKey(key, code, virtualKey) {
      const text = key === 'Enter' ? '\r' : '';
      await command('Input.dispatchKeyEvent', {type: 'keyDown', key, code, windowsVirtualKeyCode: virtualKey,
        text, unmodifiedText: text});
      await command('Input.dispatchKeyEvent', {type: 'keyUp', key, code, windowsVirtualKeyCode: virtualKey});
    }
    async function clearSelection(enhanced = true) {
      await navigate(await evaluate('document.querySelector(".charts-clear").getAttribute("href")'), enhanced);
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
    }
    async function assertFixedDashboard() {
      assert.deepEqual(await evaluate('[...document.querySelectorAll(".charts-metric > dt")].map(label => label.textContent)'),
        ['Data objects', 'Material phases', 'Texture types', 'Objects with stress–strain data']);
      assert.equal(await evaluate('document.querySelectorAll(".charts-metrics details, .charts-metrics select, .charts-metric > small").length'), 0);
      const totals = await evaluate('[...document.querySelectorAll(".charts-metric dd")].map(value => value.textContent.trim())');
      assert.ok(totals.every(value => /^\d+$/.test(value)));
      assert.equal(Number(totals[1]), await evaluate('document.querySelectorAll("[data-statistic=phase] .charts-bar").length'));
      assert.equal(Number(totals[3]), (await coverageLink('matching')).count);
      assert.equal(await evaluate('document.querySelectorAll(".charts-plot-stage .charts-lollipop-svg").length'), 1);
      assert.equal(await evaluate('document.querySelectorAll(".charts-chart-data, .charts-distribution-table, .charts-category-table").length'), 0);
      assert.equal(await evaluate('document.querySelector(".charts-page").textContent.includes("Data table")'), false);
      assert.equal(await evaluate('document.querySelectorAll("[data-statistic=phase] .charts-bar-mark").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll(".charts-additional-statistics, .charts-objects, .charts-records").length'), 0);
      assert.equal(await evaluate('/Additional statistics|Source records/.test(document.querySelector(".charts-page").textContent)'), false);
      assert.ok(await evaluate('[...document.querySelectorAll(".charts-bar, .charts-pie-slice, .charts-bin, .charts-bubble, .charts-column, .charts-heatmap-cell, .charts-box-selection")].every(link => link.getAttribute("aria-label").includes("Filter statistics"))'));
      assert.equal(await evaluate('document.querySelectorAll("#charts-filters, #charts-filter-form, .charts-more-filters, [data-filter-key]").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll("#charts-material-group, #charts-group, #charts-measure, .charts-chart-control").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll(".charts-panel-purpose, .charts-section-help, .charts-page-footnote, .charts-subtle-note").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll(".charts-curve-svg, #curve-object, #curve-component, #download-curve").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll(".charts-data-notes").length'), 0);
      assert.deepEqual(await evaluate(`[...document.querySelectorAll('[data-statistic]')]
        .map(panel => panel.dataset.statistic)`),
        ['phase', 'results', 'models', 'loading', 'temperature', 'grain_count', 'texture', 'software']);
      assert.equal(await evaluate('document.querySelectorAll("[data-statistic=outputs]").length'), 0);
    }
    async function layout(label, width, expectedGraphs = 8) {
      stage = `layout ${label} at ${width}`;
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await settleLayout();
      const metrics = await evaluate(`(() => {
        const keys = ['phase', 'results', 'models', 'loading', 'temperature', 'grain_count', 'texture', 'software'];
        const panels = keys.map(key => document.querySelector('[data-statistic="' + key + '"]')).filter(Boolean);
        const graphs = panels.flatMap(panel => [...panel.querySelector('.charts-plot-stage').querySelectorAll('svg')]);
        return {
          documentWidth: document.documentElement.scrollWidth, viewport: innerWidth,
          mainLeft: document.querySelector('.charts-page').getBoundingClientRect().left,
          sidebarRight: document.querySelector('.pc-sidebar').getBoundingClientRect().right,
          titleTop: document.querySelector('.charts-heading h1').getBoundingClientRect().top,
          headerBottom: document.querySelector('.pc-header').getBoundingClientRect().bottom,
          titleVisible: (() => {
            const title = document.querySelector('.charts-heading h1'), rect = title.getBoundingClientRect();
            return title.contains(document.elementFromPoint(rect.left + 10, rect.top + 10));
          })(),
          height: document.documentElement.scrollHeight,
          cards: panels.map(panel => {
            const rect = panel.getBoundingClientRect();
            return {key: panel.dataset.statistic, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom};
          }),
          primary: graphs.filter(svg => ['phase', 'results'].includes(svg.closest('[data-statistic]').dataset.statistic))
            .map(svg => ({top: svg.getBoundingClientRect().top, bottom: svg.getBoundingClientRect().bottom})),
          graphCount: graphs.length,
          graphTypes: {bar: graphs.filter(svg => svg.classList.contains('charts-bar-svg') && !svg.classList.contains('charts-lollipop-svg')).length,
            lollipop: graphs.filter(svg => svg.classList.contains('charts-lollipop-svg')).length,
            pie: graphs.filter(svg => svg.classList.contains('charts-pie-svg')).length,
            histogram: graphs.filter(svg => svg.classList.contains('charts-histogram-svg')).length,
            bubble: graphs.filter(svg => svg.classList.contains('charts-bubble-svg')).length,
            column: graphs.filter(svg => svg.classList.contains('charts-column-svg')).length,
            heatmap: graphs.filter(svg => svg.classList.contains('charts-heatmap-svg')).length,
            box: graphs.filter(svg => svg.classList.contains('charts-box-svg')).length},
          lollipops: [...document.querySelectorAll('.charts-plot-stage .charts-lollipop-dot')].map(dot => {
            const link = dot.closest('a'), stem = link.querySelector('.charts-lollipop-stem');
            const svg = dot.ownerSVGElement, bounds = svg.getBoundingClientRect();
            const dotRect = dot.getBoundingClientRect(), count = link.querySelector('.charts-bar-count');
            const countRect = count.getBoundingClientRect();
            return {label: link.dataset.label, dotPosition: dot.cx.baseVal.value, stemEnd: stem.x2.baseVal.value,
              count: count.textContent, dotRight: dotRect.right, countLeft: countRect.left,
              clipped: dotRect.left < bounds.left || dotRect.right > bounds.right || countRect.right > bounds.right,
              fontSize: parseFloat(getComputedStyle(count).fontSize) * svg.getScreenCTM().a};
          }),
          numericLabels: graphs.flatMap(svg => [...svg.querySelectorAll('text')])
            .filter(text => text.ownerSVGElement.checkVisibility()).map(text => {
              const svg = text.ownerSVGElement, box = text.getBoundingClientRect(), bounds = svg.getBoundingClientRect();
              return {label: text.textContent, chart: svg.getAttribute('class'), box: {x: box.x, y: box.y, width: box.width, height: box.height},
                fontSize: parseFloat(getComputedStyle(text).fontSize) * svg.getScreenCTM().a,
                clipped: box.left < bounds.left - 1 || box.top < bounds.top - 1 || box.right > bounds.right + 1 || box.bottom > bounds.bottom + 1};
            }),
          boxTicks: [...document.querySelectorAll('.charts-box-svg .charts-bin-label')].map(text => {
            const rect = text.getBoundingClientRect();
            return {left: rect.left, right: rect.right, label: text.textContent};
          }),
          categoryLabels: graphs.flatMap((svg, chart) => [...svg.querySelectorAll('.charts-svg-label')].map(label => {
            const rect = label.getBoundingClientRect(), bounds = svg.getBoundingClientRect(), style = getComputedStyle(label);
            return {chart, text: label.textContent, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
              fontSize: parseFloat(style.fontSize) * svg.getScreenCTM().a,
              bounded: style.overflow === 'hidden' && (style.textOverflow === 'ellipsis' || style.webkitLineClamp === '2'),
              clipped: rect.left < bounds.left - 1 || rect.top < bounds.top - 1 || rect.right > bounds.right + 1 || rect.bottom > bounds.bottom + 1};
          })),
          selection: (() => {
            const chip = document.querySelector('.charts-filter');
            return chip ? {top: chip.getBoundingClientRect().top, height: chip.parentElement.getBoundingClientRect().height} : null;
          })(),
          overview: [...document.querySelectorAll('.charts-metric')].map(metric => {
            const rect = metric.getBoundingClientRect();
            const value = metric.querySelector('dd');
            return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
              overflow: value.scrollWidth > value.clientWidth + 1};
          }),
        };
      })()`);
      assert.ok(metrics.documentWidth <= width, `${label} overflows at ${width}: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.mainLeft >= metrics.sidebarRight - 1, `${label} under sidebar: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.titleVisible && metrics.titleTop >= metrics.headerBottom, `${label} title under navigation: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.graphCount, expectedGraphs, `${label}: main dashboard chart count at ${width}`);
      if (metrics.overview.length) {
        assert.equal(metrics.overview.length, 4);
        metrics.overview.forEach((item, index) => {
          assert.ok(item.right <= width && !item.overflow && (!index || metrics.overview[index - 1].right <= item.left),
            `${label}: statistics totals overlap or overflow at ${width}: ${JSON.stringify(item)}`);
          assert.equal(item.top, metrics.overview[0].top, `${label}: statistics totals must share one row at ${width}`);
        });
      }
      if (metrics.cards.length) {
        assert.equal(metrics.cards.length, 8);
        for (const card of metrics.cards) {
          assert.ok(card.left >= metrics.mainLeft && card.right <= width, `${label}: card outside desktop ${JSON.stringify(card)}`);
        }
      }
      if (expectedGraphs === 8) assert.deepEqual(metrics.graphTypes,
        {bar: 1, lollipop: 1, pie: 1, histogram: 1, bubble: 1, column: 1, heatmap: 1, box: 1});
      for (const mark of metrics.lollipops) {
        assert.equal(mark.dotPosition, mark.stemEnd, `${label}: the dot must mark its count position`);
        assert.ok(!mark.clipped && mark.countLeft > mark.dotRight && mark.fontSize >= 9.5,
          `${label}: readable lollipop count at ${width}: ${JSON.stringify(mark)}`);
      }
      for (const text of metrics.numericLabels) {
        assert.ok(text.fontSize >= 9.5 && !text.clipped, `${label}: readable numeric label at ${width}: ${JSON.stringify(text)}`);
      }
      metrics.boxTicks.forEach((tick, index) => {
        assert.ok(!index || tick.left > metrics.boxTicks[index - 1].right + 3,
          `${label}: box axis labels overlap at ${width}: ${JSON.stringify(metrics.boxTicks)}`);
      });
      metrics.categoryLabels.forEach((label, index) => {
        assert.ok(label.bounded && !label.clipped && label.fontSize >= 9.5,
          `${label}: category label must fit its region at ${width}: ${JSON.stringify(label)}`);
        for (const previous of metrics.categoryLabels.slice(0, index)) {
          if (previous.chart !== label.chart) continue;
          const horizontal = Math.min(previous.right, label.right) - Math.max(previous.left, label.left);
          const vertical = Math.min(previous.bottom, label.bottom) - Math.max(previous.top, label.top);
          assert.ok(horizontal <= 1 || vertical <= 1,
            `Category labels overlap at ${width}: ${JSON.stringify([previous, label])}`);
        }
      });
      if (metrics.primary.length) {
        assert.equal(metrics.primary.length, 2);
        for (const chart of metrics.primary) {
          assert.ok(chart.top >= metrics.headerBottom && chart.bottom < 1000,
            `Phase and coverage charts must remain visible on the first screen: ${JSON.stringify(metrics)}`);
        }
      }
      if (metrics.selection) assert.ok(metrics.selection.height < 140, `Applied conditions must remain compact: ${JSON.stringify(metrics.selection)}`);
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
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
    assert.deepEqual(await evaluate('[...document.querySelectorAll("#charts-scope option")].map(option => [option.value, option.textContent])'),
      [['public', 'Public database'], ['mine', 'My data']]);
    assert.equal(await evaluate('document.body.textContent.includes("hidden-private-marker")'), false);
    assert.equal(await evaluate('document.body.textContent.includes("shared-record")'), false);
    await assertFixedDashboard();
    assert.deepEqual(await evaluate('[...document.querySelectorAll(".charts-metric dd")].map(value => Number(value.textContent))'), [13, 4, 1, 7]);
    assert.equal(await evaluate('document.querySelectorAll(".charts-pie-svg path").length'), 2);
    assert.ok(await evaluate('[...document.querySelectorAll(".charts-pie-svg path")].every(path => path.getTotalLength() > 0)'));
    const matching = await coverageLink('matching');
    const withoutMatching = await coverageLink('without_matching');
    assert.equal(matching.count, 7);
    assert.equal(withoutMatching.count, 6);
    assert.equal(matching.count + withoutMatching.count, 13);
    assert.equal(await evaluate('document.querySelectorAll(".charts-coverage-table tbody tr").length'), 2);
    const pieCounts = await evaluate(`[...document.querySelectorAll('.charts-pie-slice')]
      .map(link => Number(link.getAttribute('aria-label').match(/: (\\d+) (?:objects?|records?)/)[1])).sort((a, b) => a - b)`);
    assert.deepEqual(pieCounts, [6, 7]);
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=models] .charts-bar").length'), 2);
    assert.equal(await evaluate('document.querySelectorAll(".charts-donut-svg").length'), 1);
    const tableHeaders = await evaluate('[...document.querySelectorAll("table.charts-statistics-table th")].map(header => header.textContent)');
    assert.ok(tableHeaders.some(header => /Objects|Records/.test(header)));
    assert.ok(tableHeaders.some(header => /%|share|percentage/i.test(header)));
    for (const width of [1280, 1440, 1920]) {
      await layout('dashboard-overview', width);
      await comparePageHeadings(width);
    }
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=phase] .charts-more-categories").length'), 0);
    const dotLink = await evaluate(`(() => {
      const dot = document.querySelector('.charts-lollipop-dot'), rect = dot.getBoundingClientRect();
      const link = dot.closest('a');
      return {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2,
        path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bar-count').textContent)};
    })()`);
    await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: dotLink.x, y: dotLink.y});
    assert.equal(await evaluate('getComputedStyle(document.querySelector(".charts-lollipop-dot")).fill'), 'rgb(32, 95, 154)');
    await command('Input.dispatchMouseEvent', {type: 'mousePressed', x: dotLink.x, y: dotLink.y, button: 'left', clickCount: 1});
    await command('Input.dispatchMouseEvent', {type: 'mouseReleased', x: dotLink.x, y: dotLink.y, button: 'left', clickCount: 1});
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + dotLink.path)}
      && document.readyState === 'complete' && document.querySelector('.charts-page')?.classList.contains('charts-js')`);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), dotLink.count);
    await clearSelection();
    await assertLinkedCount(await categoryLink('models', 'Anisotropic elasticity (Elastic)'));
    await assertLinkedCount(await loadingLink('force', 'cyclic'));
    await assertLinkedCount(await categoryLink('texture', 'Goss'));
    await assertLinkedCount(await boxLink());
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 5);
    await clearSelection();
    await assertLinkedCount({path: '/charts/?texture=Goss', count: 12});
    assert.deepEqual(await evaluate('[...document.querySelectorAll(".charts-metric dd")].map(value => Number(value.textContent))'), [12, 3, 1, 6]);
    for (const width of [1280, 1440, 1920]) await layout('selected-statistics', width);
    await navigate('/charts/?coverage=all&coverage=matching');
    assert.ok(await evaluate('!!document.querySelector(".charts-errors") && !!document.querySelector(".charts-empty")'));
    await navigate(await evaluate('[...document.querySelectorAll(".charts-filter")].find(link => link.textContent.includes("all")).getAttribute("href")'));
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '7');
    await navigate('/charts/?scope=mine&include_private=1&include_private=0&phase=Copper');
    assert.ok(await evaluate('!!document.querySelector(".charts-errors") && !!document.querySelector(".charts-empty")'));
    assert.equal(await evaluate('document.getElementById("charts-include-private").checked'), false);
    await navigate(await evaluate('document.querySelector(".charts-filter").getAttribute("href")'));
    assert.ok(await evaluate('!!document.querySelector(".charts-errors") && !!document.querySelector(".charts-empty")'));
    assert.deepEqual(await evaluate('new URLSearchParams(location.search).getAll("include_private")'), ['1', '0']);
    await clearSelection();
    assert.equal(await evaluate('document.querySelectorAll(".charts-errors").length'), 0);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await navigate('/charts/?phase=Copper');
    await assertLinkedCount(await categoryLink('software', 'Software 7'));
    const selectedRows = await assertLinkedCount(await coverageLink('matching'));
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 3);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '2');
    assert.ok(selectedRows.every(row => row.text.includes('Copper') && row.text.includes('Software 7')));
    for (const width of [1280, 1440, 1920]) await layout('dashboard-selected', width);
    await assertLinkedCount(await coverageLink('without_matching'));
    for (const width of [1280, 1440, 1920]) await layout('empty-selection', width, 0);
    await clearSelection();
    await navigate('/charts/?phase=Copper&phase=Nickel');
    assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
    assert.deepEqual(await evaluate('new URLSearchParams(location.search).getAll("phase")'), ['Copper', 'Nickel']);
    await clearSelection();
    await assertLinkedCount(await histogramLink('temperature'));
    assert.ok(await evaluate('document.querySelector(".charts-filter").textContent.includes("Temperature")'));
    await navigate();
    await evaluate(`document.querySelector('.charts-coverage-link[data-coverage="without_matching"]').focus()`);
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + withoutMatching.path)} && document.readyState === 'complete'
      && document.querySelector('.charts-page').classList.contains('charts-js')`);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), withoutMatching.count);
    assert.equal((await coverageLink('matching')).count, 0);
    assert.equal((await coverageLink('without_matching')).count, 6);
    assert.equal(await evaluate('document.querySelectorAll(".charts-objects, .charts-records").length'), 0);
    const withoutAndCopper = await categoryLink('phase', 'Copper');
    await assertLinkedCount(withoutAndCopper);
    assert.equal(withoutAndCopper.count, 2);
    await navigate();
    await chooseScope('mine');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    assert.equal(await evaluate('document.getElementById("charts-include-private").checked'), false);
    await setPrivate(true);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    assert.equal((await coverageLink('matching')).count, 18);
    assert.equal((await coverageLink('without_matching')).count, 6);
    assert.equal(await evaluate('document.body.textContent.includes("shared-record")'), false);
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=software] .charts-column, [data-statistic=software] .charts-more-categories .charts-bar").length'), 12);
    const plastic = {path: '/charts/?scope=mine&include_private=1&result=plastic_strain', count: 12};
    await assertLinkedCount(plastic);
    await assertPrivate();
    const privateRows = await assertLinkedCount(await coverageLink('matching'));
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    assert.ok(privateRows.every(row => row.text.includes('Private')));
    await clearSelection();
    await assertPrivate();
    await assertLinkedCount({path: '/charts/?scope=mine&include_private=1&texture=Goss', count: 24});
    await assertPrivate();
    const cyclicRows = await assertLinkedCount({path: '/charts/?scope=mine&include_private=1&texture=Goss&loading_mode=cyclic', count: 12});
    await assertPrivate();
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    assert.ok(cyclicRows.every(row => /^charts-browser-\d+$/.test(row.identifier)));
    await assertLinkedCount(await histogramLink('grain_count'));
    await assertPrivate();
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 3);
    await navigate(await evaluate('document.querySelector(".charts-filter").getAttribute("href")'));
    await assertPrivate();
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    await clearSelection();
    await assertPrivate();
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    const phase = await categoryLink('phase', 'Copper');
    await evaluate(`document.querySelector('[data-statistic="phase"] .charts-bar[data-label="Copper"]').focus()`);
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + phase.path)} && document.readyState === 'complete'
      && document.querySelector('.charts-page').classList.contains('charts-js')`);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), phase.count);
    const phaseRows = await viewRecords();
    assert.equal(phaseRows.length, phase.count);
    await navigate(await evaluate('document.querySelector(".charts-heading-actions a").getAttribute("href")'));
    assert.ok(await evaluate('document.querySelector(".charts-filter").textContent.includes("Copper")'));
    const softwareRows = await assertLinkedCount(await categoryLink('software', 'Software 1'));
    await assertPrivate();
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    assert.ok(softwareRows.every(row => row.text.includes('Copper') && row.text.includes('Software 1')));
    await clearSelection();
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await assertPrivate();
    await assertLinkedCount(await histogramLink('temperature'));
    await navigate('/charts/?scope=mine&include_private=1&show=objects');
    const firstIds = await evaluate('[...document.querySelectorAll(".charts-object-id")].map(el => el.textContent)');
    await navigate(await evaluate('document.querySelector("a[rel=next]").getAttribute("href")'));
    await assertPrivate();
    assert.ok(await evaluate('document.querySelector(".charts-pagination").textContent.includes("Page 2")'));
    const secondIds = await evaluate('[...document.querySelectorAll(".charts-object-id")].map(el => el.textContent)');
    assert.equal(firstIds.filter(id => secondIds.includes(id)).length, 0);
    await navigate('/charts/?scope=public&software=' + encodeURIComponent('A solver with a very long uploaded descriptive name '.repeat(14).trim()) + '&show=objects');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    for (const width of [1280, 1440, 1920]) await layout('long-record', width, 0);
    await navigate(await evaluate('document.querySelector(".charts-heading-actions a").getAttribute("href")'));
    for (const width of [1280, 1440, 1920]) await layout('long-singleton', width, 4);
    for (const legacy of ['all', 'shared']) {
      await navigate(`/charts/?scope=${legacy}&include_private=1&group=software`, true, '/charts/?scope=public&group=software');
      assert.equal(await evaluate('document.getElementById("charts-scope").value'), 'public');
      assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
      assert.equal(await evaluate('document.body.textContent.includes("shared-record")'), false);
    }
    await navigate('/charts/?scope=mine&include_private=1&material_group=texture&group=loading_mode&measure=grain_count&phase=Copper&show=objects&page=2');
    await navigate(await evaluate('document.querySelector(".charts-heading-actions a").getAttribute("href")'));
    await chooseScope('public');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
    assert.equal(await evaluate('new URLSearchParams(location.search).has("include_private") || new URLSearchParams(location.search).has("page")'), false);
    assert.deepEqual(await evaluate(`['material_group', 'group', 'measure'].map(key => new URLSearchParams(location.search).get(key))`),
      ['texture', 'loading_mode', 'grain_count']);
    await assertFixedDashboard();
    await chooseScope('mine');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await setPrivate(true);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await setPrivate(false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await navigate('/charts/?scope=mine&software=Software+9&measure=grain_count');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '2');
    assert.ok(await evaluate('[...document.querySelectorAll("svg[data-measure=grain_count] text")].some(text => text.textContent.startsWith("Axis offset: +"))'));
    const narrowLabels = await evaluate('[...document.querySelectorAll("svg[data-measure=grain_count] .charts-bin-label")].map(label => label.textContent)');
    assert.deepEqual(narrowLabels, ['0', '0.2', '0.4', '0.6', '0.8', '1']);
    assert.ok(narrowLabels.every(label => label.length < 30));
    assert.equal(await evaluate('document.querySelectorAll(".charts-box-selection").length'), 0);
    const largeCount = 10n ** 50n;
    const bookmarkedIntervals = [`grain_count:${largeCount}:${largeCount}.5:0`,
      `grain_count:${largeCount}.5:${largeCount + 1n}:1`];
    const narrowRows = await evaluate(`(() => {
      return ${JSON.stringify(bookmarkedIntervals)}.map(interval => {
        const params = new URLSearchParams(location.search);
        params.append('range', interval);
        return {path: '/charts/?' + params.toString(), count: 1};
      });
    })()`);
    const countBase = (10n ** 50n) * 8n;
    const narrowMedian = await evaluate('document.querySelector("[data-statistic=grain_count] .charts-distribution-summary span:first-child strong").textContent');
    assert.equal(exactEighths(narrowMedian), countBase + 4n);
    for (const width of [1280, 1440, 1920]) await layout('narrow-counts', width);
    for (const [row, identifier] of [[narrowRows[0], 'charts-browser-8'], [narrowRows[1], 'charts-browser-20']]) {
      assert.equal(row.count, 1);
      const rows = await assertLinkedCount(row);
      assert.equal(rows[0].identifier, identifier);
    }
    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate('/charts/?scope=mine', false);
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.ok(await evaluate('getComputedStyle(document.querySelector(".charts-scope-form .charts-apply")).display !== "none"'));
    await evaluate('window.scrollTo(0, 0)');
    const visible = await evaluate(`(() => {
      const graphs = [...document.querySelectorAll('[data-statistic="phase"] .charts-bar-svg, [data-statistic="results"] .charts-pie-svg')];
      return graphs.length === 2 && graphs.every(svg => {
        const rect = svg.getBoundingClientRect(), pie = svg.classList.contains('charts-pie-svg');
        return svg.contains(document.elementFromPoint(rect.left + (pie ? rect.width * .77 : 15), rect.top + (pie ? rect.height * .5 : 30)));
      });
    })()`);
    assert.ok(visible, 'The server-rendered bar and pie remain visible without JavaScript');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    const recordsPath = await evaluate('document.querySelector(".charts-record-link").getAttribute("href")');
    assert.equal(new URL(process.env.CHARTS_BASE_URL + recordsPath).searchParams.get('show'), 'objects');
    await evaluate('document.querySelector(".charts-record-link").focus()');
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + recordsPath)}
      && document.readyState === 'complete' && !!document.querySelector('.charts-records')`);
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    await navigate('/charts/?scope=mine', false);
    const keyboardPhase = await categoryLink('phase', 'Copper');
    await evaluate('document.querySelector("[data-statistic=phase] .charts-bar").focus()');
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + keyboardPhase.path)}
      && document.readyState === 'complete' && !!document.querySelector('.charts-lollipop-svg')`);
    assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), keyboardPhase.count);
    await assertLinkedCount(await categoryLink('phase', 'Copper'), false);
    await assertLinkedCount(await categoryLink('software', 'Software 7'), false);
    await assertLinkedCount(await coverageLink('matching'), false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '2');
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.equal(await evaluate('document.querySelectorAll(".charts-objects, .charts-records").length'), 0);
    await navigate('/charts/?scope=mine', false);
    await setPrivate(true, false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await setPrivate(false, false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await setPrivate(true, false);
    await assertLinkedCount({path: '/charts/?scope=mine&include_private=1&texture=Goss', count: 24}, false);
    await assertPrivate();
    await chooseScope('public', false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
    assert.equal(await evaluate('document.body.textContent.includes("shared-record")'), false);
    await chooseScope('mine', false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    assert.equal(await evaluate('document.getElementById("charts-include-private").checked'), false);
    await command('Emulation.setScriptExecutionDisabled', {value: false});
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_EMPTY_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate();
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
    await navigate('/charts/?scope=mine');
    assert.ok(await evaluate('document.querySelector(".charts-empty h2").textContent.includes("No data")'));
    assert.equal(await evaluate('document.querySelectorAll(".charts-bar-svg, .charts-histogram-svg, .charts-pie-svg").length'), 0);
    for (const width of [1280, 1440, 1920]) await layout('empty-data', width, 0);
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_DIVERSE_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine&include_private=1');
    await assertFixedDashboard();
    assert.deepEqual(await evaluate('[...document.querySelectorAll(".charts-metric dd")].map(value => value.textContent.trim())'),
      ['8', '8', '8', '8']);
    assert.equal(await evaluate('document.querySelectorAll(".charts-bubble").length'), 6);
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=texture] .charts-bubble, [data-statistic=texture] .charts-more-categories .charts-bar").length'), 8);
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=models] .charts-bar").length'), 9);
    assert.equal(await evaluate('document.querySelectorAll(".charts-heatmap-svg g > .charts-heatmap-mark").length') > 0, true);
    for (const width of [1280, 1440, 1920]) await layout('varied-long-categories', width);
    const diverseCell = await evaluate(`(() => {
      const link = document.querySelector('.charts-heatmap-cell');
      return {path: link.getAttribute('href'), count: Number(link.dataset.count)};
    })()`);
    await assertLinkedCount(diverseCell);
    await assertPrivate();
    await clearSelection();
    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate('/charts/?scope=mine&include_private=1', false);
    await evaluate('document.querySelector("[data-statistic=texture] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    assert.equal(await evaluate('document.querySelector("[data-statistic=texture] .charts-more-categories").open'), true);
    const moreTexture = await evaluate(`(() => {
      const link = document.querySelector('[data-statistic=texture] .charts-more-categories .charts-bar');
      link.focus();
      return {path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bar-count').textContent)};
    })()`);
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + moreTexture.path)}
      && document.readyState === 'complete' && !!document.querySelector('.charts-bubble-svg')`);
    await assertLinkedCount(moreTexture, false);
    await clearSelection(false);
    await evaluate('document.querySelector("[data-statistic=loading] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    assert.equal(await evaluate('document.querySelector("[data-statistic=loading] .charts-more-categories").open'), true);
    const moreLoading = await evaluate(`(() => {
      const link = document.querySelector('[data-statistic=loading] .charts-more-categories .charts-bar');
      return {path: link.getAttribute('href'), count: Number(link.querySelector('.charts-bar-count').textContent)};
    })()`);
    await assertLinkedCount(moreLoading, false);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 2);
    await clearSelection(false);
    const labelClick = await evaluate(`(() => {
      const label = document.querySelector('.charts-column-svg .charts-svg-label');
      label.scrollIntoView({block: 'center', behavior: 'instant'});
      const rect = label.getBoundingClientRect(), link = label.closest('a');
      return {x: rect.left + rect.width / 2, y: rect.top + 8,
        path: link.getAttribute('href'), count: Number(link.dataset.count),
        hit: document.elementFromPoint(rect.left + rect.width / 2, rect.top + 8)?.closest('a')?.getAttribute('href')};
    })()`);
    assert.equal(labelClick.hit, labelClick.path, `The bounded software label must remain clickable: ${JSON.stringify(labelClick)}`);
    await command('Input.dispatchMouseEvent', {type: 'mousePressed', x: labelClick.x, y: labelClick.y, button: 'left', clickCount: 1});
    await command('Input.dispatchMouseEvent', {type: 'mouseReleased', x: labelClick.x, y: labelClick.y, button: 'left', clickCount: 1});
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + labelClick.path)}
      && document.readyState === 'complete' && !!document.querySelector('.charts-column-svg')`);
    await assertLinkedCount(labelClick, false);
    await clearSelection(false);
    const bubbleKeyboard = await evaluate(`(() => {
      const link = document.querySelector('.charts-bubble');
      link.focus();
      return {path: link.getAttribute('href'), count: Number(link.dataset.count)};
    })()`);
    await pressKey('Enter', 'Enter', 13);
    await until(`location.href === ${JSON.stringify(process.env.CHARTS_BASE_URL + bubbleKeyboard.path)}
      && document.readyState === 'complete' && !!document.querySelector('.charts-bubble-svg')`);
    await assertLinkedCount(bubbleKeyboard, false);
    await command('Emulation.setScriptExecutionDisabled', {value: false});
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SPARSE_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine&include_private=1');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    await assertFixedDashboard();
    assert.equal(await evaluate('document.querySelector("[data-overview=texture] dd").textContent'), '0');
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=temperature] svg, [data-statistic=grain_count] svg").length'), 0);
    assert.ok(await evaluate('document.querySelector("[data-statistic=temperature]").textContent.includes("No usable temperature")'));
    assert.ok(await evaluate('document.querySelector("[data-statistic=grain_count]").textContent.includes("No usable grain number")'));
    for (const width of [1280, 1440, 1920]) await layout('missing-metadata', width, 3);
    await navigate('/charts/?scope=mine&include_private=1&texture=Goss');
    assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
    await clearSelection();
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    await assertLinkedCount({path: '/charts/?scope=mine&include_private=1&note=temperature_excluded', count: 1});
    assert.deepEqual(await evaluate('new URLSearchParams(location.search).getAll("note")'), ['temperature_excluded']);
    if (process.env.CHARTS_SAMPLE_SESSION) {
      await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SAMPLE_SESSION,
        url: process.env.CHARTS_BASE_URL, path: '/'});
      await navigate('/charts/?scope=mine');
      assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
      await setPrivate(true);
      assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
      await assertFixedDashboard();
      assert.equal((await categoryLink('phase', 'Copper')).count, 1);
      assert.equal((await categoryLink('software', 'Abaqus CAE')).count, 1);
      assert.match(await evaluate('document.querySelector("[data-statistic=temperature] .charts-distribution-summary").textContent'), /Median\s+298/);
      assert.ok(await evaluate('document.querySelector("[data-statistic=temperature] h2").textContent.includes("(K)")'));
      assert.deepEqual(await evaluate(`[...document.querySelectorAll('.charts-metric dd')]
        .map(value => value.textContent.trim())`), ['1', '1', '1', '1']);
      for (const width of [1280, 1440, 1920]) await layout('sample-copper', width);
      await assertLinkedCount(await categoryLink('phase', 'Copper'));
      await assertPrivate();
      await assertLinkedCount(await categoryLink('software', 'Abaqus CAE'));
      for (const [measure, value, formatted] of [
        ['temperature', '298', '298'], ['grain_count', '343', '343'],
      ]) {
        assert.ok((await evaluate(`document.querySelector('[data-statistic=${measure}] .charts-distribution-summary').textContent`)).includes(formatted));
        const sampleBin = await histogramLink(measure);
        assert.ok(new URL(process.env.CHARTS_BASE_URL + sampleBin.path).searchParams.getAll('range')
          .some(interval => {
            const [key, low, high, inclusive] = interval.split(':');
            return key === measure && inclusive === '1'
              && exactEighths(low) === exactEighths(value)
              && exactEighths(high) === exactEighths(value);
          }));
        await assertLinkedCount(sampleBin);
        await assertPrivate();
      }
      const legacyTexture = await evaluate(`(() => {
        const params = new URLSearchParams(location.search);
        params.append('texture', 'Goss');
        return {path: '/charts/?' + params.toString(), count: 1};
      })()`);
      const sampleRows = await assertLinkedCount(legacyTexture);
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 5);
      const legacyInterval = await evaluate(`(() => {
        const params = new URLSearchParams(location.search);
        params.append('range', 'discretization_count:2744:2744:1');
        return {path: '/charts/?' + params.toString(), count: 1};
      })()`);
      await assertLinkedCount(legacyInterval);
      assert.ok(await evaluate('new URLSearchParams(location.search).getAll("range").includes("discretization_count:2744:2744:1")'));
      assert.equal(sampleRows[0].identifier, 'a46fde6c');
      assert.equal(sampleRows[0].href, process.env.CHARTS_SAMPLE_DETAIL_URL);
      assert.equal(await evaluate(`fetch(${JSON.stringify(process.env.CHARTS_SAMPLE_DETAIL_URL)}).then(response => response.status)`), 200);
      assert.equal(await evaluate('document.querySelector("[data-overview=texture] dd").textContent'), '1');
      console.log('Charts local sample checks passed: Copper, Abaqus CAE, Goss, 298 K, 343 grains, 2,744 cells, exact combined links, detail navigation, and 3 desktop layouts.');
    }
    assert.deepEqual(exceptions, []);
    console.log('Charts browser checks passed: eight statistical cards, distinct chart styles, exact counts and links, keyboard operation without JavaScript, public/private scopes, precise intervals, record navigation and desktop layouts.');
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
