const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test, before} = require('node:test');

let tensor;
before(async () => {
  const source = readFileSync(join(__dirname, '../../static/assets/js/mechanical-bc-tensor.js'), 'utf8');
  tensor = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
});

test('normal stress arrows point outward for tension and inward for compression', () => {
  const positive = tensor.tensorArrows({xx: 100});
  assert.equal(positive.length, 2);
  assert.deepEqual(positive.map(a => [a.faceSign, a.sign]), [[-1, -1], [1, 1]]);
  assert.ok(positive.every(a => a.direction === 'x' && a.normal === 'x'));
  assert.deepEqual(tensor.tensorArrows({xx: -100}).map(a => a.sign), [1, -1]);
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
  assert.deepEqual(tensor.tensorArrows(magnitude, 'normal').map(a => a.component), ['xx', 'xx']);
  assert.deepEqual(tensor.tensorArrows(magnitude, 'shear', 'yx').map(a => a.component), ['yx', 'yx']);
  assert.deepEqual(tensor.tensorArrows(magnitude, 'normal', 'xy'), []);
  assert.equal(JSON.stringify(magnitude), before);
});

test('small-strain illustration preserves sign, uses explicit symmetry, and remains bounded', () => {
  const values = {xx: 1e200, yy: -1e200, zz: 0, xy: 1e200, xz: 0, yz: 0};
  const result = tensor.strainIllustration(values);
  assert.equal(result.error, '');
  assert.ok(result.matrix[0][0] > 0 && result.matrix[1][1] < 0);
  assert.equal(result.matrix[0][1], result.matrix[1][0]);
  assert.ok(result.matrix.every(row => row.reduce((sum, n) => sum + Math.abs(n), 0) <= 0.24));
  assert.equal(values.yx, undefined);
});

test('shape preview refuses incomplete or non-symmetric strain without averaging it', () => {
  assert.ok(tensor.strainIllustration({xx: 1}).error);
  assert.ok(tensor.strainIllustration({xx: 1, yy: 0, zz: 0, xy: 2, yx: 3, xz: 0, yz: 0}).error);
});

test('an explicitly zero tensor has a zero shape change', () => {
  assert.deepEqual(tensor.strainIllustration({xx: 0, yy: 0, zz: 0, xy: 0, xz: 0, yz: 0}).matrix,
    [[0, 0, 0], [0, 0, 0], [0, 0, 0]]);
});

test('display rounding is half-up while original component values are retained', () => {
  assert.equal(tensor.formatTensorValue(1.005), '1.01');
  assert.equal(tensor.formatTensorValue(-1.005), '-1.01');
  assert.equal(tensor.formatTensorValue(-0.004), '0.00');
});
