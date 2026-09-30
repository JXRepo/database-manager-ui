const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(join(__dirname, '../../templates/pages/data_detail.html'), 'utf8');
const labels = template.slice(
  template.indexOf('  function getAxisTitlePrefix('),
  template.indexOf('  function formatPlotPlainLabel('),
);

function axisLabel(variable, plotUnits) {
  const context = vm.createContext({variable, plotUnits});
  return vm.runInContext(`${labels}\ngetVariableAxisLabel(variable)`, context);
}

test('strain axes display explicit dimensionless units as (-)', () => {
  for (const unit of [1, 1.0, '1', ' 1 ']) {
    for (const kind of ['strain', 'plastic_strain']) {
      const variable = {kind, display_label: 'ε_eq', unit: ''};
      assert.equal(axisLabel(variable, {Strain: unit}), 'Strain, ε_eq (-)');
    }
  }
});

test('strain axes do not invent dimensionless units when metadata is missing or invalid', () => {
  const variable = {kind: 'strain', display_label: 'ε_11', unit: ''};
  for (const units of [{}, null, '', {Strain: null}, {Strain: ''}, {Strain: true}, {Strain: 0}]) {
    assert.equal(axisLabel(variable, units), 'Strain, ε_11');
  }
});

test('axes retain supplied stress and non-dimensionless strain units', () => {
  for (const unit of ['MPa', 'GPa', 'Pa']) {
    const variable = {kind: 'stress', display_label: 'σ_eq', unit};
    assert.equal(axisLabel(variable, {Stress: unit, Strain: 1}), `Stress, σ_eq (${unit})`);
  }
  const strain = {kind: 'strain', display_label: 'ε_11', unit: '%'};
  assert.equal(axisLabel(strain, {Strain: '%'}), 'Strain, ε_11 (%)');
});

const scaling = template.slice(template.indexOf('function cleanScaleNumber('), template.indexOf('const cornerAxisPlugin ='));

function plotScale(values) {
  return vm.runInNewContext(`${scaling}\nbuildPlotScale(values)`, {values});
}

function visibleSigns(scale) {
  return [scale.chartMin < 0 ? '-' : '', scale.chartMax > 0 ? '+' : ''].join('');
}

test('the viewport shows only one quadrant or two adjacent quadrants when possible', () => {
  const cases = [
    [[1, 2], [3, 4], '+', '+'],
    [[-1, -2], [3, 4], '-', '+'],
    [[-1, -2], [-3, -4], '-', '-'],
    [[1, 2], [-3, -4], '+', '-'],
    [[-1, 2], [3, 4], '-+', '+'],
    [[-1, 2], [-3, -4], '-+', '-'],
    [[1, 2], [-3, 4], '+', '-+'],
    [[-1, -2], [-3, 4], '-', '-+'],
  ];
  for (const [x, y, xSigns, ySigns] of cases) {
    assert.equal(visibleSigns(plotScale(x)), xSigns);
    assert.equal(visibleSigns(plotScale(y)), ySigns);
  }
});

test('diagonal pairs and multiple quadrants retain the actual asymmetric bounds', () => {
  for (const points of [
    [[1, 3], [-2, -4]], [[-1, 3], [2, -4]],
    [[1, 3], [-2, 4], [-1, -3]], [[1, 3], [-2, 4], [-1, -3], [2, -4]],
  ]) {
    for (const coordinate of [0, 1]) {
      const values = points.map(point => point[coordinate]);
      const scale = plotScale(values);
      assert.equal(visibleSigns(scale), '-+');
      assert.equal(scale.chartMin, Math.min(...values));
      assert.equal(scale.chartMax, Math.max(...values));
    }
  }
});

test('axis-only points and constant curves keep usable scales including their true origin', () => {
  for (const values of [[0], [0, 0, 0], [2, 2], [-2, -2], [0, 2], [-2, 0], []]) {
    const scale = plotScale(values);
    assert.ok(Number.isFinite(scale.chartMin) && Number.isFinite(scale.chartMax));
    assert.ok(scale.chartMin < scale.chartMax);
    assert.ok(scale.chartMin <= 0 && scale.chartMax >= 0);
    assert.ok(scale.ticks.includes(0));
    assert.equal(new Set(scale.ticks).size, scale.ticks.length);
    for (const value of values) assert.ok(value >= scale.chartMin && value <= scale.chartMax);
  }
  assert.equal(visibleSigns(plotScale([0, 0])), '+');
  assert.equal(visibleSigns(plotScale([2, 2])), '+');
  assert.equal(visibleSigns(plotScale([-2, -2])), '-');
});

test('single-sign curves include zero without extending beyond their data extrema', () => {
  for (const values of [[10, 11, 10.5], [-11, -10, -10.5], [1e8, 1e8 + .002]]) {
    const scale = plotScale(values);
    assert.equal(scale.chartMin, Math.min(0, ...values));
    assert.equal(scale.chartMax, Math.max(0, ...values));
    assert.equal(new Set(scale.ticks).size, scale.ticks.length);
    for (const tick of scale.ticks) assert.ok(tick >= scale.chartMin && tick <= scale.chartMax);
  }
});

test('near-zero reversals never expand into a large opposite-sign half of the plot', () => {
  for (const values of [[-1.4e-5, -1e-6, 1.7e-13], [-9.5e-16, .02, .03]]) {
    const scale = plotScale(values);
    assert.equal(scale.chartMin, Math.min(...values));
    assert.equal(scale.chartMax, Math.max(...values));
    const fraction = Math.min(Math.abs(scale.chartMin), Math.abs(scale.chartMax)) / (scale.chartMax - scale.chartMin);
    assert.ok(fraction < 1e-6);
  }
});

test('small signed values retain their quadrants and distinct ticks without changing data', () => {
  for (const values of [[2e-16, 3e-16], [-2e-16, -3e-16], [-2e-16, 3e-16]]) {
    const original = [...values];
    const scale = plotScale(values);
    assert.ok(scale.chartMin <= Math.min(...values) && scale.chartMax >= Math.max(...values));
    assert.ok(scale.chartMax - scale.chartMin < 1e-14);
    assert.equal(new Set(scale.ticks).size, scale.ticks.length);
    assert.deepEqual(values, original);
  }
});

test('large nonzero samples retain an actual zero tick and distinguishable labels', () => {
  const result = vm.runInNewContext(`${scaling}
    const scale = buildPlotScale([1e8, 1e8 + .001, 1e8 + .002]);
    ({minimum: scale.chartMin, maximum: scale.chartMax, offset: scale.offset, labels: scale.ticks.map(value =>
      formatPlotTickLabel(value - scale.offset, scale.labelPrecision))})`);
  assert.equal(result.minimum, 0);
  assert.equal(result.maximum, 1e8 + .002);
  assert.equal(result.offset, 0);
  assert.equal(new Set(result.labels.map(label => JSON.stringify(label))).size, result.labels.length);
  assert.ok(result.labels.some(label => label.text === '0'));
});
