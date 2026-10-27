import { normalizeLanguage, translate, UI } from './i18n.js';
let language = 'ru';
try {
  language = normalizeLanguage(localStorage.getItem('sana-language'));
} catch {
  /* Optional storage. */
}
export const lang = () => language;
export const t = (key, values) => translate(language, key, values);
export const escapeHTML = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  );
export function setLanguage(value) {
  language = normalizeLanguage(value);
  document.documentElement.lang = language;
  try {
    localStorage.setItem('sana-language', language);
  } catch {
    /* Optional storage. */
  }
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-aria]').forEach((node) => {
    node.setAttribute('aria-label', t(node.dataset.i18nAria));
  });
  document
    .querySelectorAll('[data-language]')
    .forEach((button) =>
      button.setAttribute('aria-pressed', String(button.dataset.language === language))
    );
}
export function errorText(error) {
  const key = `error_${error.code || 'internal_error'}`;
  return t(Object.hasOwn(UI[language], key) ? key : 'error_internal_error');
}
export const number = (value) => new Intl.NumberFormat(lang()).format(value);
export const date = (value) =>
  new Intl.DateTimeFormat(lang(), { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value)
  );
export async function busy(form, work) {
  if (form.dataset.busy) return;
  form.dataset.busy = 'true';
  form.setAttribute('aria-busy', 'true');
  const buttons = [...form.querySelectorAll('button')].filter((button) => !button.disabled);
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    await work();
  } finally {
    delete form.dataset.busy;
    form.removeAttribute('aria-busy');
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}
export function notice(node, message, error = false) {
  node.textContent = message;
  node.classList.toggle('is-error', error);
  node.hidden = !message;
}
