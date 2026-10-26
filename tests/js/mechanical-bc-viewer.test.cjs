const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');

const source = readFileSync(join(__dirname, '../../static/assets/js/mechanical-bc-viewer.js'), 'utf8');

function viewerFunction(name) {
  const start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `${name} must be defined`);
  const end = source.indexOf('\nfunction ', start + 1);
  return new Function(`${source.slice(start, end)}\nreturn ${name};`)();
}

test('zero, missing and invalid scalar magnitudes never invent a positive arrow', () => {
  const signs = viewerFunction('getLoadDirectionSigns');
  for (const value of [0, -0, null, undefined, false, true, {}, 'bad', [], [0, null, false], Infinity, NaN]) {
    assert.deepEqual(signs(value), [], `Unexpected arrow for ${JSON.stringify(value)}`);
  }
  assert.deepEqual(signs(12.5), [1]);
  assert.deepEqual(signs(-7.5), [-1]);
  assert.deepEqual(signs([0, [3, -2], 0]), [-1, 1]);
});

test('scalar arrow hover identifies its quantity, axis, value and supplied step', () => {
  const tooltip = viewerFunction('formatAxisLoadHover');
  const item = {vertex: 'V111', target_type: 'Point', quantity_label: 'Force (N)', loading_type: 'force'};
  const axis = {direction: 'X', status: 'loaded', load_summary: 'magnitude: 12.50, step: 10001'};
  const result = tooltip(item, axis);
  assert.match(result, /Point/);
  assert.match(result, /V111/);
  assert.match(result, /Force \(N\)/);
  assert.match(result, /X/);
  assert.match(result, /12\.50/);
  assert.match(result, /step: 10001/);
  assert.doesNotMatch(tooltip({...item, quantity_label:'Displacement · unit not supplied'},
    {...axis,load_summary:'magnitude: 0.20'}), /\bN\b|step:/);
});
