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
  const artifacts = process.env.COLLECTION_ARTIFACT_DIR || join(tmpdir(), 'research-collections-navigation-qa');
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
    const requestedUrls = [];
    const responses = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
      if (message.method === 'Network.requestWillBeSent') requestedUrls.push(message.params.request.url);
      if (message.method === 'Network.responseReceived') responses.push(message.params.response);
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
        const box = [...element.getClientRects()].find(rect => {
          const target = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
          return rect.width && rect.height && element.contains(target);
        }) || element.getBoundingClientRect();
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
    async function follow(selector) {
      const href = await evaluate(`document.querySelector(${JSON.stringify(selector)}).href`);
      await click(selector);
      await until(`location.href === ${JSON.stringify(href)} && document.readyState === 'complete'`);
    }
    async function returnState(expectedPath) {
      const href = await evaluate(`document.querySelector('#graph-return-context').href`);
      const actual = new URL(href);
      const expected = new URL(expectedPath, process.env.COLLECTION_BASE_URL);
      assert.equal(actual.pathname, expected.pathname);
      const defaults = {links: 'relations', page: '1', groups_page: '1', view: 'compact'};
      for (const name of ['links', 'group', 'page', 'groups_page', 'view']) {
        assert.equal(actual.searchParams.get(name) || defaults[name], expected.searchParams.get(name) || defaults[name], `Return state: ${name}`);
      }
    }
    async function selectionContext(expectedPath) {
      const state = await evaluate(`({
        token: new URL(location.href).searchParams.get('graph_context'),
        fields: [...document.querySelectorAll('input[name="graph_context"]')].map(field => field.value),
        forms: [...document.querySelectorAll('#advancedSearchForm, #searchSelectionForm, #myDataFilterForm, #myDataBulkActionForm')]
          .map(form => ({id: form.id, token: form.querySelector('input[name="graph_context"]')?.value})),
        target: document.querySelector('#graph-selection-target')?.textContent,
      })`);
      assert.ok(state.token, 'Selection pages retain their target in the URL');
      assert.ok(state.target, 'Selection target is visible');
      assert.ok(state.fields.length > 0, 'Native navigation retains the target');
      assert.ok(state.fields.every(value => value === state.token));
      for (const form of state.forms) {
        assert.equal(form.token, state.token, `${form.id} retains the target`);
      }
      await returnState(expectedPath);
      return state.token;
    }
    async function screenshot(name) {
      await evaluate('window.scrollTo(0, 0)');
      const capture = await command('Page.captureScreenshot', {format: 'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }
    async function preparationState() {
      return evaluate(`(() => {
        const panel = document.querySelector('#collection-preparation');
        return {ready: Number(panel?.dataset.ready), total: Number(panel?.dataset.total),
          automatic: panel?.dataset.autoPrepare, requiresAdmin: panel?.dataset.requiresAdmin,
          graph: !!document.querySelector('#detail-relationships'),
          empty: !!document.querySelector('.collection-empty'),
          saveForm: !!document.querySelector('#collection-save-form'),
          editForm: !!document.querySelector('#collection-edit-form'),
          count: document.querySelector('#collection-preparation-count')?.textContent,
          retryVisible: !!document.querySelector('#collection-preparation-retry')?.getClientRects().length};
      })()`);
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

    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await navigate(cases.cold.automatic);
    const initialPreparation = await preparationState();
    assert.equal(initialPreparation.total, 75);
    assert.ok(initialPreparation.ready > 0 && initialPreparation.ready <= 25);
    assert.equal(initialPreparation.automatic, 'true');
    assert.equal(initialPreparation.graph, false, 'A partially prepared collection must not display a partial graph');
    assert.equal(initialPreparation.empty, false, 'Preparation must not look like an empty collection');
    assert.equal(initialPreparation.saveForm, false);
    assert.equal(initialPreparation.editForm, false, 'Automatic preparation must not offer drafts that its reload could discard');
    assert.match(initialPreparation.count, /75/);
    await screenshot('collection-preparing');
    await until(`!!document.querySelector('#detail-relationships') && document.querySelector('.collection-total')?.textContent === '75 accessible data objects'`);
    assert.equal(await evaluate(`!!document.querySelector('#collection-preparation')`), false);
    assert.equal(await evaluate(`!!document.querySelector('#collection-edit-form')`), true);
    const coldResponses = responses.filter(response => new URL(response.url).pathname === cases.cold.automatic);
    assert.equal(coldResponses[0].status, 202);
    assert.ok(coldResponses.some(response => response.status === 200));
    await screenshot('collection-prepared');

    await navigate(cases.cold.temporary);
    const temporaryPreparation = await preparationState();
    assert.equal(temporaryPreparation.total, 75);
    assert.equal(temporaryPreparation.graph, false);
    assert.equal(temporaryPreparation.saveForm, false, 'A pending selection must not offer a save draft before automatic reload');
    assert.equal(temporaryPreparation.editForm, false);
    await until(`!!document.querySelector('#detail-relationships') && !!document.querySelector('#collection-save-form')`);
    assert.equal(await evaluate(`!!document.querySelector('#collection-preparation')`), false);

    await navigate(cases.cold.interrupted);
    await command('Network.setBlockedURLs', {urls: ['https://*', process.env.COLLECTION_BASE_URL + cases.cold.interrupted + '*']});
    await until(`!!document.querySelector('#collection-preparation-retry')?.getClientRects().length`);
    const interrupted = await preparationState();
    assert.equal(interrupted.graph, false);
    assert.equal(interrupted.empty, false);
    const interruptedRequests = requestedUrls.filter(url => new URL(url).pathname === cases.cold.interrupted).length;
    await new Promise(resolve => setTimeout(resolve, 1200));
    assert.equal(requestedUrls.filter(url => new URL(url).pathname === cases.cold.interrupted).length, interruptedRequests,
      'Failed preparation must stop automatic requests until the user retries');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await click('#collection-preparation-retry');
    await until(`!!document.querySelector('#detail-relationships') && document.querySelector('.collection-total')?.textContent === '75 accessible data objects'`);

    await navigate(cases.adminPreparation);
    const adminPreparation = await preparationState();
    assert.equal(adminPreparation.total, 1);
    assert.equal(adminPreparation.ready, 0);
    assert.equal(adminPreparation.requiresAdmin, 'true');
    assert.equal(adminPreparation.automatic, 'false');
    assert.equal(adminPreparation.graph, false);
    assert.equal(adminPreparation.empty, false);
    assert.equal(responses.filter(response => new URL(response.url).pathname === cases.adminPreparation).at(-1).status, 503);
    assert.ok(await evaluate(`document.querySelector('#collection-export').href.endsWith('/export/')`));
    assert.ok(await evaluate(`!!document.querySelector('.collection-actions a[href="${cases.home}"]')`));
    const adminRequests = requestedUrls.filter(url => new URL(url).pathname === cases.adminPreparation).length;
    await new Promise(resolve => setTimeout(resolve, 1200));
    assert.equal(requestedUrls.filter(url => new URL(url).pathname === cases.adminPreparation).length, adminRequests,
      'An administrator preparation notice must not poll repeatedly');
    await screenshot('collection-preparation-admin');
    console.log('Cold collections prepare automatically with real counts; interrupted preparation stops until Retry; oversized records show a stable recovery state.');

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
    await navigate(cases.unlinked);
    assert.equal(await evaluate(`new URL(document.querySelector('.collection-dimensions [aria-current="page"]').href).searchParams.get('links')`), 'members');
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-record').length`), 2);
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-reference').length`), 0);
    await screenshot('metadata-only-members');
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
    await until(`new URL(location.href).searchParams.get('view') === 'detailed'`);
    assert.deepEqual(exceptions, [], 'Switching presentation must retain working navigation');
    const returnPath = await evaluate('location.pathname + location.search');
    await follow('.collection-object-graph');
    await returnState(returnPath);
    const objectPath = await evaluate('location.pathname');
    await follow('nav[aria-label="Data object views"] a:first-child');
    assert.equal(await evaluate(`!!document.querySelector('#data-metadata')`), true);
    await returnState(returnPath);
    await follow('nav[aria-label="Data object views"] a:last-child');
    assert.equal(await evaluate(`!!document.querySelector('#detail-relationships')`), true);
    await returnState(returnPath);
    await follow('#detail-open-graph');
    assert.notEqual(await evaluate('location.pathname'), objectPath);
    await returnState(returnPath);
    await click('.relationship-node-software');
    await evaluate(`Object.defineProperty(navigator, 'clipboard', {configurable: true,
      value: {writeText: async value => {window.copiedCollectionLink = value;}}})`);
    await click('#graph-copy-link');
    await until(`typeof window.copiedCollectionLink === 'string'`);
    const standaloneCopy = new URL(await evaluate('window.copiedCollectionLink'));
    assert.ok(standaloneCopy.searchParams.get('graph_context'));
    assert.equal(standaloneCopy.hash, '#relationship-software-info');
    await navigate(standaloneCopy.pathname + standaloneCopy.search + standaloneCopy.hash);
    await returnState(returnPath);
    assert.equal(await evaluate(`document.querySelector('.relationship-node[aria-current="true"]').dataset.node`), 'relationship-software');
    await follow('#graph-return-context');
    assert.equal(await evaluate('location.pathname'), cases.reference);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('group')`), new URL(returnPath, process.env.COLLECTION_BASE_URL).searchParams.get('group'));
    assert.equal(await evaluate(`document.querySelector('#detail-relationships').dataset.view`), 'detailed');
    assert.match(await evaluate(`document.querySelector('.collection-pagination[aria-label="Object pages"]').textContent`), /Page 2 of 2/);
    await screenshot('group-page-detailed');
    assert.equal(await evaluate(`document.querySelector('#collection-export').textContent.trim()`), 'All accessible objects (JSON)');
    await click('.graph-download summary');
    assert.equal(await evaluate(`document.querySelector('#graph-save-svg').textContent.trim()`), 'Current graph page (SVG)');
    assert.equal(await evaluate(`document.querySelector('#graph-save-png').textContent.trim()`), 'Current graph page (PNG)');
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
    console.log('Group/page/view return through Details, Graph, standalone and copied links; bounded exports and access checks passed.');

    await navigate(cases.search + '?keyword=workflow');
    assert.equal(await evaluate(`document.querySelector('#graphSelectedButton').disabled`), true);
    assert.equal(await evaluate(`!!document.querySelector('.result-checkbox[value="${cases.hidden}"]')`), false);
    assert.equal(await evaluate(`!!document.querySelector('.result-checkbox[value="${cases.shared}"]')`), true);
    await click(`.result-checkbox[value="${cases.first}"]`);
    await click(`.result-checkbox[value="${cases.public}"]`);
    assert.equal(await evaluate(`document.querySelector('#selectedResultCount').textContent`), '2 selected');
    await click('#graphSelectedButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-save-form') && document.readyState === 'complete'`);
    const temporaryPath = await evaluate('location.pathname');
    assert.equal(await evaluate(`document.querySelector('.collection-total').textContent`), '2 accessible data objects');
    for (const width of [1280, 1440, 1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
      await navigate(temporaryPath);
      await layout(`small-collection-${width}`);
      const smallGraph = await evaluate(`(() => {
        const canvas = document.querySelector('.graph-canvas').getBoundingClientRect();
        const records = [...document.querySelectorAll('.relationship-node-record')].map(node => node.dataset.node);
        const reference = document.querySelector('.relationship-node-reference')?.dataset.node;
        const edges = [...document.querySelectorAll('.relationship-edge')].map(edge => [edge.dataset.source, edge.dataset.target]);
        return {records, references: document.querySelectorAll('.relationship-node-reference').length,
          connected: records.every(record => edges.some(edge => edge.includes(record) && edge.includes(reference))),
          cardsVisible: [...document.querySelectorAll('.relationship-node-record')].every(node => {
            const box = node.getBoundingClientRect();
            return box.left >= canvas.left - 1 && box.right <= canvas.right + 1
              && box.top >= canvas.top && box.bottom <= innerHeight;
          }),
          closed: !document.querySelector('#collection-save-panel').open,
          firstScreen: canvas.top >= 0 && canvas.top + Math.min(canvas.height, 260) <= innerHeight};
      })()`);
      await screenshot(`selected-two-objects-${width}`);
      assert.deepEqual(new Set(smallGraph.records), new Set([`collection-object-${cases.first}`, `collection-object-${cases.public}`]));
      assert.equal(smallGraph.records.length, 2, 'Each selected object appears exactly once before drilling into groups');
      assert.equal(smallGraph.references, 1, 'DOI spelling variants share one declared reference');
      assert.equal(smallGraph.connected, true, 'Both objects connect to their declared reference');
      assert.equal(smallGraph.closed, true, 'Saving remains available without pushing the graph down');
      assert.equal(smallGraph.firstScreen, true, `The graph is visible on the first desktop screen at ${width}px`);
      assert.equal(smallGraph.cardsVisible, true, `Both object cards fit the initial viewport at ${width}px`);
    }
    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false});
    await follow('#collection-select-more');
    const temporaryContext = await selectionContext(temporaryPath);
    await fill('#id_keyword', 'workflow');
    await click('#advancedSearchForm .search-main-row button[type="submit"]');
    await until(`new URL(location.href).searchParams.get('keyword') === 'workflow' && document.readyState === 'complete'`);
    assert.equal(await selectionContext(temporaryPath), temporaryContext);
    await follow('.search-secondary-row [data-clear-search]');
    assert.equal(await evaluate(`new URL(location.href).searchParams.has('keyword')`), false);
    assert.equal(await selectionContext(temporaryPath), temporaryContext);
    await click('.advanced-toggle-btn');
    await until(`document.querySelector('#advancedSearchPanel').classList.contains('show')`);
    await follow('.advanced-search-actions [data-clear-search]');
    assert.equal(await evaluate(`document.querySelector('#advancedSearchPanel').classList.contains('show')`), true);
    assert.equal(await selectionContext(temporaryPath), temporaryContext);
    await fill('#id_keyword', 'workflow');
    await click('#advancedSearchForm .search-main-row button[type="submit"]');
    await until(`new URL(location.href).searchParams.get('keyword') === 'workflow' && document.readyState === 'complete'`);
    await click(`.result-checkbox[value="${cases.second}"]`);
    await click('#graphSelectedButton');
    await until(`location.pathname === ${JSON.stringify(temporaryPath)} && document.querySelector('.collection-total')?.textContent === '3 accessible data objects' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`document.querySelectorAll('.relationship-node-record').length`), 3);
    await screenshot('continued-unsaved-selection');
    await click('#collection-save-panel > summary');
    await fill('#collection-save-form [name="title"]', 'Workflow collection');
    await click('#collection-save-form button[type="submit"]');
    await until(`location.pathname.includes('/graph/collections/') && !!document.querySelector('#collection-edit-form') && document.readyState === 'complete'`);
    const savedPath = await evaluate('location.pathname');
    await screenshot('saved-collection');
    await navigate(cases.home);
    assert.match(await evaluate(`document.querySelector('.collection-list-link[href="${savedPath}"]').textContent`), /Workflow collection.*3 accessible objects/s);
    await click(`.collection-list-link[href="${savedPath}"]`);
    await until(`location.pathname === ${JSON.stringify(savedPath)} && document.readyState === 'complete'`);
    await click('.collection-dimensions a[href*="links=software"]');
    await until(`location.search.includes('links=software') && document.readyState === 'complete'`);
    assert.match(await evaluate(`document.querySelector('.collection-explanation').textContent`), /names.*version/s);
    await click('.collection-dimensions a[href*="links=relations"]');
    await until(`location.search.includes('links=relations') && document.readyState === 'complete'`);
    const savedReturnPath = await evaluate('location.pathname + location.search');
    await follow(`.collection-object-graph[href^="${cases.detail}?"]`);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('tab')`), 'graph');
    await returnState(savedReturnPath);
    assert.equal(await evaluate(`!!document.querySelector('#plot-variables-data')`), false);
    await click('.relationship-node-software');
    await evaluate(`Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {writeText: async value => {window.copiedCollectionLink = value;}}})`);
    await click('#graph-copy-link');
    await until(`typeof window.copiedCollectionLink === 'string'`);
    const copied = new URL(await evaluate('window.copiedCollectionLink'));
    assert.equal(copied.pathname, cases.detail);
    assert.equal(copied.searchParams.get('tab'), 'graph');
    assert.ok(copied.searchParams.get('graph_context'));
    assert.equal(copied.hash, '#relationship-software-info');
    await navigate(copied.pathname + copied.search + copied.hash);
    assert.equal(await evaluate(`document.querySelector('.relationship-node[aria-current="true"]').dataset.node`), 'relationship-software');
    await screenshot('object-graph-tab');

    await navigate(savedPath);
    await follow('#collection-select-more');
    await selectionContext(savedPath);
    assert.match(await evaluate(`document.querySelector('#graph-selection-target').textContent`), /Add to.*Workflow collection/s);
    await fill('#id_keyword', 'workflow');
    await click('#advancedSearchForm .search-main-row button[type="submit"]');
    await until(`new URL(location.href).searchParams.get('keyword') === 'workflow' && document.readyState === 'complete'`);
    assert.match(await evaluate(`document.querySelector('#graphSelectedButton').textContent`), /Add selected objects/);
    await click(`.result-checkbox[value="${cases.shared}"]`);
    await click('#graphSelectedButton');
    await until(`location.pathname === ${JSON.stringify(savedPath)} && document.querySelector('.collection-total')?.textContent === '4 accessible data objects' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('#target-collection')`), false);
    await follow('#collection-select-more-owned');
    const ownedContext = await selectionContext(savedPath);
    assert.match(await evaluate(`document.querySelector('#graph-selection-target').textContent`), /Add to.*Workflow collection/s);
    assert.match(await evaluate(`document.querySelector('#graphMyDataButton').textContent`), /Add selected objects/);
    await fill('#myDataFilter-software', 'damask');
    await until(`new URL(location.href).searchParams.get('software') === 'damask' && document.readyState === 'complete'`);
    assert.equal(await selectionContext(savedPath), ownedContext);
    await follow('#myDataFilterForm .my-data-filter-footer a');
    assert.equal(await selectionContext(savedPath), ownedContext);
    await click(`.my-data-checkbox[value="${cases.ownedExtra}"]`);
    await click('#graphMyDataButton');
    await until(`location.pathname === ${JSON.stringify(savedPath)} && document.querySelector('.collection-total')?.textContent === '5 accessible data objects' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('#target-collection')`), false);
    await screenshot('saved-collection-appended');
    await click('.collection-manage > summary');
    await fill('#collection-edit-form [name="title"]', 'Edited workflow collection');
    await fill('#collection-edit-form [name="description"]', 'A named research group, independent of upload batches.');
    await click('#collection-edit-form button');
    await until(`document.querySelector('#collection-title')?.textContent === 'Edited workflow collection' && document.readyState === 'complete'`);
    await click(`.collection-member-checkbox[value="${cases.first}"]`);
    assert.equal(await evaluate(`document.querySelector('#collection-selection-count').textContent`), '1 selected');
    await click('#collection-remove-button');
    await until(`document.querySelector('.collection-total')?.textContent === '4 accessible data objects' && document.readyState === 'complete'`);
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
    await navigate(cases.cold.native);
    const nativePreparation = await preparationState();
    assert.equal(nativePreparation.total, 75);
    assert.equal(nativePreparation.ready, 25);
    assert.equal(nativePreparation.graph, false);
    assert.equal(nativePreparation.empty, false);
    assert.equal(nativePreparation.saveForm, false);
    assert.equal(nativePreparation.editForm, false);
    await click('#collection-preparation-continue');
    await until(`Number(document.querySelector('#collection-preparation')?.dataset.ready) === 50 && document.readyState === 'complete'`);
    assert.equal((await preparationState()).graph, false);
    await click('#collection-preparation-continue');
    await until(`!!document.querySelector('#detail-relationships') && document.querySelector('.collection-total')?.textContent === '75 accessible data objects' && document.readyState === 'complete'`);
    assert.equal(await evaluate(`!!document.querySelector('#collection-edit-form')`), true);
    console.log('Native collection preparation completes through bounded GET requests without JavaScript.');
    await navigate(cases.myData + '?software=Append%20Solver');
    assert.equal(await evaluate(`document.querySelector('#graphMyDataButton').disabled`), false);
    await click(`.my-data-checkbox[value="${cases.second}"]`);
    await click('#graphMyDataButton');
    await until(`location.pathname.includes('/graph/selection/') && !!document.querySelector('#collection-save-form') && document.readyState === 'complete'`);
    const nativeTemporaryPath = await evaluate('location.pathname');
    assert.equal(await evaluate(`document.querySelector('#collection-save-panel').open`), false);
    await follow('#collection-select-more');
    await selectionContext(nativeTemporaryPath);
    await fill('#id_keyword', 'workflow');
    await click('#advancedSearchForm .search-main-row button[type="submit"]');
    await until(`new URL(location.href).searchParams.get('keyword') === 'workflow' && document.readyState === 'complete'`);
    await selectionContext(nativeTemporaryPath);
    await click(`.result-checkbox[value="${cases.second}"]`);
    await click('#graphSelectedButton');
    await until(`location.pathname === ${JSON.stringify(nativeTemporaryPath)} && document.querySelector('.collection-total')?.textContent === '1 accessible data object' && document.readyState === 'complete'`);
    await click('#collection-save-panel > summary');
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
    await click('#collection-save-panel > summary');
    await fill('#target-collection', nativeId);
    await click('#collection-add-form button');
    await until(`location.pathname === ${JSON.stringify(nativePath)} && document.querySelector('.collection-total')?.textContent === '2 accessible data objects' && document.readyState === 'complete'`);
    await follow('#collection-select-more');
    await selectionContext(nativePath);
    await fill('#id_keyword', 'workflow');
    await click('#advancedSearchForm .search-main-row button[type="submit"]');
    await until(`new URL(location.href).searchParams.get('keyword') === 'workflow' && document.readyState === 'complete'`);
    await click(`.result-checkbox[value="${cases.public}"]`);
    await click('#graphSelectedButton');
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
    const nativeReturnPath = await evaluate('location.pathname + location.search');
    await follow('.collection-object-graph');
    await returnState(nativeReturnPath);
    await follow('#graph-return-context');
    assert.equal(await evaluate('location.pathname'), nativePath);
    assert.equal(await evaluate(`document.querySelector('#detail-relationships').dataset.view`), 'detailed');
    assert.deepEqual(exceptions, []);
    console.log('Native forms, temporary/saved append, duplicate membership, old add dialog and graph navigation passed without JavaScript.');
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
