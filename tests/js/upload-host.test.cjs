const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {existsSync, mkdtempSync, readFileSync, rmSync} = require('node:fs');
const {createServer} = require('node:http');
const {tmpdir} = require('node:os');
const {join} = require('node:path');
const {after, before, describe, test} = require('node:test');

const root = join(__dirname, '../..');
const chromium = process.env.CHROMIUM_BIN || '/usr/bin/chromium';

describe('uploads across ordinary page navigation', {skip: !existsSync(chromium), timeout: 30000}, () => {
  let browser, directory, socket, server, origin, job;
  let postCount = 0;
  let receivedBytes = 0;
  let postMode = 'accepted';
  let expired = false;
  let postDelay = 600;
  let nativePostCount = 0;
  let legacyStreamPosts = 0;
  const dialogs = [];
  let nextId = 0;
  const pending = new Map();

  function send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++nextId;
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params, sessionId}));
    });
  }

  function snapshot(status = 'processing') {
    return {
      id: '12af1129-50bb-4b1a-8a9e-a1f822f5e8a1', status,
      files: [{name: 'sample.json', status: status === 'completed' ? 'uploaded' : 'validating',
        validated_count: status === 'completed' ? 100 : 37, object_count: 100,
        saved_count: status === 'completed' ? 100 : 0}],
      summary: status === 'completed' ? '100 data objects saved.' : '',
      level: status === 'completed' ? 'success' : 'info', report_html: '',
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
    };
  }

  function html(path) {
    let content = `<h1>${path}</h1><form id="search-form" method="get" action="/search/"><input name="q" value="steel"><button>Search</button></form>`;
    if (path === '/upload/') {
      const template = readFileSync(join(root, 'templates/pages/upload.html'), 'utf8');
      content = template.match(/<form id="uploadForm"[\s\S]*?<\/form>/)[0]
        .replace(/{%[\s\S]*?%}|{{[\s\S]*?}}/g, '')
        .replace(/data-jobs-url="[^"]*"/, '')
        .replace('id="uploadForm"', 'id="uploadForm" data-jobs-url="/upload/jobs/"');
      content += '<div id="upload-results"></div><script src="/upload.js"></script>';
    }
    return `<!doctype html><html><head><title>${path}</title></head><body>
      <nav><a id="search-link" href="/search/">Search</a><a id="data-link" href="/data-list/">My Data</a><a id="upload-link" href="/upload/">Upload</a></nav>
      ${content}<script src="/upload-host.js" data-jobs-url="/upload/jobs/" data-upload-url="/upload/"></script>
      <script>document.addEventListener('DOMContentLoaded',()=>{window.pageInitializations=(window.pageInitializations||0)+1;});</script>
    </body></html>`;
  }

  before(async () => {
    server = createServer((request, response) => {
      const url = new URL(request.url, 'http://localhost');
      if (url.pathname === '/upload.js' || url.pathname === '/upload-host.js') {
        const file = join(root, 'static/assets/js', url.pathname.slice(1));
        response.setHeader('Content-Type', 'text/javascript');
        response.end(existsSync(file) ? readFileSync(file) : '');
      } else if (url.pathname.startsWith('/upload/jobs/')) {
        if (expired) {
          response.writeHead(302, {Location: `/login/?next=${encodeURIComponent(url.pathname)}`});
          response.end();
          return;
        }
        response.setHeader('Content-Type', 'application/json');
        response.setHeader('Cache-Control', 'no-store');
        if (request.method === 'POST') {
          postCount += 1;
          let body = '';
          request.on('data', chunk => { receivedBytes += chunk.length; body += chunk.toString(); });
          request.on('end', () => {
            setTimeout(() => {
              if (postMode === 'disconnect-old') {
                response.writeHead(202);
                response.write('{"job":');
                setTimeout(() => response.destroy(), 10);
                return;
              }
              job = snapshot();
              job.submission_id = body.match(/name="submission_id"\r\n\r\n([^\r]+)/)?.[1];
              if (postMode === 'disconnect-saved') {
                response.writeHead(202);
                response.write('{"job":');
                setTimeout(() => response.destroy(), 10);
                return;
              }
              response.writeHead(202);
              response.end(JSON.stringify({job}));
            }, postDelay);
          });
        } else response.end(JSON.stringify({job}));
      } else if (url.pathname === '/upload/' && request.method === 'POST') {
        request.resume();
        if (request.headers.accept === 'application/x-ndjson') {
          legacyStreamPosts += 1;
          response.setHeader('Content-Type', 'application/x-ndjson');
          response.end([
            {type: 'file_start', index: 0},
            {type: 'file_result', index: 0, status: 'uploaded', saved_count: 1},
            {type: 'complete', summary: 'Legacy upload finished.', level: 'success', report_html: ''},
          ].map(event => JSON.stringify(event) + '\n').join(''));
        } else {
          nativePostCount += 1;
          response.setHeader('Content-Type', 'text/html');
          response.end('<!doctype html><p id="native-result">Native upload finished.</p>');
        }
      } else if (url.pathname === '/login/') {
        response.setHeader('Content-Type', 'text/html');
        response.setHeader('X-Frame-Options', 'DENY');
        response.end('<!doctype html><h1>Sign in</h1>');
      } else {
        response.setHeader('Content-Type', 'text/html');
        response.setHeader('X-Frame-Options', 'SAMEORIGIN');
        response.end(html(url.pathname));
      }
    });
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    origin = `http://127.0.0.1:${server.address().port}`;
    directory = mkdtempSync(join(tmpdir(), 'upload-host-'));
    browser = spawn(chromium, ['--headless', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
      '--remote-debugging-port=0', `--user-data-dir=${directory}`, 'about:blank'], {stdio: ['ignore', 'ignore', 'pipe']});
    const address = await new Promise((resolve, reject) => {
      let output = '';
      browser.on('error', reject);
      browser.stderr.on('data', chunk => {
        output += chunk;
        const match = output.match(/DevTools listening on (ws:\/\/\S+)/);
        if (match) resolve(match[1]);
      });
    });
    socket = new WebSocket(address);
    await once(socket, 'open');
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.method === 'Page.javascriptDialogOpening') dialogs.push(message);
      const entry = pending.get(message.id);
      if (!entry) return;
      pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message));
      else entry.resolve(message.result);
    });
  });

  after(async () => {
    socket?.close();
    if (browser && browser.exitCode === null) {
      const exited = once(browser, 'exit');
      browser.kill('SIGTERM');
      await exited;
    }
    server?.closeAllConnections();
    if (server) await new Promise(resolve => server.close(resolve));
    if (directory) rmSync(directory, {recursive: true, force: true});
  });

  async function page(t, pathname = '/upload/') {
    const {targetId} = await send('Target.createTarget', {url: `${origin}${pathname}`});
    const {sessionId} = await send('Target.attachToTarget', {targetId, flatten: true});
    t.after(() => send('Target.closeTarget', {targetId}));
    const evaluate = async expression => {
      const result = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true}, sessionId);
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
      return result.result.value;
    };
    evaluate.command = (method, params) => send(method, params, sessionId);
    await evaluate.command('Page.enable');
    await waitFor(evaluate, `location.pathname === ${JSON.stringify(pathname)} && document.readyState === "complete"`);
    return evaluate;
  }

  async function waitFor(evaluate, expression) {
    const deadline = Date.now() + 6000;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) return;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    assert.fail(`Timed out: ${expression}`);
  }

  test('real multipart transfer survives sidebar navigation and full child page scripts', async t => {
    job = null; postCount = 0; receivedBytes = 0; postMode = 'accepted';
    const evaluate = await page(t);
    assert.equal(await evaluate('typeof window.FairUploadHost'), 'object');
    await evaluate(`(() => {
      const files = new DataTransfer();
      files.items.add(new File(['x'.repeat(512 * 1024)], 'sample.json'));
      const input = document.getElementById('file-input');
      input.files = files.files; input.dispatchEvent(new Event('change'));
      uploadButton.click(); uploadButton.click(); document.getElementById('search-link').click();
    })()`);
    await waitFor(evaluate, `document.querySelector('#upload-page-frame')?.contentWindow.pageInitializations === 1`);
    assert.equal(await evaluate('location.pathname'), '/search/');
    assert.equal(await evaluate('!!document.getElementById("uploadForm")'), true);
    assert.equal(await evaluate('document.getElementById("uploadForm").inert'), true);
    await evaluate(`document.querySelector('#upload-page-frame').contentDocument.querySelector('#search-form button').click()`);
    await waitFor(evaluate, 'location.search === "?q=steel"');
    await waitFor(evaluate, `document.querySelector('#upload-page-frame')?.contentWindow.location.search === '?q=steel' && document.querySelector('#upload-page-frame').contentWindow.pageInitializations === 1`);
    await evaluate(`document.querySelector('#upload-page-frame').contentDocument.getElementById('data-link').click()`);
    await waitFor(evaluate, 'location.pathname === "/data-list/"');
    await waitFor(evaluate, `document.querySelector('#upload-page-frame')?.contentWindow.location.pathname === '/data-list/' && document.querySelector('#upload-page-frame').contentWindow.pageInitializations === 1`);
    assert.equal(await evaluate(`document.querySelector('#upload-page-frame').contentWindow.pageInitializations`), 1);
    await evaluate('history.back()');
    await waitFor(evaluate, `location.pathname === '/search/' && location.search === '?q=steel' && document.querySelector('#upload-page-frame')?.contentWindow.location.search === '?q=steel'`);
    await waitFor(evaluate, 'window.FairUploadHost.getState().job?.status === "processing"');
    assert.equal(postCount, 1);
    assert.ok(receivedBytes >= 512 * 1024);
    assert.ok(await evaluate('window.FairUploadHost.getState().loaded > 0 && window.FairUploadHost.getState().total > 0'));
    await evaluate(`(() => {
      const job = structuredClone(FairUploadHost.getState().job);
      job.files[0].name = 'long'.repeat(150) + '.json'; FairUploadHost.accept(job);
    })()`);
    assert.ok(await evaluate(`document.getElementById('upload-global-status').getBoundingClientRect().height > 44`));
    assert.ok(await evaluate(`document.querySelector('#upload-page-frame').getBoundingClientRect().bottom <= innerHeight + 1`));
    await evaluate(`document.querySelector('#upload-page-frame').contentDocument.getElementById('upload-link').click()`);
    await waitFor(evaluate, 'location.pathname === "/upload/"');
    assert.equal(await evaluate('!!document.querySelector("#upload-page-frame")'), false);
    assert.equal(await evaluate('document.getElementById("uploadForm").inert'), false);
    assert.match(await evaluate('uploadStatus.textContent'), /37.*100/);
    assert.equal(await evaluate('uploadButton.disabled'), true);
    await evaluate(`window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}))`);
    assert.match(await evaluate('document.querySelector(".selected-file-status").textContent'), /37.*100/);
    job = {...snapshot('completed'), submission_id: job.submission_id};
    await waitFor(evaluate, 'document.getElementById("upload-results").textContent.includes("100 data objects saved")');
  });

  test('a fresh page recovers an owned server task without local storage', async t => {
    job = snapshot();
    const evaluate = await page(t, '/search/');
    await waitFor(evaluate, 'window.FairUploadHost?.getState().job?.status === "processing"');
    assert.match(await evaluate('document.getElementById("upload-global-status").textContent'), /37.*100/);
    assert.equal(await evaluate('localStorage.length'), 0);
    assert.equal(await evaluate('sessionStorage.length'), 0);
    await evaluate('document.getElementById("upload-link").click()');
    await waitFor(evaluate, 'location.pathname === "/upload/" && !!document.getElementById("uploadForm")');
    assert.equal(await evaluate('window === window.top && !document.querySelector("iframe")'), true);
  });

  for (const mode of ['disconnect-saved', 'disconnect-old']) {
    test(`a lost POST response checks the submission identity (${mode})`, async t => {
      job = null; postCount = 0; postMode = mode;
      const evaluate = await page(t);
      await evaluate(`(() => {
        const files = new DataTransfer(); files.items.add(new File(['{}'], 'sample.json'));
        const input = document.getElementById('file-input'); input.files = files.files;
        input.dispatchEvent(new Event('change')); uploadButton.click();
      })()`);
      if (mode === 'disconnect-old') {
        job = {...snapshot('completed'), submission_id: 'older-submission'};
        await waitFor(evaluate, 'document.querySelector(".selected-file-status").textContent === "Unconfirmed"');
        assert.equal(await evaluate('document.getElementById("upload-results").textContent'), '');
        assert.equal(await evaluate('window.FairUploadHost.getState().job'), null);
      } else {
        await waitFor(evaluate, 'window.FairUploadHost.getState().job?.status === "processing"');
        assert.match(await evaluate('uploadStatus.textContent'), /37.*100/);
      }
      assert.equal(postCount, 1);
    });
  }

  test('expired authentication clears the old task and returns through the upload page', async t => {
    job = snapshot();
    const evaluate = await page(t, '/search/');
    await waitFor(evaluate, 'window.FairUploadHost?.getState().job?.status === "processing"');
    expired = true;
    t.after(() => { expired = false; });
    await waitFor(evaluate, 'location.pathname === "/login/"');
    assert.equal(await evaluate('new URLSearchParams(location.search).get("next")'), '/upload/');
    assert.equal(await evaluate('document.body.textContent.includes("sample.json")'), false);
  });

  test('removing a new selection does not revive a previous completed task on resize', async t => {
    job = snapshot('completed');
    const evaluate = await page(t);
    await waitFor(evaluate, 'document.getElementById("upload-results").textContent.includes("100 data objects saved")');
    const state = await evaluate(`(() => {
      window.pageErrors=[]; window.addEventListener('error', event => pageErrors.push(event.message));
      const files=new DataTransfer(); files.items.add(new File(['{}'],'new.json'));
      const input=document.getElementById('file-input'); input.files=files.files;
      input.dispatchEvent(new Event('change'));
      document.getElementById('remove-file').click(); window.dispatchEvent(new Event('resize'));
      return {errors:pageErrors,rows:document.querySelectorAll('.selected-file-row').length,hidden:uploadStatus.hidden};
    })()`);
    assert.deepEqual(state,{errors:[],rows:0,hidden:true});
  });

  test('Back past the upload document warns before interrupting an unconfirmed transfer', async t => {
    job = null; postMode = 'accepted'; postDelay = 2000;
    t.after(() => { postDelay = 600; });
    const evaluate = await page(t, '/search/');
    await evaluate.command('Page.navigate', {url: `${origin}/upload/`});
    await waitFor(evaluate, 'location.pathname === "/upload/" && document.readyState === "complete"');
    const point = await evaluate(`(() => {
      const files = new DataTransfer(); files.items.add(new File(['{}'], 'sample.json'));
      const input = document.getElementById('file-input'); input.files = files.files;
      input.dispatchEvent(new Event('change'));
      const rect = uploadButton.getBoundingClientRect(); return {x:rect.x+rect.width/2,y:rect.y+rect.height/2};
    })()`);
    await evaluate.command('Input.dispatchMouseEvent', {type: 'mousePressed', button: 'left', clickCount: 1, ...point});
    await evaluate.command('Input.dispatchMouseEvent', {type: 'mouseReleased', button: 'left', clickCount: 1, ...point});
    await evaluate('document.getElementById("search-link").click()');
    await waitFor(evaluate, `document.querySelector('#upload-page-frame')?.contentWindow.pageInitializations === 1`);
    await evaluate('history.back()');
    await waitFor(evaluate, 'location.pathname === "/upload/" && !document.querySelector("iframe")');
    dialogs.length = 0;
    await evaluate('history.back()');
    const deadline = Date.now() + 1500;
    while (!dialogs.length && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 15));
    assert.equal(dialogs[0]?.params.type, 'beforeunload');
    await evaluate.command('Page.handleJavaScriptDialog', {accept: false});
    assert.equal(await evaluate('location.pathname'), '/upload/');
  });

  for (const missing of ['fetch', 'crypto']) {
    test(`a configured jobs page keeps its existing fallback without ${missing}`, async t => {
      job = null; postCount = 0; nativePostCount = 0; legacyStreamPosts = 0;
      const evaluate = await page(t, '/search/');
      const source = missing === 'fetch' ? 'window.fetch = undefined'
        : 'Object.defineProperty(window.crypto,"getRandomValues",{value:undefined})';
      await evaluate.command('Page.addScriptToEvaluateOnNewDocument', {source});
      await evaluate.command('Page.navigate', {url: `${origin}/upload/`});
      await waitFor(evaluate, 'location.pathname === "/upload/" && document.readyState === "complete"');
      assert.equal(await evaluate('typeof window.FairUploadHost'), 'undefined');
      await evaluate(`(() => {
        const files=new DataTransfer(); files.items.add(new File(['{}'],'sample.json'));
        const input=document.getElementById('file-input'); input.files=files.files;
        input.dispatchEvent(new Event('change')); uploadButton.click();
      })()`);
      if (missing === 'fetch') {
        await waitFor(evaluate, '!!document.getElementById("native-result")');
        assert.equal(nativePostCount, 1);
      } else {
        await waitFor(evaluate, 'document.getElementById("upload-results").textContent.includes("Legacy upload finished")');
        assert.equal(legacyStreamPosts, 1);
      }
      assert.equal(postCount, 0);
    });
  }
});
