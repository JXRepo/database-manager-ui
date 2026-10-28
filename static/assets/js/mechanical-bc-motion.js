export function createTensorMotion(container, render, available, mode = () => 'calculated') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'bc-reset-btn bc-motion-btn';
  button.dataset.bcMotion = '';
  container.parentElement.appendChild(button);
  let visible = false;
  let playing = false;
  let frameId = null;
  let previousTime = null;
  let elapsed = 0;
  const duration = () => mode() === 'action' ? 2400 : 1200;

  function updateButton() {
    button.disabled = !available();
    const action = mode() === 'action';
    const verb = playing ? 'Pause' : elapsed >= duration() ? 'Replay' : elapsed > 0 ? 'Resume' : 'Play';
    button.textContent = verb + (action ? ' action' : ' deformation');
    button.setAttribute('aria-pressed', String(playing));
    button.title = available() ? action ? 'Illustrative grip, tug and rebound; not physical deformation or time.'
      : 'Animate the selected deformation; playback duration is not physical time.'
      : action ? 'Select one or more nonzero components to play their action.'
        : 'Deformation is unavailable. See the explanation beside the cube.';
  }
  function pause() {
    if (frameId !== null) cancelAnimationFrame(frameId);
    frameId = null;
    previousTime = null;
    playing = false;
    updateButton();
  }
  function reset() {
    pause();
    elapsed = 0;
    render(0, 0);
    updateButton();
  }
  function tick(now) {
    frameId = null;
    if (previousTime !== null) elapsed = Math.min(duration(), elapsed + now - previousTime);
    previousTime = now;
    const progress = elapsed / duration();
    render(1 - (1 - progress) ** 3, progress);
    if (elapsed >= duration()) pause();
    else frameId = requestAnimationFrame(tick);
  }
  function play() {
    if (!available() || document.hidden || !visible || playing) return;
    if (elapsed >= duration()) reset();
    playing = true;
    previousTime = null;
    updateButton();
    frameId = requestAnimationFrame(tick);
  }
  button.addEventListener('click', () => playing ? pause() : play());
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', pause);
  document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
  window.addEventListener('pagehide', pause);
  const observer = new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting && entry.intersectionRatio >= 0.35;
    if (!visible) pause();
  }, {threshold: [0, 0.35]});
  observer.observe(container);
  updateButton();
  return {play, pause, reset};
}
