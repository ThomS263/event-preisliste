(() => {
  if ('serviceWorker' in navigator && location.protocol !== 'file:') {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  }
  const sections = [...document.querySelectorAll('.price-section')];
  if (!sections.length) return;
  const searchBox = document.createElement('div');
  searchBox.className = 'catalog-tools';
  searchBox.innerHTML = '<label for="catalog-search">Angebote durchsuchen</label><input id="catalog-search" type="search" placeholder="z. B. Punsch, vegan oder Kekse"><span data-result-count></span>';
  sections[0].before(searchBox);
  const input = searchBox.querySelector('input');
  const count = searchBox.querySelector('[data-result-count]');
  const empty = document.querySelector('[data-catalog-empty]');
  const standButtons = [...document.querySelectorAll('[data-stand-picker] [data-stand]')];
  let selectedStand = 'all';
  const filter = () => {
    const query = input.value.trim().toLocaleLowerCase('de');
    let visible = 0;
    sections.forEach(section => {
      let sectionVisible = 0;
      section.querySelectorAll('.price-list article').forEach(item => {
        const standMatches = selectedStand === 'all' || item.dataset.stand === selectedStand;
        const searchMatches = !query || item.textContent.toLocaleLowerCase('de').includes(query);
        const show = standMatches && searchMatches;
        item.hidden = !show;
        if (show) { visible++; sectionVisible++; }
      });
      section.hidden = sectionVisible === 0;
    });
    count.textContent = `${visible} ${visible === 1 ? 'Angebot' : 'Angebote'}`;
    if (empty) empty.hidden = visible !== 0;
  };
  standButtons.forEach(button => button.addEventListener('click', () => {
    selectedStand = button.dataset.stand;
    standButtons.forEach(candidate => {
      const active = candidate === button;
      candidate.classList.toggle('active', active);
      candidate.setAttribute('aria-pressed', String(active));
    });
    filter();
    searchBox.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  input.addEventListener('input', filter);
  filter();
})();
