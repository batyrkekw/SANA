import { api, connect } from './session.js';
import {
  t,
  lang,
  setLanguage,
  escapeHTML as e,
  number,
  date,
  errorText,
  busy,
  notice,
} from './platform-common.js';
const content = document.querySelector('#workspace-content');
const status = document.querySelector('#workspace-status');
let dashboard,
  client,
  routeVersion = 0,
  pollTimer,
  dialogAction;
let assets = [];
let materialPage = 1,
  jobPage = 1,
  tokenPage = 1;
let filters = { search: '', subject: '', kind: '', order: 'desc' };
const kinds = ['lesson', 'comic', 'quiz', 'flashcards', 'image'];
const option = (value, label, selected = false) =>
  `<option value="${e(value)}"${selected ? ' selected' : ''}>${e(label)}</option>`;
const button = (label, href, secondary = false) =>
  `<a class="p-button${secondary ? '' : ' primary'}" href="${href}">${e(label)}</a>`;
const title = (heading, intro = '') =>
  `<div class="p-page-title"><div><p class="p-eyebrow">SANA / ${e(t('workspace'))}</p><h1>${e(heading)}</h1>${intro ? `<p>${e(intro)}</p>` : ''}</div></div>`;
const field = (name, label, input) =>
  `<div><label for="${name}">${e(t(label))}</label>${input}</div>`;
const input = (name, label, value = '', attrs = '') =>
  field(name, label, `<input id="${name}" name="${name}" value="${e(value)}" ${attrs}>`);
const select = (name, label, options) =>
  field(name, label, `<select id="${name}" name="${name}">${options}</select>`);
const pagination = (result, action) =>
  `<div class="p-pagination"><button class="p-button" data-page="${result.page - 1}" data-list="${action}" ${result.page === 1 ? 'disabled' : ''}>${e(t('previousListPage'))}</button><span>${e(t('pageInfo', { page: result.page, total: result.total }))}</span><button class="p-button" data-page="${result.page + 1}" data-list="${action}" ${result.page * result.page_size >= result.total ? 'disabled' : ''}>${e(t('nextListPage'))}</button></div>`;
function cards(items) {
  return `<div class="material-grid">${items.map((item) => `<article class="material-card"><div class="material-cover" data-kind="${e(item.kind)}">${item.assets?.length ? `<img data-asset="${e(item.assets[0].url)}" alt="${e(item.title)}">` : `<span aria-hidden="true">${{ lesson: '✦', comic: '▧', quiz: '?', flashcards: '▤', image: '◇' }[item.kind] || '✦'}</span>`}</div><div class="material-copy"><p class="p-eyebrow">${e(t(item.kind))} · ${e(item.language.toUpperCase())}</p><h3><a href="#material/${item.id}">${e(item.title)}</a></h3><p>${e(item.subject)} · ${e(item.topic)}</p><small>${e(date(item.created_at))}</small></div></article>`).join('')}</div>`;
}
async function loadAssets(version) {
  for (const image of content.querySelectorAll('[data-asset]')) {
    try {
      const blob = await api(image.dataset.asset.replace('/api/v1', ''), { blob: true });
      if (version !== routeVersion) return;
      const url = URL.createObjectURL(blob);
      assets.push(url);
      image.src = url;
    } catch {
      image.remove();
    }
  }
}
function topbar() {
  document.querySelector('#top-plan').textContent = dashboard.plan.name[lang()];
  document.querySelector('#top-balance').textContent =
    `${number(dashboard.tokens.available)} ${t('tokensUnit')}`;
  document.querySelector('#avatar').textContent = (dashboard.profile.display_name || 'S')
    .slice(0, 2)
    .toUpperCase();
}
async function refreshDashboard() {
  dashboard = await api('/dashboard');
  topbar();
}
function route() {
  return location.hash.slice(1).split('?')[0] || 'overview';
}
async function render() {
  const version = ++routeVersion;
  clearTimeout(pollTimer);
  assets.forEach(URL.revokeObjectURL);
  assets = [];
  notice(status, '');
  setLanguage(lang());
  const view = route();
  document.querySelectorAll('.account-nav a').forEach((link) => {
    if (link.hash === `#${view.split('/')[0]}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  content.setAttribute('aria-busy', 'true');
  try {
    let html;
    if (view === 'overview') {
      await refreshDashboard();
      html =
        title(
          t('hello', { name: dashboard.profile.display_name || t('teacher') }),
          t('dashboardIntro')
        ) +
        `<div class="p-stats"><div><span>${e(t('availableTokens'))}</span><strong>${number(dashboard.tokens.available)}</strong><small>${e(t('reservedTokens'))}: ${number(dashboard.tokens.reserved)}</small></div><div><span>${e(t('currentPlan'))}</span><strong>${e(dashboard.plan.name[lang()])}</strong><a href="#plan">${e(t('myPlan'))} ↗</a></div><div><span>${e(t('materialCount'))}</span><strong>${number(dashboard.material_count)}</strong></div></div>
        <div class="p-quick-actions">${button(t('createLesson'), '#create?kind=lesson')}${button(t('createComic'), '#create?kind=comic', true)}${button(t('createQuiz'), '#create?kind=quiz', true)}</div>
        <div class="p-section-title"><h2>${e(t('recentMaterials'))}</h2><a href="#materials">${e(t('viewAll'))} ↗</a></div>` +
        (dashboard.recent_materials.length ? cards(dashboard.recent_materials) : empty());
    } else if (view === 'materials') {
      const data = await api(
        `/materials?${new URLSearchParams({ ...filters, page: materialPage })}`
      );
      html =
        title(t('myMaterials')) +
        `<form id="filters" class="p-form filters">${input('search', 'searchMaterials', filters.search, 'maxlength="100"')}${select('subject', 'subjectFilter', option('', t('allSubjects')) + data.subjects.map((s) => option(s, s, s === filters.subject)).join(''))}${select('kind', 'materialType', option('', t('allTypes')) + kinds.map((k) => option(k, t(k), k === filters.kind)).join(''))}${select('order', 'sortOrder', option('desc', t('newest'), filters.order === 'desc') + option('asc', t('oldest'), filters.order === 'asc'))}<button class="p-button" type="submit">${e(t('applyFilters'))}</button></form>` +
        (data.items.length
          ? cards(data.items)
          : `<div class="p-empty"><p>${e(t('noResults'))}</p>${button(t('generate'), '#create')}</div>`) +
        pagination(data, 'materials');
    } else if (view === 'create') {
      html = await generator();
    } else if (view === 'jobs') {
      const data = await api(`/generations?page=${jobPage}`);
      html = title(t('generationHistory')) + jobsHTML(data) + pagination(data, 'jobs');
      if (data.items.some((job) => ['queued', 'processing'].includes(job.status)))
        pollTimer = setTimeout(() => {
          if (route() === 'jobs') void render();
        }, 4000);
    } else if (view === 'tokens') {
      const data = await api(`/me/tokens/transactions?page=${tokenPage}`);
      await refreshDashboard();
      html =
        title(t('tokenHistory'), t('tokensExplanation')) +
        `<div class="p-balance">${e(t('availableTokens'))}: <strong>${number(dashboard.tokens.available)}</strong> · ${e(t('reservedTokens'))}: ${number(dashboard.tokens.reserved)}</div>` +
        (data.items.length
          ? `<div class="p-table-wrap"><table><thead><tr><th>${e(t('dateLabel'))}</th><th>${e(t('operation'))}</th><th>${e(t('amount'))}</th></tr></thead><tbody>${data.items.map((row) => `<tr><td>${e(date(row.created_at))}</td><td>${e(t(row.kind))}</td><td>${number(row.amount)}</td></tr>`).join('')}</tbody></table></div>`
          : `<p>${e(t('noTransactions'))}</p>`) +
        pagination(data, 'tokens');
    } else if (view === 'plan') {
      const plans = await api('/plans');
      html =
        title(t('myPlan'), t('developmentPlans')) +
        `<div class="p-plan-grid">${plans.map((plan) => `<article class="p-plan ${plan.code === dashboard.plan.code ? 'selected' : ''}"><p class="p-eyebrow">${plan.code === dashboard.plan.code ? e(t('current')) : 'SANA'}</p><h2>${e(plan.name[lang()])}</h2><strong>${number(plan.limits.max_tokens ?? plan.initial_tokens)}</strong><p>${e(t('initialAllowance'))} · ${e(t('tokensUnit'))}</p><hr><h3>${e(t('allowedMaterials'))}</h3><ul>${plan.limits.kinds.map((kind) => `<li>${e(t(kind))}</li>`).join('')}</ul><p>${e(t('maxLength'))}: ${number(plan.limits.max_length)}</p></article>`).join('')}</div>`;
    } else if (view === 'settings') {
      html =
        title(t('accountSettings'), t('profileIntro')) +
        `<form id="settings-form" class="p-form settings-form">${input('display_name', 'displayName', dashboard.profile.display_name, 'required maxlength="80" autocomplete="name"')}${select('language', 'languageSetting', option('ru', 'Русский', lang() === 'ru') + option('kk', 'Қазақша', lang() === 'kk'))}<button class="p-button primary" type="submit">${e(t('save'))}</button><a href="/auth.html#reset">${e(t('resetPassword'))}</a></form>`;
    } else if (view.startsWith('material/')) {
      const material = await api(`/materials/${encodeURIComponent(view.slice(9))}`);
      html = materialHTML(material);
    } else {
      location.hash = 'overview';
      return;
    }
    if (version !== routeVersion) return;
    content.innerHTML = html;
    void loadAssets(version);
    if (view === 'create') wireGeneration();
  } catch (error) {
    if (version === routeVersion) notice(status, errorText(error), true);
  } finally {
    if (version === routeVersion) content.removeAttribute('aria-busy');
  }
}
function empty() {
  return `<div class="p-empty"><span aria-hidden="true">✦</span><h3>${e(t('emptyMaterials'))}</h3><p>${e(t('emptyMaterialsText'))}</p>${button(t('createLesson'), '#create')}</div>`;
}
function jobsHTML(data) {
  return data.items.length
    ? `<div class="job-list">${data.items.map((job) => `<article class="job-row"><div><span class="p-badge ${job.status}" role="status">${e(t(job.status))}</span><h3>${e(job.request.topic)}</h3><p>${e(t(job.request.kind))} · ${e(date(job.created_at))} · ${number(job.cost)} ${e(t('tokensUnit'))}</p>${job.error_code ? `<p class="is-error">${e(errorText({ code: job.error_code }))}</p>` : ''}</div><div>${job.material_id ? button(t('openMaterial'), `#material/${job.material_id}`, true) : ''}${job.can_cancel ? `<button class="p-button" data-cancel-job="${job.id}">${e(t('cancelJob'))}</button>` : ''}</div></article>`).join('')}</div>`
    : `<div class="p-empty"><p>${e(t('noJobs'))}</p>${button(t('generate'), '#create')}</div>`;
}
async function generator() {
  const state = await api('/ai/status');
  const chosen = new URLSearchParams(location.hash.split('?')[1] || '').get('kind') || 'lesson';
  return (
    title(t('generate'), t('generationIntro')) +
    `<div class="generation-layout"><form id="generation-form" class="p-form">
  <div class="p-form-grid">${select('kind', 'materialType', kinds.map((kind) => option(kind, t(kind), kind === chosen)).join(''))}${select('language', 'outputLanguage', option('ru', 'Русский', lang() === 'ru') + option('kk', 'Қазақша', lang() === 'kk'))}
  ${input('subject', 'subjectInput', '', 'required maxlength="100"')}${input('topic', 'topicInput', '', 'required maxlength="200"')}
  ${input('grade', 'gradeInput', '8', 'type="number" min="1" max="12" required')}${input('length', 'lengthInput', '3', 'type="number" min="1" max="12" required')}</div>
  ${field('instructions', 'instructionsInput', '<textarea id="instructions" name="instructions" rows="4" maxlength="6000"></textarea>')}
  <label class="p-checkbox"><input type="checkbox" name="include_images" id="include_images">${e(t('includeImages'))}</label>
  <div id="image-options" class="p-form-grid" hidden>${input('image_count', 'imageCount', '1', 'type="number" min="1" max="8"')}${select('style', 'imageStyle', ['educational', 'cartoon', 'infographic', 'historical', 'scientific'].map((s) => option(s, t(s))).join(''))}${select('aspect_ratio', 'aspectRatio', ['1:1', '4:3', '3:4'].map((s) => option(s, s)).join(''))}</div>
  <p id="quote-notice" class="p-notice" role="status">${e(t('quoteHint'))}</p><div class="p-actions"><button id="get-quote" type="button" class="p-button">${e(t('getQuote'))}</button><button id="generate-submit" type="submit" class="p-button primary" disabled>${e(t('generate'))}</button></div></form>
  <aside class="generation-note"><span aria-hidden="true">✦</span><h2>${e(t('modelStatus'))}</h2><p>${e(t('textModel'))}<strong>${e(t(state.text.status))}</strong></p><p>${e(t('imageModel'))}<strong>${e(t(state.image.status))}</strong></p><hr><p>${e(t('generatedReview'))}</p><p>${e(t('developmentPlans'))}</p></aside></div>`
  );
}
function wireGeneration() {
  const form = document.querySelector('#generation-form');
  const submit = form.querySelector('#generate-submit');
  const quoteNotice = form.querySelector('#quote-notice');
  let quoted = null;
  function payload() {
    const values = Object.fromEntries(new FormData(form));
    for (const key of ['grade', 'length', 'image_count']) values[key] = Number(values[key] || 1);
    values.include_images = form.elements.include_images.checked;
    return values;
  }
  function update() {
    quoted = null;
    submit.disabled = true;
    submit.textContent = t('generate');
    const kind = form.elements.kind.value;
    const canInclude = ['lesson', 'comic'].includes(kind);
    form.elements.include_images.disabled = !canInclude;
    if (!canInclude) form.elements.include_images.checked = false;
    form.querySelector('#image-options').hidden =
      kind !== 'image' && !form.elements.include_images.checked;
    form.elements.namedItem('length').min = kind === 'quiz' ? 3 : 1;
    notice(quoteNotice, t('quoteHint'));
  }
  form.addEventListener('input', update);
  update();
  form.querySelector('#get-quote').addEventListener('click', () => {
    if (!form.reportValidity()) return;
    void busy(form, async () => {
      const request = payload();
      try {
        const result = await api('/generations/quote', {
          method: 'POST',
          body: JSON.stringify(request),
        });
        if (JSON.stringify(request) !== JSON.stringify(payload())) return;
        quoted = { request, cost: result.cost };
        submit.textContent = t('startGeneration', { cost: result.cost });
        notice(quoteNotice, t('startGeneration', { cost: result.cost }));
      } catch (error) {
        notice(quoteNotice, errorText(error), true);
      }
    }).then(() => {
      submit.disabled = !quoted;
    });
  });
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!quoted || JSON.stringify(quoted.request) !== JSON.stringify(payload())) return;
    void busy(form, async () => {
      const body = JSON.stringify(quoted.request);
      let key = crypto.randomUUID();
      try {
        const pending = JSON.parse(sessionStorage.getItem('sana-pending-generation'));
        if (pending?.body === body) key = pending.key;
        sessionStorage.setItem('sana-pending-generation', JSON.stringify({ key, body }));
      } catch {
        /* Optional retry memory. */
      }
      try {
        await api('/generations', { method: 'POST', headers: { 'Idempotency-Key': key }, body });
        try {
          sessionStorage.removeItem('sana-pending-generation');
        } catch {
          /* Optional storage. */
        }
        await refreshDashboard();
        location.hash = 'jobs';
      } catch (error) {
        notice(quoteNotice, errorText(error), true);
      }
    });
  });
}
function materialHTML(material) {
  const c = material.content;
  const section = (heading, body) =>
    body ? `<section class="lesson-section"><h2>${e(t(heading))}</h2>${body}</section>` : '';
  let body =
    section(
      'objectives',
      c.objectives?.length ? `<ul>${c.objectives.map((x) => `<li>${e(x)}</li>`).join('')}</ul>` : ''
    ) +
    section(
      'explanation',
      c.explanation ? `<p class="preserve-lines">${e(c.explanation)}</p>` : ''
    ) +
    section('examples', c.examples?.map((x) => `<p class="preserve-lines">${e(x)}</p>`).join(''));
  if (c.panels?.length)
    body += `<div class="comic-panels">${c.panels.map((panel, index) => `<article><span class="p-eyebrow">${String(index + 1).padStart(2, '0')}</span>${material.assets[index] ? `<img data-asset="${e(material.assets[index].url)}" alt="${e(panel.scene)}">` : ''}<h3>${e(panel.scene)}</h3><p>${e(panel.narration)}</p><blockquote>${e(panel.dialogue)}</blockquote></article>`).join('')}</div>`;
  if (c.cards?.length)
    body += `<div class="flashcard-grid">${c.cards.map((card) => `<details><summary>${e(card.front)}</summary><p>${e(card.back)}</p></details>`).join('')}</div>`;
  body += section(
    'questions',
    c.questions
      ?.map(
        (question, index) =>
          `<article class="lesson-question"><h3>${index + 1}. ${e(question.prompt)}</h3><ol type="A">${question.options.map((option) => `<li>${e(option)}</li>`).join('')}</ol><details><summary>${e(t('showAnswer'))}</summary><p><strong>${e(t('correctAnswer'))}: ${e(question.options[question.correct_index])}</strong></p><p>${e(question.explanation)}</p></details></article>`
      )
      .join('')
  );
  body += section('summary', c.summary ? `<p>${e(c.summary)}</p>` : '');
  if (material.kind !== 'comic')
    body += material.assets
      .map(
        (asset) =>
          `<img class="generated-image" data-asset="${e(asset.url)}" alt="${e(material.title)}">`
      )
      .join('');
  return (
    title(material.title, `${material.subject} · ${material.topic}`) +
    `<div class="p-actions"><a href="#materials" class="p-button">${e(t('myMaterials'))}</a><button class="p-button" data-rename="${material.id}" data-title="${e(material.title)}">${e(t('rename'))}</button><button class="p-button danger" data-delete="${material.id}">${e(t('deleteMaterial'))}</button></div><p class="p-notice">${e(t('generatedReview'))}</p><article class="lesson-document" lang="${e(material.language)}">${body}</article>`
  );
}
content.addEventListener('submit', (event) => {
  if (event.target.id === 'filters') {
    event.preventDefault();
    filters = Object.fromEntries(new FormData(event.target));
    materialPage = 1;
    void render();
  } else if (event.target.id === 'settings-form') {
    event.preventDefault();
    void busy(event.target, async () => {
      try {
        const values = Object.fromEntries(new FormData(event.target));
        dashboard.profile = await api('/profile', {
          method: 'PATCH',
          body: JSON.stringify(values),
        });
        setLanguage(values.language);
        await render();
        notice(status, t('saved'));
      } catch (error) {
        notice(status, errorText(error), true);
      }
    });
  }
});
content.addEventListener('click', async (event) => {
  const page = event.target.closest('[data-page]');
  if (page) {
    if (page.dataset.list === 'materials') materialPage = Number(page.dataset.page);
    else if (page.dataset.list === 'jobs') jobPage = Number(page.dataset.page);
    else tokenPage = Number(page.dataset.page);
    void render();
  }
  const cancel = event.target.closest('[data-cancel-job]');
  if (cancel) {
    cancel.disabled = true;
    try {
      await api(`/generations/${cancel.dataset.cancelJob}/cancel`, { method: 'POST' });
      await refreshDashboard();
      await render();
    } catch (error) {
      notice(status, errorText(error), true);
      cancel.disabled = false;
    }
  }
  const rename = event.target.closest('[data-rename]');
  const remove = event.target.closest('[data-delete]');
  if (rename || remove) {
    const dialog = document.querySelector('#confirm-dialog');
    dialogAction = {
      kind: rename ? 'rename' : 'delete',
      id: rename?.dataset.rename || remove.dataset.delete,
      opener: rename || remove,
    };
    document.querySelector('#dialog-title').textContent = t(rename ? 'rename' : 'deleteMaterial');
    document.querySelector('#dialog-description').textContent = rename ? '' : t('deleteConfirm');
    const value = document.querySelector('#rename-value');
    value.hidden = !rename;
    value.disabled = !rename;
    value.required = Boolean(rename);
    value.value = rename?.dataset.title || '';
    document.querySelector('#rename-label').hidden = !rename;
    document.querySelector('#dialog-submit').textContent = t(rename ? 'save' : 'deleteMaterial');
    notice(document.querySelector('#dialog-error'), '');
    dialog.showModal();
    (rename ? value : document.querySelector('#dialog-cancel')).focus();
  }
});
document
  .querySelector('#dialog-cancel')
  .addEventListener('click', () => document.querySelector('#confirm-dialog').close());
document
  .querySelector('#confirm-dialog')
  .addEventListener('close', () => dialogAction?.opener?.focus());
document.querySelector('#dialog-form').addEventListener('submit', (event) => {
  event.preventDefault();
  void busy(event.target, async () => {
    try {
      await api(`/materials/${dialogAction.id}`, {
        method: dialogAction.kind === 'delete' ? 'DELETE' : 'PATCH',
        ...(dialogAction.kind === 'rename'
          ? {
              body: JSON.stringify({ title: document.querySelector('#rename-value').value.trim() }),
            }
          : {}),
      });
      document.querySelector('#confirm-dialog').close();
      if (dialogAction.kind === 'delete') location.hash = 'materials';
      else await render();
    } catch (error) {
      notice(document.querySelector('#dialog-error'), errorText(error), true);
    }
  });
});
document.querySelectorAll('[data-language]').forEach((button) =>
  button.addEventListener('click', async () => {
    setLanguage(button.dataset.language);
    topbar();
    await render();
    try {
      if (dashboard.profile.display_name)
        dashboard.profile = await api('/profile', {
          method: 'PATCH',
          body: JSON.stringify({ display_name: dashboard.profile.display_name, language: lang() }),
        });
    } catch (error) {
      notice(status, errorText(error), true);
    }
  })
);
window.addEventListener('hashchange', () => {
  void render();
  document.querySelector('#workspace').focus({ preventScroll: true });
});
window.addEventListener('sana:expired', () => location.replace('/auth.html#login'));
document.querySelector('#logout').addEventListener('click', async (event) => {
  event.currentTarget.disabled = true;
  try {
    const { error } = await client.auth.signOut({ scope: 'local' });
    if (error) throw error;
    location.replace('/');
  } catch {
    notice(status, t('error_network'), true);
    event.target.disabled = false;
  }
});
setLanguage(lang());
try {
  ({ client } = await connect());
  const session = client ? (await client.auth.getSession()).data.session : null;
  if (!session) location.replace('/auth.html#login');
  else {
    await refreshDashboard();
    setLanguage(dashboard.profile.language);
    topbar();
    client.auth.onAuthStateChange((event) => {
      if (event === 'SIGNED_OUT') location.replace('/auth.html#login');
    });
    await render();
  }
} catch (error) {
  notice(status, errorText(error), true);
  content.replaceChildren();
}
