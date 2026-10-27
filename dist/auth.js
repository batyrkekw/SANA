import { connect, api } from './session.js';
import { t, lang, setLanguage, notice, busy, errorText } from './platform-common.js';
import { birdMarkup } from './illustrations.js';
const form = document.querySelector('#auth-form');
const message = document.querySelector('#auth-notice');
document.querySelector('#auth-bird').innerHTML = birdMarkup();
let mode = new URLSearchParams(location.search).has('recovery')
  ? 'recovery'
  : location.hash.slice(1) || 'login';
let client, config;
function render() {
  if (!['login', 'register', 'reset', 'recovery'].includes(mode)) mode = 'login';
  setLanguage(lang());
  document.title = `SANA — ${t(mode === 'register' ? 'signUp' : mode === 'reset' ? 'resetPassword' : 'signIn')}`;
  document.querySelector('#auth-heading').textContent = t(
    mode === 'register'
      ? 'registerTitle'
      : ['reset', 'recovery'].includes(mode)
        ? 'resetTitle'
        : 'authTitle'
  );
  for (const [name, show] of Object.entries({
    name: mode === 'register',
    email: mode !== 'recovery',
    password: mode !== 'reset',
    confirm: ['register', 'recovery'].includes(mode),
  })) {
    const field = document.querySelector(`#${name}-field`);
    field.hidden = !show;
    field.querySelector('input').disabled = !show;
    field.querySelector('input').required = show;
  }
  document.querySelector('#password').autocomplete =
    mode === 'login' ? 'current-password' : 'new-password';
  document.querySelector('#password').minLength = mode === 'login' ? 1 : 10;
  document.querySelector('#password-hint').hidden = mode === 'login';
  document.querySelector('#auth-submit').textContent = t(
    { login: 'signIn', register: 'signUp', reset: 'resetPassword', recovery: 'savePassword' }[mode]
  );
  document.querySelector('#google').hidden =
    !client || !config?.google_oauth_enabled || !['login', 'register'].includes(mode);
  document.querySelectorAll('#auth-links a').forEach((link) => {
    link.hidden = link.hash === `#${mode}`;
  });
  if (config && !config.auth_configured) {
    document.querySelector('#auth-heading').textContent = t('authUnavailable');
    notice(message, t('authSetup'));
  }
}
window.addEventListener('hashchange', () => {
  mode = location.hash.slice(1);
  notice(message, '');
  render();
});
document.querySelectorAll('[data-language]').forEach((button) =>
  button.addEventListener('click', () => {
    setLanguage(button.dataset.language);
    render();
  })
);
async function enter() {
  const profile = await api('/profile');
  // Existing profiles keep their stored language; new registrations initialize it below.
  setLanguage(profile.language);
  location.replace('/account.html');
}
render();
try {
  ({ client, config } = await connect());
  if (!client) {
    document.querySelector('#auth-heading').textContent = t('authUnavailable');
    notice(message, t('authSetup'));
  } else {
    form.hidden = false;
    document.querySelector('#auth-links').hidden = false;
    client.auth.onAuthStateChange((event) => {
      if (event === 'PASSWORD_RECOVERY') {
        mode = 'recovery';
        render();
      }
    });
    const {
      data: { session },
    } = await client.auth.getSession();
    if (session && ['login', 'register'].includes(mode)) await enter();
    render();
  }
} catch (error) {
  notice(message, errorText(error), true);
}
form.addEventListener('submit', (event) => {
  event.preventDefault();
  void busy(form, async () => {
    notice(message, '');
    try {
      const values = new FormData(form);
      const email = String(values.get('email') || '').trim();
      const password = String(values.get('password') || '');
      if (['register', 'recovery'].includes(mode) && password !== values.get('confirmation')) {
        notice(message, t('passwordMismatch'), true);
        return;
      }
      let result;
      if (mode === 'login') result = await client.auth.signInWithPassword({ email, password });
      else if (mode === 'register')
        result = await client.auth.signUp({
          email,
          password,
          options: {
            data: { display_name: String(values.get('name')).trim(), language: lang() },
            emailRedirectTo: `${location.origin}/auth.html`,
          },
        });
      else if (mode === 'reset')
        result = await client.auth.resetPasswordForEmail(email, {
          redirectTo: `${location.origin}/auth.html?recovery=1`,
        });
      else result = await client.auth.updateUser({ password });
      if (result.error) {
        notice(message, t('auth_error'), true);
        return;
      }
      if (mode === 'reset') {
        notice(message, t('resetSent'));
        return;
      }
      if (mode === 'register' && !result.data.session) {
        notice(message, t('checkEmail'));
        return;
      }
      if (mode === 'register') {
        await api('/profile');
        await api('/profile', {
          method: 'PATCH',
          body: JSON.stringify({
            display_name: String(values.get('name')).trim(),
            language: lang(),
          }),
        });
      }
      await enter();
    } catch (error) {
      notice(message, errorText(error), true);
    }
  });
});
document.querySelector('#google').addEventListener('click', async (event) => {
  event.currentTarget.disabled = true;
  try {
    const { error } = await client.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${location.origin}/auth.html` },
    });
    if (error) notice(message, t('auth_error'), true);
  } catch {
    notice(message, t('error_network'), true);
  } finally {
    document.querySelector('#google').disabled = false;
  }
});
