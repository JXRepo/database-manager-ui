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
      const response = await send('Runtime.evaluate', {expression, returnByValue: true}, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
      return response.result.value;
    };
    const template = readFileSync(join(__dirname, '../../templates/pages/upload.html'), 'utf8');
    const form = template.match(/<form id="uploadForm"[\s\S]*?<\/form>/)[0]
      .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '');
    await evaluate(`document.body.innerHTML = ${JSON.stringify(form)};
      window.alerts = [];
      window.alert = message => window.alerts.push(message);
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
      submitted: submit(), disabled: uploadButton.disabled, spinnerHidden: uploadSpinner.hidden,
      message: uploadStatus.textContent, messageHidden: uploadStatus.hidden,
    })`);
    assert.equal(result.submitted, false);
    assert.equal(result.disabled, false);
    assert.equal(result.spinnerHidden, true);
    assert.equal(result.messageHidden, false);
    assert.equal(result.message, 'Choose at least one JSON file to upload.');
    assert.deepEqual(await evaluate(`selectFiles(['selected.json']);
      ({messageHidden: uploadStatus.hidden, submitted: submit(), disabled: uploadButton.disabled})`),
    {messageHidden: true, submitted: true, disabled: true});
  });

  test('a valid submit shows progress and keeps every selected file in the multipart data', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['first.json', 'second.json']);
      ({submitted: submit(), disabled: uploadButton.disabled, spinnerHidden: uploadSpinner.hidden,
        label: uploadButtonLabel.textContent, status: uploadStatus.textContent,
        busy: uploadForm.getAttribute('aria-busy'), inputDisabled: document.getElementById('file-input').disabled,
        files: new FormData(uploadForm).getAll('file').map(file => file.name)})`);
    assert.deepEqual(result, {
      submitted: true, disabled: true, spinnerHidden: false, label: 'Uploading…',
      status: 'Uploading and checking files…', busy: 'true', inputDisabled: false,
      files: ['first.json', 'second.json'],
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

  test('returning through the browser cache resets progress and preserves the file selection', async t => {
    const evaluate = await page(t);
    const result = await evaluate(`selectFiles(['returned.json']); submit();
      window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
      ({disabled: uploadButton.disabled, spinnerHidden: uploadSpinner.hidden,
        label: uploadButtonLabel.textContent, statusHidden: uploadStatus.hidden,
        busy: uploadForm.getAttribute('aria-busy'), pickerDisabled: document.querySelector('.file-upload-box').getAttribute('aria-disabled'),
        removeDisplay: document.getElementById('remove-file').style.display,
        selectedName: document.querySelector('.selected-file-name').textContent,
        canSubmitAgain: submit()})`);
    assert.deepEqual(result, {
      disabled: false, spinnerHidden: true, label: 'Upload', statusHidden: true,
      busy: 'false', pickerDisabled: 'false', removeDisplay: 'inline-flex',
      selectedName: 'returned.json', canSubmitAgain: true,
    });
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
