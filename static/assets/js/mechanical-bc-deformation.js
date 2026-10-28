import {TENSOR_COMPONENTS, isTensorNumber} from './mechanical-bc-tensor.js';

export function tensorDeformation(magnitude, selected, type, units = {}, context = {}) {
  const invalid = error => ({matrix: null, extensions: null, maxScale: 1, source: '', error});
  if (!selected.size) return invalid('Select one or more components to animate.');
  if (!TENSOR_COMPONENTS.every(key => isTensorNumber(magnitude?.[key]))) {
    return invalid('Deformation needs all nine numeric tensor entries. Missing or invalid values are not replaced by zero.');
  }
  for (const key of ['xy', 'xz', 'yz']) {
    const reverse = key[1] + key[0];
    if (magnitude[key] !== magnitude[reverse]) return invalid(`A symmetric tensor is required: ${key} and ${reverse} differ.`);
    if (selected.has(key) !== selected.has(reverse)) return invalid(`Select ${key} and ${reverse} together for symmetric shear.`);
  }
  const axes = ['x', 'y', 'z'];
  const values = axes.map(i => axes.map(j => selected.has(i + j) ? magnitude[i + j] : 0));
  let matrix;
  let source;
  if (type === 'strain') {
    const unit = units?.Strain === 1 ? '1' : typeof units?.Strain === 'string' ? units?.Strain.trim().toLowerCase() : '';
    const factor = ['1', '-', 'dimensionless'].includes(unit) ? 1 : ['%', 'percent'].includes(unit) ? 0.01 : null;
    if (factor === null) return invalid('Supply an explicit strain unit: 1 (dimensionless) or %.');
    matrix = values.map(row => row.map(value => value * factor));
    source = 'Supplied tensor strain · homogeneous small strain, no rigid rotation';
  } else if (type === 'stress') {
    const model = context.model;
    if (context.phaseCount !== 1 || context.phaseFraction !== 1 || context.solidFraction !== 1) {
      return invalid('Stress deformation needs one fully dense phase with volume fraction 1; effective properties are not inferred.');
    }
    const name = typeof model?.name === 'string' ? model.name.toLowerCase().replace(/[^a-z]/g, '') : '';
    if (!['isotropiclinearelasticity', 'linearisotropicelasticity', 'isotropiclinearelastic'].includes(name)) {
      return invalid('Stress deformation requires an explicitly supplied isotropic linear elastic model.');
    }
    const E = model.youngsModulus, nu = model.poissonRatio;
    if (!isTensorNumber(E) || E <= 0 || !isTensorNumber(nu) || nu <= -1 || nu >= 0.5) {
      return invalid('Supply valid youngs_modulus (> 0) and poisson_ratio (between -1 and 0.5).');
    }
    const pressureUnits = {pa: 1, kpa: 1e3, mpa: 1e6, gpa: 1e9};
    const stressUnit = typeof units?.Stress === 'string' ? pressureUnits[units?.Stress.trim().toLowerCase()] : null;
    const stiffnessUnit = typeof model.stiffnessUnit === 'string' ? pressureUnits[model.stiffnessUnit.trim().toLowerCase()] : null;
    if (!stressUnit || !stiffnessUnit) return invalid('Supply compatible Stress and material Stiffness units: Pa, kPa, MPa or GPa.');
    const compliance = stressUnit / stiffnessUnit / E;
    const trace = values[0][0] + values[1][1] + values[2][2];
    matrix = values.map((row, i) => row.map((value, j) => compliance * ((1 + nu) * value - (i === j ? nu * trace : 0))));
    source = 'Calculated linear elastic estimate · homogeneous material; plastic, thermal and local boundary effects excluded';
  } else return invalid('Deformation is available for tensor stress or strain.');
  const peak = Math.max(...matrix.map(row => row.reduce((sum, value) => sum + Math.abs(value), 0)));
  if (!Number.isFinite(peak) || peak > 0.05) return invalid('This small-strain preview requires a maximum strain row sum of 5% or less.');
  if (!peak) return invalid('The selected components produce zero deformation.');
  const size = context.size;
  const lengthsKnown = Array.isArray(size) && size.length === 3 && size.every(value => isTensorNumber(value) && value > 0)
    && typeof context.lengthUnit === 'string' && context.lengthUnit.trim();
  return {matrix, extensions: lengthsKnown ? size.map((length, i) => length * matrix[i][i]) : null,
    maxScale: Math.min(1000000, Math.max(1, Math.floor(0.45 / peak))), source, error: ''};
}
