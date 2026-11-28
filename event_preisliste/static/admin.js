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
  document.querySelector('[data-copy-status-token]')?.addEventListener('click', async () => {
    const input = document.querySelector('[data-status-token]');
    const state = document.querySelector('[data-token-state]');
    try {
      await navigator.clipboard.writeText(input.value);
      state.textContent = 'Status-Token wurde kopiert.';
    } catch (_) {
      input.type = 'text'; input.select();
      state.textContent = 'Token ist markiert – bitte kopieren.';
    }
  });
  const sortList = document.querySelector('[data-stand-sort]');
  if (sortList) {
    let dragged = null;
    sortList.querySelectorAll('[data-stand-id]').forEach(card => {
      const handle = card.querySelector('.drag-handle');
      const controls = document.createElement('span');
      controls.className = 'touch-sort';
      controls.innerHTML = '<button type="button" aria-label="Nach oben">↑</button><button type="button" aria-label="Nach unten">↓</button>';
      card.querySelector('summary')?.appendChild(controls);
      controls.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        const button = event.target.closest('button');
        if (!button) return;
        if (button === controls.firstElementChild && card.previousElementSibling) sortList.insertBefore(card, card.previousElementSibling);
        if (button === controls.lastElementChild && card.nextElementSibling) sortList.insertBefore(card.nextElementSibling, card);
        saveOrder();
      });
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
