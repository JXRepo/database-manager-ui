const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const base = process.env.STUDY_BASE_URL;
  const cases = JSON.parse(process.env.STUDY_CASES);
  const profile = mkdtempSync(join(tmpdir(), 'study-map-browser-'));
  const artifacts = process.env.STUDY_ARTIFACT_DIR || join(tmpdir(), 'study-map-qa');
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
    async function screenshot(name) {
      const capture = await command('Page.captureScreenshot', {format:'png'});
      writeFileSync(join(artifacts, `${name}.png`), Buffer.from(capture.data, 'base64'));
    }

    async function mapReady() {
      for (let attempt = 0; attempt < 5; attempt++) {
        if (await evaluate(`!!document.querySelector('#study-map-grid')`)) return;
        if (!await evaluate(`!!document.querySelector('#study-map-continue')`)) break;
        await follow('#study-map-continue');
      }
      assert.equal(await evaluate(`!!document.querySelector('#study-map-grid')`), true,
        'The complete prepared map is rendered');
    }
    async function useUnit(label) {
      await evaluate(`(() => {
        const select = document.querySelector('#study-map-unit');
        select.value = Array.from(select.options).find(option => option.text.startsWith(${JSON.stringify(label)} + ' (')).value;
      })()`);
      const token = await evaluate(`document.querySelector('#study-map-unit').value`);
      await click('#study-map-apply');
      await until(`document.readyState === 'complete' && new URL(location.href).searchParams.get('map_unit') === ${JSON.stringify(token)}`);
      await mapReady();
    }
    async function visibleMembers() {
      return evaluate(`Array.from(document.querySelectorAll('[data-study-member]'), node => Number(node.dataset.studyMember))`);
    }
    async function desktopLayout(width, section, name) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate(`(() => {
        const top = document.querySelector(${JSON.stringify(section)}).getBoundingClientRect().top + scrollY;
        scrollTo({top:Math.max(0,top-90),behavior:'instant'});
      })()`);
      const metrics = await evaluate(`({page:document.documentElement.scrollWidth,width:innerWidth,
        section:document.querySelector(${JSON.stringify(section)}).getBoundingClientRect().toJSON(),
        hidden:document.body.textContent.includes('SECRET'),badText:document.body.textContent.includes('undefined')})`);
      assert.ok(metrics.page <= width, `No desktop page overflow: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.section.width >= 390, `Useful inspection space at ${width}: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.hidden,false);
      assert.equal(metrics.badText,false);
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
    await command('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    await navigate(cases.preparing + '?panel=map');
    assert.equal(await evaluate(`!!document.querySelector('#study-map-preparation')`),true);
    assert.equal(await evaluate(`document.querySelector('#study-map-grid')`),null,'Preparation never shows a partial map');
    assert.equal(await evaluate(`document.querySelector('#study-map-counts')`),null,'Preparation never shows partial counts');
    await screenshot('map-preparing');
    await mapReady();
    await navigate(cases.collection + '?panel=map');
    await mapReady();
    await useUnit('K');
    const initialMap = await evaluate('location.href');
    assert.match(await evaluate(`document.querySelector('#study-map-counts').textContent`), /12 mapped in this unit.*17 accessible records/);
    assert.equal(await evaluate(`document.querySelectorAll('#study-map-grid tbody tr').length`),8);
    assert.equal(await evaluate(`document.querySelectorAll('#study-map-grid thead th').length`),10);
    assert.match(await evaluate(`document.querySelector('#study-map-coverage').textContent`), /1 in other temperature units.*4 outside the map/);
    await click('#study-map-exclusions > summary');
    assert.match(await evaluate(`document.querySelector('#study-map-exclusions').textContent`), /missing|not supplied/i);
    assert.equal(await evaluate(`document.body.textContent.includes('SECRET')`),false);
    for (const width of [1280,1440,1920]) await desktopLayout(width,'#study-parameter-map','map');

    await follow('#study-map-x-next');
    assert.equal(await evaluate(`document.querySelectorAll('#study-map-grid thead th').length`),5);
    assert.equal(await evaluate(`!!document.querySelector('#study-map-window-empty')`),true);
    assert.equal(await evaluate(`document.querySelector('.study-map-legend')`),null,'An empty window has no fabricated count scale');
    await follow('#study-map-y-next');
    assert.equal(await evaluate(`document.querySelectorAll('#study-map-grid tbody tr').length`),3);
    await follow('#study-map-swap');
    assert.match(await evaluate(`document.querySelector('.study-map-axis-top > span').textContent`), /discretization/i);
    await navigate(initialMap);

    const baselineCell = '#study-map-grid [data-map-count="2"]';
    const baselineHref = await evaluate(`document.querySelector(${JSON.stringify(baselineCell)}).href`);
    await evaluate(`document.querySelector(${JSON.stringify(baselineCell)}).focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter'});
    await until(`location.href === ${JSON.stringify(baselineHref)} && document.readyState === 'complete'`);
    assert.deepEqual((await visibleMembers()).sort((a,b) => a-b),[cases.baseline,cases.duplicate].sort((a,b) => a-b));
    await follow(`[data-study-add="${cases.baseline}"]`);
    assert.deepEqual(await selected(),[cases.baseline]);
    const changedCell = await evaluate(`(() => {
      const table = document.querySelector('#study-map-grid');
      const column = Array.from(table.tHead.rows[0].cells).findIndex(cell => cell.textContent.trim() === '323');
      const row = Array.from(table.tBodies[0].rows).find(row => row.cells[0].textContent.trim() === '200');
      return row.cells[column].querySelector('a').dataset.mapCell;
    })()`);
    await follow(`[data-map-cell="${changedCell}"]`);
    assert.deepEqual(await visibleMembers(),[cases.changed]);
    assert.deepEqual(await selected(),[cases.baseline]);
    await follow(`[data-study-add="${cases.changed}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await follow('#study-compare-link');
    assert.equal(await evaluate(`document.querySelector('#study-parameters')`),null,'Detailed values load only after explicit inspection');
    assert.equal(await evaluate(`!!document.querySelector('#study-parameters-open')`),true);
    assert.equal(await evaluate(`document.querySelector('#study-parameter-table')`),null,
      'Raw parameter inspection is requested explicitly');
    await follow('#study-parameters-open');
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('inspect')`),'1');
    assert.equal(await evaluate(`document.querySelector('#study-parameter-fields').open`),false);
    assert.match(await evaluate(`document.querySelector('#study-parameters-overview').textContent`), /[1-9]\d* differing/);
    assert.match(await evaluate(`document.querySelector('.study-parameter-preview-values').textContent`), /210\.000000000000000001.*220\.000000000000000002/);
    await click('#study-parameter-fields > summary');
    const parameterText = await evaluate(`document.querySelector('#study-parameter-table').textContent`);
    assert.match(parameterText,/210\.000000000000000001/);
    assert.match(parameterText,/220\.000000000000000002/);
    assert.match(parameterText,/Loading condition 1/);
    assert.match(parameterText,/Phase 1/);
    assert.match(parameterText,/false/);
    assert.match(parameterText,/GPa/);
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('[data-parameter-path]')).some(row =>
      row.dataset.parameterPath.includes('C11') && row.dataset.state === 'different')`),true);
    assert.equal(await evaluate(`Array.from(document.querySelectorAll('[data-parameter-path]')).some(row =>
      row.dataset.parameterPath.includes('stress_11') && row.dataset.state === 'different')`),true);
    for (const width of [1280,1440,1920]) await desktopLayout(width,'#study-parameters','parameters');

    const inspectedUrl = await evaluate('location.href');
    await navigate(await evaluate(`document.querySelector('[data-parameter-source="${cases.baseline}"]').href`));
    const returnUrl = await evaluate(`document.querySelector('#graph-return-context').href`);
    assert.equal(new URL(returnUrl).searchParams.get('inspect'),'1');
    assert.equal(new URL(returnUrl).searchParams.get('map_cell'),changedCell);
    await follow('#graph-return-context');
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    assert.equal(await evaluate(`document.querySelector('#study-parameters').dataset.inspected`),'true');
    await click('#study-curves > summary');
    await until(`document.querySelector('#study-curves').dataset.loaded === 'true'`);
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),2);
    await screenshot('parameters-to-curves');

    await follow('#study-map-link');
    await useUnit('°C');
    assert.match(await evaluate(`document.querySelector('#study-map-counts').textContent`), /1 mapped in this unit/);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await follow('#study-map-grid [data-map-cell]');
    assert.deepEqual(await visibleMembers(),[cases.celsius]);
    await follow('#study-map-clear');
    assert.equal((await visibleMembers()).length,cases.total);

    await navigate(cases.collection + '?panel=map&map_cell=invalid');
    assert.equal(await evaluate(`!!document.querySelector('#study-map-error')`),true);
    assert.equal(await evaluate(`document.querySelector('#study-map-grid')`),null);
    assert.equal((await visibleMembers()).length,0,'Invalid map controls do not broaden the member browser');
    await navigate(cases.empty + '?panel=map');
    assert.equal(await evaluate(`!!document.querySelector('#study-map-empty')`),true);
    await screenshot('map-empty');

    await command('Emulation.setScriptExecutionDisabled',{value:true});
    await navigate(cases.temporary + '?panel=map');
    await mapReady();
    await useUnit('K');
    await follow('#study-map-grid [data-map-count="1"]');
    const nativeMember = (await visibleMembers())[0];
    await follow(`[data-study-add="${nativeMember}"]`);
    assert.deepEqual(await selected(),[nativeMember]);
    await follow('#study-map-swap');
    assert.deepEqual(await selected(),[nativeMember]);
    await navigate(inspectedUrl);
    await click('#study-parameter-fields > summary');
    assert.equal(await evaluate(`document.querySelector('#study-parameter-fields').open`),true);
    await screenshot('parameters-native');
    await command('Emulation.setScriptExecutionDisabled',{value:false});
    assert.deepEqual(exceptions,[],'Parameter map and inspection must not produce JavaScript exceptions');
    console.log('Study map browser checks passed: exact cell counts, axis pages and swap, unit partition, excluded metadata, pins across cells, explicit parameters and loading differences, signed source return, curves, invalid controls, empty collection and native controls at 1280/1440/1920');
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
