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

function sidebarHTML() {
  return readFileSync(join(root, 'templates/includes/sidebar.html'), 'utf8')
    .replace(/{% if request.user.is_superuser %}[\s\S]*?{% endif %}/, '')
    .replace(/{% if not request.user.is_authenticated %}[\s\S]*?{% else %}/, '')
    .replace(/{% url '([^']+)' %}/g, (_match, route) => `/${route}/`)
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

  async function page(t, {autoShow = true, dismissed = false, width = 1440, height = 800, sidebar = true} = {}) {
    const {targetId} = await send('Target.createTarget', {url: 'about:blank'});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    await send('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor: 1, mobile: false,
    }, sessionId);
    const evaluate = async expression => {
      const response = await send('Runtime.evaluate', {
        expression, returnByValue: true, awaitPromise: true,
      }, sessionId);
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
      return response.result.value;
    };
    const html = '<a href="/getting-started/" data-open-quick-start>Quick start</a>'
      + '<input id="background-search" value="copper">' + (sidebar ? sidebarHTML() : '')
      + dialogHTML(autoShow, dismissed);
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
    return {
      evaluate,
      key: params => send('Input.dispatchKeyEvent', params, sessionId),
      resize: (width, height) => send('Emulation.setDeviceMetricsOverride', {
        width, height, deviceScaleFactor: 1, mobile: false,
      }, sessionId),
    };
  }

  test('first display focuses the dialog without saving before an acknowledgement', async t => {
    const {evaluate, key} = await page(t);
    assert.deepEqual(await evaluate(`({open: dialog.open, focusInside: dialog.contains(document.activeElement),
      requests: requests.length, locked: document.body.classList.contains('quick-start-open')})`),
    {open: true, focusInside: true, requests: 0, locked: true});
    await key({type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
    assert.equal(await evaluate('dialog.contains(document.activeElement)'), true);
  });

  test('Next walks through the four sidebar tools without navigation or early acknowledgement', async t => {
    const {evaluate} = await page(t);
    assert.equal(await evaluate("!!dialog.querySelector('[data-guide-next]')"), true);
    const originalURL = await evaluate('location.href');
    for (const title of ['Search', 'Upload Data', 'My Data', 'Share']) {
      await evaluate("dialog.querySelector('[data-guide-next]').click(); flush()");
      assert.deepEqual(await evaluate(`({title: dialog.querySelector('h2').textContent,
        url: location.href, requests: requests.length, open: dialog.open})`),
      {title, url: originalURL, requests: 0, open: true});
    }
    assert.equal(await evaluate("dialog.querySelector('[data-guide-next]').hidden"), true);
    await evaluate("dialog.querySelector('[data-guide-finish]').click(); flush()");
    assert.deepEqual(await evaluate('({open: dialog.open, url: location.href, requests: requests.length})'),
      {open: false, url: originalURL, requests: 1});
  });

  test('each desktop step highlights its real sidebar button and points the arrow at it', async t => {
    const {evaluate} = await page(t);
    for (const target of ['search', 'upload', 'my-data', 'share']) {
      await evaluate("dialog.querySelector('[data-guide-next]').click(); flush()");
      const state = await evaluate(`(() => {
        const target = document.querySelector('.pc-sidebar .quick-start-target');
        const r = target.getBoundingClientRect();
        const card = dialog.querySelector('.quick-start-card').getBoundingClientRect();
        const arrow = dialog.querySelector('.quick-start-pointer').getBoundingClientRect();
        const spot = dialog.querySelector('.quick-start-spotlight').getBoundingClientRect();
        return {target: target.dataset.tourTarget,
          beside: card.left > r.right && card.right <= innerWidth,
          aligned: Math.abs(arrow.y + arrow.height / 2 - r.y - r.height / 2) < 1,
          highlighted: Math.abs(spot.top - r.top - 2) < 1 && Math.abs(spot.height - r.height + 4) < 1,
          arrowVisible: !dialog.querySelector('.quick-start-pointer').hidden};
      })()`);
      assert.deepEqual(state, {target, beside: true, aligned: true, highlighted: true, arrowVisible: true});
    }
  });

  test('Back revisits the previous step and reopening always begins at welcome', async t => {
    const {evaluate} = await page(t, {autoShow: false, dismissed: true});
    await evaluate("document.querySelector('[data-open-quick-start]').click()");
    await evaluate("dialog.querySelector('[data-guide-next]').click(); dialog.querySelector('[data-guide-next]').click()");
    await evaluate("dialog.querySelector('[data-guide-back]').click()");
    assert.equal(await evaluate('dialog.dataset.step'), 'search');
    await evaluate("dialog.querySelector('[data-guide-back]').click()");
    assert.deepEqual(await evaluate(`({step: dialog.dataset.step,
      noHighlight: !document.querySelector('.quick-start-target'),
      backHidden: dialog.querySelector('[data-guide-back]').hidden})`),
    {step: 'welcome', noHighlight: true, backHidden: true});
    await evaluate("dialog.querySelector('[data-guide-next]').click(); dialog.querySelector('[data-guide-dismiss]').click()");
    await evaluate("document.querySelector('[data-open-quick-start]').click()");
    assert.equal(await evaluate('dialog.dataset.step'), 'welcome');
  });

  test('keyboard focus moves to Finish when Next disappears on the last step', async t => {
    const {evaluate} = await page(t);
    await evaluate(`dialog.querySelector('[data-guide-next]').focus();
      for (let i = 0; i < 4; i++) dialog.querySelector('[data-guide-next]').click();`);
    assert.equal(await evaluate("document.activeElement.hasAttribute('data-guide-finish')"), true);
  });

  test('collapsed menus are temporarily revealed and keep their original state after skipping', async t => {
    const {evaluate} = await page(t, {autoShow: false, dismissed: true});
    await evaluate(`document.querySelector('.pc-sidebar').classList.add('pc-sidebar-hide');
      document.querySelector('[data-open-quick-start]').click();
      dialog.querySelector('[data-guide-next]').click();`);
    assert.equal(await evaluate("document.querySelector('.quick-start-target').getBoundingClientRect().right > 0"), true);
    await evaluate("dialog.querySelector('[data-guide-dismiss]').click()");
    assert.deepEqual(await evaluate(`({collapsed: document.querySelector('.pc-sidebar').classList.contains('pc-sidebar-hide'),
      temporary: !!document.querySelector('.quick-start-sidebar'), highlighted: !!document.querySelector('.quick-start-target')})`),
    {collapsed: true, temporary: false, highlighted: false});
  });

  test('mobile steps reveal the menu and keep the arrow and card clear of their target', async t => {
    for (const [width, height] of [[320, 568], [390, 844], [640, 360]]) {
      const {evaluate} = await page(t, {width, height, dismissed: true});
      for (let step = 1; step <= 4; step++) {
        await evaluate("dialog.querySelector('[data-guide-next]').click(); flush()");
        assert.deepEqual(await evaluate(`(() => {
          const t = document.querySelector('.quick-start-target').getBoundingClientRect();
          const c = dialog.querySelector('.quick-start-card').getBoundingClientRect();
          const p = dialog.querySelector('.quick-start-pointer').getBoundingClientRect();
          return {targetVisible: t.left >= 0 && t.right <= innerWidth && t.top >= 0 && t.bottom <= innerHeight,
            cardVisible: c.left >= 0 && c.right <= innerWidth && c.top >= 0 && c.bottom <= innerHeight,
            noOverlap: c.top >= t.bottom || c.bottom <= t.top || c.left >= t.right,
            arrowAligned: Math.abs(p.left + p.width / 2 - t.left - t.width / 2) < 1};
        })()`), {targetVisible: true, cardVisible: true, noOverlap: true, arrowAligned: true}, `${width}px step ${step}`);
      }
      await evaluate("dialog.querySelector('[data-guide-finish]').click()");
      assert.equal(await evaluate("document.querySelector('.pc-sidebar').classList.contains('quick-start-sidebar')"), false);
    }
  });

  test('resizing an active desktop step reanchors it to the visible mobile menu', async t => {
    const {evaluate, resize} = await page(t);
    await evaluate("dialog.querySelector('[data-guide-next]').click()");
    await resize(320, 568);
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    assert.deepEqual(await evaluate(`({step: dialog.dataset.step,
      placement: dialog.querySelector('.quick-start-card').dataset.placement,
      visible: document.querySelector('.quick-start-target').getBoundingClientRect().left >= 0})`),
    {step: 'search', placement: 'bottom', visible: true});
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
    await evaluate(`dialog.querySelector('[data-guide-next]').click();
      dialog.querySelector('.quick-start-intro').textContent = 'LongMetadata'.repeat(50);`);
    await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
    await evaluate("dialog.querySelector('.quick-start-footer').scrollIntoView({block: 'end'})");
    assert.deepEqual(await evaluate(`(() => {
      const card = dialog.querySelector('.quick-start-card');
      const form = dialog.querySelector('form');
      const bounds = card.getBoundingClientRect();
      const footer = dialog.querySelector('.quick-start-footer').getBoundingClientRect();
      return {inside: bounds.left >= 0 && bounds.right <= innerWidth,
        noHorizontalOverflow: form.scrollWidth <= form.clientWidth,
        actionsReachable: footer.bottom <= bounds.bottom && footer.top >= bounds.top};
    })()`), {inside: true, noHorizontalOverflow: true, actionsReachable: true});
  });

  test('a missing menu leaves the introduction readable and skippable', async t => {
    const {evaluate} = await page(t, {sidebar: false});
    await evaluate("dialog.querySelector('[data-guide-next]').click()");
    assert.deepEqual(await evaluate(`({title: dialog.querySelector('h2').textContent,
      placement: dialog.querySelector('.quick-start-card').dataset.placement,
      arrowHidden: dialog.querySelector('.quick-start-pointer').hidden})`),
    {title: 'Search', placement: 'center', arrowHidden: true});
    await evaluate("dialog.querySelector('[data-guide-dismiss]').click(); flush()");
    assert.equal(await evaluate('dialog.open'), false);
  });
});
