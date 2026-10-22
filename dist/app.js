import { LESSONS, SOURCES } from './content.js';
import { UI, normalizeLanguage, translate } from './i18n.js';
import { birdMarkup, lessonArt } from './illustrations.js';
import { createGameState, answerQuestion, advanceQuestion, completedCount } from './game-state.js';
import { setupPlanDialog } from './plans.js';

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
let language = 'ru';
try { language = normalizeLanguage(localStorage.getItem('sana-language')); } catch { /* Storage can be unavailable; the page still works. */ }
const t = (key, values) => translate(language, key, values);
const localized = (value) => value[language];
let filter = 'all';
let activeGame = 'history';
let currentLesson = null;
let page = 0;
let comicTrigger = null;
const gameStates = Object.fromEntries(LESSONS.map((lesson) => [lesson.id, createGameState()]));
const modal = $('#comic');
const grid = $('#lesson-grid');
const next = $('#game-next');
const planDialog = setupPlanDialog(t);

$('#hero-bird').innerHTML = birdMarkup({ animated: true });
$('#game-bird').innerHTML = birdMarkup();

function applyLanguage() {
  document.documentElement.lang = language;
  document.title = UI[language].title;
  $('meta[name="description"]').content = UI[language].metaDescription;
  document.querySelectorAll('[data-i18n]').forEach((node) => { node.textContent = t(node.dataset.i18n); });
  document.querySelectorAll('[data-i18n-aria]').forEach((node) => { node.setAttribute('aria-label', t(node.dataset.i18nAria)); });
  document.querySelectorAll('[data-language]').forEach((button) => {
    const active = button.dataset.language === language;
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('active', active);
  });
  renderLessons(); renderGameTabs(); renderGame();
  if (currentLesson) drawPage();
  planDialog.render();
}

document.querySelectorAll('[data-language]').forEach((button) => button.addEventListener('click', () => {
  if (language === button.dataset.language) return;
  language = normalizeLanguage(button.dataset.language);
  try { localStorage.setItem('sana-language', language); } catch { /* Continue without persistence. */ }
  applyLanguage();
}));

function renderLessons() {
  grid.innerHTML = LESSONS.filter((lesson) => filter === 'all' || lesson.id === filter).map((lesson) => `
    <article class="lesson-card flex flex-col">
      <div class="card-art art-${lesson.id}">${lessonArt(lesson.id)}<span class="art-caption">${t('story')} ${String(LESSONS.indexOf(lesson) + 1).padStart(2, '0')} / SANA</span></div>
      <div class="card-body flex flex-1 flex-col">
        <div class="card-kicker flex items-center justify-between gap-3"><span>${escapeHTML(localized(lesson.subject))}</span><span class="whitespace-nowrap">${t('fourPanels')}</span></div>
        <h3>${escapeHTML(localized(lesson.title))}</h3><p class="flex-1">${escapeHTML(localized(lesson.description))}</p>
        <button type="button" class="card-open" data-lesson="${lesson.id}"><span>${t('readComic')}</span><span aria-hidden="true">↗</span></button>
      </div>
    </article>`).join('');
}

document.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => {
  filter = button.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach((item) => {
    const selected = item.dataset.filter === filter;
    item.classList.toggle('active', selected);
    item.setAttribute('aria-pressed', String(selected));
  });
  renderLessons();
}));

function drawPage() {
  const panel = currentLesson.pages[page];
  const source = SOURCES.find((item) => item.subject === currentLesson.id);
  $('#comic-label').textContent = localized(currentLesson.title);
  $('#comic-content').innerHTML = `
    <div class="comic-scene">
      <div class="comic-visual" aria-hidden="true">${lessonArt(currentLesson.id, page)}</div>
      <div class="comic-panel-copy"><div class="eyebrow">${t('panel')} ${String(page + 1).padStart(2, '0')} / 04</div><h3>${escapeHTML(localized(panel.title))}</h3>
        <div class="comic-dialogue"><span class="comic-speaker">${escapeHTML(localized(panel.speaker))}</span><p>${escapeHTML(localized(panel.dialogue))}</p></div>
        <div class="comic-insight"><strong>${t('insight')}</strong><p>${escapeHTML(localized(panel.insight))}</p></div>
      </div>
    </div>${source ? `<a class="comic-source" href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer">${t('source')} ↗</a>` : ''}`;
  $('#page-count').textContent = `${page + 1} / ${currentLesson.pages.length}`;
  $('#prev-page').disabled = page === 0;
  $('#next-page').textContent = page === currentLesson.pages.length - 1 ? t('toGame') : t('nextPage');
}

grid.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-lesson]');
  if (!trigger) return;
  comicTrigger = trigger.dataset.lesson;
  currentLesson = LESSONS.find((lesson) => lesson.id === comicTrigger);
  page = 0; drawPage(); modal.showModal();
  document.body.classList.add('modal-open');
  modal.scrollTop = 0;
  $('#close-comic').focus();
});
$('#close-comic').addEventListener('click', () => modal.close());
modal.addEventListener('close', () => {
  document.body.classList.remove('modal-open');
  // Language changes replace cards, so focus the current trigger element.
  grid.querySelector(`[data-lesson="${comicTrigger}"]`)?.focus({ preventScroll: true });
});
modal.addEventListener('click', (event) => {
  if (event.target !== modal) return;
  const rect = modal.getBoundingClientRect();
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) modal.close();
});
$('#prev-page').addEventListener('click', () => {
  if (page > 0) { page -= 1; drawPage(); modal.scrollTop = 0; }
});
$('#next-page').addEventListener('click', () => {
  if (page < currentLesson.pages.length - 1) { page += 1; drawPage(); modal.scrollTop = 0; }
  else {
    activeGame = currentLesson.id;
    modal.close(); renderGameTabs(); renderGame();
    $('#games').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    requestAnimationFrame(() => $('#game-question').focus({ preventScroll: true }));
  }
});

function renderGameTabs() {
  $('#game-tabs').innerHTML = LESSONS.map((lesson) => `<button type="button" data-game="${lesson.id}" class="${lesson.id === activeGame ? 'active' : ''}" aria-pressed="${lesson.id === activeGame}">${escapeHTML(localized(lesson.subject))}</button>`).join('');
}
$('#game-tabs').addEventListener('click', (event) => {
  const button = event.target.closest('[data-game]');
  if (!button) return;
  activeGame = button.dataset.game;
  renderGameTabs(); renderGame();
  $(`[data-game="${activeGame}"]`).focus({ preventScroll: true });
});

function renderGame() {
  const game = LESSONS.find((item) => item.id === activeGame).game;
  const state = gameStates[activeGame];
  const total = game.questions.length;
  const completed = completedCount(state, total);
  const question = game.questions[state.index];
  $('#game-title').textContent = localized(game.title);
  $('#game-description').textContent = localized(game.description);
  $('#game-mission').textContent = state.finished ? '' : localized(game.mission);
  $('#game-count').textContent = `${state.finished ? total : state.index + 1} / ${total}`;
  $('#game-stars').textContent = Array.from({ length: total }, (_, index) => index < completed ? '★' : '☆').join(' ');
  $('.game-progress').setAttribute('aria-valuenow', completed);
  $('.game-progress').setAttribute('aria-valuemax', total);
  $('.game-progress-fill').style.width = `${completed / total * 100}%`;
  $('#game-question').textContent = state.finished ? t('completed') : localized(question.prompt);
  $('#game-answers').innerHTML = state.finished ? '' : question.options.map((option, index) => {
    const attempted = state.attempts.includes(index);
    const correct = state.solved && index === question.correct;
    const wrong = attempted && index !== question.correct;
    return `<button type="button" data-answer="${index}" class="${correct ? 'correct' : wrong ? 'wrong' : ''}" ${state.solved || attempted ? 'disabled' : ''}><span class="answer-letter" aria-hidden="true">${String.fromCharCode(65 + index)}</span><span>${escapeHTML(localized(option))}</span>${correct ? '<span aria-hidden="true">✓</span>' : wrong ? '<span aria-hidden="true">×</span>' : ''}</button>`;
  }).join('');
  const feedback = $('#game-feedback');
  feedback.classList.toggle('is-correct', state.solved);
  feedback.textContent = state.finished ? `${t('result', { total, score: state.firstTry })} ${t('resultEncouragement')}`
    : state.solved ? `${t('correct')} ${localized(question.explanation)}` : state.attempts.length ? t('wrong') : t('chooseAnswer');
  next.hidden = !state.solved && !state.finished;
  next.textContent = state.finished ? t('restart') : state.index === total - 1 ? t('showResult') : t('nextQuestion');
}

$('#game-answers').addEventListener('click', (event) => {
  const button = event.target.closest('[data-answer]');
  if (!button) return;
  const state = gameStates[activeGame];
  const question = LESSONS.find((item) => item.id === activeGame).game.questions[state.index];
  if (!answerQuestion(state, question, Number(button.dataset.answer))) return;
  renderGame();
  if (state.solved) next.focus({ preventScroll: true });
  else $('#game-answers button:not(:disabled)')?.focus({ preventScroll: true });
});
next.addEventListener('click', () => {
  const state = gameStates[activeGame];
  const total = LESSONS.find((item) => item.id === activeGame).game.questions.length;
  if (state.finished) gameStates[activeGame] = createGameState();
  else advanceQuestion(state, total);
  renderGame(); $('#game-question').focus({ preventScroll: true });
});

applyLanguage();
const steps = $('.steps');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
if ('IntersectionObserver' in window && !reducedMotion.matches) {
  steps.classList.add('animate-ready');
  const observer = new IntersectionObserver((entries) => {
    if (!entries.some((entry) => entry.isIntersecting)) return;
    steps.classList.add('is-visible'); observer.disconnect();
  }, { threshold: 0.3 });
  observer.observe(steps);
} else steps.classList.add('is-visible');
