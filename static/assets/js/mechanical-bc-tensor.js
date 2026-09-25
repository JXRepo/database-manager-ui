export const TENSOR_COMPONENTS = ['xx', 'xy', 'xz', 'yx', 'yy', 'yz', 'zx', 'zy', 'zz'];
export const TENSOR_COLORS = {x: '#b45309', y: '#0f766e', z: '#7c3aed'};

export function isTensorNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function componentVisible(component, filter, selected) {
  const normal = component[0] === component[1];
  return (!selected || component === selected)
    && (filter === 'all' || (filter === 'normal' ? normal : !normal));
}

export function tensorArrows(magnitude, filter = 'all', selected = '') {
  const arrows = [];
  for (const component of TENSOR_COMPONENTS) {
    const value = magnitude?.[component];
    if (!isTensorNumber(value) || value === 0 || !componentVisible(component, filter, selected)) continue;
    for (const faceSign of [-1, 1]) {
      arrows.push({component, value, direction: component[0], normal: component[1],
        faceSign, sign: Math.sign(value) * faceSign});
    }
  }
  return arrows;
}

export function strainIllustration(magnitude, filter = 'all', selected = '') {
  const required = ['xx', 'yy', 'zz', 'xy', 'xz', 'yz'];
  if (!required.every(key => isTensorNumber(magnitude?.[key]))) {
    return {matrix: null, error: 'Shape preview needs numeric xx, yy, zz, xy, xz and yz values.'};
  }
  for (const key of ['xy', 'xz', 'yz']) {
    const reverse = key[1] + key[0];
    if (Object.hasOwn(magnitude, reverse) && magnitude[reverse] !== magnitude[key]) {
      return {matrix: null, error: 'Non-symmetric strain: use component directions; no shape is inferred.'};
    }
  }
  const axes = ['x', 'y', 'z'];
  const peak = Math.max(...required.map(key => Math.abs(magnitude[key]))) || 1;
  const matrix = axes.map(first => axes.map(second => {
    const key = first + second;
    const reverse = second + first;
    if (!componentVisible(key, filter, selected) && !componentVisible(reverse, filter, selected)) return 0;
    return (magnitude[key] ?? magnitude[reverse]) / peak;
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
