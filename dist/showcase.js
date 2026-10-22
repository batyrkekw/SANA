import { LESSONS } from './content.js';
import { lessonArt } from './illustrations.js';
import { createGameState, answerQuestion } from './game-state.js';

const escapeHTML = (value) => String(value).replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
const TABS = ['explain', 'practice', 'classroom'];
const TAB_KEYS = { explain: 'showcaseExplain', practice: 'showcasePractice', classroom: 'showcaseClassroom' };
const TIMER_STATUS_KEYS = { ready: 'timerReady', running: 'timerRunning', paused: 'timerPaused', complete: 'timerComplete' };

export function setupShowcase(t) {
  const root = document.querySelector('#feature-showcase');
  if (!root) return { render() {} };

  // Keep this live region mounted outside the panels. Replacing a panel must
  // not replace its announcement target, and hidden tabs must not hide it.
  const content = document.createElement('div');
  content.className = 'showcase-content';
  const liveRegion = document.createElement('p');
  liveRegion.className = 'sr-only';
  liveRegion.setAttribute('role', 'status');
  liveRegion.setAttribute('aria-live', 'polite');
  liveRegion.setAttribute('aria-atomic', 'true');
  root.replaceChildren(content, liveRegion);

  const mathLesson = LESSONS.find((lesson) => lesson.id === 'math');
  const sampleQuestion = LESSONS.find((lesson) => lesson.id === 'history').game.questions[0];
  const localize = (value) => value[document.documentElement.lang === 'kk' ? 'kk' : 'ru'];
  let activeTab = 'explain';
  let sampleState = createGameState();
  let durationMs = 3 * 60_000;
  let remainingMs = durationMs;
  let deadline = null;
  let timerStatus = 'ready';
  let timerInterval = null;
  let announcedTimerStatus = timerStatus;
  let announcementVersion = 0;

  const q = (selector) => root.querySelector(selector);
  const safe = (key, values) => escapeHTML(t(key, values));

  function announce(message) {
    const version = ++announcementVersion;
    liveRegion.textContent = '';
    liveRegion.lang = document.documentElement.lang;
    // Separate clearing and updating so repeated wrong answers are announced
    // too. The region itself remains the same node throughout the session.
    requestAnimationFrame(() => {
      if (version === announcementVersion) liveRegion.textContent = message;
    });
  }

  function sampleFeedback() {
    return sampleState.solved
      ? `${t('showcaseAnswerCorrect')} ${localize(sampleQuestion.explanation)}`
      : sampleState.attempts.length ? t('showcaseAnswerWrong') : t('showcaseAnswerPrompt');
  }

  function stopTicking() {
    if (timerInterval !== null) clearInterval(timerInterval);
    timerInterval = null;
  }

  // Read the deadline rather than subtracting one second per interval. This
  // catches up after browser throttling, sleep, or a hidden tab.
  function syncTimer() {
    if (timerStatus !== 'running') return;
    remainingMs = Math.max(0, deadline - Date.now());
    if (remainingMs === 0) {
      timerStatus = 'complete';
      deadline = null;
      stopTicking();
    }
  }

  function updateTimer({ announceStateChange = true } = {}) {
    syncTimer();
    const display = q('#showcase-timer-display');
    if (!display) return;
    const seconds = Math.ceil(remainingMs / 1000);
    const time = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    if (display.textContent !== time) display.textContent = time;
    q('.showcase-timer-face').style.setProperty('--timer-progress', `${remainingMs / durationMs * 360}deg`);
    const toggle = q('#showcase-timer-toggle');
    const key = timerStatus === 'running' ? 'timerPause' : timerStatus === 'paused' ? 'timerResume' : timerStatus === 'complete' ? 'timerRestart' : 'timerStart';
    if (toggle.textContent !== t(key)) toggle.textContent = t(key);
    const status = q('#showcase-timer-status');
    const message = t(TIMER_STATUS_KEYS[timerStatus]);
    // Visible status follows language changes. Only actual state transitions
    // are announced; ticking seconds never touch the live region.
    if (status.textContent !== message) status.textContent = message;
    if (timerStatus !== announcedTimerStatus) {
      announcedTimerStatus = timerStatus;
      if (announceStateChange) announce(message);
    }
    root.classList.toggle('showcase-timer-complete', timerStatus === 'complete');
  }

  function setDuration(minutes) {
    if (![1, 3, 5].includes(minutes)) return;
    stopTicking();
    durationMs = minutes * 60_000;
    remainingMs = durationMs;
    deadline = null;
    timerStatus = 'ready';
    root.querySelectorAll('[data-timer-minutes]').forEach((button) => {
      button.setAttribute('aria-pressed', String(Number(button.dataset.timerMinutes) === minutes));
    });
    updateTimer({ announceStateChange: false });
    announce(`${t('timerMinutes', { minutes })}. ${t('timerReady')}`);
  }

  function toggleTimer() {
    const wasRunning = timerStatus === 'running';
    syncTimer();
    if (wasRunning) {
      stopTicking();
      if (timerStatus !== 'complete') timerStatus = 'paused';
      deadline = null;
    } else {
      if (remainingMs === 0) remainingMs = durationMs;
      deadline = Date.now() + remainingMs;
      timerStatus = 'running';
      stopTicking();
      timerInterval = setInterval(updateTimer, 250);
    }
    updateTimer();
  }

  function panelAttributes(tab) {
    return `id="showcase-panel-${tab}" role="tabpanel" aria-labelledby="showcase-tab-${tab}" tabindex="0"${activeTab === tab ? '' : ' hidden'}`;
  }

  function render() {
    syncTimer();
    const focusedId = root.contains(document.activeElement) ? document.activeElement.id : null;
    const samplePanel = mathLesson.pages[0];
    const feedback = sampleFeedback();

    content.innerHTML = `
      <div class="showcase-tabs" role="tablist" aria-label="${safe('showcaseLabel')}">
        ${TABS.map((tab, index) => `<button type="button" id="showcase-tab-${tab}" class="showcase-tab" role="tab" data-showcase-tab="${tab}" aria-controls="showcase-panel-${tab}" aria-selected="${activeTab === tab}" tabindex="${activeTab === tab ? '0' : '-1'}"><span class="showcase-tab-number" aria-hidden="true">0${index + 1}</span>${safe(TAB_KEYS[tab])}</button>`).join('')}
      </div>
      <div class="showcase-panel" ${panelAttributes('explain')}>
        <div class="showcase-panel-heading"><span class="showcase-kicker">${safe('showcaseExplainKicker')}</span><h3>${safe('showcaseExplainTitle')}</h3><p>${safe('showcaseExplainDescription')}</p></div>
        <div class="showcase-art" aria-hidden="true">${lessonArt('math', 0)}</div>
        <div class="showcase-insight"><span class="showcase-insight-mark" aria-hidden="true">✦</span><span>${escapeHTML(localize(samplePanel.insight))}</span></div>
        <a class="showcase-link" href="#lessons">${safe('showcaseOpenLesson')}<span aria-hidden="true">↗</span></a>
      </div>
      <div class="showcase-panel" ${panelAttributes('practice')}>
        <div class="showcase-panel-heading"><span class="showcase-kicker">${safe('showcasePracticeKicker')}</span><h3>${safe('showcasePracticeTitle')}</h3><p>${safe('showcasePracticeDescription')}</p></div>
        <div class="showcase-quiz">
          <span class="showcase-quiz-label">${safe('showcaseQuestionLabel')}</span>
          <h4>${escapeHTML(localize(sampleQuestion.prompt))}</h4>
          <div class="showcase-answers">${sampleQuestion.options.map((option, index) => {
            const attempted = sampleState.attempts.includes(index);
            const correct = sampleState.solved && index === sampleQuestion.correct;
            const wrong = attempted && index !== sampleQuestion.correct;
            return `<button type="button" id="showcase-answer-${index}" data-showcase-answer="${index}" class="${correct ? 'is-correct' : wrong ? 'is-wrong' : ''}"${sampleState.solved || attempted ? ' disabled' : ''}><span>${escapeHTML(localize(option))}</span>${correct ? '<span aria-hidden="true">✓</span>' : wrong ? '<span aria-hidden="true">×</span>' : ''}</button>`;
          }).join('')}</div>
          <p id="showcase-answer-feedback" class="showcase-answer-feedback">${escapeHTML(feedback)}</p>
        </div>
        <div class="showcase-panel-footer"><a class="showcase-link" href="#games">${safe('showcaseOpenGame')}<span aria-hidden="true">↗</span></a>${sampleState.attempts.length ? `<button type="button" id="showcase-quiz-reset" class="showcase-reset" data-showcase-reset>${safe('showcaseTryAgain')}</button>` : ''}</div>
      </div>
      <div class="showcase-panel" ${panelAttributes('classroom')}>
        <div class="showcase-panel-heading"><span class="showcase-kicker">${safe('showcaseClassroomKicker')}</span><h3>${safe('showcaseClassroomTitle')}</h3><p>${safe('showcaseClassroomDescription')}</p></div>
        <div class="showcase-timer">
          <div class="showcase-timer-presets" role="group" aria-label="${safe('timerDurationLabel')}">${[1, 3, 5].map((minutes) => `<button type="button" id="showcase-timer-preset-${minutes}" data-timer-minutes="${minutes}" aria-pressed="${durationMs === minutes * 60_000}">${safe('timerMinutes', { minutes })}</button>`).join('')}</div>
          <div class="showcase-timer-face"><span id="showcase-timer-display" role="timer" aria-live="off" aria-label="${safe('timerRemaining')}"></span></div>
          <div class="showcase-timer-actions"><button type="button" id="showcase-timer-toggle" class="showcase-timer-primary" data-timer-toggle></button><button type="button" id="showcase-timer-reset" class="showcase-reset" data-timer-reset>${safe('timerReset')}</button></div>
          <p id="showcase-timer-status" class="showcase-timer-status"></p>
        </div>
      </div>`;
    updateTimer();
    if (focusedId) q(`#${focusedId}`)?.focus({ preventScroll: true });
  }

  root.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-showcase-tab]');
    if (tab) {
      activeTab = tab.dataset.showcaseTab;
      render();
      q(`#showcase-tab-${activeTab}`).focus({ preventScroll: true });
      return;
    }
    const answer = event.target.closest('[data-showcase-answer]');
    if (answer) {
      if (!answerQuestion(sampleState, sampleQuestion, Number(answer.dataset.showcaseAnswer))) return;
      render();
      announce(sampleFeedback());
      q(sampleState.solved ? '#showcase-quiz-reset' : '[data-showcase-answer]:not(:disabled)')?.focus({ preventScroll: true });
      return;
    }
    if (event.target.closest('[data-showcase-reset]')) {
      sampleState = createGameState();
      render();
      announce(t('showcaseAnswerPrompt'));
      q('[data-showcase-answer]')?.focus({ preventScroll: true });
      return;
    }
    const preset = event.target.closest('[data-timer-minutes]');
    if (preset) setDuration(Number(preset.dataset.timerMinutes));
    else if (event.target.closest('[data-timer-toggle]')) toggleTimer();
    else if (event.target.closest('[data-timer-reset]')) setDuration(durationMs / 60_000);
  });

  root.addEventListener('keydown', (event) => {
    const tab = event.target.closest('[data-showcase-tab]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = TABS.indexOf(tab.dataset.showcaseTab);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? TABS.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
    activeTab = TABS[nextIndex];
    render();
    q(`#showcase-tab-${activeTab}`).focus({ preventScroll: true });
  });

  document.addEventListener('visibilitychange', () => updateTimer());
  return { render };
}
