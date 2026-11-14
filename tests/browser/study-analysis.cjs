const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const base = process.env.STUDY_BASE_URL;
  const cases = JSON.parse(process.env.STUDY_CASES);
  const profile = mkdtempSync(join(tmpdir(), 'study-analysis-browser-'));
  const artifacts = process.env.STUDY_ARTIFACT_DIR || join(tmpdir(), 'study-analysis-qa');
  mkdirSync(artifacts, {recursive: true});
  const browser = spawn(process.env.CHROMIUM_BIN || '/usr/bin/chromium', [
    '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
    '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
  ], {stdio: ['ignore', 'ignore', 'pipe']});
  let socket;
  let command;
  let evaluate;
  const exceptions = [];
  const dialogs = [];
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
      if (message.method === 'Page.javascriptDialogOpening') {
        dialogs.push(message.params.type);
        command('Page.handleJavaScriptDialog',{accept:true}).catch(()=>{});
      }
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
    async function screenshot(name) {
      const capture = await command('Page.captureScreenshot', {format:'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }

    async function redirected(path) {
      await evaluate(`document.documentElement.dataset.awaitingNavigation = 'true'`);
      await command('Page.navigate', {url:new URL(path,base).href});
      await until(`!document.documentElement?.dataset.awaitingNavigation && document.readyState === 'complete' && !!document.querySelector('.pc-content')`);
    }
    async function openEditor() {
      if (!await evaluate(`document.querySelector('#study-analyses').open`)) await click('#study-analyses > summary');
    }
    async function fill(name, value) {
      await evaluate(`(() => {
        const field = document.querySelector('#study-analysis-form').elements[${JSON.stringify(name)}];
        field.value = ${JSON.stringify(value)};
        field.dispatchEvent(new Event('input',{bubbles:true}));
      })()`);
    }
    async function save(selector, expectedTitle) {
      await evaluate(`document.documentElement.dataset.awaitingNavigation = 'true'`);
      await click(selector);
      await until(`!document.documentElement?.dataset.awaitingNavigation && document.readyState === 'complete'
        && document.querySelector('#study-analysis-active-title')?.textContent === ${JSON.stringify(expectedTitle)}`);
    }
    async function queryField(value) {
      await evaluate(`(() => {
        const query = document.querySelector('#study-detail-query');
        query.value = ${JSON.stringify(value)};
        query.dispatchEvent(new Event('input',{bubbles:true}));
      })()`);
    }
    async function visibleRows() {
      return evaluate(`Array.from(document.querySelectorAll('[data-parameter-row]')).filter(row => !row.hidden).map(row => ({path:row.dataset.parameterPath,state:row.dataset.state}))`);
    }
    async function layout(width) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      if (width === 1280) await click('#study-browser-toggle');
      await evaluate(`document.querySelector('#study-parameters').scrollIntoView({block:'start'}); scrollBy(0,-90)`);
      assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false,`${width}px page stays within the desktop`);
      const sticky = await evaluate(`(() => {
        const scroller = document.querySelector('.study-parameter-scroll');
        scroller.scrollLeft = scroller.scrollWidth;
        const field = document.querySelector('[data-parameter-row]:not([hidden]) th');
        const reference = document.querySelector('[data-parameter-row]:not([hidden]) td.is-reference');
        return {fieldStyle:getComputedStyle(field).position, referenceStyle:getComputedStyle(reference).position,
          field:field.getBoundingClientRect().toJSON(), reference:reference.getBoundingClientRect().toJSON(),
          container:scroller.getBoundingClientRect().toJSON(), scrollLeft:scroller.scrollLeft};
      })()`);
      assert.equal(sticky.fieldStyle,'sticky');
      assert.equal(sticky.referenceStyle,'sticky');
      assert.ok(sticky.field.left >= sticky.container.left-1,`${width}px field remains visible`);
      assert.ok(sticky.reference.left >= sticky.field.right-1,`${width}px reference does not cover field labels`);
      if (width === 1280) assert.ok(sticky.scrollLeft > 0,'Sticky reference is checked during actual horizontal scrolling');
      await screenshot(`differences-${width}`);
      if (width === 1280) await click('#study-browser-toggle');
    }

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls:['https://*']});
    if (process.env.CHARTJS_TEST_BUNDLE) await command('Page.addScriptToEvaluateOnNewDocument', {source:readFileSync(process.env.CHARTJS_TEST_BUNDLE,'utf8')});
    await command('Network.setCookie', {name:process.env.STUDY_COOKIE_NAME,value:process.env.STUDY_SESSION,url:base,path:'/'});
    await command('Emulation.setDeviceMetricsOverride', {width:1280,height:1000,deviceScaleFactor:1,mobile:false});
    const four = cases.records.join(',');
    await navigate(cases.collection + '?panel=compare&compare=' + four);
    assert.equal(await evaluate(`document.querySelector('#study-analyses').open`),false);
    assert.ok(await evaluate(`document.querySelector('#study-comparison-table').getBoundingClientRect().top < 800`),
      'The compact analysis entry preserves the first-screen four-record comparison');
    await follow('#study-map-link');
    await follow('#study-map-grid [data-map-cell]');
    const mapCell = await evaluate(`new URL(location.href).searchParams.get('map_cell')`);
    await follow('#study-compare-link');
    await follow('#study-parameters-open');
    await click('[data-detail-status="incomplete"]');
    assert.ok((await visibleRows()).length > 0);
    assert.ok((await visibleRows()).every(row => row.state === 'incomplete'));
    await queryField('nothing matches this field');
    assert.deepEqual(await visibleRows(),[]);
    assert.equal(await evaluate(`document.querySelector('#study-detail-empty').hidden`),false);
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('[data-parameter-group]')).every(group=>group.hidden)`),true);
    const focusId = await evaluate(`document.querySelector('[data-detail-jump]').dataset.detailJump`);
    await click('[data-detail-jump]');
    await until(`document.activeElement.id === ${JSON.stringify(focusId)}`);
    assert.equal(await evaluate(`document.querySelector('#study-detail-query').value`),'');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('detail_status')`),null);
    await click('[data-detail-status="different"]');
    await queryField('C11');
    assert.equal((await visibleRows()).length,1);
    assert.equal((await visibleRows())[0].state,'different');
    for (const width of [1280,1440,1920]) await layout(width);
    await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});

    await evaluate('window.StudyState.flush()');
    await click('#study-curves > summary');
    await until(`document.querySelector('#study-curves').dataset.loaded === 'true'`);
    await click('#study-curves-records a');
    await until(`document.readyState === 'complete' && !!document.querySelector('#graph-return-context')`);
    assert.equal(new URL(await evaluate(`document.querySelector('#graph-return-context').href`)).searchParams.get('detail_q'),'C11',
      'Sources created by lazy curves use the latest signed detail state');
    await follow('#graph-return-context');
    await until(`document.querySelector('#study-curves').dataset.loaded === 'true'`);
    await click('#study-curves-overlay');
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').getAttribute('aria-pressed')`),'true');
    await openEditor();
    await fill('title','Copper temperature review');
    await fill('notes','Compare the supplied values. <img src=x onerror=window.analysisInjection=true>');
    for (const width of [1280,1440,1920]) {
      await command('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate(`document.querySelector('#study-analyses').scrollIntoView({block:'start'}); scrollBy(0,-90)`);
      assert.equal(await evaluate('document.documentElement.scrollWidth > innerWidth'),false);
      await screenshot(`analysis-editor-${width}`);
    }
    await save('#study-analysis-create','Copper temperature review');
    const analysisId = await evaluate(`new URL(location.href).searchParams.get('analysis')`);
    assert.ok(analysisId);
    assert.deepEqual(await selected(),cases.records);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('map_cell')`),mapCell);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('detail_q')`),'C11');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('detail_status')`),'different');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('curve_view')`),'overlay');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('curve_open')`),'1');
    assert.equal(await evaluate('window.analysisInjection === true'),false);
    await until(`document.querySelector('#study-curves').dataset.loaded === 'true'`);
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').getAttribute('aria-pressed')`),'true');
    const savedOpen = await evaluate(`document.querySelector('#study-analysis-reopen').href`);
    await openEditor();
    assert.equal(await evaluate(`document.querySelector('#study-analysis-dirty').hidden`),true,'Confirmed view is clean');
    await queryField('stress_11');
    await until(`document.querySelector('#study-analysis-dirty').hidden === false`);
    await redirected(savedOpen);
    assert.equal(await evaluate(`document.querySelector('#study-detail-query').value`),'C11');

    await openEditor();
    await fill('notes','Updated observation: compare the supplied values.');
    await save('#study-analysis-update','Copper temperature review');
    await openEditor();
    const staleRevision = await evaluate(`document.querySelector('#study-analysis-form').elements.revision.value`);
    const secondWrite = await evaluate(`(async()=>{
      const form = document.querySelector('#study-analysis-form');
      const body = new FormData(form); body.set('intent','update');
      const response = await fetch(form.action,{method:'POST',body,credentials:'same-origin',headers:{Accept:'application/json'}});
      return {status:response.status,result:await response.json()};
    })()`);
    assert.equal(secondWrite.status,200);
    assert.ok(secondWrite.result.ok);
    await fill('notes','Unsaved notes from the older tab');
    await click('#study-analysis-update');
    await until(`document.querySelector('#study-analysis-feedback').textContent.toLowerCase().includes('changed')`);
    assert.equal(await evaluate(`document.querySelector('#study-analysis-feedback').textContent.match(/This analysis changed/g).length`),1,
      'Conflict guidance is shown once');
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.notes.value`),'Unsaved notes from the older tab');
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.revision.value`),staleRevision);
    assert.equal(await evaluate(`document.querySelector('#study-analysis-update').disabled`),true);
    assert.equal(await evaluate(`document.querySelector('#study-analysis-copy').disabled`),false);
    await screenshot('stale-revision-notes');
    await redirected(savedOpen);
    assert.ok(dialogs.includes('beforeunload'),'Navigating away from unsaved notes requests explicit confirmation');
    await openEditor();
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.notes.value`),'Updated observation: compare the supplied values.');

    await fill('notes','Retain these notes when the connection fails');
    await evaluate(`window.analysisRealFetch = window.fetch; window.fetch = (...args) => {
      if (String(args[0]).includes('/analyses/save/')) return Promise.reject(new TypeError('Simulated lost connection'));
      return window.analysisRealFetch(...args);
    }`);
    await click('#study-analysis-update');
    await until(`document.querySelector('#study-analysis-feedback').textContent.includes('could not be confirmed')`);
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.notes.value`),'Retain these notes when the connection fails');
    assert.equal(await evaluate(`document.querySelector('#study-analysis-copy').disabled`),true);
    await screenshot('unconfirmed-save');
    await click('#study-analysis-acknowledge');
    assert.equal(await evaluate(`document.querySelector('#study-analysis-update').disabled`),false);
    await redirected(savedOpen);

    await openEditor();
    await fill('title','Copied review');
    await save('#study-analysis-copy','Copied review');
    const copyId = await evaluate(`new URL(location.href).searchParams.get('analysis')`);
    assert.notEqual(copyId,analysisId);
    await openEditor();
    assert.equal(await evaluate(`document.querySelectorAll('[data-saved-analysis]').length`),12,'Saved analyses have bounded pages');
    const next = await evaluate(`document.querySelector('#study-analysis-next').href`);
    await follow('#study-analysis-next');
    await openEditor();
    assert.ok(await evaluate(`document.querySelectorAll('[data-saved-analysis]').length < 12`));
    await redirected(savedOpen.replace(`/analyses/${analysisId}/`,`/analyses/${copyId}/`));
    await openEditor();
    await click('.study-analysis-delete > summary');
    await evaluate(`document.documentElement.dataset.awaitingNavigation='true'`);
    await click('#study-analysis-delete');
    await until(`!document.documentElement?.dataset.awaitingNavigation && document.readyState === 'complete' && !new URL(location.href).searchParams.has('analysis')`);
    assert.deepEqual(await selected(),cases.records,'Removing a saved view leaves the current record selection intact');

    await redirected(cases.changedOpen);
    assert.equal(await evaluate(`!!document.querySelector('#study-analysis-source-changed')`),true);
    await openEditor();
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.notes.value`),'Keep this original observation.');
    await screenshot('source-changed');
    await redirected(cases.unavailableOpen);
    assert.equal(await evaluate(`!!document.querySelector('#study-analysis-source-unavailable')`),true);
    assert.equal(await evaluate(`document.body.textContent.includes('SECRET')`),false);
    assert.deepEqual(await selected(),[],'Unavailable saved selection is not partially opened');

    await redirected(savedOpen);
    await queryField('stress_11');
    const source = await evaluate(`document.querySelector('[data-parameter-source]').href`);
    await click('[data-parameter-source]');
    await until(`document.readyState === 'complete' && !!document.querySelector('#graph-return-context')`);
    const returned = await evaluate(`document.querySelector('#graph-return-context').href`);
    assert.equal(new URL(returned).searchParams.get('detail_q'),'stress_11','Live filter survives signed source navigation');
    assert.equal(new URL(returned).searchParams.get('analysis'),analysisId);
    await follow('#graph-return-context');
    assert.equal(await evaluate(`document.querySelector('#study-detail-query').value`),'stress_11');

    await command('Emulation.setScriptExecutionDisabled',{value:true});
    await navigate(cases.collection + '?panel=compare&compare=' + cases.records.slice(0,2).join(',') + '&inspect=1');
    await follow('[data-detail-status="different"]');
    assert.ok((await visibleRows()).every(row=>row.state === 'different'));
    await queryField('C11');
    await click('#study-detail-search button');
    await until(`document.readyState === 'complete' && new URL(location.href).searchParams.get('detail_q') === 'C11'`);
    assert.equal((await visibleRows()).length,1);
    await openEditor();
    await fill('title','Native saved review');
    await fill('notes','Saved without JavaScript.');
    await save('#study-analysis-create','Native saved review');
    await openEditor();
    assert.equal(await evaluate(`document.querySelector('#study-analysis-form').elements.notes.value`),'Saved without JavaScript.');
    await screenshot('native-saved-analysis');
    await command('Emulation.setScriptExecutionDisabled',{value:false});
    await navigate(cases.temporary + '?panel=compare&compare=' + cases.records.slice(0,2).join(','));
    await click('#study-analysis-save-collection');
    assert.equal(await evaluate(`document.querySelector('#collection-save-panel').open`),true);
    assert.deepEqual(exceptions,[],'Saved analysis workflow has no JavaScript exceptions');
    console.log('Study analysis browser checks passed: detailed filters and focus, sticky reference across four records, saved visible state and curves, native save, source return, stale notes, unconfirmed save recovery, copy/delete, bounded library and source warnings at 1280/1440/1920.');
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
