(() => {
  const dialog = document.getElementById('quick-start-dialog');
  if (!dialog || typeof dialog.showModal !== 'function') return;

  const form = dialog.querySelector('form');
  const error = dialog.querySelector('.quick-start-error');
  const submitButtons = form.querySelectorAll('button[type="submit"]');
  let dismissed = dialog.dataset.dismissed === 'true';
  let saving = false;

  function openGuide() {
    if (dialog.open) return;
    error.hidden = true;
    dialog.showModal();
    document.body.classList.add('quick-start-open');
    dialog.querySelector('h2').focus();
  }

  function closeGuide() {
    dialog.close();
    document.body.classList.remove('quick-start-open');
  }

  function continueFromGuide(button) {
    closeGuide();
    if (!button.hasAttribute('data-guide-dismiss')) {
      window.location.assign(button.value);
    }
  }

  async function acknowledge(button) {
    if (saving) return;
    if (dismissed) {
      continueFromGuide(button);
      return;
    }

    const data = new FormData(form);
    data.set('next', button.value);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    saving = true;
    error.hidden = true;
    form.setAttribute('aria-busy', 'true');
    submitButtons.forEach(control => { control.disabled = true; });

    try {
      const response = await fetch(form.getAttribute('action'), {
        method: 'POST',
        credentials: 'same-origin',
        redirect: 'error',
        headers: {Accept: 'application/json'},
        body: data,
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
      submitButtons.forEach(control => { control.disabled = false; });
    }

    if (dismissed) continueFromGuide(button);
    else button.focus();
  }

  document.querySelectorAll('[data-open-quick-start]').forEach(link => {
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      openGuide();
    });
  });

  form.addEventListener('submit', event => {
    event.preventDefault();
    acknowledge(event.submitter || form.querySelector('[data-guide-dismiss]'));
  });

  dialog.addEventListener('cancel', event => {
    event.preventDefault();
    acknowledge(form.querySelector('[data-guide-dismiss]'));
  });

  dialog.querySelector('[data-guide-close-unsaved]').addEventListener('click', closeGuide);
  if (dialog.dataset.autoShow === 'true') openGuide();
})();
