(() => {
  'use strict';

  const checkbox = document.getElementById('id_remember_me');
  const orcidLink = document.getElementById('orcid-login-link');

  function updateOrcidLink() {
    const url = new URL(orcidLink.href);
    if (checkbox.checked) url.searchParams.set('remember_me', 'on');
    else url.searchParams.delete('remember_me');
    orcidLink.href = url.toString();
  }

  checkbox.addEventListener('change', updateOrcidLink);
  window.addEventListener('pageshow', updateOrcidLink);
  updateOrcidLink();
})();
