'use strict';
(() => {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try {
    const saved = localStorage.getItem('lanytic-theme');
    if (['light', 'dark', 'system'].includes(saved)) preference = saved;
  } catch { /* Storage is optional. */ }
  const update = () => {
    const resolved = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = resolved;
    document.querySelector('meta[name="theme-color"]').content = resolved === 'dark' ? '#191b1e' : '#f6f5f2';
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === preference));
    });
  };
  window.LANyticTheme = {
    update,
    set(value) {
      if (!['light', 'dark', 'system'].includes(value)) return;
      preference = value;
      try { localStorage.setItem('lanytic-theme', value); } catch { /* Storage is optional. */ }
      update();
    },
  };
  media.addEventListener('change', update);
  update();
})();
