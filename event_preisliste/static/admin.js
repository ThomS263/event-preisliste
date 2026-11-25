(() => {
  const shell = document.querySelector('[data-admin-shell]');
  if (!shell) return;
  const menu = shell.querySelector('[data-admin-menu]');
  const close = () => {
    shell.classList.remove('menu-open');
    menu?.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  };
  menu?.addEventListener('click', () => {
    const open = !shell.classList.contains('menu-open');
    shell.classList.toggle('menu-open', open);
    menu.setAttribute('aria-expanded', String(open));
    document.body.style.overflow = open ? 'hidden' : '';
  });
  shell.querySelector('[data-admin-close]')?.addEventListener('click', close);
  shell.querySelectorAll('.side-nav a').forEach(link => link.addEventListener('click', close));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
})();
