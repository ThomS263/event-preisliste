(() => {
  if ('serviceWorker' in navigator && location.protocol !== 'file:') navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  const sections = [...document.querySelectorAll('.price-section')];
  if (!sections.length) return;
  const box = document.createElement('div');
  box.className = 'catalog-tools';
  box.innerHTML = '<label for="catalog-search">Angebote durchsuchen</label><input id="catalog-search" type="search" placeholder="z. B. Punsch, vegan oder Kekse"><span data-result-count></span>';
  sections[0].before(box);
  const input = box.querySelector('input');
  const count = box.querySelector('[data-result-count]');
  const filter = () => {
    const query = input.value.trim().toLocaleLowerCase('de');
    let visible = 0;
    sections.forEach(section => {
      let sectionVisible = 0;
      section.querySelectorAll('.price-list article').forEach(item => {
        const show = !query || item.textContent.toLocaleLowerCase('de').includes(query);
        item.hidden = !show;
        if (show) { visible++; sectionVisible++; }
      });
      section.hidden = sectionVisible === 0;
    });
    count.textContent = `${visible} Treffer`;
  };
  input.addEventListener('input', filter);
  filter();
})();
