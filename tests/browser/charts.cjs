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
    async function coverageSummary(value) {
      return evaluate(`(() => {
        const link = [...document.querySelectorAll('.charts-coverage-link')]
          .find(element => element.dataset.coverage === ${JSON.stringify(value)});
        return {count: Number(link.dataset.count)};
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
    async function categorySummary(key, label) {
      return evaluate(`(() => {
        const panel = document.querySelector('[data-statistic="' + ${JSON.stringify(key)} + '"]');
        const bar = [...panel.querySelectorAll('.charts-bar, .charts-bubble, .charts-column')]
          .find(element => element.dataset.label === ${JSON.stringify(label)});
        if (bar) return {count: parseInt(bar.dataset.count ?? bar.querySelector('.charts-bar-count').textContent, 10)};
        throw new Error('Missing chart category: ' + ${JSON.stringify(key + ': ' + label)});
      })()`);
    }
    async function inspectCharts(selectors) {
      const enhanced = await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")');
      assert.equal(await evaluate('document.querySelectorAll(".charts-dashboard-grid a, .charts-dashboard-grid [role=link]").length'), 0);
      for (const selector of selectors) {
        stage = `hover ${selector}`;
        const before = await evaluate(`(async () => {
          const element = document.querySelector(${JSON.stringify(selector)});
          element.scrollIntoView({block: 'center', behavior: 'instant'});
          if (${enhanced}) await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          const mark = element.closest('[data-chart-tooltip], [role="img"]') || element;
          const rect = element.getBoundingClientRect();
          let point = null;
          for (const x of [0.5, 0.25, 0.75, 0.1, 0.9]) {
            for (const y of [0.5, 0.25, 0.75, 0.1, 0.9]) {
              const candidate = {x: rect.left + rect.width * x, y: rect.top + rect.height * y};
              const hit = document.elementFromPoint(candidate.x, candidate.y);
              if (hit && element.contains(hit)) { point = candidate; break; }
            }
            if (point) break;
          }
          return {url: location.href, scroll: scrollY, loaded: performance.timeOrigin,
            point, tooltip: mark.dataset.chartTooltip || mark.getAttribute('title') || mark.querySelector('title')?.textContent,
            focusable: mark.hasAttribute('tabindex'), statistic: element.closest('[data-statistic]').dataset.statistic,
            cursor: getComputedStyle(element).cursor};
        })()`);
        assert.ok(before.tooltip?.trim(), `Hover information is available for ${selector}`);
        assert.ok(before.point, `${selector} must have a visible surface to hover`);
        assert.notEqual(before.cursor, 'pointer', `${selector} must not suggest navigation`);
        if (enhanced) await evaluate('document.activeElement?.blur()');
        await command('Input.dispatchMouseEvent', {type: 'mouseMoved', ...before.point});
        if (enhanced) {
          await until('!!document.querySelector(".charts-tooltip:not([hidden])")');
          const shown = await evaluate(`(() => {
            const tip = document.querySelector('.charts-tooltip'), rect = tip.getBoundingClientRect();
            return {text: tip.textContent, visible: tip.checkVisibility(), left: rect.left, right: rect.right,
              top: rect.top, bottom: rect.bottom, width: innerWidth, height: innerHeight};
          })()`);
          assert.equal(shown.text, before.tooltip.trim(), `${selector} must actually display its hover information`);
          assert.ok(shown.visible && shown.left >= 0 && shown.right <= shown.width && shown.top >= 0 && shown.bottom <= shown.height,
            `${selector} tooltip must fit the visible viewport: ${JSON.stringify(shown)}`);
          if (process.env.CHARTS_SCREENSHOT_DIR) {
            const shot = await command('Page.captureScreenshot', {format: 'png'});
            writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, 'hover-' + before.statistic + '.png'), Buffer.from(shot.data, 'base64'));
          }
          await pressKey('Escape', 'Escape', 27);
          assert.equal(await evaluate('document.querySelector(".charts-tooltip").hidden'), true,
            `${selector} must dismiss on Escape without focusing the chart`);
          await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 0, y: 0});
          await command('Input.dispatchMouseEvent', {type: 'mouseMoved', ...before.point});
          await until('!!document.querySelector(".charts-tooltip:not([hidden])")');
        }
        await command('Input.dispatchMouseEvent', {type: 'mousePressed', ...before.point, button: 'left', clickCount: 1});
        await command('Input.dispatchMouseEvent', {type: 'mouseReleased', ...before.point, button: 'left', clickCount: 1});
        if (before.focusable) await evaluate(`document.querySelector(${JSON.stringify(selector)}).closest('[tabindex]').focus({preventScroll: true})`);
        await pressKey('Enter', 'Enter', 13);
        const after = await evaluate('({url: location.href, scroll: scrollY, loaded: performance.timeOrigin})');
        assert.equal(after.url, before.url, `Clicking ${selector} must not change selection`);
        assert.equal(after.loaded, before.loaded, `Clicking ${selector} must not reload the page`);
        assert.ok(Math.abs(after.scroll - before.scroll) <= 1, `Clicking ${selector} must not jump to the top`);
        if (enhanced) {
          await command('Input.dispatchMouseEvent', {type: 'mouseMoved', x: 0, y: 0});
          assert.equal(await evaluate('document.querySelector(".charts-tooltip").hidden'), true,
            `${selector} must clear its tooltip when the pointer leaves`);
          if (before.focusable) {
            await evaluate(`(() => {
              const mark = document.querySelector(${JSON.stringify(selector)}).closest('[tabindex]');
              mark.blur(); mark.focus({preventScroll: true});
            })()`);
            assert.equal(await evaluate('document.querySelector(".charts-tooltip").hidden'), false,
              `${selector} must show the same information on keyboard focus`);
            await pressKey('Escape', 'Escape', 27);
            assert.equal(await evaluate('document.querySelector(".charts-tooltip").hidden'), true);
          }
        }
      }
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
    async function searchData(enhanced = true) {
      const overview = await evaluate('location.pathname + location.search');
      stage = `Search data from Charts${enhanced ? '' : ' without JavaScript'}`;
      await evaluate('document.querySelector(".charts-search-link").focus()');
      await pressKey('Enter', 'Enter', 13);
      await until('location.pathname === "/search/" && document.readyState === "complete" && !!document.querySelector("#advancedSearchForm")');
      assert.ok(await evaluate('document.querySelector("#advancedSearchPanel").checkVisibility()'),
        'Search data must open the detailed filters');
      assert.equal(await evaluate('document.querySelector("#id_access").value'), '',
        'Search data covers all accessible objects');
      await evaluate(`(() => {
        document.querySelector('#id_phase').value = 'Copper';
        document.querySelector('#advancedSearchForm').requestSubmit();
      })()`);
      await until('document.readyState === "complete" && !!document.querySelector("#searchResultCount")');
      assert.equal(await evaluate('document.querySelector("#searchResultCount").textContent.trim()'), '8 total');
      assert.equal(await evaluate('document.querySelectorAll("#searchResultAccordion > .accordion-item").length'), 8);
      assert.equal(await evaluate('document.querySelector("#searchResultAccordion").textContent.includes("hidden-private-marker")'), false);
      await navigate(overview, enhanced);
    }
    async function assertLegacyListCount(link, enhanced = true) {
      const saved = new URL(link.path, process.env.CHARTS_BASE_URL);
      saved.searchParams.set('show', 'objects');
      await navigate(saved.pathname + saved.search + saved.hash, enhanced);
      let rows = [];
      if (!link.count) {
        assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
        assert.equal(await evaluate('document.querySelectorAll(".charts-object-id").length'), 0);
      } else {
        assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), link.count);
        assert.ok(await evaluate('!!document.querySelector(".charts-records") && !document.querySelector(".charts-dashboard-grid")'));
        rows = await evaluate('[...document.querySelectorAll(".charts-table tbody tr")].map(row => ({identifier: row.querySelector(".charts-object-id").textContent, href: row.querySelector(".charts-object-title").getAttribute("href"), text: row.textContent}))');
        assert.equal(rows.length, Math.min(link.count, 10));
        const pagination = await evaluate('document.querySelector(".charts-pagination").textContent');
        assert.match(pagination, new RegExp('of ' + link.count + ' (objects?|records?)'));
      }
      await navigate(await evaluate('document.querySelector(".charts-heading-actions a").getAttribute("href")'), enhanced);
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
      assert.ok(await evaluate('[...new URLSearchParams(location.search).keys()].every(key => ["scope", "include_private"].includes(key))'));
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
      assert.equal(Number(totals[3]), (await coverageSummary('matching')).count);
      assert.equal(await evaluate('document.querySelectorAll(".charts-plot-stage .charts-lollipop-svg").length'), 1);
      assert.equal(await evaluate('document.querySelectorAll(".charts-chart-data, .charts-distribution-table, .charts-category-table").length'), 0);
      assert.equal(await evaluate('document.querySelector(".charts-page").textContent.includes("Data table")'), false);
      assert.equal(await evaluate('document.querySelectorAll("[data-statistic=phase] .charts-bar-mark").length'), 0);
      assert.equal(await evaluate('document.querySelectorAll(".charts-additional-statistics, .charts-objects, .charts-records").length'), 0);
      assert.equal(await evaluate('/Additional statistics|Source records/.test(document.querySelector(".charts-page").textContent)'), false);
      assert.equal(await evaluate('document.querySelectorAll(".charts-dashboard-grid a, .charts-dashboard-grid [role=link]").length'), 0);
      assert.ok(await evaluate('[...document.querySelectorAll(".charts-bar, .charts-pie-slice, .charts-bin, .charts-bubble, .charts-column, .charts-heatmap-cell, .charts-box-selection")].every(mark => mark.getAttribute("aria-label") && !mark.getAttribute("aria-label").includes("Filter statistics") && (mark.dataset.chartTooltip || mark.querySelector("title")?.textContent.trim()))'));
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
          totalObjects: Number(document.querySelector('.charts-metric-total strong')?.textContent),
          mainLeft: document.querySelector('.charts-page').getBoundingClientRect().left,
          sidebarRight: document.querySelector('.pc-sidebar').getBoundingClientRect().right,
          titleTop: document.querySelector('.charts-heading h1').getBoundingClientRect().top,
          headerBottom: document.querySelector('.pc-header').getBoundingClientRect().bottom,
          titleVisible: (() => {
            const title = document.querySelector('.charts-heading h1'), rect = title.getBoundingClientRect();
            return title.contains(document.elementFromPoint(rect.left + 10, rect.top + 10));
          })(),
          intro: [...document.querySelectorAll('.charts-intro p, .charts-intro a')].map(element => {
            const rect = element.getBoundingClientRect();
            return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
              visible: element.checkVisibility()};
          }),
          height: document.documentElement.scrollHeight,
          cards: panels.map(panel => {
            const rect = panel.getBoundingClientRect();
            const heading = panel.querySelector('h2').getBoundingClientRect();
            const coverage = panel.querySelector('.charts-context-label').getBoundingClientRect();
            return {key: panel.dataset.statistic, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
              headingGap: coverage.left - heading.right};
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
          lollipops: [...document.querySelectorAll('[data-statistic=phase] .charts-lollipop-dot')].filter(dot => dot.checkVisibility()).map(dot => {
            const link = dot.closest('[role="img"]'), stem = link.querySelector('.charts-lollipop-stem');
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
                bounds: {x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height},
                fontSize: parseFloat(getComputedStyle(text).fontSize) * svg.getScreenCTM().a,
                clipped: box.left < bounds.left - 1 || box.top < bounds.top - 1 || box.right > bounds.right + 1 || box.bottom > bounds.bottom + 1};
            }),
          boxTicks: [...document.querySelectorAll('.charts-box-svg .charts-bin-label')].map(text => {
            const rect = text.getBoundingClientRect();
            return {left: rect.left, right: rect.right, label: text.textContent};
          }),
          heatmapSpacing: graphs.filter(svg => svg.classList.contains('charts-heatmap-svg')).map(svg => {
            const textBounds = element => {
              const region = element.getBoundingClientRect();
              const range = document.createRange();
              range.selectNodeContents(element);
              const rect = range.getBoundingClientRect();
              return {left: Math.max(rect.left, region.left), right: Math.min(rect.right, region.right),
                top: Math.max(rect.top, region.top), bottom: Math.min(rect.bottom, region.bottom)};
            };
            const titles = [...svg.querySelectorAll('.charts-axis-text, .charts-heatmap-axis-title')];
            const type = textBounds(titles.find(title => title.textContent.trim() === 'Type'));
            const mode = textBounds(titles.find(title => title.textContent.trim() === 'Mode'));
            const types = [...svg.querySelectorAll('.charts-svg-label-end')].map(textBounds);
            const modes = [...svg.querySelectorAll('.charts-svg-label-center')].map(textBounds);
            return {typeGap: Math.min(...types.map(rect => rect.left)) - type.right,
              modeGap: Math.min(...modes.map(rect => rect.top)) - mode.bottom};
          }),
          temperature: (() => {
            const panel = document.querySelector('[data-statistic=temperature]');
            const svg = panel?.querySelector('svg');
            if (!svg) return null;
            const bounds = svg.getBoundingClientRect();
            const textBounds = element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              const rect = range.getBoundingClientRect();
              return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
                width: rect.width, height: rect.height};
            };
            const titles = [...svg.querySelectorAll('.charts-axis-text, .charts-histogram-axis-title')];
            const yTitle = textBounds(titles.find(title => title.textContent.trim() === 'Objects'));
            const xTitle = textBounds(titles.find(title => title.textContent.trim() === 'Temperature (K)'));
            const yLabels = [...svg.querySelectorAll('.charts-histogram-y-labels .charts-histogram-tick, text.charts-axis-text')]
              .filter(element => /^\\d+$/.test(element.textContent.trim())).map(textBounds);
            const xLabels = [...svg.querySelectorAll('.charts-bin-label')].map(textBounds);
            const texts = [...svg.querySelectorAll('text, .charts-histogram-tick, .charts-histogram-axis-title')].map(element => {
              const rect = textBounds(element);
              return {text: element.textContent.trim(), fontSize: parseFloat(getComputedStyle(element).fontSize) * svg.getScreenCTM().a,
                clipped: rect.left < bounds.left - 1 || rect.right > bounds.right + 1 || rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1};
            });
            const heading = panel.querySelector('h2').getBoundingClientRect();
            const coverage = panel.querySelector('.charts-context-label').getBoundingClientRect();
            return {yTitle, xTitle, xLabels, texts,
              yGap: Math.min(...yLabels.map(rect => rect.left)) - yTitle.right,
              xGap: xTitle.top - Math.max(...xLabels.map(rect => rect.bottom)),
              headingOverlap: heading.right > coverage.left,
              coverage: panel.querySelector('.charts-context-label').textContent.trim(),
              summary: panel.querySelector('.charts-distribution-summary').textContent.trim()};
          })(),
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
      for (const [index, item] of metrics.intro.entries()) {
        assert.ok(item.visible && item.left >= metrics.mainLeft && item.right <= width
          && (!index || metrics.intro[index - 1].right + 8 <= item.left),
          `${label}: introduction and data actions must stay readable at ${width}: ${JSON.stringify(metrics.intro)}`);
      }
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
          assert.ok(card.headingGap >= 11, `${label}: card title and coverage need space at ${width}: ${JSON.stringify(card)}`);
        }
      }
      if (expectedGraphs === 8) assert.deepEqual(metrics.graphTypes,
        {bar: 1, lollipop: 1, pie: 1, histogram: 1, bubble: 1, column: 1, heatmap: 1, box: 1});
      for (const mark of metrics.lollipops) {
        assert.equal(mark.dotPosition, mark.stemEnd, `${label}: the dot must mark its count position`);
        assert.ok(!mark.clipped && mark.countLeft > mark.dotRight && mark.fontSize >= 9.5,
          `${label}: readable lollipop count at ${width}: ${JSON.stringify(mark)}`);
        const values = mark.count.match(/^(\d+) \((\d+(?:\.\d+)?)%\)$/);
        assert.ok(values, `${label}: show the count and percentage for ${mark.label}`);
        assert.equal(Number(values[2]), Number((Number(values[1]) * 100 / metrics.totalObjects).toFixed(1)),
          `${label}: phase percentage uses all selected objects`);
      }
      for (const text of metrics.numericLabels) {
        assert.ok(text.fontSize >= 9.5 && !text.clipped, `${label}: readable numeric label at ${width}: ${JSON.stringify(text)}`);
      }
      metrics.boxTicks.forEach((tick, index) => {
        assert.ok(!index || tick.left > metrics.boxTicks[index - 1].right + 3,
          `${label}: box axis labels overlap at ${width}: ${JSON.stringify(metrics.boxTicks)}`);
      });
      for (const spacing of metrics.heatmapSpacing) {
        assert.ok(spacing.typeGap > 0 && spacing.modeGap > 0 && Math.abs(spacing.typeGap - spacing.modeGap) <= 1,
          `${label}: Type and Mode need the same visible gap from their names at ${width}: ${JSON.stringify(spacing)}`);
      }
      if (metrics.temperature) {
        const temperature = metrics.temperature;
        assert.ok(temperature.texts.every(text => text.fontSize >= 9.5 && text.fontSize <= 13 && !text.clipped),
          `${label}: temperature text must stay readable and smaller than the card title at ${width}: ${JSON.stringify(temperature.texts)}`);
        assert.ok(temperature.yTitle.height > temperature.yTitle.width,
          `${label}: Objects belongs vertically beside the count axis at ${width}`);
        assert.ok(temperature.yGap > 0 && temperature.xGap > 0 && Math.abs(temperature.yGap - temperature.xGap) <= 1,
          `${label}: temperature axis titles need equal visible gaps at ${width}: ${JSON.stringify(temperature)}`);
        assert.ok(!temperature.headingOverlap, `${label}: temperature heading and coverage overlap at ${width}`);
        assert.match(temperature.coverage, /^With data:/);
        assert.match(temperature.summary, /Min–max/);
        temperature.xLabels.forEach((tick, index) => {
          assert.ok(!index || tick.left > temperature.xLabels[index - 1].right + 3,
            `${label}: temperature interval labels overlap at ${width}: ${JSON.stringify(temperature.xLabels)}`);
        });
      }
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
        writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '-axis-spacing.json'), JSON.stringify(metrics.heatmapSpacing, null, 2));
        writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '-temperature-layout.json'), JSON.stringify(metrics.temperature, null, 2));
        await command('Emulation.setDeviceMetricsOverride', {width, height: Math.min(metrics.height, 4500), deviceScaleFactor: 1, mobile: false});
        await settleLayout();
        const shot = await command('Page.captureScreenshot', {format: 'png'});
        writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '.png'), Buffer.from(shot.data, 'base64'));
        for (const statistic of ['phase', 'results', 'models', 'loading', 'temperature', 'grain_count', 'texture', 'software']) {
          const cardBounds = await evaluate(`(() => {
            const card = document.querySelector('[data-statistic="${statistic}"]');
            if (!card) return null;
            const rect = card.getBoundingClientRect();
            return {x: rect.left + scrollX, y: rect.top + scrollY, width: rect.width, height: rect.height, scale: 1};
          })()`);
          if (cardBounds) {
            const cardShot = await command('Page.captureScreenshot', {format: 'png', clip: cardBounds, captureBeyondViewport: false});
            writeFileSync(join(process.env.CHARTS_SCREENSHOT_DIR, label + '-' + statistic + '.png'), Buffer.from(cardShot.data, 'base64'));
          }
        }
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
    const matching = await coverageSummary('matching');
    const withoutMatching = await coverageSummary('without_matching');
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
    await searchData();
    assert.equal(await evaluate('document.querySelectorAll("[data-statistic=phase] .charts-more-categories").length'), 0);
    await inspectCharts(['.charts-lollipop-dot', '[data-statistic=models] .charts-bar', '.charts-pie-slice',
      '.charts-heatmap-cell', '.charts-bin', '.charts-box-selection', '.charts-bubble', '.charts-column',
      '.charts-svg-label', '.charts-coverage-link']);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
    const retiredSelections = [
      ['/charts/?plastic_model=Crystal+Plasticity&elastic_model=Anisotropic+Elasticity&coverage=matching&range=temperature:298:298:1', '/charts/', 13],
      ['/charts/?scope=mine&include_private=1&phase=Copper&phase=Nickel&software=Software+1&measure=grain_count&page=2', '/charts/?scope=mine&include_private=1', 24],
      ['/charts/?scope=public&coverage=all&coverage=matching&range=temperature:broken', '/charts/?scope=public', 13],
    ];
    for (const [path, cleanPath, count] of retiredSelections) {
      await navigate(path, true, cleanPath);
      assert.equal(await evaluate('Number(document.querySelector(".charts-metric-total strong").textContent)'), count);
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter-strip, .charts-filter").length'), 0);
      await assertFixedDashboard();
    }
    await layout('cleared-chart-selections', 1440);
    await navigate('/charts/?scope=mine&include_private=1&include_private=0&phase=Copper', true,
      '/charts/?scope=mine&include_private=1&include_private=0');
    assert.ok(await evaluate('!!document.querySelector(".charts-errors") && !!document.querySelector(".charts-empty")'));
    assert.equal(await evaluate('document.getElementById("charts-include-private").checked'), false);
    assert.deepEqual(await evaluate('new URLSearchParams(location.search).getAll("include_private")'), ['1', '0']);
    await clearSelection();
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await assertLegacyListCount({path: '/charts/?elastic_model=Anisotropic+elasticity&loading_type=force&loading_mode=cyclic&texture=Goss&range=grain_count:65:200:1', count: 6});
    const selectedRows = await assertLegacyListCount({path: '/charts/?phase=Copper&software=Software+7&coverage=matching', count: 2});
    assert.ok(selectedRows.every(row => row.text.includes('Copper') && row.text.includes('Software 7')));
    await assertLegacyListCount({path: '/charts/?phase=Copper&phase=Nickel', count: 0});
    await assertLegacyListCount({path: '/charts/?phase=Copper&coverage=matching&coverage=without_matching', count: 0});
    await assertLegacyListCount({path: '/charts/?range=temperature:273:335.5:0', count: 3});
    await chooseScope('mine');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await setPrivate(true);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    assert.equal((await coverageSummary('matching')).count, 18);
    assert.equal((await coverageSummary('without_matching')).count, 6);
    const privateRows = await assertLegacyListCount({path: '/charts/?scope=mine&include_private=1&result=plastic_strain&coverage=matching', count: 12});
    assert.ok(privateRows.every(row => row.text.includes('Private')));
    await assertPrivate();
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
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
    for (const legacy of ['all', 'shared']) {
      await navigate('/charts/?scope=' + legacy + '&include_private=1&group=software', true, '/charts/?scope=public');
      assert.equal(await evaluate('document.getElementById("charts-scope").value'), 'public');
      assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '13');
      assert.equal(await evaluate('document.body.textContent.includes("shared-record")'), false);
    }
    await chooseScope('mine');
    await setPrivate(true);
    await setPrivate(false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_NARROW_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine&include_private=1');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '2');
    assert.ok(await evaluate('[...document.querySelectorAll("svg[data-measure=grain_count] text")].some(text => text.textContent.startsWith("Axis offset: +"))'));
    const narrowLabels = await evaluate('[...document.querySelectorAll("svg[data-measure=grain_count] .charts-bin-label")].map(label => label.textContent)');
    assert.deepEqual(narrowLabels, ['0', '0.2', '0.4', '0.6', '0.8', '1']);
    assert.ok(narrowLabels.every(label => label.length < 30));
    assert.equal(await evaluate('document.querySelectorAll(".charts-box-selection").length'), 0);
    const largeCount = 10n ** 50n;
    const countBase = largeCount * 8n;
    const narrowMedian = await evaluate('document.querySelector("[data-statistic=grain_count] .charts-distribution-summary span:first-child strong").textContent');
    assert.equal(exactEighths(narrowMedian), countBase + 4n);
    for (const width of [1280, 1440, 1920]) await layout('narrow-counts', width);
    const narrowRows = [
      {path: '/charts/?scope=mine&include_private=1&range=grain_count:' + largeCount + ':' + largeCount + '.5:0', count: 1},
      {path: '/charts/?scope=mine&include_private=1&range=grain_count:' + largeCount + '.5:' + (largeCount + 1n) + ':1', count: 1},
    ];
    for (const [row, identifier] of [[narrowRows[0], 'charts-browser-8'], [narrowRows[1], 'charts-browser-20']]) {
      const rows = await assertLegacyListCount(row);
      assert.equal(rows[0].identifier, identifier);
    }
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate('/charts/?scope=mine', false);
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.ok(await evaluate('getComputedStyle(document.querySelector(".charts-scope-form .charts-apply")).display !== "none"'));
    await searchData(false);
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
    await inspectCharts(['.charts-lollipop-dot', '[data-statistic=models] .charts-bar', '.charts-pie-slice',
      '.charts-heatmap-cell', '.charts-bin', '.charts-box-selection', '.charts-bubble', '.charts-column']);
    await assertLegacyListCount({path: '/charts/?scope=mine&phase=Copper&software=Software+7&coverage=matching', count: 2}, false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    assert.equal(await evaluate('document.querySelector(".charts-page").classList.contains("charts-js")'), false);
    assert.equal(await evaluate('document.querySelectorAll(".charts-objects, .charts-records").length'), 0);
    await navigate('/charts/?scope=mine', false);
    await setPrivate(true, false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '24');
    await setPrivate(false, false);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '12');
    await setPrivate(true, false);
    await assertLegacyListCount({path: '/charts/?scope=mine&include_private=1&texture=Goss', count: 24}, false);
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
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_PAIRED_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine&include_private=1');
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    const loadingCells = await evaluate(`Object.fromEntries([...document.querySelectorAll('.charts-heatmap-cell')]
      .filter(cell => ['force', 'displacement'].includes(cell.dataset.type)
        && ['cyclic', 'static'].includes(cell.dataset.mode))
      .map(cell => [cell.dataset.type + '/' + cell.dataset.mode, Number(cell.dataset.count)]))`);
    assert.deepEqual(loadingCells, {'force/cyclic': 1, 'force/static': 0, 'displacement/cyclic': 0, 'displacement/static': 1});
    for (const width of [1280, 1440, 1920]) await layout('paired-loading-conditions', width);
    await inspectCharts(['.charts-heatmap-cell[data-type="force"][data-mode="cyclic"]',
      '.charts-heatmap-cell[data-type="force"][data-mode="static"]']);
    assert.match(await evaluate('document.querySelector(".charts-heatmap-cell[data-type=force][data-mode=cyclic]").dataset.chartTooltip'), /1 object.*100/);
    await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_DIVERSE_SESSION,
      url: process.env.CHARTS_BASE_URL, path: '/'});
    await navigate('/charts/?scope=mine&include_private=1');
    await evaluate('document.querySelector("[data-statistic=phase] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    for (const width of [1280, 1440, 1920]) await layout('expanded-phases', width);
    await inspectCharts(['[data-statistic=phase] .charts-more-categories .charts-bar',
      '[data-statistic=phase] .charts-more-categories .charts-svg-label']);
    await evaluate('document.querySelector("[data-statistic=phase] .charts-more-categories").open = false');
    await inspectCharts(['.charts-heatmap-cell', '.charts-column-svg .charts-svg-label']);
    await assertPrivate();
    await command('Emulation.setScriptExecutionDisabled', {value: true});
    await navigate('/charts/?scope=mine&include_private=1', false);
    await evaluate('document.querySelector("[data-statistic=phase] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    assert.equal(await evaluate('document.querySelector("[data-statistic=phase] .charts-more-categories").open'), true);
    await inspectCharts(['[data-statistic=phase] .charts-more-categories .charts-bar',
      '[data-statistic=phase] .charts-more-categories .charts-svg-label']);
    await evaluate('document.querySelector("[data-statistic=texture] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    assert.equal(await evaluate('document.querySelector("[data-statistic=texture] .charts-more-categories").open'), true);
    await inspectCharts(['[data-statistic=texture] .charts-more-categories .charts-bar']);
    await evaluate('document.querySelector("[data-statistic=loading] .charts-more-categories > summary").focus()');
    await pressKey('Enter', 'Enter', 13);
    assert.equal(await evaluate('document.querySelector("[data-statistic=loading] .charts-more-categories").open'), true);
    await inspectCharts(['[data-statistic=loading] .charts-more-categories .charts-bar',
      '.charts-column-svg .charts-svg-label', '.charts-bubble']);
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
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
    await navigate('/charts/?scope=mine&include_private=1&texture=Goss', true, '/charts/?scope=mine&include_private=1');
    assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
    assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
    await assertLegacyListCount({path: '/charts/?scope=mine&include_private=1&note=temperature_excluded', count: 1});
    assert.deepEqual(await evaluate('new URLSearchParams(location.search).getAll("note")'), []);
    if (process.env.CHARTS_SAMPLE_SESSION) {
      await command('Network.setCookie', {name: process.env.CHARTS_COOKIE_NAME, value: process.env.CHARTS_SAMPLE_SESSION,
        url: process.env.CHARTS_BASE_URL, path: '/'});
      await navigate('/charts/?scope=mine');
      assert.ok(await evaluate('!!document.querySelector(".charts-empty")'));
      await setPrivate(true);
      assert.equal(await evaluate('document.querySelector(".charts-metric-total strong").textContent'), '1');
      await assertFixedDashboard();
      assert.equal((await categorySummary('phase', 'Copper')).count, 1);
      assert.equal((await categorySummary('software', 'Abaqus CAE')).count, 1);
      assert.match(await evaluate('document.querySelector("[data-statistic=temperature] .charts-distribution-summary").textContent'), /Median\s+298/);
      assert.match(await evaluate('document.querySelector("[data-statistic=temperature] .charts-distribution-summary").textContent'), /Min–max\s+298–298 K/);
      assert.match(await evaluate('document.querySelector("[data-statistic=temperature] .charts-context-label").textContent'), /With data:\s+1 \/ 1 object/);
      assert.ok(await evaluate('document.querySelector("[data-statistic=temperature] h2").textContent.includes("(K)")'));
      assert.deepEqual(await evaluate(`[...document.querySelectorAll('.charts-metric dd')]
        .map(value => value.textContent.trim())`), ['1', '1', '1', '1']);
      for (const width of [1280, 1440, 1920]) await layout('sample-copper', width);
      await inspectCharts(['.charts-lollipop-dot', '[data-statistic=models] .charts-bar', '.charts-pie-slice',
        '.charts-heatmap-cell', '.charts-box-selection', '.charts-bin', '.charts-bubble', '.charts-column']);
      await assertLegacyListCount({path: '/charts/?scope=mine&include_private=1&phase=Copper', count: 1});
      await assertPrivate();
      await assertLegacyListCount({path: '/charts/?scope=mine&include_private=1&phase=Copper&software=Abaqus+CAE', count: 1});
      for (const [measure, value, formatted] of [
        ['temperature', '298', '298'], ['grain_count', '343', '343'],
      ]) {
        assert.ok((await evaluate(`document.querySelector('[data-statistic=${measure}] .charts-distribution-summary').textContent`)).includes(formatted));
        const sampleBin = await evaluate(`(() => {
          const params = new URLSearchParams(location.search);
          params.append('range', ${JSON.stringify(`${measure}:${value}:${value}:1`)});
          return {path: '/charts/?' + params.toString(), count: 1};
        })()`);
        assert.ok(new URL(process.env.CHARTS_BASE_URL + sampleBin.path).searchParams.getAll('range')
          .some(interval => {
            const [key, low, high, inclusive] = interval.split(':');
            return key === measure && inclusive === '1'
              && exactEighths(low) === exactEighths(value)
              && exactEighths(high) === exactEighths(value);
          }));
        await assertLegacyListCount(sampleBin);
        await assertPrivate();
      }
      const legacyTexture = await evaluate(`(() => {
        const params = new URLSearchParams(location.search);
        params.append('texture', 'Goss');
        return {path: '/charts/?' + params.toString(), count: 1};
      })()`);
      const sampleRows = await assertLegacyListCount(legacyTexture);
      assert.equal(await evaluate('document.querySelectorAll(".charts-filter").length'), 0);
      const legacyInterval = await evaluate(`(() => {
        const params = new URLSearchParams(location.search);
        params.append('range', 'discretization_count:2744:2744:1');
        return {path: '/charts/?' + params.toString(), count: 1};
      })()`);
      await assertLegacyListCount(legacyInterval);
      assert.equal(await evaluate('new URLSearchParams(location.search).has("range")'), false);
      assert.equal(sampleRows[0].identifier, 'a46fde6c');
      assert.equal(sampleRows[0].href, process.env.CHARTS_SAMPLE_DETAIL_URL);
      assert.equal(await evaluate(`fetch(${JSON.stringify(process.env.CHARTS_SAMPLE_DETAIL_URL)}).then(response => response.status)`), 200);
      assert.equal(await evaluate('document.querySelector("[data-overview=texture] dd").textContent'), '1');
      console.log('Charts local sample checks passed: Copper, Abaqus CAE, Goss, 298 K, 343 grains, 2,744 cells, exact combined links, detail navigation, and 3 desktop layouts.');
    }
    assert.deepEqual(exceptions, []);
    console.log('Charts browser checks passed: eight cards with visible hover tooltips, obsolete chart selections cleared, no click navigation, legacy object-list bookmarks, keyboard operation without JavaScript, public/private scopes, precise intervals, record navigation and desktop layouts.');
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
