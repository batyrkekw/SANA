---
title: SANA Story Lab
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.31.0
python_version: 3.12.12
app_file: app.py
pinned: false
models:
  - Qwen/Qwen3-4B-Instruct-2507
tags:
  - education
  - qwen3
  - zerogpu
short_description: Проверка сценариев SANA перед подключением к сайту
---

# SANA Story Lab

Экспериментальный текстовый сервис. Без настроенного адаптера используется
**базовая Qwen3-4B-Instruct-2507**. Это не дообученная модель и не подтверждение
качества учебных материалов. Сайт SANA пока использует свою текущую модель.

Запуск рассчитан исключительно на **ZeroGPU** (`zero-a10g` в API Hugging Face).
Приложение не заказывает платное оборудование. Доступ к GPU зависит от очереди
и квоты Hugging Face. Этот Space не обучает модель и не рисует иллюстрации.

API `/story` принимает `request_json`: subject, topic, grade, language (ru/kk),
instructions. kind должен быть comic, length — 4. Дополнительные поля отклоняются.
В заголовке `X-SANA-Key` нужен секрет `SANA_SPACE_KEY`. Проверка ключа и данных
выполняется **до** вызова GPU. `/status` не использует GPU и не требует этого ключа.
HF access token, если используется клиентом API, задаёт, чья квота расходуется;
наш `X-SANA-Key` не заменяет HF-аутентификацию и не обходит квоты.

Для будущего адаптера задаются `SANA_ADAPTER_REPO` и `SANA_ADAPTER_REVISION`
(точный Git SHA из 40 символов). Загружаются только adapter_config.json и
adapter_model.safetensors; база должна совпадать с обучением. Наличие адаптера
отражается в ответе API, но само по себе не означает, что качество одобрено.
Если адаптер приватный, нужен отдельный HF_TOKEN только с правом чтения этого
репозитория. Токен для публикации Space сюда не копируется.

Код проекта: https://github.com/batyrkekw/SANA
Обучение: training/comics/ в этом репозитории.
Лицензия базовой Qwen: Apache-2.0.
