// Run with node --test tests/test_animated_number.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function environment() {
  let frames = new Map(), id = 0;
  const motion = {matches: false, addEventListener() {}};
  const host = {
    document: {body: {}, querySelectorAll: () => []},
    matchMedia: () => motion,
    requestAnimationFrame: callback => {frames.set(++id, callback); return id;},
    cancelAnimationFrame: key => frames.delete(key),
    IntersectionObserver: class {observe() {} unobserve() {}},
    MutationObserver: class {observe() {}}
  };
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname, '../animated_number.js'), 'utf8'), {window: {parent: host}});
  return {Number: host.__animatedNumbers.AnimatedNumber, motion,
    frame(time) {const pending = [...frames.values()]; frames.clear(); pending.forEach(f => f(time));},
    pending: () => frames.size};
}
const element = () => ({textContent: '', style: {}, isConnected: true, setAttribute() {}});
test('waits for visibility, eases from zero, then updates from previous value', () => {
  const env = environment(), el = element();
  const counter = new env.Number(el, {value: 12450});
  assert.equal(el.textContent, '0');
  assert.equal(env.pending(), 0);
  counter.visible = true;
  counter.animate(); env.frame(0); env.frame(625);
  assert.equal(counter.current, 12450 * .875);
  env.frame(1250); assert.equal(el.textContent, '12,450');
  counter.update({value: 20000}); env.frame(2000);
  assert.equal(counter.current, 12450);
  env.frame(3250); assert.equal(el.textContent, '20,000');
});
test('formats decimal currencies, percentages, negatives and reduced motion', () => {
  const env = environment(); env.motion.matches = true;
  const el = element();
  const counter = new env.Number(el, {value: 1200.5, decimals: 2, prefix: '$'});
  assert.equal(el.textContent, '$1,200.50');
  counter.update({value: 45, suffix: '%'}); assert.equal(el.textContent, '45%');
  counter.update({value: -1250.5, decimals: 2, prefix: '$'});
  assert.equal(el.textContent, '$-1,250.50');
  counter.animate(); assert.equal(env.pending(), 0);
  assert.equal(el.style.fontVariantNumeric, 'tabular-nums');
});
