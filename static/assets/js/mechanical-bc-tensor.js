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
  if (!TENSOR_COMPONENTS.includes(component)) return false;
  if (selected instanceof Set ? !selected.has(component) : selected && component !== selected) return false;
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

export function tensorFaceLoads(magnitude, filter = 'all', selected = '') {
  const faces = new Map();
  for (const entry of tensorArrows(magnitude, filter, selected)) {
    const key = entry.normal + entry.faceSign;
    if (!faces.has(key)) faces.set(key, {normal: entry.normal, faceSign: entry.faceSign, components: []});
    faces.get(key).components.push(entry);
  }
  return [...faces.values()];
}

const tensorNumberFormat = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false,
});

export function formatTensorValue(value) {
  if (!isTensorNumber(value)) return 'Invalid';
  const formatted = tensorNumberFormat.format(value);
  return formatted === '-0.00' ? '0.00' : formatted;
}
