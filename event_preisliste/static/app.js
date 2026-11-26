(() => {
  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  const sections = [...document.querySelectorAll('.price-section')];
  if (!sections.length) return;
  const english = new URLSearchParams(location.search).get('lang') === 'en';
  const searchBox = document.createElement('div');
  searchBox.className = 'catalog-tools';
  searchBox.innerHTML = english
    ? '<label for="catalog-search">Search offers</label><input id="catalog-search" type="search" placeholder="e.g. punch, vegan or cookies"><span data-result-count></span><label class="favorite-filter"><input type="checkbox" data-favorites-only> Favourites only</label>'
    : '<label for="catalog-search">Angebote durchsuchen</label><input id="catalog-search" type="search" placeholder="z. B. Punsch, vegan oder Kekse"><span data-result-count></span><label class="favorite-filter"><input type="checkbox" data-favorites-only> Nur Favoriten</label>';
  sections[0].before(searchBox);
  const input = searchBox.querySelector('input[type="search"]');
  const favoritesOnly = searchBox.querySelector('[data-favorites-only]');
  const count = searchBox.querySelector('[data-result-count]');
  const empty = document.querySelector('[data-catalog-empty]');
  const picker = document.querySelector('[data-stand-picker]');
  const standButtons = [...document.querySelectorAll('[data-stand-picker] [data-stand]')];
  const kindButtons = [...document.querySelectorAll('[data-kind-filter]')];
  const detail = document.querySelector('[data-stand-detail]');
  let selectedStand = picker?.dataset.initialStand || 'all';
  let selectedKind = 'all';
  let favorites = new Set();
  try { favorites = new Set(JSON.parse(localStorage.getItem('eventFavorites') || '[]').map(String)); } catch (_) {}

  function saveFavorites() {
    try { localStorage.setItem('eventFavorites', JSON.stringify([...favorites])); } catch (_) {}
  }
  function updateFavoriteButtons() {
    document.querySelectorAll('[data-favorite]').forEach(button => {
      const active = favorites.has(button.dataset.favorite);
      button.classList.toggle('active', active);
      button.textContent = active ? '★' : '☆';
      button.setAttribute('aria-pressed', String(active));
    });
  }
  function showStandDetail() {
    if (!detail || selectedStand === 'all' || selectedStand === 'general') { if (detail) detail.hidden = true; return; }
    const info = document.querySelector(`[data-stand-info="${CSS.escape(selectedStand)}"]`);
    if (!info) { detail.hidden = true; return; }
    const parts = [];
    if (info.dataset.description) parts.push(`<p>${escapeHtml(info.dataset.description)}</p>`);
    if (info.dataset.hours) parts.push(`<span>🕒 ${escapeHtml(info.dataset.hours)}</span>`);
    if (info.dataset.contact) parts.push(`<span>✉ ${escapeHtml(info.dataset.contact)}</span>`);
    detail.innerHTML = parts.join('');
    detail.hidden = !parts.length;
  }
  function escapeHtml(value) {
    const node = document.createElement('span'); node.textContent = value; return node.innerHTML;
  }
  function filter() {
    const query = input.value.trim().toLocaleLowerCase('de');
    let visible = 0;
    sections.forEach(section => {
      let sectionVisible = 0;
      section.querySelectorAll('.price-list article').forEach(item => {
        const standMatches = selectedStand === 'all' || item.dataset.stand === selectedStand;
        const kindMatches = selectedKind === 'all' || item.dataset.kind === selectedKind;
        const searchMatches = !query || item.textContent.toLocaleLowerCase('de').includes(query);
        const favoriteMatches = !favoritesOnly.checked || favorites.has(item.dataset.itemId);
        const show = standMatches && kindMatches && searchMatches && favoriteMatches;
        item.hidden = !show;
        if (show) { visible++; sectionVisible++; }
      });
      section.hidden = sectionVisible === 0;
    });
    count.textContent = english ? `${visible} ${visible === 1 ? 'offer' : 'offers'}` : `${visible} ${visible === 1 ? 'Angebot' : 'Angebote'}`;
    if (empty) empty.hidden = visible !== 0;
  }
  function selectStand(value, scroll = true) {
    if (!standButtons.some(button => button.dataset.stand === value)) value = 'all';
    selectedStand = value;
    standButtons.forEach(button => {
      const active = button.dataset.stand === value;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    const url = new URL(location.href);
    if (value === 'all') url.searchParams.delete('stand'); else url.searchParams.set('stand', value);
    history.replaceState(null, '', url);
    showStandDetail(); filter();
    if (scroll) searchBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  standButtons.forEach(button => button.addEventListener('click', () => selectStand(button.dataset.stand)));
  kindButtons.forEach(button => button.addEventListener('click', () => {
    selectedKind = button.dataset.kindFilter;
    kindButtons.forEach(candidate => candidate.classList.toggle('active', candidate === button));
    filter();
  }));
  document.querySelectorAll('[data-favorite]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.favorite;
    if (favorites.has(id)) favorites.delete(id); else favorites.add(id);
    saveFavorites(); updateFavoriteButtons(); filter();
  }));
  document.addEventListener('stand:select', event => selectStand(String(event.detail), true));
  input.addEventListener('input', filter);
  favoritesOnly.addEventListener('change', filter);
  updateFavoriteButtons(); selectStand(selectedStand, false);
})();
