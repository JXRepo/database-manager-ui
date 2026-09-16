(() => {
  'use strict';

  document.querySelectorAll('form[data-credential-validation]').forEach(form => {
    const fields = new Map();
    const touched = new Set();
    const status = form.querySelector('[data-credential-status]');
    let timer;
    let controller;
    let revision = 0;

    form.querySelectorAll('[data-credential-field]').forEach(group => {
      const input = group.querySelector('input');
      const errors = group.querySelector('[data-credential-errors]');
      const name = group.dataset.credentialField;
      const descriptions = new Set((input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
      descriptions.add(errors.id);
      const help = group.querySelector('small[id]');
      if (help) descriptions.add(help.id);
      input.setAttribute('aria-describedby', [...descriptions].join(' '));
      fields.set(name, {input, errors});
      if (errors.textContent.trim()) {
        touched.add(name);
        input.classList.add('is-invalid');
        input.setAttribute('aria-invalid', 'true');
      }
    });

    function showErrors(name, messages) {
      const {input, errors} = fields.get(name);
      errors.replaceChildren();
      for (const message of messages) {
        const line = document.createElement('span');
        line.className = 'd-block mt-1 text-danger';
        line.textContent = message;
        errors.appendChild(line);
      }
      input.classList.toggle('is-invalid', messages.length > 0);
      if (messages.length) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    }

    function cancelCheck() {
      clearTimeout(timer);
      revision += 1;
      if (controller) controller.abort();
      form.removeAttribute('aria-busy');
    }

    async function checkFields() {
      const currentRevision = revision;
      const requestController = new AbortController();
      controller = requestController;
      const body = new URLSearchParams();
      body.set('mode', form.dataset.credentialMode);
      body.set('csrfmiddlewaretoken', form.querySelector('[name="csrfmiddlewaretoken"]').value);
      fields.forEach(({input}, name) => body.set(name, input.value));
      form.setAttribute('aria-busy', 'true');
      const timeout = setTimeout(() => requestController.abort(), 10000);

      try {
        const response = await fetch(form.dataset.credentialValidation, {
          method: 'POST',
          credentials: 'same-origin',
          mode: 'same-origin',
          cache: 'no-store',
          headers: {'Accept': 'application/json'},
          body,
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error('Validation unavailable');
        const result = await response.json();
        if (currentRevision !== revision) return;
        if (!result.errors || [...fields.keys()].some(name => !Array.isArray(result.errors[name]))) {
          throw new Error('Invalid validation response');
        }
        status.hidden = true;
        status.textContent = '';
        fields.forEach((field, name) => {
          if (touched.has(name)) showErrors(name, result.errors[name]);
        });
      } catch (error) {
        if (currentRevision !== revision) return;
        status.textContent = 'Live checks are unavailable. You can still submit the form to check your details.';
        status.hidden = false;
      } finally {
        clearTimeout(timeout);
        if (currentRevision === revision) form.removeAttribute('aria-busy');
      }
    }

    function scheduleCheck(name, immediate = false) {
      cancelCheck();
      touched.add(name);
      showErrors(name, []);
      // changing identity or the first password can change the other password errors
      if (name === 'username' || name === 'email') {
        if (touched.has('password1')) showErrors('password1', []);
      }
      if (name === 'password1' && touched.has('password2')) showErrors('password2', []);
      status.hidden = true;
      status.textContent = '';
      if (immediate) checkFields();
      else timer = setTimeout(checkFields, 500);
    }

    fields.forEach(({input}, name) => {
      let composing = false;
      input.addEventListener('compositionstart', () => {
        composing = true;
        cancelCheck();
      });
      input.addEventListener('compositionend', () => {
        composing = false;
        scheduleCheck(name);
      });
      input.addEventListener('input', event => {
        if (!composing && !event.isComposing) scheduleCheck(name);
      });
      input.addEventListener('change', () => {
        if (!composing) scheduleCheck(name);
      });
      input.addEventListener('blur', () => {
        if (!composing) scheduleCheck(name, true);
      });
    });

    // normal submission still uses the authoritative Django form validation
    form.addEventListener('submit', cancelCheck);
    window.addEventListener('pagehide', cancelCheck);
  });
})();
