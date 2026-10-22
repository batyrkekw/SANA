export const PLANS = {
  basic: {
    nameKey: 'basicName', tokens: 7000,
    features: ['basicFeature'],
  },
  pro: {
    nameKey: 'proName', tokens: 10000,
    features: ['proFeatureGames', 'proFeatureQuizzes', 'proFeatureTemplates'],
  },
  plus: {
    nameKey: 'plusName', tokens: 13000,
    features: ['plusFeatureAll', 'plusFeatureScenarios', 'plusFeatureLibrary', 'plusFeatureExport'],
  },
};

// These are previews of planned subscriptions, not a checkout or activation flow.
export function setupPlanDialog(t) {
  const dialog = document.querySelector('#plan-dialog');
  const closeButton = dialog.querySelector('#close-plan');
  let selectedPlan = null;
  let trigger = null;
  let navigatingToLessons = false;

  function render() {
    if (!selectedPlan) return;
    const plan = PLANS[selectedPlan];
    dialog.dataset.plan = selectedPlan;
    dialog.querySelector('#plan-dialog-title').textContent = t(plan.nameKey);
    dialog.querySelector('#plan-dialog-tokens').textContent = `${new Intl.NumberFormat(document.documentElement.lang).format(plan.tokens)} ${t('tokensUnit')}`;
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

  return { render };
}
