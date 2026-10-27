import { connect, api } from './session.js';
import { translate } from './i18n.js';
let signedIn = false;
const account = document.querySelector('#nav-account');
const login = document.querySelector('#nav-login');
function render() {
  login.hidden = signedIn;
  account.href = signedIn ? '/account.html' : '/auth.html#register';
  account.dataset.i18n = signedIn ? 'account' : 'signUp';
  account.textContent = translate(document.documentElement.lang, account.dataset.i18n);
}
try {
  const { client } = await connect();
  if (client) {
    signedIn = Boolean((await client.auth.getSession()).data.session);
    render();
    client.auth.onAuthStateChange((_event, session) => {
      signedIn = Boolean(session);
      render();
    });
  }
} catch {
  /* Public lessons remain available without an API. */
}
document.querySelectorAll('[data-language]').forEach((button) =>
  button.addEventListener('click', async () => {
    render();
    if (signedIn) {
      try {
        const profile = await api('/profile');
        if (profile.display_name)
          await api('/profile', {
            method: 'PATCH',
            body: JSON.stringify({
              display_name: profile.display_name,
              language: button.dataset.language,
            }),
          });
      } catch {
        /* Retry through account settings. */
      }
    }
  })
);
