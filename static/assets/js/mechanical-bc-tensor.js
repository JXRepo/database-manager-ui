export const TENSOR_COMPONENTS = ['xx', 'xy', 'xz', 'yx', 'yy', 'yz', 'zx', 'zy', 'zz'];
export const TENSOR_COLORS = {x: '#b45309', y: '#0f766e', z: '#7c3aed'};

export function isTensorNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

export function tensorComponentMeaning(component, value, isStrain = false) {
  if (!TENSOR_COMPONENTS.includes(component) || !isTensorNumber(value) || value === 0) return null;
  if (component[0] !== component[1]) {
    return {effect: 'shear', name: isStrain ? 'Shear strain' : 'Shear', action: 'Slide', color: '#0f766e'};
  }
  return value > 0
    ? {effect: 'outward', name: isStrain ? 'Extension' : 'Tension', action: isStrain ? 'Extend' : 'Pull', color: '#2563eb'}
    : {effect: 'inward', name: isStrain ? 'Contraction' : 'Compression', action: isStrain ? 'Shorten' : 'Push', color: '#c2410c'};
}

export function tensorComponentVisible(component, value, filter = 'all', selected = '') {
  if (!TENSOR_COMPONENTS.includes(component) || (selected && component !== selected)) return false;
  if (filter === 'all') return true;
  const effect = tensorComponentMeaning(component, value)?.effect;
  return !!effect && effect === {pull: 'outward', push: 'inward', slide: 'shear'}[filter];
}

export function tensorArrows(magnitude, filter = 'all', selected = '') {
  const arrows = [];
  for (const component of TENSOR_COMPONENTS) {
    const value = magnitude?.[component];
    if (!isTensorNumber(value) || value === 0 || !tensorComponentVisible(component, value, filter, selected)) continue;
    for (const faceSign of [-1, 1]) {
      arrows.push({component, value, direction: component[0], normal: component[1],
        faceSign, sign: Math.sign(value) * faceSign});
    }
  }
  return arrows;
}

export function strainIllustration(magnitude, filter = 'all', selected = '') {
  if (!magnitude || !TENSOR_COMPONENTS.every(key => Object.hasOwn(magnitude, key) && isTensorNumber(magnitude[key]))) {
    return {matrix: null, error: 'Shape preview needs all nine numeric strain components; missing components are not inferred.'};
  }
  for (const key of ['xy', 'xz', 'yz']) {
    const reverse = key[1] + key[0];
    if (magnitude[reverse] !== magnitude[key]) {
      return {matrix: null, error: 'Non-symmetric strain: use component directions; no shape is inferred.'};
    }
  }
  const axes = ['x', 'y', 'z'];
  const peak = Math.max(...TENSOR_COMPONENTS.map(key => Math.abs(magnitude[key]))) || 1;
  const matrix = axes.map(first => axes.map(second => {
    const key = first + second;
    const reverse = second + first;
    if (!tensorComponentVisible(key, magnitude[key], filter, selected)
      && !tensorComponentVisible(reverse, magnitude[reverse], filter, selected)) return 0;
    return magnitude[key] / peak;
  }));
  const rowSize = Math.max(...matrix.map(row => row.reduce((sum, value) => sum + Math.abs(value), 0)), 1);
  return {matrix: matrix.map(row => row.map(value => value * (0.24 / rowSize))), error: ''};
}

const tensorNumberFormat = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false,
});

export function formatTensorValue(value) {
  if (!isTensorNumber(value)) return 'Invalid';
  const formatted = tensorNumberFormat.format(value);
  return formatted === '-0.00' ? '0.00' : formatted;
}
