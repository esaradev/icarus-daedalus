(function () {
  const list = document.getElementById('review-list');
  if (!list) return;

  function applyFilters() {
    const active = document.querySelectorAll('[data-filter-kind].active');
    const allow = new Set();
    active.forEach(b => allow.add(b.dataset.filterKind));
    const showAll = allow.size === 0;
    list.querySelectorAll('.issue-row').forEach(row => {
      const k = row.dataset.kind || '';
      row.style.display = showAll || allow.has(k) ? '' : 'none';
    });
  }

  document.querySelectorAll('[data-filter-kind]').forEach(b => {
    b.addEventListener('click', () => {
      b.classList.toggle('active');
      applyFilters();
    });
  });
})();
