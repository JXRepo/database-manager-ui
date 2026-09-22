const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const root = join(__dirname, '../..');
const chromiumPath = process.env.CHROMIUM_BIN || '/usr/bin/chromium';
const scriptPath = join(root, 'static/assets/js/getting-started.js');

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

function dialogHTML(autoShow, dismissed) {
  const content = readFileSync(join(root, 'templates/includes/getting_started_content.html'), 'utf8');
  return readFileSync(join(root, 'templates/includes/getting_started_dialog.html'), 'utf8')
    .replace(/{% include[^%]+%}/, content)
    .replaceAll("{% url 'getting_started' %}", '/getting-started/')
    .replaceAll("{% url 'search' %}", '/search/')
    .replaceAll("{% url 'upload_json' %}", '/upload/')
    .replaceAll("{% url 'json_data_list' %}", '/data-list/')
    .replace('{% csrf_token %}', '<input type="hidden" name="csrfmiddlewaretoken" value="test-csrf">')
    .replaceAll('{{ request.get_full_path }}', '/search/?q=copper')
    .replace('{{ heading_id }}', 'quick-start-title')
    .replace('{{ guide_title }}', 'Welcome to the data platform')
    .replace("{{ show_getting_started|yesno:'true,false' }}", String(autoShow))
    .replace("{{ getting_started_dismissed|yesno:'true,false' }}", String(dismissed))
    .replace(/{%[^%]+%}/g, '');
}

describe('quick start in Chromium', {skip: !existsSync(chromiumPath), timeout: 30000}, () => {
  let browser;
  let profile;
  let socket;
  let send;

  before(async () => {
    profile = mkdtempSync(join(tmpdir(), 'getting-started-test-'));
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

  async function page(t, {autoShow = true, dismissed = false, width = 1440} = {}) {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    await send('Emulation.setDeviceMetricsOverride', {
      width, height: 800, deviceScaleFactor: 1, mobile: false,
    }, sessionId);
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', {
        expression, returnByValue: true, awaitPromise: true,
      }, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
      return response.result.value;
    };
    const html = '<a href="/getting-started/" data-open-quick-start>Quick start</a>'
      + '<input id="background-search" value="copper">' + dialogHTML(autoShow, dismissed);
    const css = readFileSync(join(root, 'static/assets/css/style.css'), 'utf8')
      + readFileSync(join(root, 'static/assets/css/getting-started.css'), 'utf8');
    await evaluate(`document.head.innerHTML = '<style>' + ${JSON.stringify(css)} + '</style>';
      document.body.innerHTML = ${JSON.stringify(html)};
      window.dialog = document.querySelector('dialog');
      window.requests = [];
      window.fetch = async (url, options) => {
        requests.push({url, method: options.method, credentials: options.credentials,
          redirect: options.redirect, fields: Object.fromEntries(options.body)});
        if (window.fetchOverride) return window.fetchOverride();
        return new Response(JSON.stringify({dismissed: true}), {headers: {'Content-Type': 'application/json'}});
      };
      window.flush = () => new Promise(resolve => setTimeout(resolve, 0));`);
    await evaluate(readFileSync(join(root, 'static/assets/js/plugins/feather.min.js'), 'utf8'));
    await evaluate('feather.replace()');
    await evaluate(existsSync(scriptPath) ? readFileSync(scriptPath, 'utf8') : '');
    return {evaluate, key: params => send('Input.dispatchKeyEvent', params, sessionId)};
  }

  test('first display focuses the dialog without saving before an acknowledgement', async t => {
    const {evaluate, key} = await page(t);
    assert.deepEqual(await evaluate(`({open: dialog.open, focusInside: dialog.contains(document.activeElement),
      requests: requests.length, locked: document.body.classList.contains('quick-start-open')})`),
    {open: true, focusInside: true, requests: 0, locked: true});
    await key({type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
    assert.equal(await evaluate('dialog.contains(document.activeElement)'), true);
  });

  test('skipping saves with CSRF, closes, and leaves existing search input untouched', async t => {
    const {evaluate} = await page(t);
    await evaluate("dialog.querySelector('.quick-start-footer [data-guide-dismiss]').click(); flush()");
    assert.deepEqual(await evaluate(`({open: dialog.open, value: document.querySelector('#background-search').value,
      locked: document.body.classList.contains('quick-start-open'), requests})`), {
      open: false, value: 'copper', locked: false,
      requests: [{url: '/getting-started/', method: 'POST', credentials: 'same-origin', redirect: 'error',
        fields: {csrfmiddlewaretoken: 'test-csrf', next: '/search/?q=copper'}}],
    });
  });

  test('acknowledged accounts can reopen help and Escape restores focus without another save', async t => {
    const {evaluate, key} = await page(t, {autoShow: false, dismissed: true});
    assert.equal(await evaluate('dialog.open'), false);
    await evaluate("document.querySelector('[data-open-quick-start]').focus(); document.activeElement.click()");
    assert.equal(await evaluate('dialog.open'), true);
    await key({type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await evaluate('flush()');
    assert.deepEqual(await evaluate(`({open: dialog.open, requests: requests.length,
      focusedHelp: document.activeElement.hasAttribute('data-open-quick-start')})`),
    {open: false, requests: 0, focusedHelp: true});
  });

  test('Escape acknowledges the automatic guide just like skip', async t => {
    const {evaluate, key} = await page(t);
    await key({type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await evaluate('flush()');
    assert.deepEqual(await evaluate('({open: dialog.open, requests: requests.length})'),
      {open: false, requests: 1});
  });

  test('a pending save prevents duplicate submissions and closes only after confirmation', async t => {
    const {evaluate} = await page(t);
    await evaluate(`window.fetchOverride = () => new Promise(resolve => window.finishSave = resolve);
      dialog.querySelector('[data-guide-dismiss]').click();
      dialog.querySelector('[data-guide-dismiss]').click();`);
    assert.deepEqual(await evaluate('({open: dialog.open, requests: requests.length})'),
      {open: true, requests: 1});
    await evaluate('finishSave(new Response(JSON.stringify({dismissed: true}))); flush()');
    assert.equal(await evaluate('dialog.open'), false);
  });

  test('failed saves stay visible with a retry and an exit that does not pretend to save', async t => {
    for (const failure of [
      'Promise.reject(new TypeError("Network unavailable"))',
      'Promise.resolve(new Response("Unavailable", {status: 503}))',
      'Promise.resolve(new Response("<html>Login</html>"))',
      'Promise.resolve(new Response(JSON.stringify({dismissed: false})))',
    ]) {
      const {evaluate} = await page(t);
      await evaluate(`window.fetchOverride = () => ${failure};
        dialog.querySelector('[data-guide-dismiss]').click(); flush()`);
      assert.deepEqual(await evaluate(`({open: dialog.open,
        error: !dialog.querySelector('[role="alert"]').hidden,
        retryEnabled: !dialog.querySelector('[data-guide-dismiss]').disabled})`),
      {open: true, error: true, retryEnabled: true});
      await evaluate("dialog.querySelector('[data-guide-close-unsaved]').click()");
      assert.deepEqual(await evaluate('({open: dialog.open, requests: requests.length})'),
        {open: false, requests: 1});
    }
  });

  test('a failed save can be retried successfully', async t => {
    const {evaluate} = await page(t);
    await evaluate(`window.fetchOverride = () => Promise.reject(new Error('offline'));
      dialog.querySelector('[data-guide-dismiss]').click(); flush()`);
    await evaluate(`window.fetchOverride = null;
      dialog.querySelector('[data-guide-dismiss]').click(); flush()`);
    assert.deepEqual(await evaluate('({open: dialog.open, requests: requests.length})'),
      {open: false, requests: 2});
  });

  test('mobile help keeps long content inside a scrollable dialog with reachable actions', async t => {
    const {evaluate} = await page(t, {width: 320});
    await evaluate(`dialog.querySelector('.quick-start-copy > span').textContent = 'LongMetadata'.repeat(50);
      dialog.querySelector('.quick-start-footer').scrollIntoView({block: 'end'});`);
    assert.deepEqual(await evaluate(`(() => {
      const bounds = dialog.getBoundingClientRect();
      const footer = dialog.querySelector('.quick-start-footer').getBoundingClientRect();
      return {inside: bounds.left >= 0 && bounds.right <= innerWidth,
        noHorizontalOverflow: dialog.scrollWidth <= dialog.clientWidth,
        actionsReachable: footer.bottom <= bounds.bottom && footer.top >= bounds.top};
    })()`), {inside: true, noHorizontalOverflow: true, actionsReachable: true});
  });
});
