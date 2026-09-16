const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../static/assets/js/credential-validation.js'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));

class Element extends EventTarget {
  constructor() {
    super();
    this.attributes = new Map();
    this.children = [];
    this.textContent = '';
    this.hidden = false;
    this.selectors = {};
    const classes = new Set();
    this.classList = {
      add: name => classes.add(name),
      contains: name => classes.has(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
    };
  }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  querySelector(selector) { return this.selectors[selector] ?? null; }
  replaceChildren() { this.children = []; this.textContent = ''; }
  appendChild(child) { this.children.push(child); this.textContent += child.textContent; }
}

function harness({mode = 'register', ignoreAbort = false} = {}) {
  const form = new Element();
  const status = new Element();
  status.hidden = true;
  form.dataset = {credentialMode: mode, credentialValidation: '/accounts/validate-credentials/'};
  form.selectors = {
    '[data-credential-status]': status,
    '[name="csrfmiddlewaretoken"]': {value: 'csrf-token'},
    '[name="orcid"]': {value: 'private-orcid-id'},
    '[name="next"]': {value: '/private/redirect/'},
  };
  const fields = {};
  const groups = ['username', 'email', 'password1', 'password2'].map(name => {
    const group = new Element();
    const input = new Element();
    const errors = new Element();
    input.name = mode === 'orcid_setup' ? `orcid_setup-${name}` : name;
    input.value = '';
    errors.id = `${input.name}_errors`;
    group.dataset = {credentialField: name};
    group.selectors = {input, '[data-credential-errors]': errors};
    fields[name] = {input, errors};
    return group;
  });
  form.querySelectorAll = () => groups;
  const requests = [];
  const timers = new Map();
  let now = 0;
  let timerId = 0;
  vm.runInNewContext(source, {
    document: {querySelectorAll: () => [form], createElement: () => new Element()},
    window: new EventTarget(),
    URLSearchParams, AbortController,
    setTimeout: (callback, delay) => {
      timers.set(++timerId, {callback, time: now + delay});
      return timerId;
    },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => new Promise((resolve, reject) => {
      requests.push({url, options, resolve, reject});
      if (!ignoreAbort) options.signal.addEventListener('abort', () => reject(new Error('Aborted')));
    }),
  });
  return {
    form, status, fields, requests,
    input(name, value, event = 'input') {
      fields[name].input.value = value;
      fields[name].input.dispatchEvent(new Event(event));
    },
    async advance(milliseconds) {
      const end = now + milliseconds;
      while (true) {
        const next = [...timers].sort((a, b) => a[1].time - b[1].time)[0];
        if (!next || next[1].time > end) break;
        now = next[1].time;
        timers.delete(next[0]);
        next[1].callback();
        await flush();
      }
      now = end;
    },
    async reply(index, errors = {}) {
      const defaults = {username: [], email: [], password1: [], password2: []};
      requests[index].resolve({ok: true, json: async () => ({errors: {...defaults, ...errors}})});
      await flush();
    },
  };
}

test('typing coalesces into one request after the last edit', async () => {
  const page = harness();
  page.input('username', 'a');
  await page.advance(300);
  page.input('username', 'alice');
  await page.advance(499);
  assert.equal(page.requests.length, 0);
  await page.advance(1);
  assert.equal(page.requests.length, 1);
  assert.equal(page.requests[0].options.body.get('username'), 'alice');
  await page.reply(0);
});

test('untouched errors stay hidden and corrected feedback removes invalid state', async () => {
  const page = harness();
  page.input('username', 'taken', 'blur');
  await page.reply(0, {username: ['Already taken'], password1: ['Required']});
  assert.equal(page.fields.username.errors.textContent, 'Already taken');
  assert.equal(page.fields.username.input.getAttribute('aria-invalid'), 'true');
  assert.equal(page.fields.password1.errors.textContent, '');
  assert.equal(page.fields.password1.input.classList.contains('is-invalid'), false);
  page.input('username', 'available', 'blur');
  await page.reply(1);
  assert.equal(page.fields.username.errors.textContent, '');
  assert.equal(page.fields.username.input.getAttribute('aria-invalid'), null);
  assert.equal(page.fields.username.input.classList.contains('is-invalid'), false);
});

test('a stale response cannot overwrite feedback when fetch ignores abort', async () => {
  const page = harness({ignoreAbort: true});
  page.input('username', 'old', 'blur');
  page.input('username', 'new', 'blur');
  await page.reply(1);
  await page.reply(0, {username: ['Old error']});
  assert.equal(page.fields.username.errors.textContent, '');
  assert.equal(page.fields.username.input.getAttribute('aria-invalid'), null);
  assert.equal(page.status.hidden, true);
});

for (const failure of ['offline', 'invalid JSON', 'invalid schema', 'HTTP error', 'timeout']) {
  test(`${failure} shows fallback feedback without blocking normal submission`, async () => {
    const page = harness();
    page.input('username', 'alice', 'blur');
    const request = page.requests[0];
    if (failure === 'offline') request.reject(new Error('Offline'));
    if (failure === 'invalid JSON') request.resolve({ok: true, json: async () => { throw new SyntaxError(); }});
    if (failure === 'invalid schema') request.resolve({ok: true, json: async () => ({errors: {}})});
    if (failure === 'HTTP error') request.resolve({ok: false, status: 503});
    if (failure === 'timeout') await page.advance(10000);
    await flush();
    assert.equal(page.status.hidden, false);
    assert.match(page.status.textContent, /unavailable.*still submit/i);
    assert.equal(page.form.getAttribute('aria-busy'), null);
    assert.equal(page.form.dispatchEvent(new Event('submit', {cancelable: true})), true);
    page.input('username', 'corrected', 'blur');
    await page.reply(1);
    assert.equal(page.status.hidden, true);
    assert.equal(page.status.textContent, '');
  });
}

for (const mode of ['register', 'orcid_setup']) {
  test(`${mode} posts only logical credential names with no credentials in URL or headers`, async () => {
    const page = harness({mode});
    page.fields.email.input.value = 'alice@example.test';
    page.fields.password1.input.value = 'S3cret+Password!';
    page.fields.password2.input.value = 'S3cret+Password!';
    page.input('username', 'alice', 'blur');
    const {url, options} = page.requests[0];
    assert.equal(url, '/accounts/validate-credentials/');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.cache, 'no-store');
    assert.equal(JSON.stringify(options.headers), '{"Accept":"application/json"}');
    assert.deepEqual(Object.fromEntries(options.body), {
      mode, csrfmiddlewaretoken: 'csrf-token', username: 'alice',
      email: 'alice@example.test', password1: 'S3cret+Password!', password2: 'S3cret+Password!',
    });
    await page.reply(0, {username: ['Unavailable']});
    assert.equal(page.fields.username.errors.textContent, 'Unavailable');
  });
}

test('normal submission cancels a pending debounce without preventing the submit event', async () => {
  const page = harness();
  page.input('username', 'alice');
  assert.equal(page.form.dispatchEvent(new Event('submit', {cancelable: true})), true);
  await page.advance(10000);
  assert.equal(page.requests.length, 0);
});
