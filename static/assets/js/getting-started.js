(() => {
  const dialog = document.getElementById('quick-start-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  const form = dialog.querySelector('form');
  const card = dialog.querySelector('.quick-start-card');
  const title = dialog.querySelector('h2');
  const description = dialog.querySelector('.quick-start-intro');
  const progress = dialog.querySelector('.quick-start-progress');
  const note = dialog.querySelector('.quick-start-note');
  const error = dialog.querySelector('.quick-start-error');
  const shade = dialog.querySelector('.quick-start-shade');
  const spotlight = dialog.querySelector('.quick-start-spotlight');
  const pointer = dialog.querySelector('.quick-start-pointer');
  const back = dialog.querySelector('[data-guide-back]');
  const next = dialog.querySelector('[data-guide-next]');
  const finish = dialog.querySelector('[data-guide-finish]');
  const controls = form.querySelectorAll('button');
  const sidebar = document.querySelector('.pc-sidebar');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const steps = [{title: title.textContent, description: description.cloneNode(true)}];
  dialog.querySelector('[data-guide-steps]').content.querySelectorAll('[data-tour-target]').forEach(item => {
    steps.push({
      target: item.dataset.tourTarget,
      title: item.querySelector('h3').textContent,
      description: item.querySelector('p'),
    });
  });

  let dismissed = dialog.dataset.dismissed === 'true';
  let saving = false;
  let stepIndex = 0;
  let target = null;
  let sidebarScroll = null;
  let positionFrame = null;
  let textAnimations = [];

  function stopTextAnimations() {
    textAnimations.forEach(animation => animation.cancel());
    textAnimations = [];
  }

  function animateText() {
    stopTextAnimations();
    if (reducedMotion.matches) return;
    [title, ...description.children].forEach((element, index) => {
      textAnimations.push(element.animate([
        {opacity: 0, transform: 'translateY(6px)'},
        {opacity: 1, transform: 'translateY(0)'},
      ], {
        duration: 240,
        delay: index * 45,
        easing: 'cubic-bezier(0.2, 0.7, 0.3, 1)',
        fill: 'backwards',
      }));
    });
  }

  function restoreSidebar() {
    sidebar?.classList.remove('quick-start-sidebar');
    target?.classList.remove('quick-start-target');
    if (sidebarScroll) {
      sidebarScroll.forEach(({element, top}) => { element.scrollTop = top; });
      sidebarScroll = null;
    }
    target = null;
  }

  function positionCard() {
    if (!dialog.open) return;
    const margin = 16;
    const gap = 18;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const clamp = (value, low, high) => Math.max(low, Math.min(value, high));
    card.style.maxHeight = `${viewportHeight - margin * 2}px`;
    form.style.maxHeight = `${viewportHeight - margin * 2 - 2}px`;
    shade.hidden = !!target;
    spotlight.hidden = !target;
    pointer.hidden = !target;

    if (!target) {
      card.dataset.placement = 'center';
      card.style.width = `${Math.min(440, viewportWidth - margin * 2)}px`;
      card.style.left = '50%';
      card.style.top = '50%';
      return;
    }

    const rect = target.getBoundingClientRect();
    spotlight.style.left = `${rect.left + 2}px`;
    spotlight.style.top = `${rect.top + 2}px`;
    spotlight.style.width = `${rect.width - 4}px`;
    spotlight.style.height = `${rect.height - 4}px`;
    const width = Math.min(360, viewportWidth - margin * 2);
    card.style.width = `${width}px`;
    let left;
    let top;
    let pointerOffset;

    if (rect.right + gap + width <= viewportWidth - margin) {
      card.dataset.placement = 'right';
      left = rect.right + gap;
      top = clamp(rect.top - 20, margin, viewportHeight - card.offsetHeight - margin);
      pointerOffset = clamp(rect.top + rect.height / 2 - top, 20, card.offsetHeight - 20);
    } else {
      const below = viewportHeight - rect.bottom - gap - margin;
      const above = rect.top - gap - margin;
      const placeBelow = below >= card.offsetHeight || below >= above;
      const available = Math.max(80, placeBelow ? below : above);
      card.style.maxHeight = `${available}px`;
      form.style.maxHeight = `${available - 2}px`;
      card.dataset.placement = placeBelow ? 'bottom' : 'top';
      left = clamp(rect.left + 16, margin, viewportWidth - width - margin);
      top = placeBelow ? rect.bottom + gap : rect.top - gap - card.offsetHeight;
      pointerOffset = clamp(rect.left + rect.width / 2 - left, 20, width - 20);
    }

    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
    card.style.setProperty('--pointer-offset', `${pointerOffset}px`);
  }

  function schedulePosition() {
    if (!dialog.open || positionFrame !== null) return;
    positionFrame = requestAnimationFrame(() => {
      positionFrame = null;
      positionCard();
    });
  }

  function showStep(index) {
    if (saving) return;
    const focusedControl = document.activeElement;
    stepIndex = Math.max(0, Math.min(index, steps.length - 1));
    const step = steps[stepIndex];
    const last = stepIndex === steps.length - 1;
    title.textContent = step.title;
    const content = step.description.cloneNode(true);
    description.replaceChildren(...content.childNodes);
    progress.textContent = stepIndex ? `${stepIndex} of ${steps.length - 1}` : '';
    progress.hidden = stepIndex === 0;
    note.hidden = stepIndex !== 0;
    back.hidden = stepIndex === 0;
    next.hidden = last;
    finish.hidden = !last;
    error.hidden = true;
    form.scrollTop = 0;
    dialog.dataset.step = step.target || 'welcome';
    target?.classList.remove('quick-start-target');
    target = step.target ? sidebar?.querySelector(`[data-tour-target="${step.target}"]`) : null;

    if (target) {
      if (!sidebarScroll) {
        sidebarScroll = [...sidebar.querySelectorAll('.navbar-content, .simplebar-content-wrapper')]
          .map(element => ({element, top: element.scrollTop}));
      }
      sidebar.classList.add('quick-start-sidebar');
      target.classList.add('quick-start-target');
      target.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: 'instant'});
    } else {
      restoreSidebar();
    }
    positionCard();
    if (focusedControl.hidden) (last ? finish : next).focus();
    animateText();
  }

  function openGuide() {
    if (dialog.open) return;
    dialog.showModal();
    document.body.classList.add('quick-start-open');
    showStep(0);
    title.focus();
  }

  function closeGuide() {
    if (positionFrame !== null) cancelAnimationFrame(positionFrame);
    positionFrame = null;
    stopTextAnimations();
    restoreSidebar();
    dialog.close();
    document.body.classList.remove('quick-start-open');
  }

  async function acknowledge(button) {
    if (saving) return;
    if (dismissed) {
      closeGuide();
      return;
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    saving = true;
    error.hidden = true;
    form.setAttribute('aria-busy', 'true');
    controls.forEach(control => { control.disabled = true; });

    try {
      const response = await fetch(form.getAttribute('action'), {
        method: 'POST',
        credentials: 'same-origin',
        redirect: 'error',
        headers: {Accept: 'application/json'},
        body: new FormData(form),
        signal: controller.signal,
      });
      if (!response.ok || (await response.json()).dismissed !== true) {
        throw new Error('Introduction acknowledgement failed');
      }
      dismissed = true;
    } catch {
      error.hidden = false;
    } finally {
      clearTimeout(timeout);
      saving = false;
      form.removeAttribute('aria-busy');
      controls.forEach(control => { control.disabled = false; });
    }

    if (dismissed) closeGuide();
    else {
      positionCard();
      button.focus();
    }
  }

  document.querySelectorAll('[data-open-quick-start]').forEach(link => {
    if (link.hasAttribute('data-guide-launch')) link.hidden = false;
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      openGuide();
    });
  });

  next.addEventListener('click', () => showStep(stepIndex + 1));
  back.addEventListener('click', () => showStep(stepIndex - 1));
  form.addEventListener('submit', event => {
    event.preventDefault();
    acknowledge(event.submitter || form.querySelector('[data-guide-dismiss]'));
  });
  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    acknowledge(form.querySelector('[data-guide-dismiss]'));
  });
  dialog.querySelector('[data-guide-close-unsaved]').addEventListener('click', closeGuide);
  window.addEventListener('resize', schedulePosition);
  reducedMotion.addEventListener('change', () => {
    if (reducedMotion.matches) stopTextAnimations();
  });
  document.addEventListener('scroll', schedulePosition, true);
  new ResizeObserver(schedulePosition).observe(card);
  if (dialog.dataset.autoShow === 'true') openGuide();
})();
