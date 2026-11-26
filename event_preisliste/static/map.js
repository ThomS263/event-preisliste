(() => {
  const editor = document.querySelector('[data-map-editor]');
  if (editor) {
    const xInput = document.querySelector('[data-map-x]');
    const yInput = document.querySelector('[data-map-y]');
    const preview = document.querySelector('[data-preview]');
    const hint = document.querySelector('[data-coordinate-hint]');
    editor.addEventListener('click', event => {
      const rect = editor.getBoundingClientRect();
      const x = Math.max(0, Math.min(100, (event.clientX - rect.left) / rect.width * 100));
      const y = Math.max(0, Math.min(100, (event.clientY - rect.top) / rect.height * 100));
      xInput.value = x.toFixed(3);
      yInput.value = y.toFixed(3);
      preview.style.left = `${x}%`;
      preview.style.top = `${y}%`;
      preview.hidden = false;
      hint.textContent = `Position gewählt: ${Math.round(x)} % / ${Math.round(y)} %`;
    });
  }

  const markers = [...document.querySelectorAll('.public-map .map-marker')];
  const publicMap = document.querySelector('.public-map');
  if (publicMap) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'secondary map-fullscreen';
    button.textContent = document.documentElement.lang === 'en' ? 'Open map full screen' : 'Plan im Vollbild öffnen';
    publicMap.before(button);
    button.addEventListener('click', async () => {
      try { if (!document.fullscreenElement) await publicMap.requestFullscreen(); else await document.exitFullscreen(); } catch (_) {}
    });
  }
  const detail = document.querySelector('[data-map-detail]');
  function activate(index) {
    const marker = markers[index];
    if (!marker || !detail) return;
    markers.forEach(item => item.classList.remove('active'));
    marker.classList.add('active');
    detail.querySelector('strong').textContent = marker.dataset.label;
    detail.querySelector('p').textContent = marker.dataset.description || 'Keine weitere Beschreibung.';
    if (marker.dataset.linkedStand) document.dispatchEvent(new CustomEvent('stand:select', {detail: marker.dataset.linkedStand}));
  }
  markers.forEach((marker, index) => marker.addEventListener('click', () => activate(index)));
  document.querySelectorAll('[data-marker-index]').forEach(button => button.addEventListener('click', () => activate(Number(button.dataset.markerIndex))));
})();
