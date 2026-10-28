import {TENSOR_COMPONENTS, tensorComponentMeaning, tensorConceptPoint} from './mechanical-bc-tensor.js';
import {createTensorMotion} from './mechanical-bc-motion.js';

const ACTIONS = {pull: ['xx', 1], push: ['xx', -1], slide: ['xy', 1]};
const EFFECT_ACTION = {outward: 'pull', inward: 'push', shear: 'slide'};
const VERTICES = Array.from({length: 8}, (_, index) => [
  index & 4 ? 0.5 : -0.5, index & 2 ? 0.5 : -0.5, index & 1 ? 0.5 : -0.5,
]);
const FACES = [[4, 6, 7, 5], [2, 3, 7, 6], [1, 5, 7, 3]];

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  return element;
}

function project(point) {
  const [x, y, z] = point;
  return `${(80 + (y - x) * 36).toFixed(2)},${(52 + (x + y) * 15 - z * 39).toFixed(2)}`;
}

function path(points, closed = false) {
  return points.map((point, index) => `${index ? 'L' : 'M'}${project(point)}`).join(' ') + (closed ? ' Z' : '');
}

function createExample(host) {
  const svg = svgElement('svg', {viewBox: '0 0 160 108', 'aria-hidden': 'true'});
  svg.dataset.tensorExample = '';
  const changed = svgElement('g', {'data-example-shape': ''});
  const facePaths = FACES.map((_, index) => {
    const face = svgElement('path', {fill: 'currentColor', 'fill-opacity': [0.18, 0.12, 0.08][index],
      stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linejoin': 'round'});
    changed.appendChild(face);
    return face;
  });
  const gridLines = [];
  for (let normal = 0; normal < 3; normal++) {
    const axes = [0, 1, 2].filter(axis => axis !== normal);
    for (const fixed of axes) {
      const varying = axes.find(axis => axis !== fixed);
      for (const offset of [-1 / 6, 1 / 6]) {
        const points = [-0.5, 0.5].map(value => {
          const point = [0, 0, 0];
          point[normal] = 0.5;
          point[fixed] = offset;
          point[varying] = value;
          return point;
        });
        const line = svgElement('path', {fill: 'none', stroke: 'currentColor', 'stroke-opacity': 0.4, 'stroke-width': 0.8});
        changed.appendChild(line);
        gridLines.push({line, points});
      }
    }
  }
  svg.appendChild(changed);
  const edges = [];
  for (let index = 0; index < VERTICES.length; index++) {
    for (const bit of [1, 2, 4]) {
      if (!(index & bit)) edges.push(path([VERTICES[index], VERTICES[index | bit]]));
    }
  }
  svg.appendChild(svgElement('path', {d: edges.join(' '), fill: 'none', stroke: '#94a3b8',
    'stroke-width': 1.2, 'stroke-dasharray': '3 3', 'data-example-original': ''}));
  host.replaceChildren(svg);
  return (component, value, progress) => {
    const point = original => tensorConceptPoint(original, component, value, progress);
    svg.dataset.exampleComponent = component;
    svg.dataset.exampleSign = String(Math.sign(value));
    facePaths.forEach((face, index) => face.setAttribute('d', path(FACES[index].map(vertex => point(VERTICES[vertex])), true)));
    gridLines.forEach(({line, points}) => line.setAttribute('d', path(points.map(point))));
  };
}

export function createTensorIllustrations(container) {
  if (!container) return null;
  const cards = Array.from(container.querySelectorAll('[data-tensor-action-card]')).map(button => ({
    button, action: button.dataset.tensorFilter,
    draw: createExample(button.querySelector('[data-tensor-example-host]')),
  }));
  let view = null;
  let hovered = [];
  let counts = {};
  let revision = 0;

  function actionFor(component) {
    return EFFECT_ACTION[tensorComponentMeaning(component, view?.load?.magnitude?.[component])?.effect] || '';
  }

  function activeAction() {
    if (!view || view.shapeMatrix) return '';
    if (view.selected) return actionFor(view.selected);
    return counts[view.filter] ? view.filter : '';
  }

  function draw(progress = 1) {
    for (const card of cards) {
      const preview = hovered.length === 1 ? hovered[0] : view?.selected;
      const specific = preview && actionFor(preview) === card.action;
      const [component, value] = specific
        ? [preview, view.load.magnitude[preview]] : ACTIONS[card.action];
      const meaning = tensorComponentMeaning(component, value, view?.item.loading_type === 'strain');
      card.button.style.setProperty('--bc-action-color', meaning.color);
      card.button.classList.toggle('is-current', activeAction() === card.action);
      card.button.classList.toggle('is-hovered', hovered.some(key => actionFor(key) === card.action));
      card.button.classList.toggle('is-empty', !counts[card.action]);
      card.button.querySelector('[data-tensor-example-component]').textContent = specific
        ? `${component} · ±${component[1].toUpperCase()} faces` : 'Example';
      card.draw(component, value, activeAction() === card.action ? progress : 1);
    }
  }

  const motion = createTensorMotion(container, draw, () => !!activeAction());
  function update(next) {
    motion.stop();
    view = next;
    hovered = [];
    counts = {pull: 0, push: 0, slide: 0};
    for (const component of TENSOR_COMPONENTS) {
      const action = actionFor(component);
      if (action) counts[action]++;
    }
    for (const card of cards) {
      const count = counts[card.action];
      card.button.querySelector('[data-tensor-action-count]').textContent = count
        ? `${count} component${count === 1 ? '' : 's'}` : 'No components';
    }
    container.hidden = !!view.shapeMatrix;
    motion.stop();
    const currentRevision = ++revision;
    // Matrix focus is restored synchronously after a selection is rendered.
    queueMicrotask(() => {
      if (revision === currentRevision) motion.play();
    });
  }

  function highlight(components) {
    const keys = (Array.isArray(components) ? components : [components]).filter(key => actionFor(key));
    if (keys.join(',') === hovered.join(',')) return;
    motion.stop();
    hovered = keys;
    draw();
  }

  return {update, highlight, stop: motion.stop};
}
