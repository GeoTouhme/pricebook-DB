(() => {
  const host = window.parent;
  if (host.__dashboardCharts || !host.IntersectionObserver) return;
  const doc = host.document;
  const motion = host.matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new WeakSet();
  const waiting = new Set();
  const active = new Map();
  let queued = false;

  function show(element) {
    element.style.removeProperty('opacity');
    waiting.delete(element);
    visibility.unobserve(element);
  }

  const visibility = new host.IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const element = entry.target;
      show(element);
      if (motion.matches || !element.animate) continue;
      const animation = element.animate([
        {opacity: 0, transform: 'translateY(12px)'},
        {opacity: 1, transform: 'translateY(0)'}
      ], {duration: 1100, easing: 'cubic-bezier(0.215, 0.61, 0.355, 1)'});
      active.set(element, animation);
      const cleanup = () => active.delete(element);
      animation.onfinish = cleanup;
      animation.oncancel = cleanup;
    }
  }, {threshold: 0});

  function scan() {
    queued = false;
    for (const [element, animation] of active) {
      if (!element.isConnected) { animation.cancel(); active.delete(element); }
    }
    for (const element of waiting) {
      if (!element.isConnected) show(element);
    }
    for (const element of doc.querySelectorAll('[data-testid="stVegaLiteChart"]')) {
      // Wait until Vega has mounted its drawing surface, not a loading skeleton.
      if (seen.has(element) || !element.querySelector('canvas, svg')) continue;
      seen.add(element);
      if (motion.matches || !element.animate) continue;
      element.style.opacity = '0';
      waiting.add(element);
      visibility.observe(element);
    }
  }

  const observer = new host.MutationObserver(() => {
    if (!queued) { queued = true; host.requestAnimationFrame(scan); }
  });
  observer.observe(doc.body, {childList: true, subtree: true});
  motion.addEventListener('change', () => {
    if (!motion.matches) return;
    for (const element of waiting) show(element);
    for (const animation of active.values()) animation.cancel();
    active.clear();
  });
  host.__dashboardCharts = {observer, visibility};
  scan();
})();
