import * as THREE from 'three';
import {tensorComponentMeaning, tensorConceptPoint} from './mechanical-bc-tensor.js';

export function createTensorIllustration(parent, component, value) {
  const meaning = tensorComponentMeaning(component, value);
  if (!meaning) return null;

  const group = new THREE.Group();
  group.userData.tensorConcept = {component, value};
  group.matrixAutoUpdate = false;
  const cube = new THREE.BoxGeometry(1, 1, 1);
  group.add(new THREE.Mesh(cube, new THREE.MeshBasicMaterial({
    color: meaning.color, transparent: true, opacity: 0.07,
    side: THREE.DoubleSide, depthWrite: false,
  })));
  const outline = new THREE.LineSegments(new THREE.EdgesGeometry(cube),
    new THREE.LineBasicMaterial({color: meaning.color, transparent: true, opacity: 0.9}));
  group.add(outline);

  const gridPoints = [];
  for (let normal = 0; normal < 3; normal++) {
    const axes = [0, 1, 2].filter(axis => axis !== normal);
    for (const sign of [-1, 1]) {
      for (const fixed of axes) {
        const varying = axes.find(axis => axis !== fixed);
        for (const offset of [-1 / 6, 1 / 6]) {
          for (const end of [-0.5, 0.5]) {
            const point = [0, 0, 0];
            point[normal] = sign * 0.502;
            point[fixed] = offset;
            point[varying] = end;
            gridPoints.push(new THREE.Vector3(...point));
          }
        }
      }
    }
  }
  group.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(gridPoints),
    new THREE.LineBasicMaterial({color: meaning.color, transparent: true, opacity: 0.3})));

  const reference = new THREE.LineSegments(new THREE.EdgesGeometry(cube),
    new THREE.LineDashedMaterial({color: '#64748b', dashSize: 0.035, gapSize: 0.025,
      transparent: true, opacity: 0.65, depthTest: false}));
  reference.computeLineDistances();
  reference.renderOrder = 5;
  reference.userData.tensorReference = true;
  parent.add(reference, group);

  function setProgress(progress) {
    const basis = [[1, 0, 0], [0, 1, 0], [0, 0, 1]].map(point =>
      new THREE.Vector3(...tensorConceptPoint(point, component, value, progress)));
    group.matrix.makeBasis(...basis);
    group.matrixWorldNeedsUpdate = true;
  }
  setProgress(1);
  return {group, reference, setProgress};
}
