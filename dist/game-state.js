// State is independent of UI language, so translation never resets an attempt.
export function createGameState() { return { index: 0, attempts: [], solved: false, firstTry: 0, finished: false }; }
export function answerQuestion(state, question, choice) {
  if (state.finished || state.solved || !Number.isInteger(choice) || choice < 0 || choice >= question.options.length || state.attempts.includes(choice)) return false;
  state.attempts.push(choice);
  if (choice === question.correct) { state.solved = true; if (state.attempts.length === 1) state.firstTry += 1; }
  return true;
}
export function advanceQuestion(state, total) {
  if (!state.solved || state.finished) return false;
  if (state.index === total - 1) state.finished = true;
  else { state.index += 1; state.attempts = []; state.solved = false; }
  return true;
}
export function completedCount(state, total) { return state.finished ? total : state.index + Number(state.solved); }
