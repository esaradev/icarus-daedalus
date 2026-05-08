(function () {
  const list = document.getElementById('activity-list');
  if (!list) return;

  const pauseBtn = document.getElementById('pause-btn');
  let paused = false;
  if (pauseBtn) {
    pauseBtn.addEventListener('click', () => {
      paused = !paused;
      pauseBtn.textContent = paused ? 'Resume' : 'Pause';
      pauseBtn.classList.toggle('active', paused);
    });
  }

  function applyFilters() {
    const activeKindBtns = document.querySelectorAll('[data-filter-kinds].active');
    const activeAgentBtns = document.querySelectorAll('[data-filter-agent].active');
    const allowKinds = new Set();
    activeKindBtns.forEach(b => {
      b.dataset.filterKinds.split(',').forEach(k => allowKinds.add(k));
    });
    const allowAgents = new Set();
    activeAgentBtns.forEach(b => allowAgents.add(b.dataset.filterAgent));
    const allKinds = allowKinds.size === 0;
    const allAgents = allowAgents.size === 0;
    list.querySelectorAll('.event-row').forEach(row => {
      const k = row.dataset.kind || '';
      const a = row.dataset.agent || '';
      const ok = (allKinds || allowKinds.has(k)) && (allAgents || allowAgents.has(a));
      row.style.display = ok ? '' : 'none';
    });
  }

  document.querySelectorAll('[data-filter-kinds],[data-filter-agent]').forEach(b => {
    b.addEventListener('click', () => {
      b.classList.toggle('active');
      applyFilters();
    });
  });

  if (window.EventSource) {
    const es = new EventSource('/activity/stream');
    es.onmessage = (e) => {
      if (paused) return;
      try {
        const msg = JSON.parse(e.data);
        list.insertAdjacentHTML('afterbegin', msg.html);
        while (list.children.length > 300) {
          list.removeChild(list.lastChild);
        }
        applyFilters();
      } catch (err) {
        console.error('activity sse parse error', err);
      }
    };
    es.onerror = () => {
      // EventSource auto-reconnects; nothing else to do.
    };
  }
})();
