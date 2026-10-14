import test from 'node:test';
import assert from 'node:assert/strict';
import { LESSONS } from '../dist/content.js';
import { createGameState, answerQuestion, advanceQuestion, completedCount } from '../dist/game-state.js';

for (const lesson of LESSONS) {
  test(`${lesson.id}: every correct answer completes the game with full first-try credit`, () => {
    const state = createGameState();
    const questions = lesson.game.questions;
    assert.equal(completedCount(state, questions.length), 0);
    questions.forEach((question, index) => {
      assert.equal(state.index, index);
      assert.equal(state.finished, false);
      assert.equal(answerQuestion(state, question, question.correct), true);
      assert.equal(completedCount(state, questions.length), index + 1);
      assert.equal(state.firstTry, index + 1);
      assert.equal(advanceQuestion(state, questions.length), true);
    });
    assert.equal(state.finished, true);
    assert.equal(completedCount(state, questions.length), questions.length);
    assert.equal(state.firstTry, questions.length);
    const finished = structuredClone(state);
    assert.equal(advanceQuestion(state, questions.length), false);
    assert.equal(answerQuestion(state, questions.at(-1), questions.at(-1).correct), false);
    assert.deepEqual(state, finished, 'a completed game must stay unchanged');
  });

  test(`${lesson.id}: a wrong answer neither advances progress nor earns first-try credit`, () => {
    const state = createGameState();
    const questions = lesson.game.questions;
    const question = questions[0];
    const wrong = question.options.findIndex((_, index) => index !== question.correct);
    assert.equal(answerQuestion(state, question, wrong), true);
    assert.equal(state.index, 0);
    assert.equal(state.solved, false);
    assert.equal(state.firstTry, 0);
    assert.equal(completedCount(state, questions.length), 0);
    const afterWrong = structuredClone(state);
    assert.equal(advanceQuestion(state, questions.length), false);
    assert.deepEqual(state, afterWrong, 'cannot skip a question after an error');
    assert.equal(answerQuestion(state, question, wrong), false);
    assert.deepEqual(state, afterWrong, 'repeated incorrect clicks are ignored');
    assert.equal(answerQuestion(state, question, question.correct), true);
    assert.equal(state.solved, true);
    assert.equal(state.firstTry, 0, 'success after an error is not a first try');
    assert.equal(completedCount(state, questions.length), 1);
    assert.equal(advanceQuestion(state, questions.length), true);
    assert.deepEqual(state.attempts, [], 'each next question starts with fresh attempts');
    assert.equal(answerQuestion(state, questions[1], questions[1].correct), true);
    assert.equal(state.firstTry, 1, 'a previous error must not affect the next question');
  });
}

test('a fresh unresolved question cannot be skipped', () => {
  const state = createGameState();
  const before = structuredClone(state);
  assert.equal(advanceQuestion(state, 5), false);
  assert.deepEqual(state, before);
});

test('repeating a correct answer cannot add points or change attempts', () => {
  const state = createGameState();
  const question = LESSONS[0].game.questions[0];
  assert.equal(answerQuestion(state, question, question.correct), true);
  const solved = structuredClone(state);
  assert.equal(answerQuestion(state, question, question.correct), false);
  assert.equal(answerQuestion(state, question, (question.correct + 1) % question.options.length), false);
  assert.deepEqual(state, solved);
  assert.equal(state.firstTry, 1);
});

test('invalid answer indexes are ignored without spending an attempt', () => {
  const state = createGameState();
  const question = LESSONS[0].game.questions[0];
  const before = structuredClone(state);
  for (const invalid of [-1, question.options.length, 0.5, NaN, Infinity, '1', null, undefined]) {
    assert.equal(answerQuestion(state, question, invalid), false);
    assert.deepEqual(state, before);
  }
});

test('subject states keep independent scores, attempts and progress', () => {
  const states = Object.fromEntries(LESSONS.map((lesson) => [lesson.id, createGameState()]));
  const initialMath = structuredClone(states.math);
  const initialPhysics = structuredClone(states.physics);
  const question = LESSONS.find((lesson) => lesson.id === 'history').game.questions[0];
  answerQuestion(states.history, question, question.correct);
  advanceQuestion(states.history, 5);
  assert.equal(states.history.index, 1);
  assert.deepEqual(states.math, initialMath);
  assert.deepEqual(states.physics, initialPhysics);
  assert.notEqual(states.math.attempts, states.physics.attempts);
  assert.notEqual(states.history.attempts, states.physics.attempts);
});

test('restart creates a clean game without changing a different subject', () => {
  const history = LESSONS.find((lesson) => lesson.id === 'history');
  const states = { history: createGameState(), math: createGameState() };
  for (const question of history.game.questions) {
    answerQuestion(states.history, question, question.correct);
    advanceQuestion(states.history, history.game.questions.length);
  }
  assert.equal(states.history.finished, true);
  const oldHistory = states.history;
  const mathBefore = structuredClone(states.math);
  states.history = createGameState();
  assert.equal(states.history.index, 0);
  assert.equal(states.history.finished, false);
  assert.equal(states.history.solved, false);
  assert.equal(states.history.firstTry, 0);
  assert.equal(completedCount(states.history, 5), 0);
  assert.deepEqual(states.history.attempts, []);
  assert.notEqual(states.history.attempts, oldHistory.attempts);
  assert.deepEqual(states.math, mathBefore);
  assert.equal(answerQuestion(states.history, history.game.questions[0], history.game.questions[0].correct), true);
  assert.equal(states.history.firstTry, 1);
});
