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
      '--dashboard-canvas': dark ? '#1c1917' : '#fafaf9',
      '--dashboard-wash': dark ? '#164363' : '#c1e1f7',
      '--dashboard-card': dark ? '#292524' : '#ffffff',
      '--dashboard-sidebar': dark ? '#1c1917' : '#ffffff',
      '--dashboard-border': dark ? '#44403c' : '#e8e6e5',
      '--dashboard-hover': dark ? '#292524' : '#e8e6e5',
      '--dashboard-selected': dark ? '#292524' : '#f5f5f4',
      '--dashboard-selected-border': dark ? '#57534e' : '#e8e6e5',
      '--dashboard-brand': dark ? '#f5f5f4' : '#0c0a09',
      '--dashboard-muted': dark ? '#a8a29e' : '#78716c',
      '--dashboard-accent': dark ? '#3ba6f1' : '#3ba6f1',
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
