const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test, before} = require('node:test');

let tensor;
before(async () => {
  const source = readFileSync(join(__dirname, '../../static/assets/js/mechanical-bc-tensor.js'), 'utf8');
  tensor = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
});

test('face loads retain independent components on both opposing faces', () => {
  assert.equal(typeof tensor.tensorFaceLoads, 'function');
  const values = {xx: 15, xy: 2, yx: -7, zz: 0, yz: null};
  const original = JSON.stringify(values);
  assert.deepEqual(tensor.tensorFaceLoads(values).map(face => [face.normal, face.faceSign,
    face.components.map(entry => [entry.component, entry.value])]), [
    ['x', -1, [['xx', 15], ['yx', -7]]], ['x', 1, [['xx', 15], ['yx', -7]]],
    ['y', -1, [['xy', 2]]], ['y', 1, [['xy', 2]]],
  ]);
  assert.deepEqual(tensor.tensorFaceLoads(values, 'push'), []);
  assert.deepEqual(tensor.tensorFaceLoads(values, 'slide', 'xy').map(face => face.normal), ['y', 'y']);
  assert.equal(JSON.stringify(values), original);
});



test('normal stress arrows point outward for tension and inward for compression', () => {
  const positive = tensor.tensorArrows({xx: 100});
  assert.equal(positive.length, 2);
  assert.deepEqual(positive.map(a => [a.faceSign, a.sign]), [[-1, -1], [1, 1]]);
  assert.ok(positive.every(a => a.direction === 'x' && a.normal === 'x'));
  assert.deepEqual(tensor.tensorArrows({xx: -100}).map(a => a.sign), [1, -1]);
});

test('component meaning distinguishes stress actions from strain guides and keeps tiny signs', () => {
  const meaning = tensor.tensorComponentMeaning;
  assert.deepEqual(meaning('xx', 15), {effect: 'outward', name: 'Tension', action: 'Pull', color: '#2563eb'});
  assert.deepEqual(meaning('yy', -0.0001), {effect: 'inward', name: 'Compression', action: 'Push', color: '#c2410c'});
  assert.equal(meaning('xx', 0.001, true).action, 'Extend');
  assert.equal(meaning('zz', -2, true).action, 'Shorten');
  assert.equal(meaning('zz', -2, true).name, 'Contraction');
  for (const value of [-9, 3]) {
    assert.equal(meaning('xy', value).effect, 'shear');
    assert.equal(meaning('yx', value).action, 'Slide');
    assert.equal(meaning('yx', value, true).name, 'Shear strain');
  }
  for (const value of [0, -0, undefined, null, true, '5', NaN, Infinity, {}]) {
    assert.equal(meaning('xx', value), null);
  }
  assert.equal(meaning('unknown', 1), null);
});

test('shear components stay independent and use the declared direction/normal convention', () => {
  const arrows = tensor.tensorArrows({xy: 3, yx: -7});
  assert.equal(arrows.length, 4);
  assert.deepEqual(arrows.map(a => [a.component, a.direction, a.normal, a.sign]), [
    ['xy', 'x', 'y', -1], ['xy', 'x', 'y', 1],
    ['yx', 'y', 'x', 1], ['yx', 'y', 'x', -1],
  ]);
  assert.ok(tensor.tensorArrows({xy: 3}).every(a => a.component === 'xy'));
});

test('zero, missing, invalid and unknown components never become directional arrows', () => {
  assert.deepEqual(tensor.tensorArrows({xx: 0, yy: null, zz: true, xy: '3', yz: Infinity, xz: [], unknown: 9}), []);
  assert.deepEqual(tensor.tensorArrows(null), []);
  assert.deepEqual(tensor.tensorArrows(10), []);
});

test('filters and component selection do not alter the source tensor', () => {
  const magnitude = {xx: 2, xy: 3, yx: -5, yz: 0};
  const before = JSON.stringify(magnitude);
  assert.deepEqual(tensor.tensorArrows(magnitude, 'pull').map(a => a.component), ['xx', 'xx']);
  assert.deepEqual(tensor.tensorArrows(magnitude, 'slide', 'yx').map(a => a.component), ['yx', 'yx']);
  assert.deepEqual(tensor.tensorArrows(magnitude, 'pull', 'xy'), []);
  assert.equal(JSON.stringify(magnitude), before);
});

test('action filters separate pulling, pushing and sliding using original finite values', () => {
  const values = {xx: 15, yy: -5, zz: -0.0001, xy: 2, yx: -7, xz: 0, yz: null, zx: '3'};
  const original = JSON.stringify(values);
  const components = filter => tensor.tensorArrows(values, filter).map(arrow => arrow.component);
  assert.deepEqual(components('pull'), ['xx', 'xx']);
  assert.deepEqual(components('push'), ['yy', 'yy', 'zz', 'zz']);
  assert.deepEqual(components('slide'), ['xy', 'xy', 'yx', 'yx']);
  assert.deepEqual(components('unknown'), []);
  assert.deepEqual(tensor.tensorArrows(values, 'pull', 'xy'), []);
  assert.equal(JSON.stringify(values), original);
});







test('display rounding is half-up while original component values are retained', () => {
  assert.equal(tensor.formatTensorValue(1.005), '1.01');
  assert.equal(tensor.formatTensorValue(-1.005), '-1.01');
  assert.equal(tensor.formatTensorValue(-0.004), '0.00');
});

test('multi-selection keeps only the selected supplied components on their own faces', () => {
  const values = {xx: 15, yy: -5, xy: 2, yx: 2};
  assert.deepEqual(tensor.tensorArrows(values, 'all', new Set(['xx','xy','yx'])).map(a => a.component),
    ['xx','xx','xy','xy','yx','yx']);
  assert.deepEqual(tensor.tensorArrows(values, 'all', new Set()), []);
});
