const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const profile = mkdtempSync(join(tmpdir(), 'recovery-browser-'));
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
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
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
      for (let attempt = 0; attempt < 150; attempt++) {
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out waiting for ${expression}`);
    }
    async function click(selector) {
      const point = await evaluate(`(() => {
        const element = document.querySelector(${JSON.stringify(selector)});
        if (!element) throw new Error('Missing click target');
        element.scrollIntoView({block: 'center', behavior: 'instant'});
        const rect = element.getBoundingClientRect();
        return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
      })()`);
      await command('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
      await command('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
    }
    async function fill(selector, value) {
      await evaluate(`document.querySelector(${JSON.stringify(selector)}).value = ${JSON.stringify(value)}`);
    }
    async function checkLayout(label) {
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, `${label}: page overflow`);
      assert.equal(await evaluate('[...document.images].every(image => image.complete && image.naturalWidth > 0)'), true, `${label}: image loading`);
      assert.equal(await evaluate(`(() => {
        const rect = document.querySelector('.card').getBoundingClientRect();
        return rect.left >= 0 && rect.right <= innerWidth;
      })()`), true, `${label}: card bounds`);
      if (process.env.RESET_SCREENSHOT_DIR) {
        mkdirSync(process.env.RESET_SCREENSHOT_DIR, {recursive: true});
        const screenshot = await command('Page.captureScreenshot', {format: 'png'});
        writeFileSync(join(process.env.RESET_SCREENSHOT_DIR, `${label}.png`), Buffer.from(screenshot.data, 'base64'));
      }
    }
    const base = process.env.RESET_BASE_URL;
    await command('Page.enable');
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    for (const item of JSON.parse(process.env.RESET_CASES)) {
      await command('Network.clearBrowserCookies');
      await command('Emulation.setDeviceMetricsOverride', {width: item.width, height: 900, deviceScaleFactor: 1, mobile: false});
      await command('Emulation.setScriptExecutionDisabled', {value: !item.javascript});
      await command('Page.navigate', {url: base + '/login/'});
      await until("location.pathname === '/login/' && document.readyState === 'complete'");
      await click('a[href="/accounts/password-reset/"]');
      await until("location.pathname === '/accounts/password-reset/' && document.readyState === 'complete'");
      await checkLayout(`request-${item.width}`);
      await fill('#id_email', 'not-an-email');
      await click('button[type="submit"]');
      await until("!!document.querySelector('#id_email_error')");
      const beforeMail = new Set(readdirSync(process.env.RESET_MAIL_DIR));
      await fill('#id_email', item.email);
      await click('button[type="submit"]');
      await until("location.pathname === '/accounts/password-reset-done/' && document.readyState === 'complete'");
      await checkLayout(`acknowledged-${item.width}`);
      const files = readdirSync(process.env.RESET_MAIL_DIR).filter(name => !beforeMail.has(name));
      assert.equal(files.length, 1, 'One actual test email was generated');
      const body = readFileSync(join(process.env.RESET_MAIL_DIR, files[0]), 'utf8');
      assert.ok(body.includes(item.username));
      const link = body.match(/https?:\/\/[^\s]+\/accounts\/password-reset-confirm\/[^\s]+/)[0];
      assert.equal(new URL(link).origin, base);
      await command('Page.navigate', {url: link});
      await until("location.pathname.endsWith('/set-password/') && !!document.querySelector('#id_new_password1') && document.readyState === 'complete'");
      await checkLayout(`new-password-${item.width}`);
      await fill('#id_new_password1', 'short');
      await fill('#id_new_password2', 'short');
      await click('button[type="submit"]');
      await until("!!document.querySelector('.errorlist')");
      await checkLayout(`password-errors-${item.width}`);
      await fill('#id_new_password1', 'Copper!Meadow58Orchard');
      await fill('#id_new_password2', 'Copper!Meadow58Orchard');
      await click('button[type="submit"]');
      await until("location.pathname === '/accounts/password-reset-complete/' && document.readyState === 'complete'");
      await checkLayout(`complete-${item.width}`);
      await command('Page.navigate', {url: link});
      await until("document.querySelector('h1')?.textContent.includes('invalid') && document.readyState === 'complete'");
      await checkLayout(`used-link-${item.width}`);
      await click('a[href="/accounts/login/"]');
      await until("location.pathname === '/accounts/login/' && !!document.querySelector('#id_username')");
      await fill('#id_username', item.username);
      await fill('#id_password', 'OriginalQuartz!47River');
      await click('button[type="submit"]');
      await until("!!document.querySelector('.text-danger') && document.readyState === 'complete'");
      await fill('#id_password', 'Copper!Meadow58Orchard');
      await click('button[type="submit"]');
      await until("location.pathname === '/search/' && document.readyState === 'complete'");
      console.log(`${item.width}px, JavaScript ${item.javascript ? 'enabled' : 'disabled'}: recovery email, validation, password update, token reuse and login passed`);
    }
  } finally {
    socket?.close();
    browser.kill();
    await once(browser, 'exit').catch(() => {});
    rmSync(profile, {recursive: true, force: true});
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
