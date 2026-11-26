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
  const sortList = document.querySelector('[data-stand-sort]');
  if (sortList) {
    let dragged = null;
    sortList.querySelectorAll('[data-stand-id]').forEach(card => {
      const handle = card.querySelector('.drag-handle');
      handle?.addEventListener('dragstart', event => { dragged = card; card.classList.add('dragging'); event.dataTransfer.effectAllowed = 'move'; });
      handle?.addEventListener('dragend', () => { card.classList.remove('dragging'); dragged = null; saveOrder(); });
      card.addEventListener('dragover', event => {
        if (!dragged || dragged === card) return;
        event.preventDefault();
        const rect = card.getBoundingClientRect();
        sortList.insertBefore(dragged, event.clientY < rect.top + rect.height / 2 ? card : card.nextSibling);
      });
    });
    async function saveOrder() {
      const order = [...sortList.querySelectorAll('[data-stand-id]')].map(card => Number(card.dataset.standId));
      try {
        await fetch(sortList.dataset.reorderUrl, {method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({order})});
      } catch (_) {}
    }
  }
})();
