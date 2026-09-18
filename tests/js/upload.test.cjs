const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const chromiumPath = process.env.CHROMIUM_BIN || '/usr/bin/chromium';
const scriptPath = join(__dirname, '../../static/assets/js/upload.js');

function connect(socket) {
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) request.reject(new Error(message.error.message));
    else request.resolve(message.result);
  });
  return (method, params = {}, sessionId) => new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, {resolve, reject});
    socket.send(JSON.stringify({id, method, params, sessionId}));
  });
}

describe('upload controls in Chromium', {skip: !existsSync(chromiumPath), timeout: 30000}, () => {
  let browser;
  let profile;
  let socket;
  let send;

  before(async () => {
    profile = mkdtempSync(join(tmpdir(), 'upload-test-'));
    browser = spawn(chromiumPath, [
      '--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
      '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank',
    ], {stdio: ['ignore', 'ignore', 'pipe']});
    const address = await new Promise((resolve, reject) => {
      let output = '';
      browser.on('error', reject);
      browser.on('exit', code => reject(new Error(`Chromium exited: ${code}`)));
      browser.stderr.on('data', chunk => {
        output += chunk;
        const match = output.match(/DevTools listening on (ws:\/\/\S+)/);
        if (match) resolve(match[1]);
      });
    });
    socket = new WebSocket(address);
    await once(socket, 'open');
    send = connect(socket);
  });

  after(async () => {
    if (socket) socket.close();
    if (browser && browser.exitCode === null) {
      const exited = once(browser, 'exit');
      browser.kill('SIGTERM');
      await exited;
    }
    if (profile) rmSync(profile, {recursive: true, force: true});
  });

  async function page(t) {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
      return response.result.value;
    };
    const template = readFileSync(join(__dirname, '../../templates/pages/upload.html'), 'utf8');
    const form = template.match(/<form id="uploadForm"[\s\S]*?<\/form>/)[0]
      .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '');
    await evaluate(`document.body.innerHTML = ${JSON.stringify(form + '<div id="upload-results"></div>')};
      window.alerts = [];
      window.alert = message => window.alerts.push(message);
      window.requests = [];
      window.fetch = async (url, options) => {
        requests.push({url, options});
        if (window.responseOverride) return window.responseOverride;
        return new Response(new ReadableStream({start(controller) {
          window.uploadStream = controller;
        }}), {headers: {'Content-Type': 'application/x-ndjson'}});
      };
      window.flush = () => new Promise(resolve => setTimeout(resolve, 0));
      window.waitForIdle = async () => {
        const deadline = Date.now() + 2000;
        while (document.getElementById('uploadForm').getAttribute('aria-busy') === 'true') {
          if (Date.now() > deadline) throw new Error('Upload did not finish');
          await new Promise(resolve => setTimeout(resolve, 10));
        }
      };
      window.deliver = async (events, close = false) => {
        uploadStream.enqueue(new TextEncoder().encode(events.map(event => JSON.stringify(event) + '\\n').join('')));
        if (close) uploadStream.close();
        await flush();
      };
      window.rowStates = () => [...document.querySelectorAll('.selected-file-status')].map(row => row.textContent);
      window.activeSpinners = () => [...document.querySelectorAll('.selected-file-spinner')].filter(spinner => !spinner.hidden).length;
      window.selectFiles = names => {
        const transfer = new DataTransfer();
        names.forEach(name => transfer.items.add(new File(['{}'], name, {type: 'application/json'})));
        const input = document.getElementById('file-input');
        input.files = transfer.files;
        input.dispatchEvent(new Event('change'));
      };
      window.dropFiles = names => {
        const transfer = new DataTransfer();
        names.forEach(name => transfer.items.add(new File(['{}'], name)));
        document.querySelector('.file-upload-box').dispatchEvent(new DragEvent('drop', {
          bubbles: true, cancelable: true, dataTransfer: transfer,
        }));
      };
      window.submit = () => document.getElementById('uploadForm').dispatchEvent(
        new Event('submit', {bubbles: true, cancelable: true}));
    `);
    await evaluate(readFileSync(scriptPath, 'utf8'));
    await evaluate(`document.dispatchEvent(new Event('DOMContentLoaded'));
      window.dispatchEvent(new PageTransitionEvent('pageshow'));`);
    return evaluate;
  }

  test('an empty submit keeps controls usable and gives clear guidance', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`({
      submitted: submit(), disabled: uploadButton.disabled, requests: requests.length,
      message: uploadStatus.textContent, messageHidden: uploadStatus.hidden,
    })`);
    assert.equal(result.submitted, false);
    assert.equal(result.disabled, false);
    assert.equal(result.requests, 0);
    assert.equal(result.messageHidden, false);
    assert.equal(result.message, 'Choose at least one JSON file to upload.');
    assert.deepEqual(await evaluate(`selectFiles(['selected.json']);
      ({messageHidden: uploadStatus.hidden, submitted: submit(), disabled: uploadButton.disabled})`),
    {messageHidden: true, submitted: false, disabled: true});
  });

  test('one multipart request retains every file and waits for real server progress', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['first.json', 'second.json']);
      ({submitted: submit(), disabled: uploadButton.disabled, spinners: activeSpinners(),
        label: uploadButtonLabel.textContent, status: uploadStatus.textContent,
        busy: uploadForm.getAttribute('aria-busy'), inputDisabled: document.getElementById('file-input').disabled,
        files: requests[0]?.options.body.getAll('file').map(file => file.name),
        accept: requests[0]?.options.headers.Accept, rows: rowStates(), requests: requests.length})`);
    assert.deepEqual(result, {
      submitted: false, disabled: true, spinners: 0, label: 'Uploading…',
      status: 'Sending files…', busy: 'true', inputDisabled: false,
      files: ['first.json', 'second.json'], accept: 'application/x-ndjson',
      rows: ['Waiting', 'Waiting'], requests: 1,
    });
  });

  test('busy uploads reject repeated submits, picker clicks, removal and replacement drops', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['original.json']); submit();
      (() => {
        const input = document.getElementById('file-input');
        const box = document.querySelector('.file-upload-box');
        const pickerAllowed = input.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
        document.getElementById('remove-file').click();
        dropFiles(['replacement.json']);
        box.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true}));
        return {repeatAllowed: submit(), pickerAllowed,
          fileNames: [...input.files].map(file => file.name),
          removeDisplay: document.getElementById('remove-file').style.display,
          dragActive: box.classList.contains('drag-active')};
      })()`);
    assert.deepEqual(result, {
      repeatAllowed: false, pickerAllowed: false, fileNames: ['original.json'],
      removeDisplay: 'none', dragActive: false,
    });
  });

  test('server events advance one file at a time and show the final report below the form', async t => {
    const evaluate = await page(t);
    await evaluate(`selectFiles(['first.json', 'bad.json', 'last.json']); submit(); flush()`);
    assert.deepEqual(await evaluate(`deliver([{type:'file_start',index:0}]).then(() => ({rows:rowStates(),spinners:activeSpinners()}))`), {
      rows: ['Processing', 'Waiting', 'Waiting'], spinners: 1,
    });
    assert.deepEqual(await evaluate(`deliver([{type:'file_result',index:0,status:'uploaded',saved_count:2},{type:'file_start',index:1}]).then(() => ({rows:rowStates(),spinners:activeSpinners()}))`), {
      rows: ['Uploaded', 'Processing', 'Waiting'], spinners: 1,
    });
    assert.deepEqual(await evaluate(`deliver([{type:'file_result',index:1,status:'failed',saved_count:0},{type:'file_start',index:2}]).then(() => ({rows:rowStates(),spinners:activeSpinners(),report:document.getElementById('upload-results').textContent}))`), {
      rows: ['Uploaded', 'Failed', 'Processing'], spinners: 1, report: '',
    });
    const final = await evaluate(`deliver([{type:'file_result',index:2,status:'uploaded',saved_count:1},
      {type:'complete',summary:'2 uploaded, 1 failed.',level:'warning',report_html:'<p>Missing: phase</p>'}],true)
      .then(() => ({rows:rowStates(),spinners:activeSpinners(),report:document.getElementById('upload-results').textContent,
        busy:uploadForm.getAttribute('aria-busy'),disabled:uploadButton.disabled,repeat:submit(),requests:requests.length}))`);
    assert.deepEqual(final, {rows: ['Uploaded', 'Failed', 'Uploaded'], spinners: 0,
      report: '2 uploaded, 1 failed.Missing: phase', busy: 'false', disabled: true, repeat: false, requests: 1});
    assert.deepEqual(await evaluate(`selectFiles(['new.json']); ({disabled:uploadButton.disabled,rows:rowStates()})`), {
      disabled: false, rows: ['Waiting'],
    });
  });

  test('decoding keeps UTF-8 and JSON intact across arbitrary stream chunks', async t => {
    const evaluate = await page(t);
    await evaluate(`selectFiles(['unicode.json']); submit(); flush()`);
    await evaluate(`(async () => {
      const events = [{type:'file_start',index:0},{type:'file_result',index:0,status:'uploaded',saved_count:1},
        {type:'complete',summary:'Uploaded 日本語 <img src=x>.',level:'success',report_html:''}];
      const bytes = new TextEncoder().encode(events.map(event => JSON.stringify(event) + '\\n').join(''));
      for (const byte of bytes) uploadStream.enqueue(new Uint8Array([byte]));
      uploadStream.close(); await flush();
    })()`);
    assert.deepEqual(await evaluate(`({text:document.getElementById('upload-results').textContent,images:document.querySelectorAll('img').length,rows:rowStates()})`), {
      text: 'Uploaded 日本語 <img src=x>.', images: 0, rows: ['Uploaded'],
    });
  });

  test('a disconnected stream retains confirmed results and never retries automatically', async t => {
    const evaluate = await page(t);
    await evaluate(`selectFiles(['saved.json','unknown.json','waiting.json']); submit(); flush()`);
    await evaluate(`deliver([{type:'file_start',index:0},{type:'file_result',index:0,status:'uploaded',saved_count:1},{type:'file_start',index:1}])`);
    const result = await evaluate(`uploadStream.error(new Error('offline')); flush().then(() => ({rows:rowStates(),
      spinners:activeSpinners(),message:uploadStatus.textContent,disabled:uploadButton.disabled,repeat:submit(),requests:requests.length}))`);
    assert.deepEqual(result.rows, ['Uploaded', 'Unconfirmed', 'Unconfirmed']);
    assert.equal(result.spinners, 0);
    assert.match(result.message, /Check My Data before/);
    assert.equal(result.disabled, true);
    assert.equal(result.repeat, false);
    assert.equal(result.requests, 1);
  });

  for (const scenario of ['early complete', 'out of order', 'truncated', 'duplicate result', 'after complete']) {
    test(`an invalid stream (${scenario}) cannot display a successful final report`, async t => {
      const evaluate = await page(t);
      await evaluate(`selectFiles(['first.json','second.json']); submit(); flush()`);
      const events = {
        'early complete': [{type:'complete',summary:'Success',level:'success',report_html:''}],
        'out of order': [{type:'file_start',index:1}],
        'truncated': [{type:'file_start',index:0}],
        'duplicate result': [{type:'file_start',index:0},{type:'file_result',index:0,status:'uploaded',saved_count:1},{type:'file_result',index:0,status:'uploaded',saved_count:1}],
        'after complete': [{type:'file_start',index:0},{type:'file_result',index:0,status:'uploaded',saved_count:1},
          {type:'file_start',index:1},{type:'file_result',index:1,status:'uploaded',saved_count:1},
          {type:'complete',summary:'Success',level:'success',report_html:''},{type:'file_start',index:0}],
      }[scenario];
      const result = await evaluate(`deliver(${JSON.stringify(events)},true).then(() => ({message:uploadStatus.textContent,
        report:document.getElementById('upload-results').textContent,spinners:activeSpinners(),disabled:uploadButton.disabled}))`);
      assert.match(result.message, /Check My Data before/);
      assert.equal(result.report, '');
      assert.equal(result.spinners, 0);
      assert.equal(result.disabled, true);
    });
  }

  for (const [code, message] of [[400, 'Too many data objects.'], [403, 'Reload this page'], [429, 'Too many upload attempts'], [503, 'temporarily unavailable']]) {
    test(`HTTP ${code} gives clear guidance without displaying an error page`, async t => {
      const evaluate = await page(t);
      const result = await evaluate(`responseOverride = new Response(${JSON.stringify(code === 400 ? JSON.stringify({error: message}) : '<script>alert(1)</script>')},
        {status:${code},headers:{'Content-Type':${JSON.stringify(code === 400 ? 'application/json' : 'text/html')}}});
        selectFiles(['one.json']); submit(); waitForIdle().then(() => ({message:uploadStatus.textContent,rows:rowStates(),
          scripts:document.getElementById('upload-results').querySelectorAll('script').length,requests:requests.length}))`);
      assert.ok(result.message.includes(message), result.message);
      assert.deepEqual(result.rows, [code === 503 ? 'Unconfirmed' : 'Not uploaded']);
      if (code === 503) assert.match(result.message, /Check My Data before/);
      assert.equal(result.scripts, 0);
      assert.equal(result.requests, 1);
    });
  }

  test('an expired session shows sign-in guidance instead of rendering login HTML', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`responseOverride = new Response('<h1>Login</h1>',{headers:{'Content-Type':'text/html'}});
      Object.defineProperty(responseOverride,'redirected',{value:true}); selectFiles(['one.json']); submit();
      flush().then(() => ({message:uploadStatus.textContent,rows:rowStates(),report:document.getElementById('upload-results').textContent}))`);
    assert.match(result.message, /Sign in again/);
    assert.deepEqual(result.rows, ['Not uploaded']);
    assert.equal(result.report, '');
  });

  test('unsupported streaming falls back to native submission before any fetch', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`window.ReadableStream = undefined; selectFiles(['native.json']);
      ({submitted:submit(),requests:requests.length,disabled:uploadButton.disabled,inputDisabled:document.getElementById('file-input').disabled})`);
    assert.deepEqual(result, {submitted:true,requests:0,disabled:true,inputDisabled:false});
  });

  test('returning through browser history cannot resubmit an unconfirmed upload', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['returned.json']); submit();
      window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
      ({disabled:uploadButton.disabled,spinners:activeSpinners(),rows:rowStates(),message:uploadStatus.textContent,
        busy:uploadForm.getAttribute('aria-busy'),repeat:submit(),requests:requests.length})`);
    assert.deepEqual(result.rows, ['Unconfirmed']);
    assert.equal(result.disabled, true);
    assert.equal(result.spinners, 0);
    assert.equal(result.busy, 'false');
    assert.match(result.message, /Check My Data before/);
    assert.equal(result.repeat, false);
    assert.equal(result.requests, 1);
  });

  test('file selection still enforces five files and renders filenames only as text', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['<img src=x onerror=alert(1)>.json', 'second.json']);
      (() => {
        const names = [...document.querySelectorAll('.selected-file-name')].map(e => e.textContent);
        const dangerousNodes = document.getElementById('file-text').querySelectorAll('img,script,svg').length;
        selectFiles(Array.from({length: 6}, (_, index) => index + '.json'));
        return {names, dangerousNodes, count: document.getElementById('file-input').files.length,
          disabled: uploadButton.disabled, alerts: window.alerts};
      })()`);
    assert.deepEqual(result.names, ['<img src=x onerror=alert(1)>.json', 'second.json']);
    assert.equal(result.dangerousNodes, 0);
    assert.equal(result.count, 0);
    assert.equal(result.disabled, false);
    assert.deepEqual(result.alerts, ['You can upload up to 5 JSON files at once.']);
  });

  test('drag and drop keeps JSON filtering, multi selection and clear behavior', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`dropFiles(['first.JSON', 'ignore.txt', 'second.json']);
      (() => {
        const input = document.getElementById('file-input');
        const names = [...input.files].map(file => file.name);
        document.getElementById('remove-file').click();
        const cleared = input.files.length === 0;
        dropFiles(['ignore.txt']);
        const rejected = input.files.length === 0;
        dropFiles(Array.from({length: 6}, (_, index) => index + '.json'));
        return {names, cleared, rejected, count: input.files.length, alerts: window.alerts};
      })()`);
    assert.deepEqual(result, {
      names: ['first.JSON', 'second.json'], cleared: true, rejected: true, count: 0,
      alerts: ['Please drop JSON files only.', 'You can upload up to 5 JSON files at once.'],
    });
  });
});
