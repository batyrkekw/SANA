# Локальный AI

## Выбранные провайдеры

Текст: `LocalLLMProvider` вызывает локальный OpenAI-compatible `/chat/completions`. Рекомендуемая стартовая конфигурация этого Mac — Ollama и **Qwen3:4b**, квантованная Q4_K_M модель около 2.5 GB, лицензия Apache 2.0. Модель поддерживает много языков; качество русского и казахского нужно проверять на предметных примерах. Возможна замена на llama.cpp/LM Studio или другой совместимый сервер через URL/model. Платный API не требуется.

Изображения: **stable-diffusion-v1-5/stable-diffusion-v1-5**, Diffusers pipeline и safetensors fp16 в кеше. Лицензия CreativeML OpenRAIL-M содержит ограничения использования; это не безусловная MIT/Apache лицензия. Выбрана как сравнительно компактная модель с исходным разрешением 512, подходящая для первоначального запуска на Mac с 16 GB общей памяти. SDXL Base 1.0 также рассмотрена: она тяжелее, имеет другую OpenRAIL++ лицензию и требует отдельного замера памяти/качества. Замена ID не означает, что любая архитектура автоматически совместима: нужны поддержка AutoPipelineForText2Image и отдельный smoke check.

Официальные источники:

- [SD 1.5 model card и лицензия](https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5)
- [SDXL Base model card](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Diffusers на Apple MPS](https://huggingface.co/docs/diffusers/optimization/mps)
- [Qwen3:4b в Ollama](https://ollama.com/library/qwen3:4b) и [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B)
- [OpenAI compatibility в Ollama](https://docs.ollama.com/api/openai-compatibility)

## Текстовая модель

Установите Ollama из официального источника. Отдельный терминал:

```sh
ollama serve
```

Загрузите веса:

```sh
ollama pull qwen3:4b
ollama create sana-qwen3:4b -f config/Ollama.Modelfile
```

В `.env`:

```dotenv
SANA_LLM_BASE_URL=http://127.0.0.1:11434/v1
SANA_LLM_MODEL=sana-qwen3:4b
SANA_LLM_TIMEOUT_SECONDS=180
SANA_LLM_MAX_TOKENS=4096
```

Локальный alias `sana-qwen3:4b` использует те же веса и контекст 8192 из Modelfile. `SANA_LLM_REASONING_EFFORT=none` отключает thinking для Qwen3, чтобы лимит вывода расходовался на материал. Если другой сервер не поддерживает это поле, задайте пустое значение.

Перезапустите API и worker. Веса Ollama на macOS по умолчанию лежат в `~/.ollama/models`, вне репозитория. Для освобождения памяти: `ollama stop sana-qwen3:4b`. На 16 GB не держите одновременно большую LLM и Diffusers без замера памяти. Умеренный размер контекста и короткие задания экономят память и время.

Проверка реального вывода из `backend/`:

```sh
uv run --no-sync python -m app.smoke lesson --model sana-qwen3:4b --language ru
uv run --no-sync python -m app.smoke quiz --model sana-qwen3:4b --language kk
uv run --no-sync python -m app.smoke comic --model sana-qwen3:4b --language ru
uv run --no-sync python -m app.smoke flashcards --model sana-qwen3:4b --language kk
```

Результат сохраняется в `.data/smoke/`. По умолчанию `SANA_LLM_RESPONSE_FORMAT=json_schema`: схема с точным числом элементов передаётся серверу для ограниченного декодирования и повторно проверяется после ответа. Для серверов без JSON Schema есть явный режим `json_object`, но слабая модель может чаще возвращать ошибки. Проверяются JSON schema, тип, язык-маркер, число вопросов/панелей/карточек, варианты ответов и индексы, максимальный размер. Поля урока: цели, объяснение, примеры, вопросы и итог. Модель возвращает текст правильного ответа, который должен точно совпасть с одним из вариантов; индекс вычисляет сервер, устраняя путаницу нумерации с нуля/единицы. Для комикса — последовательные панели с сценой, репликой, пояснением и английским image prompt. При наличии `arithmetic_check` арифметика проверяется безопасным AST с ограниченными операциями; выбранный числовой вариант дополнительно сверяется с результатом. Это не математический решатель и не гарантия фактической правильности.

Проверка наличия кириллицы отсеивает очевидный неверный язык, но не доказывает качество казахского или правильность перевода. В интерфейсе есть указание проверить материал преподавателем. При невалидном ответе job завершается с ошибкой, резерв возвращается; шаблонный ответ вместо AI не подставляется. Повторных платных попыток/автоматического исправления моделью нет.

## Подготовка изображений на Apple Silicon

Из `backend/`:

```sh
uv sync --frozen --extra ai
uv run --no-sync python -m app.manage prepare-model
SANA_IMAGE_ENABLED=true uv run --no-sync python -m app.smoke image
```

Команда подготовки скачивает только компоненты выбранного варианта и конфигурацию, без дубликатов полных checkpoint. Кеш: `SANA_MODEL_CACHE_DIR`, по умолчанию `<репозиторий>/.data/models`. Реальные PNG: `SANA_STORAGE_DIR`, по умолчанию `.data/assets`. Оба каталога исключены из Git и Docker build context. При последующем старте pipeline использует `local_files_only=True`; автоматического скрытого скачивания из API нет.

После успешного smoke check включите в `.env`:

```dotenv
SANA_IMAGE_ENABLED=true
SANA_IMAGE_DEVICE=auto
SANA_IMAGE_SIZE=512
SANA_IMAGE_STEPS=20
SANA_IMAGE_MAX_COUNT=4
```

Запустите worker на host с `--pool=solo --concurrency=1`. Auto выбирает CUDA → MPS → CPU. На MPS/CPU используются float32 вычисления с attention/vae slicing; файл fp16 при загрузке преобразуется. Поэтому размер файлов не равен потреблению RAM. На CUDA — float16. На Mac рекомендуется свободная память в несколько GB сверх весов; точная потребность зависит от размера и окружения. Контейнер Docker на macOS не получает MPS: там будет CPU.

Smoke check действительно загружает pipeline, выполняет 20 шагов и сохраняет `.data/smoke/image.png`. Статус `cached_not_verified` в API означает только наличие snapshot в кеше; только успешный inference подтверждает работу модели. API не загружает веса в свою память. Worker кеширует pipeline на процесс; ошибка памяти выгружает его, и следующий job может повторить загрузку.

## CPU / CUDA / Docker

CPU значительно медленнее; начните с 256–512 px и малого числа шагов, измерьте время и при необходимости увеличьте `SANA_JOB_TIMEOUT_SECONDS`. CUDA требует совместимого драйвера, поддерживаемой видеокарты и PyTorch wheel; в конкретном CUDA окружении нужно повторить smoke check. CUDA в этой разработке не тестировалась.

Для CPU AI в Docker:

```sh
docker compose build --build-arg INSTALL_AI=true
docker compose run --rm --no-deps worker uv run --no-sync python -m app.manage prepare-model
docker compose run --rm --no-deps -e SANA_IMAGE_ENABLED=true worker uv run --no-sync python -m app.smoke image --output /data/assets/smoke
```

При переходе с host MPS на обычный Docker-образ выключите `SANA_IMAGE_ENABLED` или сначала соберите AI-образ и подготовьте его отдельный volume. Для подготовленного AI-образа установите `SANA_IMAGE_ENABLED=true` в `.env`, затем `docker compose up -d` без пересборки образа в обычный вариант. Веса остаются в volume `models`, изображения — `assets`. Не запускайте одновременно host worker и контейнерный worker для той же очереди с разной AI-конфигурацией. Для CUDA контейнеру нужно отдельно настроить NVIDIA runtime/GPU allocation; готового проверенного GPU Compose профиля здесь нет.

## Ограничения модели и эксплуатации

- SD 1.5 лучше понимает английские визуальные описания. Для отдельной картинки вводите английский prompt, оставляя тему урока на RU/KK; комикс запрашивает английский image_prompt у LLM.
- Без LoRA/ControlNet/references одинаковые персонажи между панелями не гарантируются. Текстовые описания повторяются, но визуальную связность проверяет человек.
- Точные надписи, формулы, карты и научные диаграммы могут искажаться; подписи лучше показывать HTML-текстом рядом.
- Safety checker не отключён. Отфильтрованное изображение считается ошибкой с возвратом резерва.
- Один worker, ограниченное число картинок, фиксированный размер и шаги защищают память. Размер и стоимость управляются сервером.
- PNG записывается атомарно, БД содержит путь/метаданные. Файлы не доступны через static URL; endpoint проверяет владельца и возвращает blob. При ошибке до фиксации файлы удаляются. Аварийное завершение процесса может оставить непривязанный файл: для эксплуатации нужен отдельный периодический сборщик таких файлов и стратегия backup.
- HTTP timeout, ограниченный ответ, deadline между шагами и watchdog возвращают резерв. Нативное зависание на MPS требует перезапуска worker; автоматически убивать сторонние процессы приложение не пытается.

Фактические результаты запусков записаны в [отчёте](IMPLEMENTATION.md); скачивание весов не приравнивается к успешной генерации.

## Проверка отдельного worker через настоящую очередь

После подготовки моделей и запуска DB/Redis, из `backend/`:

```sh
uv run --no-sync python scripts/queue_smoke.py --kind quiz --language ru --model sana-qwen3:4b
uv run --no-sync python scripts/queue_smoke.py --kind image
```

Скрипт создаёт временную случайную схему PostgreSQL, отдельную очередь, запускает дочерний Celery-worker и отправляет ему реальное задание. Проверяет сохранённый материал, списание и нулевой резерв; затем останавливает свой worker и удаляет только собственную схему. Отчёт и изображения сохраняются в `.data/smoke/`. Настоящая пользовательская сессия не создаётся и не подменяется. Выполняйте проверку последовательно, чтобы модели не боролись за память.
