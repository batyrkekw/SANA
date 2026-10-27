import { PLANS } from './plans.js';

export function setupEnhancements(t) {
  const header = document.querySelector('header');
  const links = [...header.querySelectorAll('nav a')];
  const targets = links.map(link => document.querySelector(link.getAttribute('href')));
  let scheduled = false;
  let headerOffset = 100;
  function refreshHeader() {
    headerOffset = header.getBoundingClientRect().height + 18;
    document.documentElement.style.setProperty('--header-offset', `${headerOffset}px`);
    updateNavigation();
  }
  function updateNavigation() {
    scheduled = false;
    let active = -1;
    targets.forEach((section, index) => {
      if (section && section.getBoundingClientRect().top <= headerOffset + 40) active = index;
    });
    links.forEach((link, index) => {
      if (index === active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }
  window.addEventListener('scroll', () => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(updateNavigation); }
  }, { passive: true });
  if ('ResizeObserver' in window) new ResizeObserver(refreshHeader).observe(header);
  else window.addEventListener('resize', refreshHeader);
  refreshHeader();

  function render() {
    const rows = [
      ['initialAllowance', ...Object.values(PLANS).map(plan => plan.tokens === null ? '—' : new Intl.NumberFormat(document.documentElement.lang).format(plan.tokens))],
      ...['lesson','quiz','comic','flashcards','image'].map(kind => [kind, ...Object.values(PLANS).map(plan => plan.features.includes(kind))]),
    ];
    document.querySelector('#comparison-body').replaceChildren(...rows.map(([key, ...values]) => {
      const row = document.createElement('tr');
      const heading = document.createElement('th');
      heading.scope = 'row'; heading.textContent = t(key); row.append(heading);
      values.forEach(value => {
        const cell = document.createElement('td');
        if (typeof value === 'boolean') {
          const icon = document.createElement('span');
          icon.setAttribute('aria-hidden', 'true'); icon.textContent = value ? '✓' : '—';
          const label = document.createElement('span');
          label.className = 'sr-only'; label.textContent = t(value ? 'comparisonIncluded' : 'comparisonExcluded');
          cell.append(icon, label); cell.classList.toggle('is-included', value);
        } else cell.textContent = value;
        row.append(cell);
      });
      return row;
    }));
  }
  window.addEventListener('sana:plans',render);
  return { render };
}
