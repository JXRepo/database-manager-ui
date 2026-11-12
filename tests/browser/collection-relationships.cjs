const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const base = process.env.MANUAL_GRAPH_BASE_URL;
  const cases = JSON.parse(process.env.MANUAL_GRAPH_CASES);
  const profile = mkdtempSync(join(tmpdir(), 'manual-graph-browser-'));
  const artifacts = process.env.MANUAL_GRAPH_ARTIFACT_DIR || join(tmpdir(), 'manual-relationships-qa');
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
    const requests = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails);
      if (message.method === 'Network.requestWillBeSent') requests.push(message.params.request);
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
        url: location.href, status: document.querySelector('#manual-relationship-status')?.textContent,
        body: document.body.innerText.slice(0, 1500)})`))}`);
    }
    async function navigate(path) {
      const url = new URL(path, base).href;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete'
        && !!document.querySelector('.pc-content')`);
    }
    async function point(selector) {
      return evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) throw new Error('Missing control: ' + ${JSON.stringify(selector)});
        const box = element.getBoundingClientRect();
        const x = box.left + box.width / 2, y = box.top + box.height / 2;
        const hit = document.elementFromPoint(x, y);
        if (!box.width || !box.height || !element.contains(hit)) {
          throw new Error('Covered control: ' + ${JSON.stringify(selector)} + ' by ' + hit?.outerHTML.slice(0, 200));
        }
        return {x, y};
      })()`);
    }
    async function clickPoint(position) {
      await command('Input.dispatchMouseEvent', {type: 'mouseMoved', ...position});
      await command('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...position});
      await command('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...position});
    }
    async function click(selector) {
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'instant'})`);
      await clickPoint(await point(selector));
    }
    async function fill(name, value) {
      await evaluate(`(() => {
        const element = document.querySelector('#manual-relationship-form [name="${name}"]');
        element.value = ${JSON.stringify(String(value))};
        element.dispatchEvent(new Event('input', {bubbles:true}));
        element.dispatchEvent(new Event('change', {bubbles:true}));
      })()`);
    }
    async function formValues() {
      return evaluate(`Object.fromEntries(new FormData(document.querySelector('#manual-relationship-form')))`);
    }
    async function relationships() {
      return evaluate(`fetch(document.querySelector('#manual-relationship-export').href)
        .then(response => response.json())`);
    }
    async function screenshot(name) {
      const capture = await command('Page.captureScreenshot', {format:'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }
    async function layout(width) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      await until('innerWidth === ' + width);
      const metrics = await evaluate(`(() => {
        const canvas = document.querySelector('.graph-canvas').getBoundingClientRect();
        const inspector = document.querySelector('.relationship-inspector').getBoundingClientRect();
        return {width:innerWidth, documentWidth:document.documentElement.scrollWidth,
          beside: inspector.left >= canvas.right - 1, canvasHeight:canvas.height,
          secret:document.body.textContent.includes('SECRET'), injection:!!window.manualInjection};
      })()`);
      assert.ok(metrics.documentWidth <= width, `Desktop overflow: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.beside && metrics.canvasHeight >= 400, `Graph layout: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.secret, false);
      assert.equal(metrics.injection, false);
      await evaluate('window.scrollTo(0,0)');
      await screenshot(`manual-relationships-${width}`);
      await evaluate(`document.querySelector('#manual-relationships').scrollIntoView({block:'center',behavior:'instant'})`);
      await screenshot(`manual-relationship-editor-${width}`);
    }
    async function draw(source, target) {
      await click('#graph-draw-connection');
      await until(`document.querySelector('#graph-draw-connection').getAttribute('aria-pressed') === 'true'`);
      await evaluate(`document.querySelector('.relationship-viewport').scrollIntoView({block:'center',behavior:'instant'})`);
      const start = await point(`.relationship-port[data-source-object="${source}"]`);
      const end = await point(`.relationship-node[data-object-pk="${target}"]`);
      await command('Input.dispatchMouseEvent', {type:'mouseMoved',...start});
      await command('Input.dispatchMouseEvent', {type:'mousePressed',button:'left',clickCount:1,...start});
      for (let step = 1; step <= 8; step++) {
        await command('Input.dispatchMouseEvent', {type:'mouseMoved',buttons:1,
          x:start.x + (end.x - start.x) * step / 8, y:start.y + (end.y - start.y) * step / 8});
      }
      await command('Input.dispatchMouseEvent', {type:'mouseReleased',button:'left',clickCount:1,...end});
      await until(`document.querySelector('#manual-relationship-source').value === '${source}'
        && document.querySelector('#manual-relationship-target').value === '${target}'`);
    }
    async function waitSaved(label) {
      await until(`document.readyState === 'complete' && !!new URL(location.href).searchParams.get('edge')
        && document.querySelector('#manual-relationship-form [name="label"]')?.value === ${JSON.stringify(label)}
        && document.querySelector('.relationship-edge[data-manual-id] title')?.textContent.includes(${JSON.stringify(label)})`);
      return Number(await evaluate(`new URL(location.href).searchParams.get('edge')`));
    }

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls:['https://*']});
    if (process.env.CHARTJS_TEST_BUNDLE) {
      await command('Page.addScriptToEvaluateOnNewDocument', {source:readFileSync(process.env.CHARTJS_TEST_BUNDLE,'utf8')});
    }
    await command('Network.setCookie', {name:process.env.MANUAL_GRAPH_COOKIE_NAME,
      value:process.env.MANUAL_GRAPH_SESSION,url:base,path:'/'});
    await send('Browser.setDownloadBehavior', {behavior:'allow',downloadPath:artifacts});
    await command('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});

    await navigate(cases.temporary);
    assert.equal(await evaluate(`!!document.querySelector('#manual-relationship-form')`), false,
      'Temporary selections require saving before manual relationship editing');
    await navigate(cases.small + '?links=members');
    assert.equal(await evaluate(`!!document.querySelector('#graph-draw-connection')`), true,
      'Saved collections expose a control for drawing manual connections');
    assert.equal(await evaluate(`!!document.querySelector('#manual-relationship-source option[value="${cases.hidden}"]')`), false);
    await draw(cases.first, cases.second);
    assert.equal(await evaluate(`document.activeElement.id`), 'manual-relationship-label');
    const label = 'Derived from <img src=x onerror=window.manualInjection=true>';
    await fill('label', label);
    await click('#manual-relationship-save');
    const relationId = await waitSaved(label);
    let exported = await relationships();
    assert.equal(exported.relationships.length, 1);
    assert.equal(exported.relationships[0].label, label);
    assert.equal(exported.relationships[0].source.id, cases.first);
    assert.equal(exported.relationships[0].target.id, cases.second);
    await navigate(cases.small + '?links=members&edge=' + relationId);
    assert.equal((await formValues()).label, label, 'A reload retains the saved relation');
    for (const width of [1280,1440,1920]) await layout(width);

    const svgPath = join(artifacts, 'collection-relationships-compact.svg');
    rmSync(svgPath, {force:true});
    await click('.graph-download summary');
    await click('#graph-save-svg');
    for (let attempt = 0; attempt < 100 && !existsSync(svgPath); attempt++) {
      await new Promise(resolve => setTimeout(resolve,50));
    }
    assert.ok(existsSync(svgPath), 'The current graph downloads as SVG');
    const svgText = readFileSync(svgPath,'utf8');
    assert.match(svgText, /stroke-dasharray=/, 'Manual connections remain distinct in the exported image');
    assert.match(svgText, /Derived from &lt;img/);
    assert.doesNotMatch(svgText, /class="relationship-port|manual-relationship-preview/);

    await fill('label','Revised dependency');
    await fill('target',cases.third);
    await click('#manual-relationship-save');
    await waitSaved('Revised dependency');
    exported = await relationships();
    assert.equal(exported.relationships[0].target.id,cases.third);
    assert.equal(exported.relationships[0].revision,2);
    await layout(1280);

    const oldRevision = (await formValues()).revision;
    const concurrent = await evaluate(`(async () => {
      const form = document.querySelector('#manual-relationship-form');
      const body = new FormData(form);
      body.set('label','Saved in another tab');
      const response = await fetch(form.action,{method:'POST',body,headers:{Accept:'application/json'}});
      return {status:response.status,body:await response.json()};
    })()`);
    assert.equal(concurrent.status,200);
    await fill('label','Stale tab draft');
    assert.equal((await formValues()).revision,oldRevision);
    await click('#manual-relationship-save');
    await until(`!document.querySelector('#manual-relationship-status').hidden
      && document.querySelector('#manual-relationship-save').disabled`);
    assert.equal((await formValues()).label,'Stale tab draft');
    assert.equal((await relationships()).relationships[0].label,'Saved in another tab');
    await click('#manual-relationship-reload');
    await waitSaved('Saved in another tab');

    await fill('label','Draft retained after connection failure');
    const saveUrl = await evaluate(`document.querySelector('#manual-relationship-form').action`);
    await command('Network.setBlockedURLs',{urls:['https://*',saveUrl]});
    const beforeFailure = requests.filter(request => request.url === saveUrl && request.method === 'POST').length;
    await click('#manual-relationship-save');
    await until(`!document.querySelector('#manual-relationship-status').hidden
      && !document.querySelector('#manual-relationship-save').disabled`);
    assert.equal((await formValues()).label,'Draft retained after connection failure');
    await new Promise(resolve => setTimeout(resolve,900));
    assert.equal(requests.filter(request => request.url === saveUrl && request.method === 'POST').length,
      beforeFailure + 1,'A failed save must not retry automatically');
    await command('Network.setBlockedURLs',{urls:['https://*']});
    await click('#manual-relationship-save');
    await waitSaved('Draft retained after connection failure');

    await click('#manual-relationship-cancel');
    await evaluate(`document.querySelector('.relationship-viewport').scrollIntoView({block:'center',behavior:'instant'})`);
    const edgePoint = await evaluate(`(() => {
      const edge = document.querySelector('.relationship-edge[data-manual-id="${relationId}"]');
      const position = edge.getPointAtLength(edge.getTotalLength() / 2);
      const point = new DOMPoint(position.x,position.y).matrixTransform(edge.getScreenCTM());
      return {x:point.x,y:point.y,hit:document.elementFromPoint(point.x,point.y)?.outerHTML.slice(0,220)};
    })()`);
    assert.ok(edgePoint.hit?.includes('data-manual-id'), `Manual connection must be clickable along its curve: ${JSON.stringify(edgePoint)}`);
    await clickPoint({x:edgePoint.x,y:edgePoint.y});
    await until(`document.querySelector('#manual-relationship-editor').open
      && document.querySelector('#manual-relationship-form [name="relationship_id"]').value === '${relationId}'`);
    await click('#manual-relationship-cancel');
    await click('#graph-draw-connection');
    await evaluate(`document.querySelector('.relationship-viewport').focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
    assert.equal(await evaluate(`document.querySelector('#graph-draw-connection').getAttribute('aria-pressed')`),'false');
    assert.equal((await relationships()).relationships.length,1,'Cancelling drawing never persists a new relation');

    await click('#graph-draw-connection');
    await evaluate(`document.querySelector('.relationship-port[data-source-object="${cases.first}"]').focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
    await evaluate(`document.querySelector('.relationship-node[data-object-pk="${cases.third}"]').focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
    assert.equal((await formValues()).source,String(cases.first));
    assert.equal((await formValues()).target,String(cases.third));
    await fill('label','Discard this unsaved connection');
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
    assert.equal(await evaluate(`document.querySelector('#manual-relationship-editor').open`),false,
      'Escape discards the form after both endpoints have been selected');
    assert.equal((await formValues()).label,'');
    assert.equal((await formValues()).source,'');
    assert.equal((await relationships()).relationships.length,1);

    await navigate(cases.small + '?links=members&edge=' + relationId);
    await evaluate(`document.querySelector('#manual-relationship-delete-form').closest('details').open = true`);
    await click('#manual-relationship-delete');
    await until(`document.readyState === 'complete' && !new URL(location.href).searchParams.has('edge')
      && !document.querySelector('.relationship-edge[data-manual-id]')`);
    assert.equal((await relationships()).relationships.length,0);

    await navigate(cases.large + '?links=members');
    assert.equal(await evaluate(`!!document.querySelector('.relationship-node[data-object-pk="${cases.first}"]')`),false);
    await click('#graph-add-relationship');
    await fill('source',cases.distant);
    await fill('target',cases.first);
    await fill('label','Related across member pages');
    await click('#manual-relationship-save');
    await waitSaved('Related across member pages');
    for (const endpoint of [cases.first,cases.distant]) {
      assert.equal(await evaluate(`!!document.querySelector('.relationship-node[data-object-pk="${endpoint}"]')`),true);
    }
    assert.equal((await relationships()).relationships.length,1);
    await screenshot('relationship-across-pages');

    await navigate(cases.parallel + '?links=members');
    for (const view of ['compact','detailed']) {
      if (view === 'detailed') await click('[data-graph-view="detailed"]');
      await click('#graph-zoom-reset');
      for (let step = 0; step < 5; step++) await click('#graph-zoom-out');
      assert.equal(await evaluate(`new Set(Array.from(document.querySelectorAll('.relationship-edge[data-manual-id]'), edge => edge.getAttribute('d'))).size`),13,
        'Thirteen same-pair relationships must retain distinct paths');
      for (const id of [cases.parallel_ids[0],cases.parallel_ids[12]]) {
        await evaluate(`document.querySelector('.relationship-viewport').scrollIntoView({block:'center',behavior:'instant'})`);
        const position = await evaluate(`(() => {
          const edge = document.querySelector('.relationship-edge[data-manual-id="${id}"]');
          const point = edge.getPointAtLength(edge.getTotalLength() / 2);
          const screen = new DOMPoint(point.x,point.y).matrixTransform(edge.getScreenCTM());
          return {x:screen.x,y:screen.y,hitId:document.elementFromPoint(screen.x,screen.y)?.dataset.manualId,
            hitAligned:edge.nextElementSibling.getAttribute('d') === edge.getAttribute('d')};
        })()`);
        assert.equal(position.hitAligned,true,'The wide interaction path follows presentation changes');
        assert.ok(position.hitId,'The actual curve can receive pointer input');
        if (id === cases.parallel_ids[0]) assert.notEqual(position.hitId,String(id),
          'The fixture must exercise overlapping hit areas, where SVG stacking points to another edge');
        await clickPoint({x:position.x,y:position.y});
        assert.equal((await formValues()).relationship_id,String(id),
          `Clicking the nearest ${view} curve must select its own relationship`);
        await click('#manual-relationship-cancel');
      }
    }
    await evaluate(`document.querySelector('.relationship-edge[data-manual-id="${cases.parallel_ids[0]}"]').focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
    assert.equal((await formValues()).relationship_id,String(cases.parallel_ids[0]),
      'Keyboard activation edits the explicitly focused relationship');

    await command('Emulation.setScriptExecutionDisabled',{value:true});
    await navigate(cases.small + '?links=members');
    await evaluate(`document.querySelector('#manual-relationship-editor').open = true`);
    await fill('source',cases.first);
    await fill('target',cases.first);
    await fill('label','Native recorded relationship');
    await click('#manual-relationship-save');
    await until(`document.readyState === 'complete' && location.pathname.includes('/relationships/save/')
      && !!document.querySelector('#manual-relationship-form .errorlist')`);
    assert.equal((await formValues()).label,'Native recorded relationship', 'Native errors retain the entered name');
    assert.equal((await formValues()).source,String(cases.first));
    await fill('target',cases.second);
    await click('#manual-relationship-save');
    await until(`document.readyState === 'complete' && !!new URL(location.href).searchParams.get('edge')
      && document.body.textContent.includes('Native recorded relationship')`);
    assert.equal((await relationships()).relationships.length,1,'Native form submissions persist without JavaScript');
    await evaluate(`document.querySelector('#manual-relationships').scrollIntoView({block:'center',behavior:'instant'})`);
    await screenshot('native-relationship-form');
    assert.deepEqual(exceptions,[], 'The workflow must not produce JavaScript errors');
    console.log('Manual relationship browser checks passed: drag, persistence, editing, stale updates, network errors, Escape discard, delete, exports, 13 overlapping hit areas in both views, keyboard selection, cross-page and native forms; desktop widths 1280/1440/1920');
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
