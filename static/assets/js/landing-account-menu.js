(() => {
  const menus = document.querySelectorAll('.atlas-account-menu');

  document.addEventListener('click', (event) => {
    for (const menu of menus) {
      if (!menu.contains(event.target)) menu.open = false;
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    for (const menu of menus) {
      if (!menu.open) continue;
      menu.open = false;
      menu.querySelector('summary').focus();
    }
  });
})();
