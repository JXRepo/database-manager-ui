import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {tensorArrows, formatTensorValue} from './mechanical-bc-tensor.js';
import {createTensorPanel} from './mechanical-bc-tensor-panel.js';

const VERTICES = ["V000", "V100", "V010", "V110", "V001", "V101", "V011", "V111"];
const AXIS_DIRECTIONS = {
  X: new THREE.Vector3(1, 0, 0),
  Y: new THREE.Vector3(0, 1, 0),
  Z: new THREE.Vector3(0, 0, 1),
};
const STATUS_COLORS = {
  loaded: "#dc2626",
  fixed: "#2563eb",
  mixed: "#7c3aed",
  empty: "#64748b",
};
const WHOLE_COLOR = "#a21caf";
const WHOLE_FIXED_COLOR = "#047857";
const THREE_ARROW_OFFSETS = [-0.24, 0, 0.24];

function readMechanicalBcItems() {
  const script = document.getElementById("mechanical-bc-data");

  if (!script) {
    return [];
  }

  try {
    const parsed = JSON.parse(script.textContent || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function vertexCoordinates(vertexName) {
  const bits = String(vertexName || "").replace(/^V/i, "").padEnd(3, "0");

  return new THREE.Vector3(
    bits[0] === "1" ? 0.5 : -0.5,
    bits[1] === "1" ? 0.5 : -0.5,
    bits[2] === "1" ? 0.5 : -0.5
  );
}

function pointsFromVertices(vertexNames) {
  return (vertexNames || []).map(vertexCoordinates);
}

function averagePoints(points) {
  if (!points.length) {
    return new THREE.Vector3();
  }

  const total = points.reduce(
    (sum, point) => sum.add(point),
    new THREE.Vector3()
  );

  return total.divideScalar(points.length);
}

function directionVector3d(direction) {
  return (AXIS_DIRECTIONS[direction] || AXIS_DIRECTIONS.X).clone();
}

function getLoadDirectionSigns(magnitude) {
  const values = (Array.isArray(magnitude) ? magnitude.flat(Infinity) : [magnitude])
    .filter(value => typeof value === 'number' && Number.isFinite(value) && value !== 0);
  return [-1, 1].filter(sign => values.some(value => Math.sign(value) === sign));
}

function getBoundaryConditionMarkerColor(item) {
  const statuses = (item.axes || []).map(axis => String(axis.status || "").toLowerCase());
  const hasLoaded = item.is_tensor_load || statuses.includes("loaded");
  const hasFixed = statuses.includes("fixed");

  if (hasLoaded && hasFixed) {
    return STATUS_COLORS.mixed;
  }

  if (hasLoaded) {
    return STATUS_COLORS.loaded;
  }

  if (hasFixed) {
    return STATUS_COLORS.fixed;
  }

  return STATUS_COLORS.empty;
}

function formatBoundaryConditionHover(item) {
  if (item.is_tensor_load) {
    return `${item.vertex || "Whole cube"}\n${item.loading_type} tensor: loaded`;
  }

  const axes = (item.axes || []).map(axis => {
    const status = String(axis.status || "empty").toLowerCase();
    return `${axis.direction}: ${status}`;
  });

  return [item.vertex || item.target_type || "Boundary condition", item.quantity_label || '']
    .concat(axes)
    .filter(Boolean)
    .join("\n");
}

function formatAxisLoadHover(item, axis) {
  const location = item.target_type === 'Whole cube' ? 'Whole cube'
    : `${item.target_type || 'Boundary'} · ${item.vertex || ''}`;
  return [location, item.quantity_label || item.loading_type || 'Load',
    `${axis.direction}: ${axis.status}`, axis.load_summary || 'No load value supplied'].join('\n');
}

function createMaterials() {
  return {
    cubeSurface: new THREE.MeshBasicMaterial({
      color: "#e0f2fe",
      transparent: true,
      opacity: 0.18,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
    cubeSheen: new THREE.MeshBasicMaterial({
      color: "#ffffff",
      transparent: true,
      opacity: 0.1,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
    cubeEdgeHalo: new THREE.LineBasicMaterial({
      color: "#93c5fd",
      transparent: true,
      opacity: 0.42,
      depthWrite: false,
    }),
    cubeEdgeLine: new THREE.LineBasicMaterial({
      color: "#7c9fca",
      transparent: true,
      opacity: 0.96,
      depthWrite: false,
    }),
    vertex: new THREE.MeshStandardMaterial({
      color: "#ffffff",
      roughness: 0.32,
      metalness: 0.04,
      emissive: "#dbeafe",
      emissiveIntensity: 0.04,
    }),
    loaded: new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.loaded,
      roughness: 0.34,
      metalness: 0.06,
    }),
    fixed: new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.fixed,
      roughness: 0.36,
      metalness: 0.06,
    }),
    whole: new THREE.MeshStandardMaterial({
      color: WHOLE_COLOR,
      roughness: 0.34,
      metalness: 0.06,
    }),
    wholeFixed: new THREE.MeshStandardMaterial({
      color: WHOLE_FIXED_COLOR,
      roughness: 0.36,
      metalness: 0.06,
    }),
    mixed: new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.mixed,
      roughness: 0.34,
      metalness: 0.06,
    }),
    empty: new THREE.MeshStandardMaterial({
      color: STATUS_COLORS.empty,
      roughness: 0.42,
      metalness: 0.04,
    }),
    edgeLineHighlight: new THREE.MeshBasicMaterial({
      color: "#facc15",
      depthWrite: false,
    }),
    faceHighlight: new THREE.MeshBasicMaterial({
      color: "#f59e0b",
      transparent: true,
      opacity: 0.34,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  };
}

function materialForItem(item, materials) {
  const color = getBoundaryConditionMarkerColor(item);

  if (color === STATUS_COLORS.loaded) {
    return materials.loaded;
  }

  if (color === STATUS_COLORS.fixed) {
    return materials.fixed;
  }

  if (color === STATUS_COLORS.mixed) {
    return materials.mixed;
  }

  return materials.empty;
}

function makeCylinderBetween(start, end, radius, material, radialSegments = 24) {
  const direction = end.clone().sub(start);
  const length = direction.length();

  if (length < 0.0001) {
    return null;
  }

  const geometry = new THREE.CylinderGeometry(radius, radius, length, radialSegments);
  const mesh = new THREE.Mesh(geometry, material);
  const center = start.clone().add(end).multiplyScalar(0.5);

  mesh.position.copy(center);
  mesh.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    direction.clone().normalize()
  );

  return mesh;
}

function makeConeAt(tip, direction, radius, length, material) {
  const unit = direction.clone().normalize();
  const geometry = new THREE.ConeGeometry(radius, length, 32);
  const cone = new THREE.Mesh(geometry, material);

  cone.position.copy(tip.clone().sub(unit.clone().multiplyScalar(length / 2)));
  cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), unit);

  return cone;
}

function addMesh(group, mesh, tooltip, selectableMeshes) {
  if (!mesh) {
    return null;
  }

  if (tooltip) {
    mesh.userData.tooltip = tooltip;
    selectableMeshes.push(mesh);
  }

  group.add(mesh);
  return mesh;
}

function createSphere(position, radius, material, tooltip, group, selectableMeshes) {
  const geometry = new THREE.SphereGeometry(radius, 32, 20);
  const mesh = new THREE.Mesh(geometry, material);

  mesh.position.copy(position);
  addMesh(group, mesh, tooltip, selectableMeshes);
  return mesh;
}

function getPerpendicularVector3d(vector) {
  const reference = Math.abs(vector.z) < 0.9
    ? new THREE.Vector3(0, 0, 1)
    : new THREE.Vector3(0, 1, 0);

  return new THREE.Vector3().crossVectors(vector, reference).normalize();
}

function fixedMarkerOutwardVector(point, direction) {
  if (direction === "X") {
    return new THREE.Vector3(point.x < 0 ? -1 : 1, 0, 0);
  }

  if (direction === "Y") {
    return new THREE.Vector3(0, point.y < 0 ? -1 : 1, 0);
  }

  return new THREE.Vector3(0, 0, point.z < 0 ? -1 : 1);
}

function createArrow(origin, axis, sign, materials, group, tooltip, selectableMeshes, lengthScale = 1, sizeScale = 1) {
  const direction = directionVector3d(axis.direction).multiplyScalar(sign).normalize();
  const start = origin.clone().add(direction.clone().multiplyScalar(0.075 * sizeScale));
  const shaftEnd = origin.clone().add(direction.clone().multiplyScalar(0.29 * lengthScale * sizeScale));
  const tip = origin.clone().add(direction.clone().multiplyScalar(0.39 * lengthScale * sizeScale));
  const shaft = makeCylinderBetween(start, shaftEnd, 0.012 * sizeScale, materials.loaded);
  const head = makeConeAt(tip, direction, 0.04 * sizeScale, 0.105 * sizeScale, materials.loaded);

  addMesh(group, shaft, tooltip, selectableMeshes);
  addMesh(group, head, tooltip, selectableMeshes);
  return [shaft, head];
}

function drawLoadedAxesAt(origins, item, materials, group, selectableMeshes, sizeScale = 1, opposingSizeScale = sizeScale, edgeDirection = "") {
  (item.axes || [])
    .filter(axis => axis.status === "loaded")
    .forEach(axis => {
      const tooltip = formatAxisLoadHover(item, axis);
      const signs = getLoadDirectionSigns(axis.magnitude);
      const arrowSize = signs.length > 1 ? opposingSizeScale : sizeScale;
      const arrowLength = signs.length > 1 ? 0.82 : 1;
      const originOffset = axis.direction === edgeDirection
        ? 0.39 * arrowLength * (arrowSize - Math.min(arrowSize, 0.35))
        : 0;
      origins.forEach(origin => {
        signs.forEach(sign => {
          // Extend parallel shafts back from their tips to keep the heads inside the edge.
          const arrowOrigin = origin.clone().addScaledVector(directionVector3d(axis.direction), -sign * originOffset);
          createArrow(arrowOrigin, axis, sign, materials, group, tooltip, selectableMeshes, arrowLength, arrowSize);
        });
      });
    });
}

function createClampMarker(origin, item, materials, group, selectableMeshes, {sizeScale = 1, viewFacing = false, axes = item.axes} = {}) {
  const fixedAxes = (axes || []).filter(axis => axis.status === "fixed");
  const tooltip = formatBoundaryConditionHover(item);

  fixedAxes.forEach(axis => {
    const anchor = origin;
    const outward = fixedMarkerOutwardVector(anchor, axis.direction).normalize();
    const tangent = getPerpendicularVector3d(outward);
    const guideStart = anchor.clone().add(outward.clone().multiplyScalar(0.045 * sizeScale));
    const plateCenter = anchor.clone().add(outward.clone().multiplyScalar(0.17 * sizeScale));
    const guideEnd = plateCenter.clone();
    const halfBar = 0.07 * sizeScale;

    addMesh(
      group,
      makeCylinderBetween(guideStart, guideEnd, 0.01 * sizeScale, materials.fixed, 18),
      tooltip,
      selectableMeshes
    );
    const crossbar = addMesh(
      group,
      makeCylinderBetween(
        plateCenter.clone().add(tangent.clone().multiplyScalar(-halfBar)),
        plateCenter.clone().add(tangent.clone().multiplyScalar(halfBar)),
        0.012 * sizeScale,
        materials.fixed,
        18
      ),
      tooltip,
      selectableMeshes
    );
    if (viewFacing) {
      crossbar.userData.fixedDirection = outward;
    } else {
      const secondTangent = new THREE.Vector3().crossVectors(outward, tangent).normalize();
      addMesh(
        group,
        makeCylinderBetween(
          plateCenter.clone().add(secondTangent.clone().multiplyScalar(-halfBar * 0.72)),
          plateCenter.clone().add(secondTangent.clone().multiplyScalar(halfBar * 0.72)),
          0.01 * sizeScale,
          materials.fixed,
          18
        ),
        tooltip,
        selectableMeshes
      );
    }
  });
}

function orientFixedCrossbar(crossbar, camera) {
  const start = crossbar.position.clone().project(camera);
  const end = crossbar.position.clone()
    .addScaledVector(crossbar.userData.fixedDirection, 0.01)
    .project(camera);
  const aspect = camera.isOrthographicCamera
    ? (camera.right - camera.left) / (camera.top - camera.bottom)
    : camera.aspect;
  const screenX = (end.x - start.x) * aspect;
  const screenY = end.y - start.y;
  const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  const tangent = right.clone().multiplyScalar(-screenY).addScaledVector(up, screenX);

  if (tangent.lengthSq() < 1e-12) {
    tangent.copy(right);
  }

  crossbar.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent.normalize());
}

function getFaceConstantAxis(points) {
  const axes = ["x", "y", "z"];

  return axes.find(axis => {
    const first = points[0] ? points[0][axis] : 0;
    return points.every(point => Math.abs(point[axis] - first) < 0.001);
  }) || "";
}

function getOrderedFacePoints(vertexNames) {
  const points = pointsFromVertices(vertexNames);

  if (points.length !== 4) {
    return points;
  }

  const constantAxis = getFaceConstantAxis(points);
  const projectedAxes = ["x", "y", "z"].filter(axis => axis !== constantAxis);
  const center = averagePoints(points);

  return points.slice().sort((first, second) => {
    const firstAngle = Math.atan2(
      first[projectedAxes[1]] - center[projectedAxes[1]],
      first[projectedAxes[0]] - center[projectedAxes[0]]
    );
    const secondAngle = Math.atan2(
      second[projectedAxes[1]] - center[projectedAxes[1]],
      second[projectedAxes[0]] - center[projectedAxes[0]]
    );

    return firstAngle - secondAngle;
  });
}

function createFaceMesh(points, material) {
  const geometry = new THREE.BufferGeometry();
  const vertices = new Float32Array([
    points[0].x, points[0].y, points[0].z,
    points[1].x, points[1].y, points[1].z,
    points[2].x, points[2].y, points[2].z,
    points[0].x, points[0].y, points[0].z,
    points[2].x, points[2].y, points[2].z,
    points[3].x, points[3].y, points[3].z,
  ]);

  geometry.setAttribute("position", new THREE.BufferAttribute(vertices, 3));
  geometry.computeVertexNormals();

  return new THREE.Mesh(geometry, material);
}

function createTextSprite(text, color = "#334155", fontSize = 42, worldScale = 0.07) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const padding = 16;

  context.font = `700 ${fontSize}px Arial, sans-serif`;
  const width = Math.ceil(context.measureText(text).width + (padding * 2));
  const height = fontSize + (padding * 2);
  canvas.width = width;
  canvas.height = height;

  context.font = `700 ${fontSize}px Arial, sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = color;
  context.fillText(text, width / 2, height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthTest: false,
  });
  const sprite = new THREE.Sprite(material);
  sprite.userData.fontSize = fontSize;
  sprite.scale.set(width / height * worldScale, worldScale, 1);
  return sprite;
}

function addVertexLabels(group, vertices = VERTICES) {
  vertices.forEach(vertex => {
    const position = vertexCoordinates(vertex);
    const label = createTextSprite(vertex, "#334155", 48, 0.052);
    const offset = position.clone().normalize().multiplyScalar(0.28);

    label.material.sizeAttenuation = false;
    label.userData.textPixelHeight = 14;
    label.renderOrder = 10;

    label.position.copy(position.clone().add(offset));
    label.userData.vertexLabelBase = label.position.clone();
    group.add(label);
  });
}

function restoreVertexLabelPositions(group) {
  group.traverse(label => {
    if (label.userData.vertexLabelBase) label.position.copy(label.userData.vertexLabelBase);
  });
}

function avoidWholeCubeLabelOverlap(root, meshes, camera, viewport, container) {
  if (!meshes.length) return;
  const {width, height} = viewport;
  const overlaps = (first, second) => first.left < second.right && first.right > second.left
    && first.top < second.bottom && first.bottom > second.top;
  const rectangle = (x, y, halfWidth, halfHeight) => ({
    left: x - halfWidth, right: x + halfWidth, top: y - halfHeight, bottom: y + halfHeight,
  });
  const obstacles = meshes.map(mesh => {
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const box = mesh.geometry.boundingBox;
    const bounds = {left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity};
    for (const x of [box.min.x, box.max.x]) {
      for (const y of [box.min.y, box.max.y]) {
        for (const z of [box.min.z, box.max.z]) {
          const point = new THREE.Vector3(x, y, z).applyMatrix4(mesh.matrixWorld).project(camera);
          const screenX = (point.x + 1) * width / 2;
          const screenY = (1 - point.y) * height / 2;
          bounds.left = Math.min(bounds.left, screenX - 3);
          bounds.right = Math.max(bounds.right, screenX + 3);
          bounds.top = Math.min(bounds.top, screenY - 3);
          bounds.bottom = Math.max(bounds.bottom, screenY + 3);
        }
      }
    }
    return bounds;
  });
  const containerRect = container.getBoundingClientRect();
  container.parentElement.querySelectorAll(".bc-axis-overlay, [data-bc-reset], .bc-whole-heading")
    .forEach(element => {
      const bounds = element.getBoundingClientRect();
      obstacles.push({left: bounds.left - containerRect.left - 3, right: bounds.right - containerRect.left + 3,
        top: bounds.top - containerRect.top - 3, bottom: bounds.bottom - containerRect.top + 3});
    });
  const labels = [];
  root.traverseVisible(label => {
    if (!label.userData.vertexLabelBase) return;
    const point = label.getWorldPosition(new THREE.Vector3()).project(camera);
    const texture = label.material.map.image;
    const pixels = label.userData.textPixelHeight / label.userData.fontSize;
    const x = (point.x + 1) * width / 2;
    const y = (1 - point.y) * height / 2;
    const halfWidth = texture.width * pixels / 2 + 2;
    const halfHeight = texture.height * pixels / 2 + 2;
    labels.push({label, point, x, y, halfWidth, halfHeight, bounds: rectangle(x, y, halfWidth, halfHeight)});
  });
  labels.forEach(entry => {
    const blocked = [...obstacles, ...labels.filter(other => other !== entry).map(other => other.bounds)];
    const fits = bounds => bounds.left >= 4 && bounds.right <= width - 4 && bounds.top >= 4
      && bounds.bottom <= height - 4 && !blocked.some(other => overlaps(bounds, other));
    if (fits(entry.bounds)) return;
    for (const distance of [12, 24, 36, 48, 60, 72, 84]) {
      for (let direction = 0; direction < 8; direction += 1) {
        const angle = direction * Math.PI / 4;
        const x = Math.max(entry.halfWidth + 4, Math.min(width - entry.halfWidth - 4, entry.x + Math.cos(angle) * distance));
        const y = Math.max(entry.halfHeight + 4, Math.min(height - entry.halfHeight - 4, entry.y + Math.sin(angle) * distance));
        const bounds = rectangle(x, y, entry.halfWidth, entry.halfHeight);
        if (!fits(bounds)) continue;
        entry.bounds = bounds;
        const position = new THREE.Vector3(x / width * 2 - 1, 1 - y / height * 2, entry.point.z).unproject(camera);
        entry.label.position.copy(entry.label.parent.worldToLocal(position));
        return;
      }
    }
  });
}

function getHighlightedEdgeKeys(items) {
  const edges = new Set();

  items.forEach(item => {
    if (item.target_type !== "Edge" || item.is_defined === false || item.is_tensor_load
      || !(item.axes || []).some(axis => axis.status === "loaded" || axis.status === "fixed")) {
      return;
    }

    const vertices = (Array.isArray(item.vertices) ? item.vertices : [])
      .map(vertex => String(vertex).toUpperCase());
    if (vertices.length !== 2 || !vertices.every(vertex => VERTICES.includes(vertex))) {
      return;
    }

    const points = vertices.map(vertexCoordinates);
    const differingAxes = ["x", "y", "z"].filter(axis => points[0][axis] !== points[1][axis]);
    if (differingAxes.length === 1) {
      edges.add(vertices.sort().join("|"));
    }
  });

  return edges;
}

function createCubeWireBox(size, material, renderOrder, excludedEdges = new Set()) {
  const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size, size, size));
  if (excludedEdges.size) {
    const points = geometry.getAttribute("position");
    const positions = [];

    for (let index = 0; index < points.count; index += 2) {
      const key = [index, index + 1].map(pointIndex => {
        const coordinates = [points.getX(pointIndex), points.getY(pointIndex), points.getZ(pointIndex)];
        return `V${coordinates.map(coordinate => coordinate > 0 ? "1" : "0").join("")}`;
      }).sort().join("|");

      if (!excludedEdges.has(key)) {
        positions.push(...points.array.slice(index * 3, index * 3 + 6));
      }
    }

    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  }
  const edges = new THREE.LineSegments(geometry, material);

  edges.renderOrder = renderOrder;
  return edges;
}

function drawGlassCubeEdges(group, materials, excludedEdges) {
  group.add(createCubeWireBox(1.018, materials.cubeEdgeHalo, 2, excludedEdges));
  group.add(createCubeWireBox(1.006, materials.cubeEdgeLine, 3, excludedEdges));
}

function drawBaseCube(group, materials, items = []) {
  const cube = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), materials.cubeSurface);
  const sheen = new THREE.Mesh(new THREE.BoxGeometry(1.018, 1.018, 1.018), materials.cubeSheen);

  group.add(cube);
  group.add(sheen);
  drawGlassCubeEdges(group, materials, getHighlightedEdgeKeys(items));

  VERTICES.forEach(vertex => {
    createSphere(vertexCoordinates(vertex), 0.032, materials.vertex, `${vertex}\nNo boundary condition`, group, []);
  });
}

function drawPointCondition(item, materials, group, selectableMeshes) {
  const point = vertexCoordinates(item.vertex);
  const tooltip = formatBoundaryConditionHover(item);

  createSphere(point, 0.052, materialForItem(item, materials), tooltip, group, selectableMeshes);
  drawLoadedAxesAt([point], item, materials, group, selectableMeshes);
  createClampMarker(point, item, materials, group, selectableMeshes, {viewFacing: true});
}

function drawEdgeCondition(item, materials, group, selectableMeshes) {
  const points = pointsFromVertices(item.vertices);

  if (points.length !== 2) {
    return;
  }

  const tooltip = formatBoundaryConditionHover(item);
  const hasConstraint = (item.axes || []).some(axis => axis.status === "loaded" || axis.status === "fixed");
  const edge = hasConstraint
    ? makeCylinderBetween(points[0], points[1], 0.015, materials.edgeLineHighlight, 18)
    : new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), materials.cubeEdgeLine);
  const edgeVector = points[1].clone().sub(points[0]).normalize();
  const center = averagePoints(points);
  const markerOrigins = THREE_ARROW_OFFSETS
    .map(offset => center.clone().addScaledVector(edgeVector, offset));
  const edgeDirection = Object.keys(AXIS_DIRECTIONS).find(direction => Math.abs(edgeVector.dot(AXIS_DIRECTIONS[direction])) > 0.999);

  if (edge) {
    // Keep the thicker edge behind arrows and constraint markers
    edge.renderOrder = hasConstraint ? -1 : 4;
    addMesh(group, edge, tooltip, selectableMeshes);
  }
  drawLoadedAxesAt(markerOrigins, item, materials, group, selectableMeshes, 0.65, 0.45, edgeDirection);
  createClampMarker(markerOrigins[1], item, materials, group, selectableMeshes, {sizeScale: 0.65, viewFacing: true});
}

function getFaceArrowOrigins(points, direction, offsets = [-0.42, -0.21, 0, 0.21, 0.42]) {
  const center = averagePoints(points);
  const firstTangent = points[1].clone().sub(points[0]);
  const secondTangent = points[3].clone().sub(points[0]);
  const normal = new THREE.Vector3().crossVectors(firstTangent, secondTangent).normalize();
  const spread = new THREE.Vector3().crossVectors(normal, directionVector3d(direction));

  if (spread.lengthSq() < 0.0001) {
    spread.copy(firstTangent);
    if (spread.lengthSq() < 0.0001) {
      spread.copy(secondTangent);
    }
  }

  spread.normalize();
  return offsets
    .map(offset => center.clone().addScaledVector(spread, offset));
}

function drawFaceCondition(item, materials, group, selectableMeshes) {
  const points = getOrderedFacePoints(item.vertices);

  if (points.length !== 4) {
    return;
  }

  const tooltip = formatBoundaryConditionHover(item);
  const center = averagePoints(points);
  addMesh(group, createFaceMesh(points, materials.faceHighlight), tooltip, selectableMeshes);
  (item.axes || []).filter(axis => axis.status === "loaded").forEach(axis => {
    const origins = getFaceArrowOrigins(points, axis.direction, THREE_ARROW_OFFSETS);
    const loadTooltip = formatAxisLoadHover(item, axis);
    const signs = getLoadDirectionSigns(axis.magnitude);
    const sizeScale = signs.length > 1 ? 0.45 : 0.5;
    const lengthScale = signs.length > 1 ? 0.82 : 1;

    origins.forEach(origin => {
      signs.forEach(sign => {
        createArrow(origin, axis, sign, materials, group, loadTooltip, selectableMeshes, lengthScale, sizeScale);
      });
    });
  });
  createClampMarker(center, item, materials, group, selectableMeshes);
}

function wholeCubeAnchor3d(direction, distance) {
  return directionVector3d(direction).multiplyScalar(distance);
}

function drawWholeCubeCondition(item, materials, group, selectableMeshes) {
  const wholeMaterials = {loaded: materials.whole, fixed: materials.wholeFixed};
  // The outer layer leaves room for local face, edge and point markers.
  const distance = 0.9;
  (item.axes || []).filter(axis => axis.status === "loaded").forEach(axis => {
    const tooltip = formatAxisLoadHover(item, axis);
    const signs = getLoadDirectionSigns(axis.magnitude);
    signs.forEach(sign => {
      const origin = wholeCubeAnchor3d(axis.direction, sign * distance);
      createArrow(origin, axis, sign, wholeMaterials, group, tooltip, selectableMeshes,
        signs.length > 1 ? 0.82 : 1, 1.3);
    });
  });
  (item.axes || []).filter(axis => axis.status === "fixed").forEach(axis => {
    const anchor = wholeCubeAnchor3d(axis.direction, distance + 0.1);
    createClampMarker(anchor, item, wholeMaterials, group, selectableMeshes,
      {sizeScale: 2, viewFacing: true, axes: [axis]});
  });
}

function createWholeCubeControls(container, items, state, materials, tooltip) {
  const heading = document.createElement("label");
  heading.className = "bc-whole-heading";
  const select = document.createElement("select");
  select.className = "bc-whole-select";
  select.setAttribute("aria-label", "Whole cube boundary condition");
  items.forEach(({item, index}, position) => {
    const option = document.createElement("option");
    option.value = String(position);
    option.textContent = `Condition ${position + 1} · ${item.quantity_label || item.loading_type || "constraints"}`;
    select.appendChild(option);
  });
  if (items.length > 1) {
    heading.appendChild(document.createTextNode('Whole cube '));
    heading.appendChild(select);
  } else {
    heading.textContent = `Whole cube · ${items[0].item.quantity_label || 'Constraints'}`;
  }
  container.parentElement.insertAdjacentElement('afterend', heading);

  function showCondition(position) {
    state.wholeRoot.traverse(object => {
      object.geometry?.dispose();
      if (object.isSprite) {
        object.material.map?.dispose();
        object.material.dispose();
      }
    });
    state.wholeRoot.clear();
    state.wholeMeshes.length = 0;
    const {item, index} = items[position];
    container.dataset.wholeSourceIndex = String(index);
    drawWholeCubeCondition(item, materials, state.wholeRoot, state.wholeMeshes);
    state.root.userData.hasWholeGlyphs = state.wholeMeshes.length > 0;
    tooltip.style.opacity = "0";
    state.fitScene();
  }

  select.addEventListener("change", () => showCondition(Number(select.value)));
  showCondition(0);
}

function drawBoundaryConditions(items, group, materials, selectableMeshes) {
  items
    .filter(item => item.is_defined !== false)
    .forEach(item => {
      if (item.target_type === "Whole cube") {
        return;
      }

      if (item.target_type === "Face") {
        drawFaceCondition(item, materials, group, selectableMeshes);
        return;
      }

      if (item.target_type === "Edge") {
        drawEdgeCondition(item, materials, group, selectableMeshes);
        return;
      }

      drawPointCondition(item, materials, group, selectableMeshes);
    });
}

function createTooltip(container) {
  const tooltip = document.createElement("div");

  tooltip.style.position = "absolute";
  tooltip.style.pointerEvents = "none";
  tooltip.style.padding = "7px 9px";
  tooltip.style.borderRadius = "8px";
  tooltip.style.background = "#111827";
  tooltip.style.color = "#ffffff";
  tooltip.style.font = "600 12px/1.35 Arial, sans-serif";
  tooltip.style.whiteSpace = "pre-wrap";
  tooltip.style.overflowWrap = "anywhere";
  tooltip.style.boxShadow = "0 10px 24px rgba(15, 23, 42, 0.22)";
  tooltip.style.opacity = "0";
  tooltip.style.transform = "translate(-50%, calc(-100% - 12px))";
  tooltip.style.transition = "opacity 0.12s ease";
  container.appendChild(tooltip);

  return tooltip;
}

function setupTooltip(container, camera, selectableMeshes, tooltip, onHighlight = () => {}, getView = null) {
  const raycaster = new THREE.Raycaster();
  raycaster.params.Line.threshold = 0.02;
  const pointer = new THREE.Vector2();
  const clear = () => {
    tooltip.style.opacity = '0';
    onHighlight('');
  };

  container.addEventListener("pointermove", event => {
    if (event.buttons) {
      clear();
      return;
    }
    const rect = container.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const view = getView ? getView(y) : {camera, meshes: selectableMeshes, left: 0, top: 0, width: rect.width, height: rect.height};
    if (!view || x < view.left || x > view.left + view.width || y < view.top || y > view.top + view.height) {
      tooltip.style.opacity = "0";
      onHighlight('');
      return;
    }
    pointer.x = ((x - view.left) / view.width) * 2 - 1;
    pointer.y = -(((y - view.top) / view.height) * 2 - 1);
    raycaster.setFromCamera(pointer, view.camera);

    const hits = raycaster.intersectObjects(view.meshes, false);
    const hit = hits.find(item => item.object.userData.tooltip);

    if (!hit) {
      tooltip.style.opacity = "0";
      onHighlight('');
      return;
    }

    onHighlight(hit.object.userData.component || '');
    tooltip.textContent = hit.object.userData.tooltip;
    tooltip.style.maxWidth = `${Math.max(rect.width - 16, 1)}px`;
    tooltip.style.transform = 'none';
    const left = Math.max(8, Math.min(x - tooltip.offsetWidth / 2, rect.width - tooltip.offsetWidth - 8));
    const top = y >= tooltip.offsetHeight + 12 ? y - tooltip.offsetHeight - 12 : y + 12;
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${Math.max(8, Math.min(top, rect.height - tooltip.offsetHeight - 8))}px`;
    tooltip.style.opacity = "1";
  });

  container.addEventListener('pointerleave', clear);
  window.addEventListener('scroll', clear, true);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') clear();
  });
}

function disposeTensorGroup(group) {
  const materials = new Set();
  group.traverse(object => {
    object.geometry?.dispose();
    if (object.material) materials.add(object.material);
  });
  materials.forEach(material => {
    material.map?.dispose();
    material.dispose();
  });
  group.clear();
}

function drawTensorLoading(view, group, selectableMeshes, hasLocalMarkers = false) {
  const isStrain = view.item.loading_type === 'strain';
  if (view.shapeMatrix) {
    const outline = createCubeWireBox(1, new THREE.LineBasicMaterial({color: '#7c3aed'}), 5);
    const positions = outline.geometry.attributes.position;
    for (let index = 0; index < positions.count; index += 1) {
      const point = [positions.getX(index), positions.getY(index), positions.getZ(index)];
      const moved = point.map((value, row) => value + view.shapeMatrix[row]
        .reduce((sum, amount, column) => sum + amount * point[column], 0));
      positions.setXYZ(index, ...moved);
    }
    positions.needsUpdate = true;
    outline.geometry.computeBoundingSphere();
    group.add(outline);
    return;
  }

  const componentMaterials = new Map();
  const sizeScale = 1.3;
  const tipDistance = 0.39 * sizeScale;
  const arrowCenter = (0.075 + 0.39) * sizeScale / 2;
  const shearLaneOffset = 0.28;
  for (const arrow of tensorArrows(view.load?.magnitude, view.filter, view.selected)) {
    if (!componentMaterials.has(arrow.component)) {
      componentMaterials.set(arrow.component, new THREE.MeshStandardMaterial({
        color: WHOLE_COLOR, roughness: 0.34, metalness: 0.06,
        transparent: true, opacity: 1,
      }));
    }
    const material = componentMaterials.get(arrow.component);
    const normal = AXIS_DIRECTIONS[arrow.normal.toUpperCase()].clone().multiplyScalar(arrow.faceSign);
    const axis = {direction: arrow.direction.toUpperCase()};
    const direction = directionVector3d(axis.direction).multiplyScalar(arrow.sign);
    const normalDistance = hasLocalMarkers && arrow.direction !== arrow.normal ? 1.25 : 0.9;
    const origin = normal.clone().multiplyScalar(normalDistance);
    const tooltip = `${isStrain ? 'Strain guide' : 'Stress component'} ${arrow.component}: ${formatTensorValue(arrow.value)}${view.unit ? ` ${view.unit}` : ''}\n${arrow.faceSign > 0 ? '+' : '-'}${arrow.normal.toUpperCase()} face · ${arrow.sign > 0 ? '+' : '-'}${arrow.direction.toUpperCase()} direction`;
    if (arrow.direction === arrow.normal && arrow.value < 0) {
      origin.addScaledVector(normal, tipDistance);
    } else if (arrow.direction !== arrow.normal) {
      // Separate both shear directions from each other and the normal arrow
      const laneAxis = ['x', 'y', 'z'].find(key => key !== arrow.direction && key !== arrow.normal);
      origin[laneAxis] = shearLaneOffset * arrow.faceSign;
      origin.addScaledVector(direction, -arrowCenter);
    }
    const meshes = createArrow(origin, axis, arrow.sign, {loaded: material}, group,
      tooltip, selectableMeshes, 1, sizeScale);
    for (const mesh of meshes) {
      mesh.userData.component = arrow.component;
      mesh.userData.value = arrow.value;
    }
    const faceMaterial = new THREE.MeshBasicMaterial({
      color: WHOLE_COLOR, transparent: true, opacity: 0.055,
      side: THREE.DoubleSide, depthWrite: false,
    });
    const face = new THREE.Mesh(new THREE.PlaneGeometry(0.96, 0.96), faceMaterial);
    face.position.copy(normal.clone().multiplyScalar(0.505 + 'xyz'.indexOf(arrow.direction) * 0.002));
    face.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    face.userData.component = arrow.component;
    face.userData.tensorFace = true;
    // Faces provide a highlight; arrow hit targets choose individual components.
    group.add(face);
  }
}

function highlightTensor(group, component) {
  group.traverse(mesh => {
    if (!mesh.userData.component) return;
    const active = !component || mesh.userData.component === component;
    mesh.material.opacity = mesh.userData.tensorFace
      ? (component && active ? 0.18 : 0.055)
      : (active ? 1 : 0.18);
  });
}

function frameScene(camera, controls, root, container, cameraDirection) {
  restoreVertexLabelPositions(root);
  const bounds = new THREE.Box3().setFromObject(root);

  if (bounds.isEmpty()) {
    return;
  }

  const center = new THREE.Vector3();
  const sphere = new THREE.Sphere();

  bounds.getCenter(center);
  bounds.getBoundingSphere(sphere);

  if (root.userData.hasWholeGlyphs) {
    center.set(0, 0, 0);
    sphere.radius = 0;
    root.updateMatrixWorld(true);
    root.traverseVisible(object => {
      // Vertex labels use fixed screen pixels, not their shared unit geometry.
      if (!object.geometry || object.isSprite) return;
      if (!object.geometry.boundingSphere) object.geometry.computeBoundingSphere();
      const extent = object.geometry.boundingSphere.clone().applyMatrix4(object.matrixWorld);
      sphere.radius = Math.max(sphere.radius, extent.center.length() + extent.radius);
    });
  } else if (root.userData.tensorView) {
    center.set(0, 0, 0);
    sphere.radius = root.userData.tensorRadius;
  }

  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
  const verticalDistance = sphere.radius / Math.tan(verticalFov / 2);
  const horizontalDistance = sphere.radius / Math.tan(horizontalFov / 2);
  const padding = root.userData.hasWholeGlyphs ? 1.06
    : root.userData.tensorView ? 1.06 : container.clientWidth < 460 ? 1.42 : 1.16;
  const distance = Math.max(verticalDistance, horizontalDistance) * padding;

  controls.target.copy(center);
  camera.position.copy(center.clone().add(cameraDirection.clone().multiplyScalar(distance)));
  controls.minDistance = Math.max(distance * 0.48, 1.8);
  controls.maxDistance = Math.max(distance * 2.5, 5.4);
  camera.lookAt(center);
  controls.update();
}

function resetCameraView(camera, controls, root, container, cameraDirection) {
  frameScene(camera, controls, root, container, cameraDirection);
}

function createScene(container, hasWholeMarkers = false) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 100);
  camera.up.set(0, 0, 1);
  const wholeRoot = new THREE.Group();
  const wholeMeshes = [];
  const tensorMeshes = [];
  const mainViewport = {left: 0, top: 0, width: 1, height: 1};

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  const controls = new OrbitControls(camera, renderer.domElement);
  const axisOverlay = container.parentElement?.querySelector(".bc-axis-overlay");
  const axisLines = Array.from(axisOverlay?.querySelectorAll("line") || []);
  const axisLabels = Array.from(axisOverlay?.querySelectorAll("text") || []);
  const root = new THREE.Group();
  root.userData.hasWholeConditions = hasWholeMarkers;
  root.add(wholeRoot);
  const cameraDirection = new THREE.Vector3(1.45, 1.45, 1.15).normalize();
  const ambient = new THREE.AmbientLight("#ffffff", 1.35);
  const keyLight = new THREE.DirectionalLight("#ffffff", 2.35);
  const fillLight = new THREE.DirectionalLight("#dbeafe", 0.95);

  container.innerHTML = "";
  container.style.position = "relative";
  container.tabIndex = 0;
  if (hasWholeMarkers) container.setAttribute("role", "group");
  renderer.domElement.setAttribute("aria-label", "Mechanical boundary condition 3D viewer");
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  controls.target.set(0, 0, 0);
  controls.enableDamping = false;
  controls.enablePan = false;
  controls.rotateSpeed = 0.58;
  controls.zoomSpeed = 0.72;

  keyLight.position.set(2.8, -3.2, 3.4);
  fillLight.position.set(-2.2, 2.4, 2.2);
  scene.add(ambient);
  scene.add(keyLight);
  scene.add(fillLight);
  scene.add(root);

  function renderSceneOnce() {
    restoreVertexLabelPositions(root);
    camera.updateMatrixWorld();
    Object.keys(AXIS_DIRECTIONS).forEach((axis, index) => {
      const line = axisLines[index];
      const label = axisLabels[index];
      if (!line || !label) return;
      const direction = AXIS_DIRECTIONS[axis].clone().transformDirection(camera.matrixWorldInverse);
      const projectedLength = Math.hypot(direction.x, direction.y);
      const labelOffset = projectedLength > 0.001 ? 8 / projectedLength : 0;
      line.setAttribute("x1", "54");
      line.setAttribute("y1", "50");
      line.setAttribute("x2", String(54 + direction.x * 26));
      line.setAttribute("y2", String(50 - direction.y * 26));
      label.setAttribute("x", String(54 + direction.x * (26 + labelOffset)));
      label.setAttribute("y", String(projectedLength > 0.001
        ? 50 - direction.y * (26 + labelOffset) : 64));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("dominant-baseline", "middle");
    });
    // Keep vertex text readable at the same screen size across zoom and resize.
    const viewportHeight = mainViewport.height;
    const projectionHeight = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));

    root.traverse(child => {
      if (child.userData.fixedDirection) {
        // Only the crossbar turns; the stem retains its X, Y or Z direction.
        orientFixedCrossbar(child, camera);
      }
      if (child.userData.faceNormal) {
        child.visible = child.userData.tensorFaceSelected !== false
          && child.userData.faceNormal.dot(camera.position.clone().sub(child.position)) > 0;
      }
      if (!child.userData.textPixelHeight) return;
      const texture = child.material.map.image;
      const height = child.userData.textPixelHeight * (texture.height / child.userData.fontSize)
        * projectionHeight / viewportHeight;
      child.scale.set(height * texture.width / texture.height, height, 1);
    });
    root.updateMatrixWorld(true);
    avoidWholeCubeLabelOverlap(root, [...wholeMeshes, ...tensorMeshes], camera, mainViewport, container);
    renderer.render(scene, camera);
  }

  controls.addEventListener("change", renderSceneOnce);

  function resize() {
    const width = Math.max(container.clientWidth, 1);
    const height = Math.max(container.clientHeight || width, 1);
    mainViewport.width = width;
    mainViewport.height = height;

    camera.aspect = width / mainViewport.height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  }

  resize();
  const resizeObserver = new ResizeObserver(() => {
    resize();
    resetCameraView(camera, controls, root, container, cameraDirection);
    renderSceneOnce();
  });

  resizeObserver.observe(container);

  return {
    scene,
    camera,
    renderer,
    controls,
    root,
    wholeRoot,
    wholeMeshes,
    tensorMeshes,
    mainViewport,
    getHoverView(y, meshes) {
      return {...mainViewport, camera, meshes: [...meshes, ...wholeMeshes]};
    },
    resize,
    renderSceneOnce,
    fitScene: () => {
      const direction = camera.position.clone().sub(controls.target);
      frameScene(camera, controls, root, container,
        direction.lengthSq() ? direction.normalize() : cameraDirection);
      renderSceneOnce();
    },
    resetCameraView: () => {
      resetCameraView(camera, controls, root, container, cameraDirection);
      renderSceneOnce();
    },
  };
}

function renderMechanicalBcViewer() {
  const container = document.getElementById("mechanical-bc-cube");
  const items = readMechanicalBcItems();

  if (!container || !items.length) {
    return;
  }

  const wholeItems = items.map((item, index) => ({item, index}))
    .filter(({item}) => item.target_type === "Whole cube" && !item.is_tensor_load && item.is_defined !== false);
  const state = createScene(container, wholeItems.length > 0);
  const materials = createMaterials();
  const selectableMeshes = [];
  const tooltip = createTooltip(container);
  const tensorItems = items.filter(item => item.is_tensor_load);
  const scalarItems = items.filter(item => !item.is_tensor_load && item.is_defined !== false);
  const legend = container.closest('.bc-layout').querySelector('.bc-legend');
  const localItems = scalarItems.filter(item => item.target_type !== 'Whole cube');
  const localLoadLegend = legend.firstElementChild;
  localLoadLegend.hidden = !localItems.some(item => (item.axes || []).some(axis => axis.status === 'loaded'));
  legend.children[1].hidden = !localItems.some(item => (item.axes || []).some(axis => axis.status === 'fixed'));
  const hasLocalMarkers = scalarItems.some(item => item.target_type !== "Whole cube"
    && (item.axes || []).some(axis => axis.status === "loaded" || axis.status === "fixed"));
  const tensorGroup = new THREE.Group();
  let tensorPanel = null;
  let highlighted = '';

  drawBaseCube(state.root, materials, scalarItems);
  if (!tensorItems.length && !wholeItems.length) {
    addVertexLabels(state.root);
  } else if (scalarItems.length) {
    const namedVertices = new Set(scalarItems
      .filter(item => item.target_type !== "Whole cube")
      .flatMap(item => item.vertices || [])
      .map(vertex => String(vertex).toUpperCase()));
    addVertexLabels(state.root, VERTICES.filter(vertex => namedVertices.has(vertex)));
  }
  drawBoundaryConditions(items.filter(item => !item.is_tensor_load), state.root, materials, selectableMeshes);
  if (wholeItems.length) createWholeCubeControls(container, wholeItems, state, materials, tooltip);
  const staticMeshCount = selectableMeshes.length;
  function highlight(component) {
    if (highlighted === component) return;
    highlighted = component;
    highlightTensor(tensorGroup, component);
    tensorPanel?.highlight(component);
    state.renderSceneOnce();
  }
  if (tensorItems.length) {
    state.root.userData.tensorView = true;
    // A fixed envelope keeps the camera stable while components and loads change.
    state.root.userData.tensorRadius = scalarItems.length ? 1.7 : 1.55;
    state.root.add(tensorGroup);
    const faceLabels = [];
    for (const axis of ['x', 'y', 'z']) {
      for (const sign of [-1, 1]) {
        const label = createTextSprite(`${sign > 0 ? '+' : '-'}${axis.toUpperCase()}`, '#475569', 42, 0.13);
        label.material.sizeAttenuation = false;
        label.userData.textPixelHeight = 12;
        label.userData.faceNormal = AXIS_DIRECTIONS[axis.toUpperCase()].clone().multiplyScalar(sign);
        label.userData.tensorFaceAxis = axis;
        label.position[axis] = sign * 0.62;
        for (const other of ['x', 'y', 'z'].filter(other => other !== axis)) {
          label.position[other] = 0.32;
        }
        state.root.add(label);
        faceLabels.push(label);
      }
    }
    const legend = container.closest('.bc-layout').querySelector('.bc-legend');
    const loadLegend = legend.firstElementChild;
    loadLegend.querySelectorAll('line').forEach(line => line.setAttribute('stroke', STATUS_COLORS.loaded));
    const tensorLegend = loadLegend.cloneNode(true);
    tensorLegend.hidden = false;
    tensorLegend.dataset.tensorLegend = '';
    tensorLegend.querySelectorAll('line').forEach(line => line.setAttribute('stroke', WHOLE_COLOR));
    if (scalarItems.length) legend.appendChild(tensorLegend);
    else legend.replaceChildren(tensorLegend);
    const unitsElement = document.getElementById('plot-units-data');
    const units = unitsElement ? JSON.parse(unitsElement.textContent) : {};
    tensorPanel = createTensorPanel(document.querySelector('[data-bc-tensor-panel]'), items, units, view => {
      highlighted = '';
      disposeTensorGroup(tensorGroup);
      selectableMeshes.splice(staticMeshCount);
      state.tensorMeshes.length = 0;
      tooltip.style.opacity = '0';
      drawTensorLoading(view, tensorGroup, state.tensorMeshes, hasLocalMarkers);
      selectableMeshes.push(...state.tensorMeshes);
      faceLabels.forEach(label => {
        label.userData.tensorFaceSelected = !view.shapeMatrix
          && (!view.selected || label.userData.tensorFaceAxis === view.selected[1]);
      });
      tensorLegend.lastChild.textContent = view.shapeMatrix ? ' Strain shape illustration'
        : view.item.loading_type === 'strain' ? ' Whole cube strain guides' : ' Whole cube stress components';
      state.renderSceneOnce();
    }, highlight);
  }
  if (wholeItems.length) {
    const legend = container.closest('.bc-layout').querySelector('.bc-legend');
    const wholeLegend = document.createElement('span');
    wholeLegend.className = 'bc-legend-item';
    wholeLegend.innerHTML = `<svg width="48" height="16" viewBox="0 0 48 16" aria-hidden="true">
      <path d="M2 8h17m-6-5 6 5-6 5" fill="none"
        stroke="${WHOLE_COLOR}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      <path d="M27 8h15m0-6v12" fill="none"
        stroke="${WHOLE_FIXED_COLOR}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
    </svg>`;
    wholeLegend.appendChild(document.createTextNode(' Whole cube'));
    legend.appendChild(wholeLegend);
  }
  setupTooltip(container, state.camera, selectableMeshes, tooltip, highlight,
    y => state.getHoverView(y, selectableMeshes));
  state.resetCameraView();

  const resetButton = container.parentElement
    ? container.parentElement.querySelector("[data-bc-reset]")
    : null;

  if (resetButton) {
    resetButton.addEventListener("click", state.resetCameraView);
  }
  state.renderSceneOnce();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", renderMechanicalBcViewer);
} else {
  renderMechanicalBcViewer();
}
