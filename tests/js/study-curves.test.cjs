const assert = require('node:assert/strict');
const {test} = require('node:test');
const curves = require('../../static/assets/js/study-curves.js');

const record = (x, y, extra = {}) => ({pk: 1, state: 'ready', x, y, ...extra});

test('curve bounds preserve signed extrema and the origin without adding samples', () => {
  const source = record([.01, -.02, .005, .01], [1, -4, 2, 3]);
  const original = JSON.stringify(source);
  assert.deepEqual(curves.bounds([source]), {x: [-.02, .01], y: [-4, 3]});
  const projected = curves.projected(source, curves.bounds([source]), {left: 0, right: 300, top: 0, bottom: 200});
  assert.deepEqual(projected.map(point => point.index), [0, 1, 2, 3]);
  assert.ok(projected[0].x > projected[1].x && projected[1].x < projected[2].x);
  assert.equal(JSON.stringify(source), original);
  assert.deepEqual(curves.bounds([record([2, 3], [8, 10])]), {x: [0, 3], y: [0, 10]});
  assert.deepEqual(curves.bounds([record([0], [0])]), {x: [0, 1], y: [0, 1]});
});

test('projection stays finite across extreme finite magnitudes and subnormals', () => {
  for (const limit of [1e308, 1e-308, Number.MIN_VALUE]) {
    assert.equal(curves.position(-limit, [-limit, limit], 10, 210), 10);
    assert.equal(curves.position(0, [-limit, limit], 10, 210), 110);
    assert.equal(curves.position(limit, [-limit, limit], 10, 210), 210);
  }
});

test('hover tests segments but returns a real original sample of an unsorted loop', () => {
  const source = record([0, 10, -10, 0], [0, 10, 10, 0]);
  const points = [{x: 20, y: 80, index: 0}, {x: 120, y: 20, index: 1},
    {x: 0, y: 20, index: 2}, {x: 20, y: 80, index: 3}];
  const sample = curves.nearestSample([{record: source, points}], 90, 21, 4);
  assert.equal(sample.index, 1);
  assert.equal(sample.record.x[sample.index], 10);
  assert.equal(sample.record.y[sample.index], 10);
  assert.equal(curves.nearestSample([{record: source, points}], 100, 100, 4), null);
});

test('hover preserves duplicate points and works for a one-sample response', () => {
  const source = record([0], [0]);
  const sample = curves.nearestSample([{record: source, points: [{x: 10, y: 10, index: 0}]}], 11, 10, 2);
  assert.equal(sample.index, 0);
  assert.equal(curves.nearestSample([{record: source, points: []}], 10, 10), null);
});

test('overlay requires explicit backend approval and complete paired responses', () => {
  const records = [record([0, 1], [0, 2]), record([0, 2], [0, 3], {pk: 2})];
  assert.equal(curves.canOverlay({records, overlay_allowed: true}), true);
  assert.equal(curves.canOverlay({records, overlay_allowed: false}), false);
  assert.equal(curves.canOverlay({records, overlay_allowed: 'true'}), false);
  assert.equal(curves.canOverlay({records: [...records, record([], [], {pk: 3, state: 'missing'})], overlay_allowed: true}), false);
  assert.equal(curves.canOverlay({records: [records[0], record([1], [2, 3])], overlay_allowed: true}), false);
  assert.equal(curves.canOverlay({records: [records[0], record([1], [Infinity])], overlay_allowed: true}), false);
});

test('axis labels use half-up rounding and never turn tiny nonzero values into zero', () => {
  assert.equal(curves.tickText(0), '0');
  assert.equal(curves.tickText(2.675), '2.68');
  assert.equal(curves.tickText(-1.005), '−1.01');
  assert.equal(curves.tickText(.025), '0.03');
  assert.equal(curves.tickText(1e-20), '1.00e−20');
  assert.equal(curves.tickText(Number.MIN_VALUE), '5.00e−324');
  assert.equal(curves.tickText(-9.999e100), '−1.00e+101');
});
