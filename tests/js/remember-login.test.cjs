const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const scriptPath = join(__dirname, '../../static/assets/js/remember-login.js');
const source = readFileSync(scriptPath, 'utf8');

function harness(checked = false) {
  const checkbox = new EventTarget();
  checkbox.checked = checked;
  checkbox.name = 'remember_me';
  const link = new EventTarget();
  link.href = 'https://materials.example/login/orcid/?next=%2Fsearch%2F%3Fq%3Dsteel';
  const fields = {
    id_remember_me: checkbox,
    'orcid-login-link': link,
    id_username: {value: 'private-username'},
    id_password: {value: 'private-password'},
  };
  const window = new EventTarget();
  vm.runInNewContext(source, {
    document: {getElementById: id => fields[id]},
    window,
    URL,
  });
  return {checkbox, link, window};
}

test('checking remember updates the ORCID link before it can open in another tab', () => {
  const page = harness();
  page.checkbox.checked = true;
  page.checkbox.dispatchEvent(new Event('change'));

  const url = new URL(page.link.href);
  assert.equal(url.searchParams.get('remember_me'), 'on');
  assert.equal(url.searchParams.get('next'), '/search/?q=steel');
  assert.equal(url.pathname, '/login/orcid/');
});

test('unchecking removes a previously selected remember choice', () => {
  const page = harness(true);
  assert.equal(new URL(page.link.href).searchParams.get('remember_me'), 'on');
  page.checkbox.checked = false;
  page.checkbox.dispatchEvent(new Event('change'));

  assert.equal(new URL(page.link.href).searchParams.has('remember_me'), false);
});

test('initial and history restored choices update the ORCID link', () => {
  const page = harness(true);
  assert.equal(new URL(page.link.href).searchParams.get('remember_me'), 'on');
  page.checkbox.checked = false;
  page.window.dispatchEvent(new Event('pageshow'));
  assert.equal(new URL(page.link.href).searchParams.has('remember_me'), false);
});

test('the link exposes only next and remember choice, never password form fields', () => {
  const page = harness(true);

  assert.deepEqual(Object.fromEntries(new URL(page.link.href).searchParams), {
    next: '/search/?q=steel',
    remember_me: 'on',
  });
});
