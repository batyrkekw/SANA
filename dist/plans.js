export const PLANS = {
  basic: {
    nameKey: 'basicName', tokens: null, features: [],
  },
  pro: {
    nameKey: 'proName', tokens: null, features: [],
  },
  plus: {
    nameKey: 'plusName', tokens: null, features: [],
  },
};

// Actual limits come from the API; no checkout or self-service upgrade exists.
export function setupPlanDialog(t) {
  const dialog = document.querySelector('#plan-dialog');
  const closeButton = dialog.querySelector('#close-plan');
  let selectedPlan = null;
  let trigger = null;
  let navigatingToLessons = false;

  function render() {
    for (const [code, plan] of Object.entries(PLANS)) {
      const card = document.querySelector(`button[data-plan="${code}"]`)?.closest('article');
      if (!card) continue;
      card.querySelector('.token-amount strong').textContent = plan.tokens === null ? '—' : new Intl.NumberFormat(document.documentElement.lang).format(plan.tokens);
      card.querySelector('.plan-features').replaceChildren(...plan.features.map(key => {
        const item = document.createElement('li'); item.textContent = t(key); return item;
      }));
    }
    if (!selectedPlan) return;
    const plan = PLANS[selectedPlan];
    dialog.dataset.plan = selectedPlan;
    dialog.querySelector('#plan-dialog-title').textContent = t(plan.nameKey);
    dialog.querySelector('#plan-dialog-tokens').textContent = plan.tokens === null ? '—' : `${new Intl.NumberFormat(document.documentElement.lang).format(plan.tokens)} ${t('tokensUnit')}`;
    dialog.querySelector('#plan-dialog-features').replaceChildren(...plan.features.map((key) => {
      const item = document.createElement('li');
      item.textContent = t(key);
      return item;
    }));
  }

  document.querySelectorAll('[data-plan]').forEach((button) => {
    button.addEventListener('click', () => {
      const plan = button.dataset.plan;
      if (!Object.hasOwn(PLANS, plan)) return;
      selectedPlan = plan;
      trigger = button;
      navigatingToLessons = false;
      render();
      dialog.showModal();
      document.body.classList.add('modal-open');
      dialog.scrollTop = 0;
      closeButton.focus();
    });
  });

  closeButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.body.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
    if (navigatingToLessons) {
      const heading = document.querySelector('#lessons-title');
      heading.setAttribute('tabindex', '-1');
      heading.focus({ preventScroll: true });
      navigatingToLessons = false;
    } else if (trigger?.isConnected) trigger.focus({ preventScroll: true });
  });
  dialog.querySelector('#plan-try-free').addEventListener('click', () => {
    navigatingToLessons = true;
    dialog.close();
  });

  fetch('/api/v1/plans', {signal:AbortSignal.timeout(8000)}).then(response => {
    if (!response.ok) throw new Error('Plans unavailable');
    return response.json();
  }).then(plans => {
    for (const plan of plans) {
      if (!Object.hasOwn(PLANS, plan.code)) continue;
      PLANS[plan.code].tokens = plan.limits.max_tokens;
      PLANS[plan.code].features = plan.limits.kinds;
    }
    render();
    window.dispatchEvent(new Event('sana:plans'));
  }).catch(() => { render(); });
  return { render };
}
