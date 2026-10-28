export function createTensorMotion(container, render, available) {
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

  function updateButton() {
    button.hidden = !available();
    button.disabled = !available();
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
    updateButton();
    render(1);
  }

  function tick(now) {
    frameId = null;
    if (startedAt === null) startedAt = now;
    const elapsed = now - startedAt;
    if (elapsed >= 1200) {
      stop();
      return;
    }
    const progress = Math.min(elapsed / 1000, 1);
    const eased = 1 - (1 - progress) ** 3;
    render(eased);
    frameId = requestAnimationFrame(tick);
  }

  function play(manual = false) {
    stop();
    if ((reducedMotion.matches && !manual) || !available() || document.hidden) return;
    if (!visible) {
      pending = manual;
      return;
    }
    playing = true;
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
