export function createTensorMotion(container, meshes, render) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'bc-reset-btn bc-motion-btn';
  button.dataset.bcMotion = '';
  container.parentElement.appendChild(button);
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let visible = false;
  let pending = null;
  let playing = false;
  let frameId = null;
  let startedAt = null;
  let opacities = new Map();

  function updateButton() {
    button.hidden = !meshes.length;
    button.disabled = !meshes.length;
    button.textContent = playing ? 'Stop motion' : 'Replay motion';
    button.setAttribute('aria-pressed', String(playing));
    button.title = reducedMotion.matches
      ? 'Automatic motion is off. Manual replay shows the direction cue, not a simulated response.'
      : 'A short direction cue, not a simulated response or loading history.';
  }

  function stop() {
    if (frameId !== null) cancelAnimationFrame(frameId);
    frameId = null;
    startedAt = null;
    playing = false;
    pending = null;
    for (const mesh of meshes) {
      mesh.position.copy(mesh.userData.motion.position);
    }
    for (const [material, opacity] of opacities) material.opacity = opacity;
    opacities.clear();
    updateButton();
    render();
  }

  function tick(now) {
    frameId = null;
    if (startedAt === null) startedAt = now;
    const elapsed = now - startedAt;
    if (elapsed >= 1200) {
      stop();
      return;
    }
    const progress = Math.min(Math.max((elapsed - 80) / 540, 0), 1);
    const eased = 1 - (1 - progress) ** 3;
    const returning = elapsed >= 940;
    const opacity = returning ? (elapsed - 940) / 260
      : Math.min(elapsed / 80, 1, Math.max((940 - elapsed) / 220, 0));
    for (const mesh of meshes) {
      const motion = mesh.userData.motion;
      // Compression approaches its resting tip without entering the cube.
      const offset = returning ? 0 : 0.075 * (motion.effect === 'inward' ? eased - 1 : eased);
      mesh.position.copy(motion.position).addScaledVector(motion.direction, offset);
      mesh.material.opacity = opacities.get(mesh.material) * opacity;
    }
    render();
    frameId = requestAnimationFrame(tick);
  }

  function play(manual = false) {
    stop();
    if ((reducedMotion.matches && !manual) || !meshes.length || document.hidden) return;
    if (!visible) {
      pending = manual;
      return;
    }
    playing = true;
    opacities = new Map(meshes.map(mesh => [mesh.material, mesh.material.opacity]));
    updateButton();
    frameId = requestAnimationFrame(tick);
  }

  button.addEventListener('click', () => playing ? stop() : play(true));
  reducedMotion.addEventListener('change', stop);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
  });
  window.addEventListener('pagehide', stop);
  const observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting && entry.intersectionRatio >= 0.35;
    if (!visible && playing) stop();
    else if (visible && pending !== null) play(pending);
  }, {threshold: [0, 0.35]});
  observer.observe(container);
  updateButton();
  return {play, stop};
}
