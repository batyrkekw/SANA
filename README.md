# SANA

Образовательная платформа на русском и казахском: уроки, викторины, комиксы, карточки и иллюстрации. Исходная витрина с голубем, тремя комиксами, тремя играми, таймером и локальными черновиками отзывов сохранена. Кабинет работает через FastAPI и PostgreSQL; вход — через Supabase Auth. Платежей нет.

## Архитектура

```mermaid
flowchart LR
  Browser[HTML / JavaScript / Tailwind] --> Auth[Supabase Auth]
  Browser --> API[FastAPI: проверка JWT и владельца]
  API --> DB[(PostgreSQL: профили, квоты, материалы, задания)]
  API --> Queue[(Redis)]
  Queue --> Worker[Celery: один процесс генерации]
  Worker --> LLM[Локальная LLM / OpenAI-compatible API]
  Worker --> Images[PyTorch + Diffusers]
  Worker --> DB
  Worker --> Files[Приватные PNG вне Git]
```

- Node.js 22+, ESM JavaScript, Tailwind 4; Supabase JS собирается локально esbuild, без CDN.
- Python 3.12–3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 17, Redis 7, Celery 5.
- Зависимости зафиксированы в `package-lock.json` и `backend/uv.lock`.
- `dist/` содержит исходные HTML/JS и собранный CSS. Редактировать стили в `src/`, затем выполнять сборку. `dist/vendor/` создаётся сборкой и не хранится в Git.
- `backend/app/`: API, JWT, модели, схемы, сервис квот, worker, AI-провайдеры и приватное файловое хранилище. `config/plans.json` — единая конфигурация уровней доступа.

## Быстрый запуск на этом Mac

Нужны Node 22+, uv, Docker Desktop. Для AI также Ollama и свободное место для весов. Команды ниже выполняются из корня репозитория, если не указан `cd`. Создайте `.env` из примера **только если своего файла ещё нет**:

```sh
test -f .env || cp .env.example .env
npm ci
npm run build
docker compose -f compose.yaml -f compose.host.yaml up -d db redis
cd backend
uv sync --frozen --python 3.12
uv run --no-sync alembic upgrade head
uv run --no-sync python -m app.manage seed-plans
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Откройте [сайт](http://127.0.0.1:8000/) и [API-документацию](http://127.0.0.1:8000/docs). В отдельном терминале из корня можно запустить `npm start`: [витрина на 4173](http://127.0.0.1:4173/) проксирует `/api/` в API на 8000. `npm run dev` пересобирает CSS при изменениях.

Worker запускается отдельно из `backend/`:

```sh
uv run --no-sync celery -A app.worker:celery_app worker --pool=solo --concurrency=1 --loglevel=INFO
```

На macOS используйте `solo` для MPS. На Linux — обычный prefork (`--concurrency=1`, без `--pool=solo`). API и worker должны использовать одинаковые `.env`, PostgreSQL, Redis и каталог файлов. Запуск двух workers с общей GPU требует отдельного расчёта памяти; текущая конфигурация предполагает один.

Без настроенного Supabase открывается витрина и объяснение на странице входа; фиктивного входа нет. Без LLM генерация честно возвращает ошибку конфигурации до резервирования. [Подготовка и проверка AI](docs/AI.md).

## Supabase Auth

На 28 октября 2026 локальное окружение подключено к существующему проекту `xbmphrhmgahqydrdbgbi` в организации `sana-dev` (в Dashboard он называется `batyrkekw's Project`). Проект активен, регион — Singapore, тариф — Free. Его можно использовать с Python: Supabase Auth не зависит от языка предыдущего бэкенда.

В Dashboard сохранены Site URL `http://127.0.0.1:4173`, четыре точных redirect URL для `auth.html` и `auth.html?recovery=1` на портах 4173 и 8000, минимальная длина пароля 10. Email и подтверждение почты включены; anonymous и Google выключены. Текущий ключ подписи — ECC P-256 / ES256; для API используется `jwks`. URL и существующий publishable key сохранены только в локальном `.env`. Данные приложения остаются в локальном PostgreSQL.

Custom SMTP включён: Gmail, `smtp.gmail.com:465`, имя отправителя `SANA`. Адрес отправителя, логин и пароль хранятся в Supabase Dashboard; пароль не нужен в `.env` приложения и не должен попадать в Git. После сохранения Supabase установил лимит 30 писем в час. Gmail используется для начальной проверки; перед публичным запуском нужен проверенный домен и сервис транзакционных писем. Подробнее: [Custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

Проверены публичный Auth settings endpoint (HTTP 200, Email включён, подтверждение обязательно), `/api/v1/config` (`auth_configured=true`), готовность PostgreSQL/Redis и отказ защищённого API без токена/с неверным токеном (401). Пользователь подтвердил регистрацию, вход и создание урока до настройки Custom SMTP. 29 октября 2026 после замены SMTP-пароля тест восстановления через SANA успешно завершился: Auth Logs подтвердили `POST /recover`, HTTP 200 для существующего аккаунта. Прежняя ошибка Gmail `535 / 5.7.8` устранена. Пользователь подтвердил получение тестового письма в папке «Спам». Новая регистрация через Custom SMTP также проверена: письмо подтверждения получено, почта подтверждена, вход зафиксирован в Supabase, открытие кабинета подтверждено пользователем. В PostgreSQL создан профиль, стартовые 100 токенов начислены одной операцией, резерв — 0. Доставка через SMTP работает, попадание во «Входящие» не гарантируется.

Для Gmail создайте [пароль приложения Google](https://support.google.com/accounts/answer/185833?hl=ru) в том же аккаунте, который указан в SMTP Username (нужна двухэтапная аутентификация). В Supabase → Authentication → Emails → SMTP Settings введите этот пароль в Password и сохраните. Обычный пароль Google здесь не подходит. Сообщение об успешном сохранении подтверждает запись настроек; работоспособность проверяется отправкой письма и открытием ссылки в том же браузере. Для проверки новой регистрации используйте ещё не зарегистрированный адрес; Gmail-алиас с `+меткой` позволяет получить письмо в тот же ящик.

Для подключения с другого компьютера или к другому Supabase-проекту:

1. Включите Email provider, подтверждение email и минимальную длину пароля 10 символов. Настройте отправку писем/SMTP для реальных пользователей.
2. В `.env` запишите `SANA_SUPABASE_URL=https://PROJECT.supabase.co` и **publishable key** в `SANA_SUPABASE_PUBLISHABLE_KEY`. Допускается старый `anon` key. `service_role`, secret key, JWT secret в браузер не передаются; конфигурация отклоняет secret/service-role ключи.
3. В Auth → URL Configuration задайте Site URL `http://127.0.0.1:4173` и redirect allowlist: `http://127.0.0.1:4173/auth.html`, `http://127.0.0.1:4173/auth.html?recovery=1`. Если используете порт 8000, добавьте обе аналогичные ссылки с 8000. Используйте один hostname последовательно: `localhost` и `127.0.0.1` — разные origins.
4. Для актуальных асимметричных signing keys оставьте `SANA_AUTH_MODE=jwks`. Проверяются ES256/RS256, подпись, фиксированные issuer/audience, срок, `sub`, роль и запрет anonymous. JWKS кешируется на 5 минут. Для проекта с legacy HS256 установите `SANA_AUTH_MODE=auth_server`: сервер проверяет токен через Supabase `/auth/v1/user`.
5. Google необязателен: включите provider в Supabase, настройте Google OAuth credentials и callback из Supabase Dashboard, затем `SANA_GOOGLE_OAUTH_ENABLED=true`. Секрет Google хранится в Supabase, не в клиентском коде.
6. Перезапустите API; обновите страницу. Проверьте регистрацию, письмо подтверждения, вход, перезагрузку сессии, выход и восстановление пароля через письмо. Ссылку из письма откройте на том же устройстве и в том же браузере, где начата регистрация или восстановление: PKCE verifier хранится локально. Проверьте Google отдельно, если включён.

Supabase хранит пароль и сессию; наша БД хранит профиль с уникальным Supabase UUID. Профиль и стартовый баланс создаются ровно один раз при первом проверенном запросе. PKCE, хранение/обновление сессии выполняет Supabase SDK. Клиентский session state не заменяет серверную проверку JWT. При JWKS уже выданный access token действителен до истечения срока; немедленный отзыв требует режима auth_server/политики Supabase. Данные приложения находятся в отдельном PostgreSQL; SQLAlchemy API всегда проверяет владельца. Этот PostgreSQL не следует открывать напрямую клиенту.

## Docker Compose

```sh
docker compose up --build -d
docker compose ps
docker compose logs --tail=50 api worker
```

Полный стек доступен на `127.0.0.1:8000`. Сначала выполняется миграция и загрузка тарифов, затем API и worker. DB/Redis доступны только в приватной сети. Для host Python используйте `compose.host.yaml`, который публикует их только на loopback. Не запускайте контейнерный и host API на одном порту одновременно.

По умолчанию Docker-образ не содержит многогигабайтный PyTorch; текстовый AI работает через отдельный LLM-сервер. `SANA_DOCKER_LLM_BASE_URL` указывает на него из контейнера (по умолчанию `host.docker.internal:11434/v1`), `SANA_LLM_BASE_URL` — с host. LLM должен быть доступен по этому адресу; не открывайте Ollama в публичную сеть. Для локальной macOS разработки проще запускать API и worker на host, а DB/Redis в Docker. Инструкция по CPU/CUDA образу — в AI-документе.

Volumes: `postgres`, `redis`, `assets`, `models`. `docker compose down` сохраняет данные; флаг `-v` удаляет их, для обычной остановки он не нужен. `.env` не попадает в образ. Контейнер приложения работает не от root. Для размещения в интернете дополнительно нужны HTTPS, резервное копирование БД/файлов, отдельные credentials и ограничения на уровне reverse proxy.

## Тарифы и токены

Это тестовые внутренние единицы использования, не деньги и не токены LLM. Начальные лимиты:

| Уровень | Максимальный баланс | Возможности | Длина | Панели / изображения |
|---|---:|---|---:|---|
| Обычный | 100 | уроки, викторины, карточки | 4 | 0 / 0 |
| Про | 1000 | все пять типов | 8 | 4 / 2 |
| Плюс | 5000 | все пять типов | 12 | 8 / 4 |

Сгенерировать комикс можно без картинок; с картинками их число равно числу панелей и ограничено лимитом изображений. Возможности проверяются сервером. Конфигурация `config/plans.json` загружается командой `seed-plans`, не сбрасывая накопленные балансы. При уменьшении лимита существующие средства не отнимаются; новые начисления выше лимита блокируются. Автоматических ежедневных начислений нет.

Новый аккаунт получает 100 один раз. Смена тарифа не добавляет токены. CLI администратора из `backend/`:

```sh
uv run --no-sync python -m app.manage assign-plan --supabase-id USER_UUID --plan pro
uv run --no-sync python -m app.manage grant --supabase-id USER_UUID --amount 900 --operation-id UNIQUE_UUID
uv run --no-sync python -m app.manage reconcile --supabase-id USER_UUID
```

UUID операции сгенерируйте `python3 -c 'import uuid; print(uuid.uuid4())'`. Повтор с тем же UUID не начислит средства снова; изменение суммы/пользователя отклоняется. Баланс вместе с резервом не может превысить лимит при начислении. Понижение тарифа при превышении его лимита отклоняется. Публичного административного API нет.

Стоимость задаётся `SANA_COSTS`: lesson 10, quiz 6, flashcards 6, comic 12, image 10. Текст умножается на `ceil(length/4)`, картинки — на количество и `ceil(size²/512²)`. Quote и резерв используют одну серверную формулу. Фронтенд показывает стоимость до отправки задания.

Транзакция с `SELECT FOR UPDATE` блокирует счёт, проверяет лимит/баланс, создаёт job и reserve. Уникальные ключи предотвращают двойное начисление, резерв и завершение. Успех атомарно сохраняет материал и списывает резерв; любая ошибка генерации возвращает весь резерв, частичный результат не продаётся. Журнал содержит grant/reserve/charge/refund/adjustment и позволяет сверить баланс. Отмена возможна только пока job в очереди.

Задания PostgreSQL служат outbox: при недоступности Redis остаются в БД и отправляются повторно. API каждые 5 секунд проверяет зависшие задания и возвращает резерв после timeout. Повторная доставка не запускает завершённый job; идентификатор исполнения не даёт опоздавшему worker записать результат после возврата. На macOS solo не поддерживает принудительный Celery time limit: применяются сетевой timeout, проверки между шагами Diffusers и watchdog API. Если процесс завис в нативной операции, его придётся перезапустить; деньги/резерв не зависят от завершения этого процесса.

## API

Полная схема: `/docs` в development (отключена в production).

| Маршрут | Назначение |
|---|---|
| `GET /api/v1/config`, `/plans` | публичная конфигурация без секретов и тарифы |
| `GET/PATCH /api/v1/profile` | профиль и язык |
| `GET /api/v1/dashboard`, `/me/plan`, `/me/tokens` | кабинет, тариф, баланс |
| `GET /api/v1/me/tokens/transactions?page=1` | история |
| `GET/POST /api/v1/materials` | поиск/фильтры/сортировка, сохранение структурированного материала |
| `GET/PATCH/DELETE /api/v1/materials/{id}` | открыть, переименовать, удалить своё |
| `GET /api/v1/assets/{id}` | приватный PNG с проверкой владельца |
| `POST /api/v1/generations/quote` | стоимость и проверка тарифа |
| `POST /api/v1/generations` | создать job; обязательный `Idempotency-Key` |
| `GET /api/v1/generations`, `/{id}` | список и состояние |
| `POST /api/v1/generations/{id}/cancel` | отменить queued |
| `GET /api/v1/ai/status`, `/ai/models` | доступность провайдеров |
| `GET /health/live`, `/health/ready` | процесс, DB/Redis/миграция |

Закрытым запросам нужен `Authorization: Bearer <Supabase access token>`. `user_id`, стоимость и тариф от клиента не принимаются. Чужие ID возвращают 404. Ошибки содержат локализуемый `error.code`, без ключей и промптов. Лимиты запросов и вывода задаются в `.env.example`.

## Проверки

```sh
npm run build
npm test
npx playwright install chromium
npm run test:browser
cd backend
uv sync --frozen
uv run --no-sync ruff check app tests alembic scripts
uv run --no-sync ruff format --check app tests alembic scripts
TEST_DATABASE_URL=postgresql+psycopg://sana:sana_local_only@127.0.0.1:5432/sana uv run --no-sync pytest -q
```

Postgres-тесты создают и удаляют отдельную случайную схему, не трогая public. Без `TEST_DATABASE_URL` интеграционные тесты пропускаются: это не полноценный зелёный прогон. Проверяются гонки, идемпотентность, возвраты, права доступа, миграция, JWT и валидация AI. Playwright использует тестовый API и Supabase route fixtures; это проверка контракта UI, а не доказательство доставки email или рабочего реального OAuth. Исходные 21 JS-тест сохранены. GitHub Actions запускает эти проверки без весов и Supabase credentials.

`uv sync` без `--extra ai` удаляет AI-extra из venv; для AI-окружения используйте `uv sync --frozen --extra ai`, а команды запуска — с `--no-sync`.

## Частые проблемы

- «Supabase не настроен»: заполните URL/publishable key и перезапустите API. Это не ошибка браузера.
- 401: истёк/неверен токен, issuer, audience или signing mode. Не отключайте проверку подписи.
- `database_unavailable`: проверьте DB, порт, пароль, `alembic upgrade head`, `seed-plans`.
- Job остаётся queued: запущены ли Redis и worker с той же конфигурацией. При восстановлении брокера outbox повторит отправку.
- `text_model_not_configured`/`model_missing`: запустите Ollama, загрузите модель, задайте `SANA_LLM_MODEL`.
- `weights_missing`/`model_load_failed`: выполните prepare-model и реальный smoke check; файлы кеша сами по себе не доказывают работоспособность inference.
- `invalid_model_output`: модель вернула невалидную структуру/язык/число элементов. Резерв возвращается; используйте другую модель, меньший объём или уточните тему.
- Ошибка памяти: уменьшите разрешение, число изображений, выгрузите LLM; прочитайте [AI-инструкцию](docs/AI.md).

[Аудит исходного состояния](docs/AUDIT.md) · [AI и ограничения](docs/AI.md) · [Отчёт о проверках](docs/IMPLEMENTATION.md)
