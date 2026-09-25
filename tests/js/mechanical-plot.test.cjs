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
