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

function tickLabel(value, mode = 'auto') {
  const label = vm.runInNewContext(`${scaling}\nformatPlotTickLabel(value, mode)`, {value, mode});
  return JSON.parse(JSON.stringify(label));
}

function axisTick(value, scale) {
  return JSON.parse(JSON.stringify(vm.runInNewContext(`${scaling}\nformatPlotTickLabel(value, scale.tickFormat, scale.exponent)`, {value, scale})));
}

function measuredLayout(xValues, yValues) {
  const textRuns = template.slice(template.indexOf('  function getPlotTextRuns('),
    template.indexOf('  let isSyncingPlotSelects'));
  // Geometry checks use simple glyph widths; the browser suite measures actual fonts.
  const context = {
    font: '',
    measureText(text) {
      const size = Number(this.font.match(/([\d.]+)px/)[1]);
      return {width: text.length * size * .5, actualBoundingBoxLeft: 0,
        actualBoundingBoxRight: text.length * size * .5,
        actualBoundingBoxAscent: size * .75, actualBoundingBoxDescent: size * .2};
    },
  };
  return JSON.parse(JSON.stringify(vm.runInNewContext(`${textRuns}\n${scaling}
    function scale(values, title) {
      const result = buildPlotScale(values);
      return {min: result.chartMin, max: result.chartMax, customTickValues: result.ticks,
        customTickFormat: result.tickFormat, customExponent: result.exponent, title: {text: title}};
    }
    buildMechanicalPlotLayout(context, {left: 150, right: 650, top: 100, bottom: 400},
      scale(xValues, 'Strain, ε_12 (-)'), scale(yValues, 'Stress, σ_12 (MPa)'))`,
  {context, xValues, yValues})));
}

test('single quadrant factors use separate outer ends and titles follow their axes', () => {
  const cases = [
    {x: 1, y: 1, xSide: 1, ySide: -1, xEnd: 'right', yEnd: 'top'},
    {x: -1, y: 1, xSide: 1, ySide: 1, xEnd: 'left', yEnd: 'top'},
    {x: -1, y: -1, xSide: -1, ySide: 1, xEnd: 'left', yEnd: 'bottom'},
    {x: 1, y: -1, xSide: -1, ySide: -1, xEnd: 'right', yEnd: 'bottom'},
  ];
  for (const item of cases) {
    const layout = measuredLayout([0, item.x * .00108], [0, item.y * 7.82e-6]);
    assert.deepEqual(layout.titleSides, {x: item.xSide, y: item.ySide});
    assert.equal(layout.multipliers.length, 2);
    const xFactor = layout.multipliers.find(factor => factor.axis === 'x');
    const yFactor = layout.multipliers.find(factor => factor.axis === 'y');
    assert.ok(item.xEnd === 'left' ? xFactor.right < 400 : xFactor.left > 400,
      `X factor belongs at the ${item.xEnd} end for signs ${item.x}, ${item.y}`);
    assert.ok(item.yEnd === 'top' ? yFactor.bottom < 250 : yFactor.top > 250,
      `Y factor belongs at the ${item.yEnd} end for signs ${item.x}, ${item.y}`);
    assert.ok(item.xSide < 0 ? xFactor.bottom < layout.axes.y : xFactor.top > layout.axes.y);
    assert.ok(item.ySide < 0 ? yFactor.right < layout.axes.x : yFactor.left > layout.axes.x);
    for (const factor of [xFactor, yFactor]) {
      assert.ok(factor.group.runs.some(run => run.text === '· 10'));
    }
  }
});

test('tiny positive reversals keep titles and factors beside the visible negative branches', () => {
  const layout = measuredLayout([-.00108, 1e-14], [-7.82e-6, 1e-18]);
  assert.ok(layout.axes.x > 649 && layout.axes.y < 101);
  assert.deepEqual(layout.titleSides, {x: -1, y: 1});
  assert.ok(layout.titles.x.bottom < layout.area.top);
  assert.ok(layout.titles.y.left > layout.area.right);
  const xFactor = layout.multipliers.find(factor => factor.axis === 'x');
  const yFactor = layout.multipliers.find(factor => factor.axis === 'y');
  assert.ok(xFactor.right < 400, 'X factor leaves the crowded upper-right origin');
  assert.ok(yFactor.top > 250, 'Y factor leaves the crowded upper-right origin');
});

test('visible positive branches retain the preferred right and top multiplier ends', () => {
  const layout = measuredLayout([-.001, .002], [-2e-6, 4e-6]);
  assert.ok(layout.multipliers.find(factor => factor.axis === 'x').left > 400);
  assert.ok(layout.multipliers.find(factor => factor.axis === 'y').bottom < 250);
  assert.deepEqual(layout.titleSides, {x: layout.xSide, y: layout.ySide});
});

test('one shared power formats small axis ticks without changing their values', () => {
  const scale = plotScale([-0.00014, 0]);
  assert.equal(scale.exponent, -4);
  for (const [value, text] of [[-0.0001, '-1.00'], [-0.00006, '-0.60'], [-0.00002, '-0.20'], [0, '0']]) {
    assert.deepEqual(axisTick(value, scale), {type: 'plain', text});
  }
  assert.equal(scale.chartMin, -0.00014);
  assert.equal(scale.chartMax, 0);
});

test('independent axis ranges choose their own multiplier or ordinary decimal ticks', () => {
  const ordinary = plotScale([0, .1]);
  const tiny = plotScale([0, .000002]);
  const large = plotScale([0, 200000]);
  assert.equal(ordinary.exponent, null);
  assert.equal(tiny.exponent, -6);
  assert.equal(large.exponent, 5);
  assert.deepEqual(axisTick(.02, ordinary), {type: 'plain', text: '0.02'});
  assert.deepEqual(axisTick(.000001, tiny), {type: 'plain', text: '1.00'});
  assert.deepEqual(axisTick(150000, large), {type: 'plain', text: '1.50'});
});

test('three-decimal regular steps use a multiplier while hundredths stay decimal', () => {
  const thousandths = plotScale([0, .15]);
  assert.equal(thousandths.step, .025);
  assert.equal(thousandths.exponent, -1);
  assert.deepEqual(axisTick(.025, thousandths), {type: 'plain', text: '0.25'});
  const fine = plotScale([0, .03]);
  assert.equal(fine.exponent, -2);
  assert.deepEqual(axisTick(.015, fine), {type: 'plain', text: '1.50'});
  const hundredths = plotScale([0, .05]);
  assert.equal(hundredths.exponent, null);
  assert.deepEqual(axisTick(.01, hundredths), {type: 'plain', text: '0.01'});
  assert.equal(plotScale([0, .1335464475862735]).exponent, null);
});

test('shared multipliers preserve half-up rounding and tiny signed endpoint coefficients', () => {
  const scale = plotScale([-0.00014, 1.7e-13]);
  for (const value of [1.7e-13, -1.7e-13]) {
    const label = axisTick(value, scale);
    const coefficient = label.type === 'plain' ? Number(label.text) : Number(`${label.mantissa}e${label.exponent}`);
    assert.notEqual(coefficient, 0);
    assert.equal(Math.sign(coefficient), Math.sign(value));
    assert.ok(Math.abs(coefficient * 10 ** scale.exponent / value - 1) < .005);
  }
  assert.deepEqual(axisTick(-0.0001005, scale), {type: 'plain', text: '-1.01'});
  const wide = plotScale([-1e-100, 1e300]);
  assert.deepEqual(axisTick(-1e-100, wide), {type: 'scientific', mantissa: '-1.00', exponent: '-400'});
});

test('ordinary tick labels keep two decimal places with half-up rounding', () => {
  for (const [value, text] of [
    [1, '1.00'], [0.01, '0.01'], [1.004, '1.00'], [1.005, '1.01'],
    [2.675, '2.68'], [-1.005, '-1.01'], [-2.675, '-2.68'], [9.999, '10.00'],
  ]) {
    for (const mode of ['auto', 'decimal']) {
      assert.deepEqual(tickLabel(value, mode), {type: 'plain', text});
    }
  }
});

test('tiny and large nonzero ticks use two-place scientific mantissas', () => {
  for (const [value, mantissa, exponent] of [
    [1e-16, '1.00', '-16'], [-1e-16, '-1.00', '-16'],
    [1.005e-16, '1.01', '-16'], [-1.005e-16, '-1.01', '-16'],
    [0.00999, '9.99', '-3'], [10000, '1.00', '4'],
    [Number.MIN_VALUE, '5.00', '-324'], [Number.MAX_VALUE, '1.80', '308'],
  ]) {
    for (const mode of ['auto', 'decimal', 'scientific']) {
      assert.deepEqual(tickLabel(value, mode), {type: 'scientific', mantissa, exponent});
    }
  }
});

test('scientific mode formats every nonzero tick consistently', () => {
  for (const [value, mantissa, exponent] of [
    [1, '1.00', '0'], [12.5, '1.25', '1'], [0.1, '1.00', '-1'],
    [-2.675, '-2.68', '0'],
  ]) {
    assert.deepEqual(tickLabel(value, 'scientific'), {type: 'scientific', mantissa, exponent});
  }
});

test('scientific rounding carries into the exponent at mantissa boundaries', () => {
  for (const [value, mantissa, exponent] of [
    [9.994, '9.99', '0'], [9.995, '1.00', '1'], [9.999, '1.00', '1'],
    [-9.999, '-1.00', '1'], [9.999e-16, '1.00', '-15'],
    [99999, '1.00', '5'],
  ]) {
    assert.deepEqual(tickLabel(value, 'scientific'), {type: 'scientific', mantissa, exponent});
  }
});

test('both true zero signs remain plain origin labels in every mode', () => {
  for (const value of [0, -0]) {
    for (const mode of ['auto', 'decimal', 'scientific']) {
      assert.deepEqual(tickLabel(value, mode), {type: 'plain', text: '0'});
    }
  }
});

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

test('range endpoints are labelled even when they are not regular tick multiples', () => {
  for (const values of [[0, 87], [-.0137, .0203], [-1.4e-5, 1.7e-13], [1e8, 1e8 + .002]]) {
    const scale = plotScale(values);
    assert.ok(scale.ticks.includes(scale.chartMin));
    assert.ok(scale.ticks.includes(scale.chartMax));
    assert.equal(new Set(scale.ticks).size, scale.ticks.length);
    assert.ok(scale.ticks.every((value, index) => !index || value > scale.ticks[index - 1]));
    for (const value of scale.ticks) {
      if (value === 0 || value === scale.chartMin || value === scale.chartMax) continue;
      assert.ok(Math.abs(value - scale.chartMin) >= scale.step / 5);
      assert.ok(Math.abs(value - scale.chartMax) >= scale.step / 5);
    }
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
      formatPlotTickLabel(value - scale.offset, scale.tickFormat))})`);
  assert.equal(result.minimum, 0);
  assert.equal(result.maximum, 1e8 + .002);
  assert.equal(result.offset, 0);
  assert.equal(new Set(result.labels.map(label => JSON.stringify(label))).size, result.labels.length);
  assert.ok(result.labels.some(label => label.text === '0'));
});

function hoverIndex(points, position, radius = 16) {
  return vm.runInNewContext(`${scaling}\nfindCurveHoverIndex(points, position, radius)`, {points, position, radius});
}

test('hover reaches the whole sparse segment and selects an actual nearby sample', () => {
  const points = [{x: 0, y: 0}, {x: 200, y: 0}];
  assert.equal(hoverIndex(points, {x: 75, y: 8}), 0);
  assert.equal(hoverIndex(points, {x: 125, y: 8}), 1);
  assert.equal(hoverIndex(points, {x: 75, y: 17}), -1);
  assert.equal(hoverIndex(points, {x: 75, y: 16}), 0);
});

test('hover preserves supplied loop order and remains deterministic at crossings', () => {
  const points = [{x: -100, y: -100}, {x: 100, y: 100}, {x: -100, y: 100}, {x: 100, y: -100}];
  const original = JSON.stringify(points);
  assert.equal(hoverIndex(points, {x: 0, y: 0}), 0);
  assert.equal(hoverIndex(points, {x: -75, y: 75}), 2);
  assert.equal(hoverIndex(points, {x: 75, y: -75}), 3);
  assert.equal(JSON.stringify(points), original);
});

test('hover handles single and repeated points without connecting skipped or invalid samples', () => {
  assert.equal(hoverIndex([{x: 30, y: 40}], {x: 35, y: 40}), 0);
  assert.equal(hoverIndex([{x: 30, y: 40}, {x: 30, y: 40}], {x: 35, y: 40}), 0);
  for (const middle of [{x: 100, y: 100, skip: true}, {x: 100, y: NaN}]) {
    assert.equal(hoverIndex([{x: 0, y: 0}, middle, {x: 200, y: 0}], {x: 100, y: 0}), -1);
  }
  assert.equal(hoverIndex([], {x: 0, y: 0}), -1);
  assert.equal(hoverIndex([{x: 0, y: 0}], {x: NaN, y: 0}), -1);
});
