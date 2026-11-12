const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const base = process.env.STUDY_BASE_URL;
  const cases = JSON.parse(process.env.STUDY_CASES);
  const profile = mkdtempSync(join(tmpdir(), 'study-comparison-browser-'));
  const artifacts = process.env.STUDY_ARTIFACT_DIR || join(tmpdir(), 'study-workbench-qa', 'after');
  mkdirSync(artifacts, {recursive: true});
  const browser = spawn(process.env.CHROMIUM_BIN || '/usr/bin/chromium', [
    '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio: ['ignore', 'ignore', 'pipe']});
  let socket;
  let command;
  let evaluate;
  const exceptions = [];
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
    let sequence = 0;
    const pending = new Map();
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
      const id = ++sequence;
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params, sessionId}));
    });
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    command = (method, params = {}) => send(method, params, sessionId);
    evaluate = async expression => {
      const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    async function until(expression) {
      for (let attempt = 0; attempt < 160; attempt++) {
        try {
          if (await evaluate(expression)) return;
        } catch (error) {
          if (!/context|navigation/i.test(error.message)) throw error;
        }
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out: ${expression}; state=${JSON.stringify(await evaluate(`({
        url:location.href,body:document.body.innerText.slice(0,2000)})`))}`);
    }
    async function navigate(path) {
      const url = new URL(path, base).href;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'
        && !!document.querySelector('.pc-content')`);
    }
    async function click(selector) {
      const needsBrowser = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        return !!element?.closest('#study-member-browser') && !element.getBoundingClientRect().width;
      })()`);
      if (needsBrowser) await click('#study-browser-toggle');
      await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) throw new Error('Missing control: ' + ${JSON.stringify(selector)});
        element.scrollIntoView({block:'center',behavior:'instant'});
      })()`);
      const point = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        const box = element.getBoundingClientRect();
        const x = box.left + box.width / 2, y = box.top + box.height / 2;
        const hit = document.elementFromPoint(x,y);
        if (!box.width || !box.height || !element.contains(hit)) {
          throw new Error('Covered control: ' + ${JSON.stringify(selector)} + ' by ' + hit?.outerHTML.slice(0,200));
        }
        return {x,y};
      })()`);
      await command('Input.dispatchMouseEvent', {type:'mouseMoved',...point});
      await command('Input.dispatchMouseEvent', {type:'mousePressed',button:'left',clickCount:1,...point});
      await command('Input.dispatchMouseEvent', {type:'mouseReleased',button:'left',clickCount:1,...point});
    }
    async function follow(selector) {
      const href = await evaluate(`document.querySelector(${JSON.stringify(selector)}).href`);
      await click(selector);
      await until(`location.href === ${JSON.stringify(href)} && document.readyState === 'complete'`);
    }
    async function selected() {
      return evaluate(`Array.from(document.querySelectorAll('[data-study-pin]'),node => Number(node.dataset.studyPin))`);
    }
    async function search(text) {
      await evaluate(`(() => {
        const input = document.querySelector('#study-member-query');
        input.value = ${JSON.stringify(text)};
        input.dispatchEvent(new Event('input',{bubbles:true}));
      })()`);
      await click('#study-member-search button[type="submit"]');
      await until(`document.readyState === 'complete'
        && new URL(location.href).searchParams.get('member_q') === ${JSON.stringify(text)}`);
    }
    async function screenshot(name) {
      const capture = await command('Page.captureScreenshot', {format:'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }
    async function visibleRows() {
      return evaluate(`Array.from(document.querySelectorAll('#study-comparison-table tr[data-field]'))
        .filter(row => row.getBoundingClientRect().height > 0).map(row => ({field:row.dataset.field,state:row.dataset.state}))`);
    }
    async function checkLayout(width, name) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      await until('innerWidth === ' + width);
      await evaluate('window.scrollTo(0,0)');
      const metrics = await evaluate(`(() => {
        const table = document.querySelector('#study-comparison-table');
        const browser = document.querySelector('#study-member-browser');
        return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,
          table:table?.getBoundingClientRect().toJSON(),browser:browser?.getBoundingClientRect().toJSON(),
          secret:document.body.textContent.includes('SECRET'),injection:!!window.studyInjection,
          clippedCells:table ? Array.from(table.querySelectorAll('td')).filter(cell =>
            cell.clientWidth > 0 && cell.scrollWidth > cell.clientWidth + 2 && getComputedStyle(cell).overflowX === 'hidden').length : 0};
      })()`);
      assert.ok(metrics.documentWidth <= width, `Desktop overflow: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.secret,false,'Inaccessible member metadata must not enter the page');
      assert.equal(metrics.injection,false,'Supplied labels must remain escaped');
      assert.equal(metrics.clippedCells,0,`Comparison values must remain readable: ${JSON.stringify(metrics)}`);
      if (metrics.table) assert.ok(metrics.table.top < 800,`The comparison should be visible on the initial desktop screen: ${JSON.stringify(metrics)}`);
      await screenshot(`${name}-${width}`);
    }

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls:['https://*']});
    if (process.env.CHARTJS_TEST_BUNDLE) {
      await command('Page.addScriptToEvaluateOnNewDocument', {source:readFileSync(process.env.CHARTJS_TEST_BUNDLE,'utf8')});
    }
    await command('Network.setCookie', {name:process.env.STUDY_COOKIE_NAME,value:process.env.STUDY_SESSION,url:base,path:'/'});
    await send('Browser.setDownloadBehavior', {behavior:'allow',downloadPath:artifacts});
    await command('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});

    await navigate(cases.empty + '?panel=compare');
    assert.equal(await evaluate(`!!document.querySelector('#study-workspace')`),true,
      'An empty study still explains how to select data');
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),false);
    assert.equal(await evaluate(`!!document.querySelector('#study-member-browser')`),false,
      'An empty collection leads to adding data instead of browsing an empty list');
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('.study-empty-actions a')).length`),2);
    assert.ok(await evaluate(`Array.from(document.querySelectorAll('.study-empty-actions a'))
      .every(link => new URL(link.href).searchParams.get('graph_context'))`),
      'Empty-study actions retain the collection they will add records to');
    await screenshot('empty-study');
    await navigate(cases.collection + '?links=members');
    assert.equal(await evaluate(`!!document.querySelector('#study-workspace')`),true,
      'Collections expose the study exploration and comparison workspace');
    assert.equal(await evaluate(`!!document.querySelector('[data-study-member="${cases.hidden}"]')`),false);
    await follow(`[data-study-add="${cases.changed}"]`);
    assert.deepEqual(await selected(),[cases.changed]);
    await follow('#study-member-next');
    assert.deepEqual(await selected(),[cases.changed],'Pinned records survive member pagination');
    await follow(`[data-study-add="${cases.baseline}"]`);
    assert.deepEqual(await selected(),[cases.changed,cases.baseline]);
    await follow(`[data-study-reference="${cases.baseline}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await follow('#study-compare-link');
    await until(`!!document.querySelector('#study-comparison-table')`);
    const pairRows = await visibleRows();
    assert.equal(pairRows.find(row => row.field === 'software').state,'same');
    for (const field of ['software_version','temperature','grain_count']) {
      assert.equal(pairRows.find(row => row.field === field).state,'different',`${field} differs in the supplied records`);
    }
    assert.match(await evaluate(`document.querySelector('tr[data-field="temperature"]').textContent`),/298/);
    assert.match(await evaluate(`document.querySelector('tr[data-field="temperature"]').textContent`),/323/);
    assert.match(await evaluate(`document.querySelector('tr[data-field="temperature"]').textContent`),/\bK\b/,
      'Temperature retains its explicitly supplied unit');
    assert.match(await evaluate(`document.querySelector('tr[data-field="grain_count"]').textContent`),/343/);
    assert.match(await evaluate(`document.querySelector('tr[data-field="grain_count"]').textContent`),/500/);
    for (const width of [1280,1440,1920]) await checkLayout(width,'comparison-pair');

    const csvPath = join(artifacts,'study-comparison.csv');
    rmSync(csvPath,{force:true});
    await click('#study-comparison-export');
    for (let attempt = 0; attempt < 100 && !existsSync(csvPath); attempt++) {
      await new Promise(resolve => setTimeout(resolve,50));
    }
    assert.ok(existsSync(csvPath),'Comparison downloads as a separate CSV snapshot');
    const csv = readFileSync(csvPath,'utf8');
    assert.match(csv,/comparison_status/);
    assert.match(csv,/study-browser-0/);
    assert.match(csv,/study-browser-30/);
    assert.match(csv,/343/);
    assert.match(csv,/500/);
    assert.match(csv,/'=SUM\(1,2\)/,'Spreadsheet formula text must be escaped');
    assert.doesNotMatch(csv,/SECRET/);

    await search('Study run 31');
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await follow(`[data-study-add="${cases.missing}"]`);
    await search('Study run 32');
    await follow(`[data-study-add="${cases.ambiguous}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed,cases.missing,cases.ambiguous]);
    await follow('#study-compare-link');
    assert.equal((await visibleRows()).find(row => row.field === 'temperature').state,'incomplete');
    const temperatureStates = await evaluate(`Array.from(document.querySelectorAll('tr[data-field="temperature"] td[data-state]'),cell => cell.dataset.state)`);
    assert.ok(temperatureStates.includes('not_supplied'),'Missing temperature stays explicit');
    assert.ok(temperatureStates.includes('ambiguous'),'Conflicting temperature stays explicit');
    const grainStyles = await evaluate(`Array.from(document.querySelectorAll('tr[data-field="grain_count"] td'),
      cell => ({state:cell.dataset.state,background:getComputedStyle(cell).backgroundColor}))`);
    assert.equal(grainStyles[1].state,'recorded');
    assert.equal(grainStyles[2].state,'not_supplied');
    assert.notEqual(grainStyles[1].background,grainStyles[0].background,
      'A recorded difference stays highlighted even when another record makes the row incomplete');
    assert.notEqual(grainStyles[1].background,grainStyles[2].background,
      'Missing information must not receive the recorded-difference highlight');
    await follow('#study-differences-link');
    const differing = await visibleRows();
    assert.ok(differing.some(row => row.state === 'incomplete'),'Differences view must retain incomplete information');
    assert.ok(differing.every(row => row.state !== 'same'),'Differences view omits only equal recorded rows');
    for (const width of [1280,1440,1920]) await checkLayout(width,'comparison-four');
    await command('Emulation.setDeviceMetricsOverride', {width:1280,height:1000,deviceScaleFactor:1,mobile:false});
    if (await evaluate(`document.querySelector('#study-browser-toggle').getAttribute('aria-expanded') === 'false'`)) {
      await click('#study-browser-toggle');
    }
    await until(`!document.querySelector('#study-column-navigation').hidden`);
    await click('#study-columns-right');
    await until(`document.querySelector('.study-comparison-scroll').scrollLeft > 0`);
    await click('#study-columns-left');
    await until(`document.querySelector('.study-comparison-scroll').scrollLeft === 0`);
    await evaluate(`document.querySelector('tr[data-field="temperature"]').scrollIntoView({block:'center',behavior:'instant'})`);
    const scrollPoint = await evaluate(`(() => {
      const box = document.querySelector('.study-comparison-scroll').getBoundingClientRect();
      return {x:box.right - 40,y:Math.max(80,box.top + 80)};
    })()`);
    await command('Input.dispatchMouseEvent', {type:'mouseWheel',deltaX:10000,deltaY:0,...scrollPoint});
    await until(`(() => {
      const viewport = document.querySelector('.study-comparison-scroll').getBoundingClientRect();
      const last = document.querySelector('#study-comparison-table thead th:last-child').getBoundingClientRect();
      return last.left >= viewport.left && last.right <= viewport.right + 1;
    })()`);
    await screenshot('comparison-four-final-column-1280');

    await follow('#study-explore-link');
    const visibleObjects = await evaluate(`Array.from(document.querySelectorAll('.relationship-node[data-object-pk]'),node => Number(node.dataset.objectPk))`);
    assert.deepEqual(new Set(visibleObjects),new Set([cases.baseline,cases.changed,cases.missing,cases.ambiguous]),
      'The graph focuses the records currently being compared');
    const detailUrl = await evaluate(`document.querySelector('#collection-object-${cases.baseline}-info .graph-source-link').href`);
    assert.ok(new URL(detailUrl).searchParams.get('graph_context'));
    await navigate(detailUrl);
    const returnUrl = await evaluate(`document.querySelector('#graph-return-context').href`);
    assert.equal(new URL(returnUrl).searchParams.get('compare'),[cases.baseline,cases.changed,cases.missing,cases.ambiguous].join(','));
    assert.equal(new URL(returnUrl).searchParams.get('differences'),'1',
      'The selected comparison filter survives graph and detail navigation');
    await follow('#graph-return-context');
    assert.equal((await selected()).length,4);
    await follow(`[data-study-remove="${cases.missing}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed,cases.ambiguous]);
    const beforeClear = await evaluate('location.href');
    await follow('#study-clear-selection');
    assert.deepEqual(await selected(),[]);
    await evaluate('history.back()');
    await until(`location.href === ${JSON.stringify(beforeClear)} && document.readyState === 'complete'`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed,cases.ambiguous]);

    await navigate(cases.collection + '?panel=compare&compare=' + cases.baseline + ',' + cases.hidden);
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-error')`),true);
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),false,
      'An unavailable selected record must not produce a misleading partial comparison');
    assert.equal(await evaluate(`document.body.textContent.includes('SECRET')`),false);
    await navigate(cases.temporary + '?panel=compare&compare=' + cases.baseline + ',' + cases.changed);
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),true,
      'An unsaved accessible selection can be compared before saving a collection');

    await command('Emulation.setScriptExecutionDisabled',{value:true});
    await navigate(cases.collection + '?panel=compare&compare=' + cases.baseline + ',' + cases.changed);
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),true);
    await follow('#study-differences-link');
    assert.ok((await visibleRows()).every(row => row.state !== 'same'));
    await search('Study run 31');
    await follow(`[data-study-add="${cases.missing}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed,cases.missing]);
    await follow(`[data-study-reference="${cases.changed}"]`);
    assert.equal((await selected())[0],cases.changed);
    await checkLayout(1440,'comparison-native');
    await follow('#study-clear-selection');
    assert.deepEqual(await selected(),[]);
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),false);

    const pinnedOrder = [cases.changed,cases.baseline,cases.missing];
    await navigate(cases.collection + '?panel=explore&compare=' + pinnedOrder.join(',')
      + '&differences=1&member_q=Study+run+32');
    await click('#manual-relationship-editor-heading');
    await evaluate(`(() => {
      const form = document.querySelector('#manual-relationship-form');
      form.elements.source.value = ${JSON.stringify(String(cases.changed))};
      form.elements.target.value = ${JSON.stringify(String(cases.missing))};
      form.elements.label.value = 'Pinned native study annotation';
    })()`);
    await click('#manual-relationship-save');
    await until(`document.readyState === 'complete' && !!new URL(location.href).searchParams.get('edge')
      && document.body.textContent.includes('Pinned native study annotation')`);
    assert.deepEqual(await selected(),pinnedOrder,'Saving a manual relationship preserves the ordered comparison');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('differences')`),'1');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('member_q')`),'Study run 32');
    await screenshot('native-pinned-relationship');
    await click('#manual-relationship-delete-confirm > summary');
    await click('#manual-relationship-delete');
    await until(`document.readyState === 'complete' && !new URL(location.href).searchParams.has('edge')
      && !document.body.textContent.includes('Pinned native study annotation')`);
    assert.deepEqual(await selected(),pinnedOrder,'Deleting a manual relationship preserves the ordered comparison');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('differences')`),'1');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('member_q')`),'Study run 32');

    await navigate(cases.temporary + '?panel=compare&compare=' + cases.changed + ',' + cases.baseline + '&differences=1');
    await click('#collection-save-panel > summary');
    await evaluate(`document.querySelector('#collection-save-form [name="title"]').value = 'Saved native comparison study'`);
    await click('#collection-save-form button[type="submit"]');
    await until(`document.readyState === 'complete' && location.pathname.includes('/graph/collections/')
      && document.querySelector('#collection-title').textContent === 'Saved native comparison study'`);
    assert.deepEqual(await selected(),[cases.changed,cases.baseline],
      'Saving a temporary study preserves the reference record and comparison order');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('panel')`),'compare');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('differences')`),'1');
    assert.equal(await evaluate(`!!document.querySelector('#study-comparison-table')`),true);
    await screenshot('native-saved-comparison');
    assert.deepEqual(exceptions,[],'The study workflow must not produce JavaScript errors');
    console.log('Study comparison browser checks passed: cross-page pins, reference order, recorded differences, incomplete metadata, CSV, focused graph, return navigation, history, native manual save/delete and temporary-save continuation; desktop widths 1280/1440/1920');
  } catch (error) {
    if (command) {
      try {
        const capture = await command('Page.captureScreenshot',{format:'png'});
        writeFileSync(join(artifacts,'failure.png'),Buffer.from(capture.data,'base64'));
      } catch (_) {}
    }
    throw error;
  } finally {
    socket?.close();
    browser.kill();
    await once(browser,'exit').catch(() => {});
    rmSync(profile,{recursive:true,force:true});
  }
})().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
