(() => {
  const host = window.parent;
  if (host.__dashboardTheme) return;
  const doc = host.document;
  let pending = false;
  function sync() {
    pending = false;
    const app = doc.querySelector('[data-testid="stApp"]');
    if (!app) return;
    const style = host.getComputedStyle(app);
    const background = style.backgroundColor;
    const rgb = background.match(/[\d.]+/g);
    if (!rgb || rgb.length < 3) return;
    const dark = (+rgb[0] * .2126 + +rgb[1] * .7152 + +rgb[2] * .0722) < 128;
    const values = {
      '--dashboard-text': style.color,
      '--dashboard-card': dark ? '#1e293b' : '#f1f5f9',
      '--dashboard-sidebar': dark ? '#111c30' : '#f1f5f9',
      '--dashboard-border': dark ? '#334155' : '#e2e8f0',
      '--dashboard-hover': dark ? '#26364d' : '#e2e8f0',
      '--dashboard-selected': dark ? '#243d61' : '#dbeafe',
      '--dashboard-selected-border': dark ? '#365784' : '#bfdbfe',
      '--dashboard-brand': dark ? '#dbeafe' : '#172554',
      '--dashboard-muted': dark ? '#a8b8cf' : '#64748b',
      '--dashboard-accent': dark ? '#93c5fd' : '#2563eb',
      '--dashboard-icon-filter': dark ? 'brightness(0) invert(1)' : 'none',
    };
    for (const [name, value] of Object.entries(values)) {
      if (doc.documentElement.style.getPropertyValue(name) !== value) {
        doc.documentElement.style.setProperty(name, value);
      }
    }
  }
  const observer = new host.MutationObserver(() => {
    if (!pending) { pending = true; host.requestAnimationFrame(sync); }
  });
  observer.observe(doc.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'style']});
  host.__dashboardTheme = observer;
  sync();
})();
