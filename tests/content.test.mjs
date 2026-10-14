import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { LESSONS } from '../dist/content.js';
import { UI, normalizeLanguage, translate } from '../dist/i18n.js';

const languages = ['ru', 'kk'];
const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');

function assertLocalized(value, label) {
  assert.ok(value && typeof value === 'object', `${label}: localized object required`);
  for (const language of languages) {
    assert.equal(typeof value[language], 'string', `${label}.${language}`);
    assert.ok(value[language].trim().length > 0, `${label}.${language} must not be empty`);
    assert.doesNotMatch(value[language], /\uFFFD/, `${label}.${language}: invalid encoding`);
  }
}

test('Russian and Kazakh have the same complete UI vocabulary and placeholders', () => {
  assert.deepEqual(Object.keys(UI.ru).sort(), Object.keys(UI.kk).sort());
  assert.ok(Object.keys(UI.ru).length > 0);
  for (const key of Object.keys(UI.ru)) {
    assertLocalized({ ru: UI.ru[key], kk: UI.kk[key] }, `UI.${key}`);
    const placeholders = (text) => [...new Set(text.match(/\{\w+\}/g) || [])].sort();
    assert.deepEqual(placeholders(UI.ru[key]), placeholders(UI.kk[key]), `UI.${key}: same interpolation values`);
  }
});

test('all text and accessibility translations referenced by the HTML exist in both languages', () => {
  const keys = [...html.matchAll(/\bdata-i18n(?:-aria)?=["']([^"']+)["']/g)].map((match) => match[1]);
  assert.ok(keys.length > 0, 'HTML must contain translated UI');
  assert.match(html, /\bdata-i18n-aria=/, 'accessibility labels must also be translated');
  for (const key of new Set(keys)) {
    for (const language of languages) {
      assert.ok(Object.hasOwn(UI[language], key), `${language}.${key} used in HTML`);
      assert.equal(translate(language, key), UI[language][key]);
    }
  }
});

test('language normalization and result interpolation handle both supported languages', () => {
  assert.equal(normalizeLanguage('kk'), 'kk');
  assert.equal(normalizeLanguage('ru'), 'ru');
  for (const unsupported of [null, undefined, '', 'en', 'RU']) {
    assert.equal(normalizeLanguage(unsupported), 'ru');
  }
  for (const language of languages) {
    const result = translate(language, 'result', { total: 5, score: 3 });
    assert.match(result, /5/);
    assert.match(result, /3/);
    assert.doesNotMatch(result, /\{\w+\}/);
  }
  assert.throws(() => translate('ru', '__missing_translation__'), /Missing translation/);
});

test('the library contains exactly the three requested grade 8 subjects', () => {
  assert.deepEqual(LESSONS.map((lesson) => lesson.id).sort(), ['history', 'math', 'physics']);
  for (const lesson of LESSONS) {
    for (const field of ['subject', 'title', 'description', 'topic']) {
      assertLocalized(lesson[field], `${lesson.id}.${field}`);
    }
    for (const language of languages) assert.match(lesson.topic[language], /8/, `${lesson.id} grade`);
  }
});

for (const lesson of LESSONS) {
  test(`${lesson.id}: all four comic panels are available in Russian and Kazakh`, () => {
    assert.equal(lesson.pages.length, 4);
    lesson.pages.forEach((panel, index) => {
      for (const field of ['title', 'speaker', 'dialogue', 'insight']) {
        assertLocalized(panel[field], `${lesson.id}.pages[${index}].${field}`);
      }
    });
  });

  test(`${lesson.id}: five localized game tasks have valid and distinguishable answers`, () => {
    for (const field of ['title', 'description', 'mission']) {
      assertLocalized(lesson.game[field], `${lesson.id}.game.${field}`);
    }
    assert.equal(lesson.game.questions.length, 5);
    lesson.game.questions.forEach((question, index) => {
      const label = `${lesson.id}.questions[${index}]`;
      assertLocalized(question.prompt, `${label}.prompt`);
      assertLocalized(question.explanation, `${label}.explanation`);
      assert.ok(question.options.length >= 2, `${label}: choice required`);
      assert.ok(Number.isInteger(question.correct), `${label}: integer correct index`);
      assert.ok(question.correct >= 0 && question.correct < question.options.length, `${label}: correct index is in range`);
      question.options.forEach((option, optionIndex) => assertLocalized(option, `${label}.options[${optionIndex}]`));
      for (const language of languages) {
        const normalized = question.options.map((option) => option[language].trim().normalize('NFC').toLocaleLowerCase(language));
        assert.equal(new Set(normalized).size, question.options.length, `${label}.${language}: visually distinct options`);
      }
    });
  });
}
