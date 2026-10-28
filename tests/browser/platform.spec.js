import { test, expect } from '@playwright/test';

// Deterministic browser contract tests only. Production has no fake auth or fake API mode.
const uid = '00000000-0000-4000-8000-000000000001';
const materialId = '00000000-0000-4000-8000-000000000002';
const plan = {
  code: 'basic',
  name: { ru: 'Обычный', kk: 'Қарапайым' },
  initial_tokens: 100,
  limits: { kinds: ['lesson', 'quiz', 'flashcards'], max_length: 4, max_tokens: 100 },
};
const material = {
  id: materialId,
  title: 'Закон Ома',
  subject: 'Физика',
  topic: 'Ток',
  language: 'ru',
  kind: 'quiz',
  created_at: '2026-10-28T00:00:00Z',
  assets: [],
  status: 'ready',
  content: {
    title: 'Закон Ома',
    language: 'ru',
    kind: 'quiz',
    questions: [
      {
        prompt: 'Сколько будет 2 + 2?',
        options: ['3', '4'],
        correct_index: 1,
        explanation: 'Два плюс два равно четырём.',
      },
    ],
  },
};
async function setup(page, { signedIn = false, configured = true } = {}) {
  const session = {
    access_token: 'browser-contract-token',
    refresh_token: 'browser-contract-refresh',
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    token_type: 'bearer',
    user: {
      id: uid,
      email: 'teacher@example.test',
      aud: 'authenticated',
      role: 'authenticated',
      app_metadata: { provider: 'email' },
      user_metadata: { display_name: 'Айдана' },
    },
  };
  let items = [],
    jobs = [],
    profile = { id: uid, display_name: 'Айдана', language: 'ru' };
  const requests = [];
  await page.route('https://sana-test.supabase.co/**', async (route) => {
    requests.push({ url: route.request().url(), body: route.request().postDataJSON() });
    const url = new URL(route.request().url());
    await route.fulfill({ json: url.pathname.endsWith('/user') ? session.user : session });
  });
  if (signedIn)
    await page.addInitScript(
      (value) => localStorage.setItem('sb-sana-test-auth-token', JSON.stringify(value)),
      session
    );
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname.replace('/api/v1', '');
    requests.push({
      path,
      method: req.method(),
      headers: req.headers(),
      body: req.postData() ? req.postDataJSON() : null,
    });
    let data;
    if (path === '/config')
      data = {
        auth_configured: configured,
        supabase_url: 'https://sana-test.supabase.co',
        supabase_publishable_key: 'sb_publishable_test',
        google_oauth_enabled: false,
      };
    else if (path === '/profile') {
      if (req.method() === 'PATCH') profile = { ...profile, ...req.postDataJSON() };
      data = profile;
    } else if (path === '/dashboard')
      data = {
        profile,
        plan,
        tokens: { available: 94, reserved: 6 },
        material_count: items.length,
        recent_materials: items,
      };
    else if (path === '/plans') data = [plan];
    else if (path === '/ai/status')
      data = { text: { status: 'available' }, image: { status: 'disabled' } };
    else if (path === '/generations/quote') data = { cost: 6 };
    else if (path === '/generations' && req.method() === 'POST') {
      jobs = [
        {
          id: 'job-1',
          status: 'completed',
          cost: 6,
          request: req.postDataJSON(),
          created_at: '2026-10-28T00:00:00Z',
          material_id: materialId,
          can_cancel: false,
        },
      ];
      items = [material];
      data = jobs[0];
    } else if (path === '/generations')
      data = { items: jobs, page: 1, page_size: 20, total: jobs.length };
    else if (path === '/materials')
      data = { items, page: 1, page_size: 12, total: items.length, subjects: ['Физика'] };
    else if (path === `/materials/${materialId}`) {
      if (req.method() === 'DELETE') {
        items = [];
        await route.fulfill({ status: 204 });
        return;
      }
      if (req.method() === 'PATCH') material.title = req.postDataJSON().title;
      data = material;
    } else if (path === '/me/tokens/transactions')
      data = { items: [], page: 1, page_size: 20, total: 0 };
    else if (path === '/me/tokens') data = { available: 94, reserved: 6 };
    else data = {};
    await route.fulfill({ json: data });
  });
  return requests;
}

test('public lessons survive and missing auth is explained in both languages', async ({ page }) => {
  await setup(page, { configured: false });
  await page.goto('/');
  await expect(page.locator('#lesson-grid .lesson-card')).toHaveCount(3);
  await page.locator('#nav-login').click();
  await expect(page.getByRole('heading', { name: 'Вход ещё не подключён' })).toBeVisible();
  await expect(page.locator('#auth-form')).toBeHidden();
  await page.getByRole('button', { name: 'ҚАЗ', exact: true }).click();
  await expect(page.locator('#auth-notice')).toContainText('тіркелусіз');
});

test('anonymous dashboard redirects and registration validates passwords', async ({ page }) => {
  const requests = await setup(page);
  await page.goto('/account.html');
  await expect(page).toHaveURL(/auth.html#login/);
  await page.locator('#auth-links').getByRole('link', { name: 'Создать аккаунт' }).click();
  await page.getByLabel('Ваше имя').fill('Айдана');
  await page.getByLabel('Email', { exact: true }).fill('teacher@example.test');
  await page.getByLabel('Пароль', { exact: true }).fill('longpassword123');
  await page.getByLabel('Повторите пароль').fill('differentpassword');
  await page.locator('#auth-submit').click();
  await expect(page.locator('#auth-notice')).toHaveText('Пароли не совпадают.');
  expect(requests.filter((r) => r.url?.includes('/signup'))).toHaveLength(0);
});

test('account reads real API values, quotes before submission, opens and deletes own result', async ({
  page,
}) => {
  const requests = await setup(page, { signedIn: true });
  await page.goto('/account.html');
  await expect(page.getByRole('heading', { name: 'Здравствуйте, Айдана.' })).toBeVisible();
  await expect(page.locator('#top-balance')).toContainText('94');
  expect(requests.filter((r) => r.path === '/dashboard')).toHaveLength(1);
  await page.getByRole('link', { name: 'Создать викторину', exact: true }).click();
  await page.getByLabel('Предмет', { exact: true }).fill('Физика');
  await page.getByLabel('Тема', { exact: true }).fill('Ток');
  await expect(page.locator('#generate-submit')).toBeDisabled();
  await page.getByRole('button', { name: 'Рассчитать стоимость' }).click();
  await expect(page.locator('#generate-submit')).toHaveText('Создать за 6 токенов');
  await page.locator('#generate-submit').click();
  await expect(page.getByRole('heading', { name: 'История генераций' })).toBeVisible();
  const submission = requests.find((r) => r.path === '/generations' && r.method === 'POST');
  expect(submission.headers['idempotency-key']).toBeTruthy();
  expect(submission.body.cost).toBeUndefined();
  await page.getByRole('link', { name: 'Открыть', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Закон Ома', exact: true })).toBeVisible();
  await page.getByText('Показать ответ', { exact: true }).click();
  await expect(page.getByText('Правильный ответ: 4')).toBeVisible();
  await page.getByRole('button', { name: 'Удалить материал', exact: true }).click();
  expect(requests.filter((r) => r.method === 'DELETE')).toHaveLength(0);
  await page.locator('#confirm-dialog').getByRole('button', { name: 'Отмена' }).click();
  expect(requests.filter((r) => r.method === 'DELETE')).toHaveLength(0);
  await page.getByRole('button', { name: 'Удалить материал', exact: true }).click();
  await page.locator('#dialog-submit').click();
  await expect(page).toHaveURL(/#materials/);
  expect(requests.filter((r) => r.method === 'DELETE')).toHaveLength(1);
});

test('mobile dashboard and language settings remain usable without overflow', async ({ page }) => {
  const requests = await setup(page, { signedIn: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/account.html#settings');
  await expect(page.locator('#settings-form')).toBeVisible();
  await page.getByLabel('Язык интерфейса').selectOption('kk');
  await page.getByRole('button', { name: 'Сохранить', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'kk');
  await expect(page.getByRole('heading', { name: 'Баптаулар' })).toBeVisible();
  expect(requests.some((r) => r.path === '/profile' && r.body?.language === 'kk')).toBeTruthy();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('signed-in user can request a recovery email from settings', async ({ page }) => {
  const requests = await setup(page, { signedIn: true });
  await page.goto('/account.html#settings');
  await page.locator('#settings-form a').click();
  await expect(page).toHaveURL(/auth.html#reset/);
  await page.getByLabel('Email', { exact: true }).fill('teacher@example.test');
  await page.locator('#auth-submit').click();
  await expect(page.locator('#auth-notice')).not.toBeEmpty();
  expect(requests.some((r) => r.url?.includes('/recover'))).toBeTruthy();
});

test('changing sections cancels stale reads and removes the previous form', async ({ page }) => {
  await setup(page, { signedIn: true });
  await page.goto('/account.html#settings');
  await expect(page.locator('#settings-form')).toBeVisible();
  let release, started;
  const pending = new Promise((resolve) => { release = resolve; });
  const requested = new Promise((resolve) => { started = resolve; });
  const failures = [];
  page.on('requestfailed', (request) => failures.push(request.url()));
  await page.route('**/api/v1/materials?**', async (route) => {
    started();
    await pending;
    await route.fulfill({ json: { items: [], subjects: [], page: 1, page_size: 12, total: 0 } }).catch(() => {});
  });
  await page.locator('.account-nav a[href="#materials"]').click();
  await requested;
  await expect(page.locator('#settings-form')).toHaveCount(0);
  await expect(page.locator('#workspace-content')).toHaveAttribute('aria-busy', 'true');
  await page.locator('.account-nav a[href="#plan"]').click();
  await expect(page.getByRole('heading', { name: 'Мой тариф', exact: true })).toBeVisible();
  await expect.poll(() => failures.some((url) => url.includes('/materials?'))).toBe(true);
  release();
  await expect(page.locator('#workspace-content')).not.toHaveAttribute('aria-busy');
  await expect(page.locator('#settings-form')).toHaveCount(0);
  await expect(page.locator('#workspace-status')).toBeEmpty();
});
