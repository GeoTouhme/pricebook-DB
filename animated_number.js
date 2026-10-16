/* Enhance native Streamlit metrics without adding layout containers. */
(() => {
  const host = window.parent;
  if (host.__animatedNumbers) return;
  const doc = host.document;
  const motion = host.matchMedia('(prefers-reduced-motion: reduce)');
  const states = new Map();
  const bindings = new WeakMap();
  class AnimatedNumber {
    constructor(element, {value, duration = 200, decimals = 0, prefix = '', suffix = ''}) {
      this.element = element;
      this.current = 0;
      this.started = false;
      this.visible = false;
      this.frame = null;
      this.update({value, duration, decimals, prefix, suffix});
    }
    format(value) {
      return this.prefix + value.toLocaleString('en-US', {
        minimumFractionDigits: this.decimals, maximumFractionDigits: this.decimals
      }) + this.suffix;
    }
    paint(value) {
      this.current = value;
      this.rendered = this.format(value);
      if (this.element.textContent !== this.rendered) this.element.textContent = this.rendered;
    }
    update({value, duration = 200, decimals = 0, prefix = '', suffix = ''}) {
      host.cancelAnimationFrame(this.frame);
      Object.assign(this, {value, duration: Math.max(0, Math.min(300, duration)), decimals, prefix, suffix});
      this.element.style.fontVariantNumeric = 'tabular-nums';
      this.element.setAttribute('aria-label', this.format(value));
      if (motion.matches) { this.started = true; this.paint(value); }
      else if (this.visible) this.animate();
      else this.paint(this.current);
    }
    animate() {
      if (motion.matches) { this.started = true; this.paint(this.value); return; }
      host.cancelAnimationFrame(this.frame);
      this.started = true;
      const from = this.current;
      const target = this.value;
      let start;
      const tick = time => {
        if (!this.element.isConnected) return;
        if (start === undefined) start = time;
        const progress = Math.min((time - start) / this.duration, 1);
        this.paint(progress === 1 ? target : from + (target - from) * (1 - (1 - progress) ** 3));
        if (progress < 1) this.frame = host.requestAnimationFrame(tick);
      };
      this.frame = host.requestAnimationFrame(tick);
    }
  }
  const visibility = new host.IntersectionObserver(entries => {
    for (const entry of entries) {
      const state = bindings.get(entry.target);
      if (!state) continue;
      state.visible = entry.isIntersecting;
      if (entry.isIntersecting && (!state.started || state.current !== state.value)) state.animate();
    }
  });
  function scan() {
    for (const card of doc.querySelectorAll('[data-testid="stMetric"]')) {
      const element = card.querySelector('[data-testid="stMetricValue"] > div');
      if (!element) continue;
      const existing = bindings.get(element);
      const text = element.textContent.trim();
      if (existing && text === existing.rendered) continue;
      const match = text.match(/^([^\d+−-]*)([+−-]?\d[\d,]*(?:\.\d+)?)([^\d]*)$/);
      if (!match) continue; // Preserve missing values (—), identifiers and other text.
      const value = Number(match[2].replaceAll(',', '').replace('−', '-'));
      if (!Number.isFinite(value)) continue;
      const props = {value, decimals: (match[2].split('.')[1] || '').length, prefix: match[1], suffix: match[3]};
      const label = card.querySelector('[data-testid="stMetricLabel"]')?.textContent || '';
      const key = label;
      let state = existing || states.get(key);
      if (existing && existing.value === value && existing.decimals === props.decimals && existing.prefix === props.prefix && existing.suffix === props.suffix) {
        existing.paint(existing.current);
        continue;
      }
      if (state && state.element !== element) {
        visibility.unobserve(state.element);
        host.cancelAnimationFrame(state.frame);
        state.element = element;
        state.visible = false;
      }
      if (state) state.update(props);
      else state = new AnimatedNumber(element, props);
      states.set(key, state);
      bindings.set(element, state);
      visibility.observe(element);
    }
  }
  const observer = new host.MutationObserver(scan);
  observer.observe(doc.body, {childList: true, subtree: true, characterData: true});
  motion.addEventListener('change', () => {
    if (motion.matches) for (const state of states.values()) {
      host.cancelAnimationFrame(state.frame);
      state.started = true;
      state.paint(state.value);
    }
  });
  host.__animatedNumbers = {AnimatedNumber, observer, visibility};
  scan();
})();
