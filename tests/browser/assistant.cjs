const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {mkdtempSync, rmSync, mkdirSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const {join} = require('node:path');

(async () => {
  const profile = mkdtempSync(join(tmpdir(), 'assistant-browser-'));
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
    const exceptions = [];
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
      for (let attempt = 0; attempt < 120; attempt++) {
        if (await evaluate(expression)) return;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error(`Timed out: ${expression}`);
    }
    async function navigate(path) {
      const url = process.env.ASSISTANT_BASE_URL + path;
      await command('Page.navigate', {url});
      await until(`location.href === ${JSON.stringify(url)} && document.readyState === 'complete' && !!document.querySelector('.fair-assistant-widget')`);
      await evaluate("document.querySelector('.fair-assistant-toggle').click()");
    }
    async function choose(label) {
      assert.ok(await evaluate(`!![...document.querySelectorAll('.fair-assistant-suggestion, .fair-assistant-browse')].find(button => button.textContent.trim() === ${JSON.stringify(label)})`), label);
      const count = await evaluate("document.querySelectorAll('.fair-assistant-message').length");
      await evaluate(`[...document.querySelectorAll('.fair-assistant-suggestion, .fair-assistant-browse')].find(button => button.textContent.trim() === ${JSON.stringify(label)}).click()`);
      await until(`document.querySelectorAll('.fair-assistant-message').length > ${count} && !document.querySelector('.fair-assistant-send').disabled`);
    }
    async function ask(question) {
      const count = await evaluate("document.querySelectorAll('.fair-assistant-message').length");
      await evaluate(`document.querySelector('.fair-assistant-input').value = ${JSON.stringify(question)}; document.querySelector('.fair-assistant-form').requestSubmit()`);
      await until(`document.querySelectorAll('.fair-assistant-message').length > ${count} && !document.querySelector('.fair-assistant-send').disabled`);
    }
    const lastAnswer = () => evaluate("[...document.querySelectorAll('.fair-assistant-message.assistant')].at(-1).textContent");
    async function layout(label) {
      for (const [width, height] of [[1280, 720], [1440, 900], [1920, 1080]]) {
        await command('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: false});
        const metrics = await evaluate(`(() => {
          const panel = document.querySelector('.fair-assistant-panel');
          const rect = panel.getBoundingClientRect();
          const send = document.querySelector('.fair-assistant-send').getBoundingClientRect();
          return {top: rect.top, bottom: rect.bottom, right: rect.right, width: rect.width,
            overflow: panel.scrollWidth - panel.clientWidth, sendBottom: send.bottom, sendTop: send.top};
        })()`);
        assert.ok(metrics.top >= 0 && metrics.bottom <= height && metrics.right <= width, `${label}: ${JSON.stringify(metrics)}`);
        assert.ok(metrics.overflow <= 1 && metrics.width <= 420 && metrics.sendTop >= metrics.top && metrics.sendBottom <= metrics.bottom,
          `${label}: ${JSON.stringify(metrics)}`);
        if (process.env.ASSISTANT_SCREENSHOT_DIR && width === 1440) {
          mkdirSync(process.env.ASSISTANT_SCREENSHOT_DIR, {recursive: true});
          const shot = await command('Page.captureScreenshot', {format: 'png'});
          writeFileSync(join(process.env.ASSISTANT_SCREENSHOT_DIR, label + '.png'), Buffer.from(shot.data, 'base64'));
        }
      }
    }
    await command('Runtime.enable');
    await command('Network.enable');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await command('Network.setCookie', {name: process.env.ASSISTANT_COOKIE_NAME, value: process.env.ASSISTANT_SESSION,
      url: process.env.ASSISTANT_BASE_URL, path: '/'});
    await command('Emulation.setDeviceMetricsOverride', {width: 1440, height: 900, deviceScaleFactor: 1, mobile: false});
    await navigate('/search/');
    await choose('Browse help topics');
    await layout('categories');
    await choose('Account help');
    await layout('account-topics');
    const firstAccountPage = await evaluate("[...document.querySelectorAll('.fair-assistant-suggestion')].map(button => button.textContent)");
    await ask('the sixth one');
    assert.match(await lastAnswer(), /public information/);
    await ask('Account help');
    await ask('more');
    assert.match(await lastAnswer(), /page 2 of/);
    await ask('back');
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.fair-assistant-suggestion')].map(button => button.textContent)"), firstAccountPage);
    const nextAccountPage = firstAccountPage.find(label => /^Account help \(2\//.test(label));
    assert.ok(nextAccountPage);
    await choose(nextAccountPage);
    await ask('the second one');
    assert.match(await lastAnswer(), /365-day session/);
    await ask('How do I recover a forgotten password?');
    assert.match(await lastAnswer(), /email password recovery is not available/);
    assert.ok(await evaluate("[...document.querySelectorAll('.fair-assistant-message.assistant')].at(-1).querySelector('a').pathname === '/settings/'"));
    await layout('account-answer');
    await choose('Browse help topics');
    await choose('Upload help');
    await choose('Why was my upload rejected?');
    assert.match(await lastAnswer(), /entire file/);
    assert.ok(await evaluate("[...document.querySelectorAll('.fair-assistant-message a')].some(link => link.pathname === '/upload/')"));
    await ask('data form');
    assert.match(await lastAnswer(), /JSON data format or the upload form/);
    await ask('format');
    assert.match(await lastAnswer(), /JSON object with named fields/);
    await ask('which fields?');
    assert.match(await lastAnswer(), /creator_affiliation/);
    await layout('required-fields');
    await ask('how big?');
    assert.match(await lastAnswer(), /100 MiB per file/);
    await ask('I want to erase my old simulations');
    assert.match(await lastAnswer(), /Only the owner can delete/);
    await ask('What is the weather?');
    assert.match(await lastAnswer(), /I can help with this data platform/);
    await ask('delete and download');
    assert.deepEqual(await evaluate("[...document.querySelectorAll('.fair-assistant-suggestion')].map(button => button.textContent)"),
      ['How do I download data?', 'How do I delete my data?']);
    await command('Network.setBlockedURLs', {urls: ['https://*', '*assistant/ask/*']});
    await ask('the second one');
    assert.match(await lastAnswer(), /could not be completed/i);
    assert.equal(await evaluate("document.querySelector('.fair-assistant-input').value"), 'the second one');
    await command('Network.setBlockedURLs', {urls: ['https://*']});
    await ask('the second one');
    assert.match(await lastAnswer(), /does not delete data/);
    await ask('How do identifiers work?');
    assert.match(await lastAnswer(), /automatically/);
    await choose('Browse help topics');
    await ask('the second one');
    assert.match(await lastAnswer(), /Choose a help topic first/);

    await navigate(process.env.ASSISTANT_DETAIL_PATH);
    await choose('Summarize');
    assert.match(await lastAnswer(), /assistant-browser-object/);
    assert.equal(await evaluate("!!window.assistantInjected || !!document.querySelector('.fair-assistant-message img')"), false);
    await layout('long-object');
    await command('Input.dispatchKeyEvent', {type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    assert.equal(await evaluate("document.querySelector('.fair-assistant-toggle').getAttribute('aria-expanded')"), 'false');
    await command('Network.setCookie', {name: process.env.ASSISTANT_COOKIE_NAME, value: process.env.ASSISTANT_EMPTY_SESSION,
      url: process.env.ASSISTANT_BASE_URL, path: '/'});
    await navigate(process.env.ASSISTANT_EMPTY_PATH);
    await choose('Browse help topics');
    assert.equal(await evaluate("document.querySelector('.fair-assistant-suggestions').textContent.includes('Current object help')"), false);
    await layout('empty-data');
    assert.deepEqual(exceptions, []);
    console.log('Assistant browser checks passed: categories, menu pagination, numbered choices, semantic questions, follow-ups, HTTP recovery, access context, safe text, keyboard and 18 desktop layouts.');
  } finally {
    if (socket) socket.close();
    browser.kill();
    await once(browser, 'exit').catch(() => {});
    rmSync(profile, {recursive: true, force: true});
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
