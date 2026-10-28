import * as THREE from 'three';
import {tensorFaceLoads, tensorComponentMeaning} from './mechanical-bc-tensor.js';
import {tensorActionPoint, tensorTug} from './mechanical-bc-action.js';

function capture(object) {
  object.updateMatrix();
  return {object, positions: object.geometry.attributes.position.array.slice(),
    matrix: object.matrix.clone(), inverse: object.matrix.clone().invert()};
}

function subdivideEdges(object) {
  const old = object.geometry.attributes.position;
  const points = [];
  const start = new THREE.Vector3(), end = new THREE.Vector3();
  for (let i = 0; i < old.count; i += 2) {
    start.fromBufferAttribute(old, i);
    end.fromBufferAttribute(old, i + 1);
    for (let part = 0; part < 12; part++) {
      points.push(...start.clone().lerp(end, part / 12).toArray(),
        ...start.clone().lerp(end, (part + 1) / 12).toArray());
    }
  }
  object.geometry.setAttribute('position', new THREE.Float32BufferAttribute(points, 3));
}

function gripGeometry() {
  const shape = new THREE.Shape();
  const w = .15, h = .11, r = .035;
  shape.moveTo(-w + r, -h);
  shape.lineTo(w - r, -h); shape.quadraticCurveTo(w, -h, w, -h + r);
  shape.lineTo(w, h - r); shape.quadraticCurveTo(w, h, w - r, h);
  shape.lineTo(-w + r, h); shape.quadraticCurveTo(-w, h, -w, h - r);
  shape.lineTo(-w, -h + r); shape.quadraticCurveTo(-w, -h, -w + r, -h);
  return new THREE.ExtrudeGeometry(shape, {depth: .025, bevelEnabled: true, bevelSize: .008,
    bevelThickness: .008, bevelSegments: 2, steps: 1, curveSegments: 5});
}

export function createTensorAction(baseCube, tensorGroup, root) {
  const grips = new THREE.Group();
  grips.userData.tensorActionGrips = true;
  root.add(grips);
  const surfaces = baseCube.children.filter(object => object.geometry && object.geometry.type !== 'SphereGeometry');
  surfaces.filter(object => object.isLineSegments).forEach(subdivideEdges);
  const originalSurfaces = surfaces.map(capture);
  const corners = baseCube.children.filter(object => object.geometry?.type === 'SphereGeometry')
    .map(object => ({object, position: object.position.clone()}));
  let faceSurfaces = [];
  let view = null;
  const point = new THREE.Vector3();

  function map(position, amount) {
    return tensorActionPoint(position, view?.load?.magnitude, view?.selected || new Set(), amount);
  }
  function warp(entry, amount) {
    const attribute = entry.object.geometry.attributes.position;
    if (!amount) attribute.array.set(entry.positions);
    else for (let index = 0; index < attribute.count; index++) {
      point.fromArray(entry.positions, index * 3).applyMatrix4(entry.matrix);
      point.fromArray(map(point.toArray(), amount)).applyMatrix4(entry.inverse);
      attribute.setXYZ(index, point.x, point.y, point.z);
    }
    attribute.needsUpdate = true;
    if (entry.object.isMesh) entry.object.geometry.computeVertexNormals();
    entry.object.geometry.computeBoundingSphere();
    entry.object.geometry.computeBoundingBox();
  }
  function update(progress) {
    const amount = tensorTug(progress);
    [...originalSurfaces, ...faceSurfaces].forEach(entry => warp(entry, amount));
    corners.forEach(entry => entry.object.position.fromArray(map(entry.position.toArray(), amount)));
    grips.children.forEach(grip => grip.position.fromArray(map(grip.userData.anchor, amount)));
    return amount;
  }
  function setView(next) {
    update(0);
    grips.children.forEach(grip => grip.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); }));
    grips.clear();
    view = next;
    faceSurfaces = tensorGroup.children.filter(object => object.geometry).map(capture);
    grips.visible = view.mode === 'action';
    if (!grips.visible) return;
    for (const face of tensorFaceLoads(view.load?.magnitude, 'all', view.selected)) {
      const normal = new THREE.Vector3();
      normal[face.normal] = face.faceSign;
      const colors = new Set(face.components.map(entry => tensorComponentMeaning(entry.component, entry.value).color));
      const color = colors.size === 1 ? [...colors][0] : '#7c3aed';
      const grip = new THREE.Group();
      grip.position.copy(normal).multiplyScalar(.52);
      grip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
      grip.userData = {anchor: grip.position.toArray(), normal: face.normal, faceSign: face.faceSign,
        components: face.components.map(entry => entry.component)};
      grip.add(new THREE.Mesh(gripGeometry(), new THREE.MeshPhongMaterial({color, shininess: 90,
        transparent: true, opacity: .92})));
      const loop = new THREE.Mesh(new THREE.TorusGeometry(.043, .009, 8, 24),
        new THREE.MeshPhongMaterial({color: '#f8fafc', shininess: 100}));
      loop.position.z = .044;
      grip.add(loop);
      grips.add(grip);
    }
  }
  return {setView, update, reset: () => update(0), map};
}
