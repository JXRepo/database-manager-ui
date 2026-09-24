import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

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
  if (Array.isArray(magnitude)) {
    const values = magnitude
      .flat(Infinity)
      .map(value => Number(value))
      .filter(value => Number.isFinite(value) && value !== 0);
    const hasPositive = values.some(value => value > 0);
    const hasNegative = values.some(value => value < 0);

    if (hasPositive && hasNegative) {
      return [-1, 1];
    }

    if (hasNegative) {
      return [-1];
    }

    return [1];
  }

  const value = Number(magnitude);
  return Number.isFinite(value) && value < 0 ? [-1] : [1];
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

  return [item.vertex || item.target_type || "Boundary condition"]
    .concat(axes)
    .join("\n");
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
    edgeHighlight: new THREE.MeshStandardMaterial({
      color: "#0f766e",
      roughness: 0.3,
      metalness: 0.06,
    }),
    faceHighlight: new THREE.MeshBasicMaterial({
      color: "#f59e0b",
      transparent: true,
      opacity: 0.34,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
    wholeCubeHighlight: new THREE.MeshBasicMaterial({
      color: "#c4b5fd",
      transparent: true,
      opacity: 0.24,
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

function createArrow(origin, axis, sign, materials, group, tooltip, selectableMeshes, lengthScale = 1) {
  const direction = directionVector3d(axis.direction).multiplyScalar(sign).normalize();
  const start = origin.clone().add(direction.clone().multiplyScalar(0.075));
  const shaftEnd = origin.clone().add(direction.clone().multiplyScalar(0.29 * lengthScale));
  const tip = origin.clone().add(direction.clone().multiplyScalar(0.39 * lengthScale));
  const shaft = makeCylinderBetween(start, shaftEnd, 0.012, materials.loaded);
  const head = makeConeAt(tip, direction, 0.04, 0.105, materials.loaded);

  addMesh(group, shaft, tooltip, selectableMeshes);
  addMesh(group, head, tooltip, selectableMeshes);
}

function drawLoadedAxesAt(origins, item, materials, group, selectableMeshes) {
  const tooltip = formatBoundaryConditionHover(item);

  (item.axes || [])
    .filter(axis => axis.status === "loaded")
    .forEach(axis => {
      const signs = getLoadDirectionSigns(axis.magnitude);
      origins.forEach(origin => {
        signs.forEach(sign => {
          createArrow(origin, axis, sign, materials, group, tooltip, selectableMeshes, signs.length > 1 ? 0.82 : 1);
        });
      });
    });
}

function createClampMarker(origin, item, materials, group, selectableMeshes) {
  const fixedAxes = (item.axes || []).filter(axis => axis.status === "fixed");
  const tooltip = formatBoundaryConditionHover(item);

  fixedAxes.forEach(axis => {
    const outward = fixedMarkerOutwardVector(origin, axis.direction).normalize();
    const tangent = getPerpendicularVector3d(outward);
    const secondTangent = new THREE.Vector3().crossVectors(outward, tangent).normalize();
    const guideStart = origin.clone().add(outward.clone().multiplyScalar(0.045));
    const plateCenter = origin.clone().add(outward.clone().multiplyScalar(0.17));
    const guideEnd = plateCenter.clone();
    const halfBar = 0.07;

    addMesh(
      group,
      makeCylinderBetween(guideStart, guideEnd, 0.01, materials.fixed, 18),
      tooltip,
      selectableMeshes
    );
    addMesh(
      group,
      makeCylinderBetween(
        plateCenter.clone().add(tangent.clone().multiplyScalar(-halfBar)),
        plateCenter.clone().add(tangent.clone().multiplyScalar(halfBar)),
        0.012,
        materials.fixed,
        18
      ),
      tooltip,
      selectableMeshes
    );
    addMesh(
      group,
      makeCylinderBetween(
        plateCenter.clone().add(secondTangent.clone().multiplyScalar(-halfBar * 0.72)),
        plateCenter.clone().add(secondTangent.clone().multiplyScalar(halfBar * 0.72)),
        0.01,
        materials.fixed,
        18
      ),
      tooltip,
      selectableMeshes
    );
  });
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

function addVertexLabels(group) {
  VERTICES.forEach(vertex => {
    const position = vertexCoordinates(vertex);
    const label = createTextSprite(vertex, "#334155", 48, 0.052);
    const offset = position.clone().normalize().multiplyScalar(0.28);

    label.material.sizeAttenuation = false;
    label.userData.textPixelHeight = 14;
    label.renderOrder = 10;

    label.position.copy(position.clone().add(offset));
    group.add(label);
  });
}

function createCubeWireBox(size, material, renderOrder) {
  const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(size, size, size));
  const edges = new THREE.LineSegments(geometry, material);

  edges.renderOrder = renderOrder;
  return edges;
}

function drawGlassCubeEdges(group, materials) {
  group.add(createCubeWireBox(1.018, materials.cubeEdgeHalo, 2));
  group.add(createCubeWireBox(1.006, materials.cubeEdgeLine, 3));
}

function drawBaseCube(group, materials) {
  const cube = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), materials.cubeSurface);
  const sheen = new THREE.Mesh(new THREE.BoxGeometry(1.018, 1.018, 1.018), materials.cubeSheen);

  group.add(cube);
  group.add(sheen);
  drawGlassCubeEdges(group, materials);

  VERTICES.forEach(vertex => {
    createSphere(vertexCoordinates(vertex), 0.032, materials.vertex, `${vertex}\nNo boundary condition`, group, []);
  });
}

function drawPointCondition(item, materials, group, selectableMeshes) {
  const point = vertexCoordinates(item.vertex);
  const tooltip = formatBoundaryConditionHover(item);

  createSphere(point, 0.052, materialForItem(item, materials), tooltip, group, selectableMeshes);
  drawLoadedAxesAt([point], item, materials, group, selectableMeshes);
  createClampMarker(point, item, materials, group, selectableMeshes);
}

function drawEdgeCondition(item, materials, group, selectableMeshes) {
  const points = pointsFromVertices(item.vertices);

  if (points.length !== 2) {
    return;
  }

  const tooltip = formatBoundaryConditionHover(item);
  const center = averagePoints(points);

  addMesh(
    group,
    makeCylinderBetween(points[0], points[1], 0.026, materials.edgeHighlight, 24),
    tooltip,
    selectableMeshes
  );
  createSphere(center, 0.058, materialForItem(item, materials), tooltip, group, selectableMeshes);
  drawLoadedAxesAt([center], item, materials, group, selectableMeshes);
  createClampMarker(center, item, materials, group, selectableMeshes);
}

function drawFaceCondition(item, materials, group, selectableMeshes) {
  const points = getOrderedFacePoints(item.vertices);

  if (points.length !== 4) {
    return;
  }

  const tooltip = formatBoundaryConditionHover(item);
  const center = averagePoints(points);
  const tangent = points[1].clone().sub(points[0]).normalize();
  const arrowOrigins = [
    center.clone().add(tangent.clone().multiplyScalar(-0.18)),
    center,
    center.clone().add(tangent.clone().multiplyScalar(0.18)),
  ];

  addMesh(group, createFaceMesh(points, materials.faceHighlight), tooltip, selectableMeshes);
  points.forEach((point, index) => {
    const next = points[(index + 1) % points.length];
    addMesh(
      group,
      makeCylinderBetween(point, next, 0.012, materials.edgeHighlight, 18),
      tooltip,
      selectableMeshes
    );
  });
  createSphere(center, 0.06, materialForItem(item, materials), tooltip, group, selectableMeshes);
  drawLoadedAxesAt(arrowOrigins, item, materials, group, selectableMeshes);
  createClampMarker(center, item, materials, group, selectableMeshes);
}

function drawWholeCubeCondition(item, materials, group, selectableMeshes) {
  const tooltip = formatBoundaryConditionHover(item);
  const center = new THREE.Vector3(0, 0, 0);
  const overlay = new THREE.Mesh(new THREE.BoxGeometry(1.08, 1.08, 1.08), materials.wholeCubeHighlight);
  const label = createTextSprite("Whole cube", "#6d28d9", 40, 0.076);

  label.position.set(-0.18, -0.02, 0.26);
  addMesh(group, overlay, tooltip, selectableMeshes);
  createSphere(center, 0.068, materialForItem(item, materials), tooltip, group, selectableMeshes);
  group.add(label);
  drawLoadedAxesAt([center], item, materials, group, selectableMeshes);
  createClampMarker(center, item, materials, group, selectableMeshes);
}

function drawBoundaryConditions(items, group, materials, selectableMeshes) {
  items
    .filter(item => item.is_defined !== false)
    .forEach(item => {
      if (item.target_type === "Whole cube") {
        drawWholeCubeCondition(item, materials, group, selectableMeshes);
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
  tooltip.style.whiteSpace = "pre";
  tooltip.style.boxShadow = "0 10px 24px rgba(15, 23, 42, 0.22)";
  tooltip.style.opacity = "0";
  tooltip.style.transform = "translate(-50%, calc(-100% - 12px))";
  tooltip.style.transition = "opacity 0.12s ease";
  container.appendChild(tooltip);

  return tooltip;
}

function setupTooltip(container, camera, selectableMeshes, tooltip) {
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();

  container.addEventListener("pointermove", event => {
    const rect = container.getBoundingClientRect();
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -(((event.clientY - rect.top) / rect.height) * 2 - 1);
    raycaster.setFromCamera(pointer, camera);

    const hits = raycaster.intersectObjects(selectableMeshes, false);
    const hit = hits.find(item => item.object.userData.tooltip);

    if (!hit) {
      tooltip.style.opacity = "0";
      return;
    }

    tooltip.textContent = hit.object.userData.tooltip;
    tooltip.style.left = `${event.clientX - rect.left}px`;
    tooltip.style.top = `${event.clientY - rect.top}px`;
    tooltip.style.opacity = "1";
  });

  container.addEventListener("pointerleave", () => {
    tooltip.style.opacity = "0";
  });
}

function frameScene(camera, controls, root, container, cameraDirection) {
  const bounds = new THREE.Box3().setFromObject(root);

  if (bounds.isEmpty()) {
    return;
  }

  const center = new THREE.Vector3();
  const sphere = new THREE.Sphere();

  bounds.getCenter(center);
  bounds.getBoundingSphere(sphere);

  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
  const verticalDistance = sphere.radius / Math.tan(verticalFov / 2);
  const horizontalDistance = sphere.radius / Math.tan(horizontalFov / 2);
  const padding = container.clientWidth < 460 ? 1.42 : 1.16;
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

function createScene(container) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 100);
  camera.up.set(0, 0, 1);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  const controls = new OrbitControls(camera, renderer.domElement);
  const root = new THREE.Group();
  const cameraDirection = new THREE.Vector3(1.45, -1.45, 1.15).normalize();
  const ambient = new THREE.AmbientLight("#ffffff", 1.35);
  const keyLight = new THREE.DirectionalLight("#ffffff", 2.35);
  const fillLight = new THREE.DirectionalLight("#dbeafe", 0.95);

  container.innerHTML = "";
  container.style.position = "relative";
  container.tabIndex = 0;
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
    // Keep vertex text readable at the same screen size across zoom and resize.
    const viewportHeight = Math.max(container.clientHeight, 1);
    const projectionHeight = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));

    root.children.forEach(child => {
      if (!child.userData.textPixelHeight) return;
      const texture = child.material.map.image;
      const height = child.userData.textPixelHeight * (texture.height / child.userData.fontSize)
        * projectionHeight / viewportHeight;
      child.scale.set(height * texture.width / texture.height, height, 1);
    });
    renderer.render(scene, camera);
  }

  controls.addEventListener("change", renderSceneOnce);

  function resize() {
    const width = Math.max(container.clientWidth, 320);
    const height = Math.max(container.clientHeight || width, 320);

    camera.aspect = width / height;
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
    resize,
    renderSceneOnce,
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

  const state = createScene(container);
  const materials = createMaterials();
  const selectableMeshes = [];
  const tooltip = createTooltip(container);

  drawBaseCube(state.root, materials);
  addVertexLabels(state.root);
  drawBoundaryConditions(items, state.root, materials, selectableMeshes);
  setupTooltip(container, state.camera, selectableMeshes, tooltip);
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
