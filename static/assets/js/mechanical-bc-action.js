import {TENSOR_COMPONENTS, isTensorNumber} from './mechanical-bc-tensor.js';

export function tensorTug(progress) {
  const frames = [[0,0],[.14,1.08],[.25,.85],[.36,1],[.56,1],[.70,.08],[.78,.18],[.88,.03],[1,0]];
  const time = Math.min(1, Math.max(0, progress));
  for (let i = 1; i < frames.length; i++) {
    if (time > frames[i][0]) continue;
    const [start, a] = frames[i - 1], [end, b] = frames[i];
    const t = (time - start) / (end - start);
    return a + (b - a) * t * t * (3 - 2 * t);
  }
  return 0;
}

export function tensorActionPoint(point, magnitude, selected, amount) {
  const result = [...point];
  if (!amount) return result;
  for (const key of TENSOR_COMPONENTS) {
    const value = magnitude?.[key];
    if (!selected.has(key) || !isTensorNumber(value) || !value) continue;
    const direction = 'xyz'.indexOf(key[0]), normal = 'xyz'.indexOf(key[1]);
    const n = Math.min(1, Math.abs(point[normal]) * 2);
    const radial = point.reduce((sum, coordinate, axis) => sum + (axis === normal ? 0 : coordinate ** 2), 0);
    const grip = .25 + .75 * Math.exp(-radial / .12);
    const strength = .24 * Math.sign(value) * amount;
    result[direction] += strength * Math.sign(point[normal]) * n ** 3 * grip;
    if (direction === normal) {
      for (let axis = 0; axis < 3; axis++) {
        if (axis !== normal) result[axis] -= strength * .45 * point[axis] * (1 - n ** 2);
      }
    }
  }
  return result;
}
