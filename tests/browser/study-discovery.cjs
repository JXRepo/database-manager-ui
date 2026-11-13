const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync, existsSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const base = process.env.STUDY_BASE_URL;
  const cases = JSON.parse(process.env.STUDY_CASES);
  const profile = mkdtempSync(join(tmpdir(), 'study-discovery-browser-'));
  const artifacts = process.env.STUDY_ARTIFACT_DIR || join(tmpdir(), 'study-discovery-qa');
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

    async function loaded() {
      await until(`document.querySelector('#study-curves')?.dataset.loaded === 'true'`);
    }
    async function openCurves() {
      await click('#study-curves > summary');
      await loaded();
    }
    async function changeCurves(component, strain) {
      await evaluate(`document.querySelector('#study-curve-component').value = ${JSON.stringify(component)};
        document.querySelector('#study-curve-strain').value = ${JSON.stringify(strain)}`);
      await click('#study-curves-form button[type="submit"]');
      await until(`document.readyState === 'complete'
        && new URL(location.href).searchParams.get('curve_component') === ${JSON.stringify(component)}
        && new URL(location.href).searchParams.get('curve_strain') === ${JSON.stringify(strain)}`);
      await loaded();
    }
    async function curveLayout(width, label) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate(`document.querySelector('#study-curves').scrollIntoView({block:'start',behavior:'instant'})`);
      await until(`Array.from(document.querySelectorAll('#study-curves-records canvas')).every(canvas => canvas.width > 100)`);
      const metrics = await evaluate(`(() => {
        const cards = Array.from(document.querySelectorAll('.study-curve-record'));
        return {width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
          cards:cards.map(card => card.getBoundingClientRect().toJSON()),
          canvases:cards.map(card => card.querySelector('canvas')?.getBoundingClientRect().toJSON()),
          badText:document.querySelector('#study-curves').textContent.includes('undefined'),
          secret:document.body.textContent.includes('SECRET')};
      })()`);
      assert.ok(metrics.scrollWidth <= width, `No page overflow: ${JSON.stringify(metrics)}`);
      assert.equal(metrics.secret,false);
      assert.equal(metrics.badText,false);
      assert.equal(metrics.cards.length,2);
      assert.ok(metrics.canvases.every(box => box.width >= 190 && box.height >= 240),
        `Curves remain large enough to inspect at ${width}: ${JSON.stringify(metrics)}`);
      assert.ok(metrics.cards[0].right <= metrics.cards[1].left, 'The two records have independent parallel panels');
      await screenshot(`${label}-${width}`);
    }

    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls:['https://*']});
    if (process.env.CHARTJS_TEST_BUNDLE) {
      await command('Page.addScriptToEvaluateOnNewDocument', {source:readFileSync(process.env.CHARTJS_TEST_BUNDLE,'utf8')});
    }
    await command('Page.addScriptToEvaluateOnNewDocument', {source:`(() => {
      const original = window.fetch;
      window.studyCurveFetches = [];
      window.studyFailCurves = false;
      window.fetch = function(input, options) {
        if (String(input).includes('curves')) {
          window.studyCurveFetches.push(String(input));
          if (window.studyFailCurves) return Promise.reject(new Error('Synthetic connection failure'));
        }
        return original.call(this,input,options);
      };
    })()`});
    await command('Network.setCookie', {name:process.env.STUDY_COOKIE_NAME,value:process.env.STUDY_SESSION,url:base,path:'/'});
    await command('Emulation.setDeviceMetricsOverride', {width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    const pair = `${cases.baseline},${cases.changed}`;
    const pairUrl = cases.collection + '?panel=compare&compare=' + pair;

    await navigate(cases.collection + '?compare=' + cases.baseline);
    await follow('#study-find-candidates');
    assert.equal(await evaluate(`document.querySelector('#study-candidates').open`),true);
    assert.deepEqual(await selected(),[cases.baseline]);
    assert.deepEqual(await evaluate(`Array.from(document.querySelectorAll('#study-candidate-form input:checked'), input => input.value)`),['software','phase']);
    assert.equal(await evaluate(`document.querySelector('#study-vary-field').value`),'temperature');
    assert.match(await evaluate(`document.querySelector('#study-candidate-counts').textContent`),/29 match the selected conditions.*1 need more information.*1 do not match/);
    assert.equal(await evaluate(`document.querySelectorAll('#study-candidate-results article').length`),25);
    assert.equal(await evaluate(`document.querySelector('[data-candidate="${cases.excluded}"]')`),null);
    assert.equal(await evaluate(`document.body.textContent.includes('SECRET')`),false);
    await click(`[data-candidate="${cases.changed}"] .study-candidate-evidence > summary`);
    const evidence = await evaluate(`document.querySelector('[data-candidate="${cases.changed}"] [data-candidate-field="temperature"]').textContent`);
    assert.match(evidence,/298/);
    assert.match(evidence,/323/);
    assert.match(evidence,/Different recorded values/);
    await click('#study-candidate-uncertain > summary');
    await click(`[data-candidate="${cases.uncertain}"] .study-candidate-evidence > summary`);
    assert.match(await evaluate(`document.querySelector('[data-candidate="${cases.uncertain}"] [data-candidate-field="temperature"]').textContent`),/Not supplied.*Incomplete information/);
    for (const width of [1280,1440,1920]) {
      await command('Emulation.setDeviceMetricsOverride', {width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate(`document.querySelector('#study-candidates').scrollIntoView({block:'start',behavior:'instant'})`);
      assert.ok(await evaluate(`document.documentElement.scrollWidth <= innerWidth`),'Candidate discovery stays within the desktop viewport');
      await screenshot('candidates-' + width);
    }
    await follow('#study-candidate-next');
    assert.equal(await evaluate(`document.querySelectorAll('#study-candidate-results article').length`),4);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('match_fields')`),'software,phase');
    assert.deepEqual(await selected(),[cases.baseline]);
    await follow('#study-candidate-previous');

    await click('#study-candidate-form input[value="software"]');
    await click('#study-candidate-form input[value="phase"]');
    await click('#study-candidate-submit');
    await until(`!!document.querySelector('#study-candidate-error') && document.readyState === 'complete'`);
    assert.match(await evaluate(`document.querySelector('#study-candidate-error').textContent`),/at least one/);
    assert.equal(await evaluate(`document.querySelector('#study-candidate-results')`),null);
    await evaluate(`document.querySelectorAll('#study-candidate-form input[type="checkbox"]').forEach(input => {
      input.checked = ['software','phase'].includes(input.value);
    })`);
    await click('#study-candidate-submit');
    await until(`!!document.querySelector('#study-candidate-results') && document.readyState === 'complete'`);
    assert.equal(await evaluate(`new URL(document.querySelector('[data-candidate-compare="${cases.changed}"]').href).searchParams.get('match_fields')`),'software,phase',
      'Outgoing links normalize native checkbox submissions to one canonical signed representation');
    await follow(`[data-candidate-compare="${cases.changed}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    assert.equal(await evaluate(`document.querySelector('#study-candidates').open`),false);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('match_fields')`),'software,phase');
    assert.equal(await evaluate(`document.querySelector('#study-curves').open`),false);
    assert.equal(await evaluate(`window.studyCurveFetches.length`),0,
      'Browsing metadata must not fetch mechanical arrays before the user opens curves');
    await openCurves();
    assert.equal(await evaluate(`window.studyCurveFetches.length`),1);
    assert.equal(await evaluate(`document.querySelector('#study-curves-scale-note').textContent`),'Each panel uses its own scale.');
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').disabled`),false);
    assert.match(await evaluate(`document.querySelector('.study-curve-record-note').textContent`),/3 paired samples.*4 strain.*3 stress/);
    const endpointWidth = await evaluate(`(() => {
      const context = document.querySelector('#study-curves-records canvas').getContext('2d');
      context.save(); context.font = '12px "Open Sans", sans-serif';
      const width = Math.max(...['1.80e+308','5.00e−324'].map(label => context.measureText(label).width));
      context.restore(); return width;
    })()`);
    assert.ok(endpointWidth <= 68, 'Extreme positive endpoint labels fit within the centered 34px canvas margin');
    for (const width of [1280,1440,1920]) await curveLayout(width,'curves-pair');

    await click(`[data-curve-record="${cases.changed}"] .study-curve-record-name`);
    assert.equal(await evaluate(`document.querySelector('#study-curves').dataset.activeRecord`),String(cases.changed));
    assert.ok(await evaluate(`Array.from(document.querySelectorAll('[data-study-object="${cases.changed}"]'))
      .every(node => node.classList.contains('is-study-active'))`), 'Record focus reaches the pinned card and settings column');
    await click('#study-curves-overlay');
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay-view').hidden`),false);
    assert.equal(await evaluate(`document.querySelector('#study-curves-scale-note').textContent`),'All curves use the same axes and scale.');
    await until(`document.querySelector('#study-curves-overlay-view canvas').width > 200`);
    await screenshot('curves-overlay-1920');
    await click('#study-curves-clear-focus');
    assert.equal(await evaluate(`document.querySelectorAll('[data-study-object].is-study-active').length`),0);
    await click('#study-curves-separate');

    await changeCurves('11','total');
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    assert.equal(await evaluate(`new URL(location.href).searchParams.get('match_fields')`),'software,phase');
    const canvasSelector = `[data-curve-record="${cases.baseline}"] canvas`;
    await evaluate(`document.querySelector(${JSON.stringify(canvasSelector)}).focus()`);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'End',code:'End'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'End',code:'End'});
    assert.equal(await evaluate(`document.querySelector(${JSON.stringify(canvasSelector)}).dataset.sampleIndex`),'4');
    assert.match(await evaluate(`document.querySelector('[data-curve-record="${cases.baseline}"] .study-curve-hover').textContent`),/Sample 4.*X: 0.002.*Y: 24/);
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowLeft',code:'ArrowLeft'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowLeft',code:'ArrowLeft'});
    assert.equal(await evaluate(`document.querySelector(${JSON.stringify(canvasSelector)}).dataset.sampleIndex`),'3');
    await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape'});
    assert.equal(await evaluate(`document.querySelector(${JSON.stringify(canvasSelector)}).dataset.sampleIndex`),'');

    await evaluate(`document.querySelector(${JSON.stringify(canvasSelector)}).scrollIntoView({block:'center',behavior:'instant'})`);
    const curvePixel = await evaluate(`(() => {
      const canvas = document.querySelector(${JSON.stringify(canvasSelector)});
      const context = canvas.getContext('2d'), box = canvas.getBoundingClientRect();
      const pixels = context.getImageData(0,0,canvas.width,canvas.height).data;
      for (let y = Math.floor(canvas.height/3); y < canvas.height-40; y++) {
        for (let x = Math.floor(canvas.width/3); x < canvas.width-40; x++) {
          const index = (y*canvas.width+x)*4;
          if (pixels[index] < 50 && pixels[index+1] > 90 && pixels[index+1] < 160
              && pixels[index+2] > 100 && pixels[index+2] < 180 && pixels[index+3] > 200) {
            return {x:box.left+x*box.width/canvas.width,y:box.top+y*box.height/canvas.height};
          }
        }
      }
      throw new Error('No drawn recorded curve pixel was found');
    })()`);
    await command('Input.dispatchMouseEvent',{type:'mouseMoved',...curvePixel});
    await until(`document.querySelector(${JSON.stringify(canvasSelector)}).dataset.sampleIndex !== ''`);
    const sample = await evaluate(`({index:Number(document.querySelector(${JSON.stringify(canvasSelector)}).dataset.sampleIndex),
      label:document.querySelector('[data-curve-record="${cases.baseline}"] .study-curve-hover').textContent})`);
    const recordedX = [0,.003,-.001,.001,.002], recordedY = [0,30,-15,12,24];
    assert.ok(sample.index >= 0 && sample.index < 5);
    assert.ok(sample.label.includes(`X: ${recordedX[sample.index]}`));
    assert.ok(sample.label.includes(`Y: ${recordedY[sample.index]}`));
    await command('Input.dispatchMouseEvent',{type:'mouseMoved',x:5,y:5});
    await screenshot('curves-cyclic-component');
    await navigate(await evaluate(`document.querySelector('[data-curve-source="${cases.baseline}"]').href`));
    const collectionReturn = await evaluate(`document.querySelector('#graph-return-context').href`);
    assert.equal(new URL(collectionReturn).searchParams.get('match_fields'),'software,phase');
    assert.equal(new URL(collectionReturn).searchParams.get('vary_field'),'temperature');
    assert.equal(new URL(collectionReturn).searchParams.get('curve_component'),'11');
    await follow('#graph-return-context');
    await loaded();
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);

    const four = [cases.baseline,cases.changed,cases.uncertain,cases.excluded];
    await navigate(cases.collection + '?panel=compare&compare=' + four.join(','));
    await openCurves();
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),4);
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').disabled`),false);
    await click('#study-curves-overlay');
    assert.equal(await evaluate(`document.querySelectorAll('[data-curve-highlight]').length`),4);
    await click(`[data-curve-highlight="${cases.excluded}"]`);
    assert.equal(await evaluate(`document.querySelector('#study-curves').dataset.activeRecord`),String(cases.excluded));
    await screenshot('curves-four-record-overlay');

    await navigate(cases.collection + '?panel=compare&compare=' + cases.baseline + ',' + cases.mismatch);
    await openCurves();
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').disabled`),true,
      'MPa and GPa cannot be overlaid without an explicit supported conversion');
    assert.match(await evaluate(`document.querySelector('#study-curves-overlay-note').textContent`),/unit/i);
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),2);
    await screenshot('curves-unit-mismatch');

    await navigate(cases.collection + '?panel=compare&compare=' + cases.baseline + ',' + cases.missing);
    await openCurves();
    assert.equal(await evaluate(`document.querySelector('#study-curves-overlay').disabled`),true);
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),1);
    assert.match(await evaluate(`document.querySelector('[data-curve-record="${cases.missing}"]').textContent`),/supplied|missing|available/i);

    await navigate(pairUrl);
    await evaluate('window.studyFailCurves = true');
    await click('#study-curves > summary');
    await until(`document.querySelector('#study-curves').dataset.loaded === 'error'`);
    assert.equal(await evaluate(`document.querySelector('#study-curves-retry').hidden`),false);
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),0);
    await evaluate('window.studyFailCurves = false');
    await click('#study-curves-retry');
    await loaded();
    assert.equal(await evaluate(`window.studyCurveFetches.length`),2,'Failed requests retry only after an explicit action');

    await navigate(cases.temporary + '?panel=compare&compare=' + pair);
    await openCurves();
    assert.equal(await evaluate(`document.querySelectorAll('#study-curves-records canvas').length`),2);
    await changeCurves('11','plastic');
    assert.match(await evaluate(`document.querySelector('.study-curve-record-units').textContent`),/Plastic strain/);
    const source = await evaluate(`document.querySelector('[data-curve-source="${cases.baseline}"]').href`);
    await navigate(source);
    const returnLink = await evaluate(`Array.from(document.querySelectorAll('a')).find(link => link.textContent.trim() === 'Back to selection').href`);
    assert.equal(new URL(returnLink).searchParams.get('curve_component'),'11');
    assert.equal(new URL(returnLink).searchParams.get('curve_strain'),'plastic');

    await command('Emulation.setScriptExecutionDisabled',{value:true});
    await navigate(cases.collection + '?compare=' + cases.baseline + '&find_candidates=1');
    assert.equal(await evaluate(`document.querySelector('#study-candidates').open`),true);
    await evaluate(`document.querySelector('#study-candidate-form input[value="software"]').checked = false`);
    await click('#study-candidate-submit');
    await until(`document.readyState === 'complete' && new URL(location.href).searchParams.getAll('match_field').join(',') === ',phase'`);
    assert.match(await evaluate(`document.querySelector('#study-candidate-counts').textContent`),/30 match the selected conditions/);
    await follow(`[data-candidate-compare="${cases.changed}"]`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await navigate(pairUrl + '&curve_component=11&curve_strain=plastic');
    assert.equal(await evaluate(`document.querySelector('#study-curve-component').value`),'11');
    assert.equal(await evaluate(`document.querySelectorAll('[data-curve-source]').length`),2);
    assert.equal(await evaluate(`!!document.querySelector('noscript').textContent.trim()`),true);
    await evaluate(`document.querySelector('#study-curve-component').value = 'equivalent';
      document.querySelector('#study-curve-strain').value = 'total'`);
    await click('#study-curves-form button[type="submit"]');
    await until(`document.readyState === 'complete' && new URL(location.href).searchParams.get('curve_component') === 'equivalent'`);
    assert.deepEqual(await selected(),[cases.baseline,cases.changed]);
    await screenshot('curves-native-controls');
    await command('Emulation.setScriptExecutionDisabled',{value:false});

    assert.deepEqual(exceptions,[],'The study workflow must not produce JavaScript exceptions');
    console.log(`Extreme endpoint font probe: ${endpointWidth.toFixed(2)}px inside 68px of centered space`);
    console.log('Study discovery browser checks passed: explicit candidate evidence, uncertainty, pagination, criteria errors and recovery, candidate-to-comparison navigation, lazy complete curves, recorded loops and hover, keyboard samples, linked settings, explicit overlay, incompatible units, missing responses, retry, temporary scope, signed return and native controls at 1280/1440/1920');
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
