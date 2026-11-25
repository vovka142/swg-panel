# SWG Panel Management API Gateway

Gateway — внутренний HTTP API для Telegram-бота. Он не публикует порт наружу в штатном Compose overlay и вызывает штатные /api/... маршруты панели с отдельной учётной записью.

## Развёртывание

Используйте общий Compose overlay из корня репозитория: docker-compose.management.yml. Настройка Telegram-бота описана в telegram-bot/README.ru.md.

Gateway обращается к swg-panel по http://swg-panel:8088 — это внутренний listener в Docker-сети, не опубликованный на внешнем интерфейсе. Не подключайте к этой сети недоверенные контейнеры.

Создайте .env.gateway и .env.telegram по примерам в корне репозитория и задайте права 0600. Gateway получает PANEL_USER, PANEL_PASSWORD и GATEWAY_API_KEY из .env.gateway. Бот получает TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_IDS и такой же GATEWAY_API_KEY из .env.telegram.

## Авторизация

Все маршруты, кроме /healthz, требуют:

    Authorization: Bearer <GATEWAY_API_KEY>

Токен Gateway не является токеном панели. Cookie сессии панели хранится только внутри процесса Gateway.

## Маршруты

| Метод | Путь | Назначение |
|---|---|---|
| GET | /v1/state | Полный snapshot панели |
| GET | /v1/users | Список пользователей |
| POST | /v1/users | Создать пользователя |
| PATCH | /v1/users/{id} | Изменить параметры пользователя |
| DELETE | /v1/users/{id} | Удалить пользователя |
| POST | /v1/users/{id}/block | Заблокировать пользователя |
| POST | /v1/users/{id}/unblock | Разблокировать пользователя |
| GET | /v1/peers | Список устройств |
| POST | /v1/peers | Создать WG/AWG peer |
| GET | /v1/next-ip?nodes=...&iface=... | Получить свободный IP |
| DELETE | /v1/peers/{id} | Удалить peer |
| POST | /v1/peers/{id}/block | Заблокировать peer |
| POST | /v1/peers/{id}/unblock | Разблокировать peer |

Gateway не генерирует приватные ключи и не расшифровывает конфиги из зашифрованного хранилища панели. Генерация ключей и формирование клиентского файла выполняются Telegram-ботом в памяти.

## Проверка

После запуска бота:

    docker compose --profile master -f docker-compose.yml -f docker-compose.management.yml ps
    docker compose --profile master -f docker-compose.yml -f docker-compose.management.yml logs --tail=100 management-api telegram-bot

Замените профиль master на host, если панель запущена с профилем host.
