# Telegram bot для SWG Panel

Бот управляет пользователями и WG/AWG-устройствами через management-api Gateway.

## Функции

- Список пользователей и устройств.
- Создание и удаление пользователя.
- Блокировка и разблокировка пользователя.
- Просмотр устройств пользователя.
- Создание WG/AWG peer на выбранном узле и интерфейсе.
- Получение свободного IP штатным API панели.
- Генерация X25519 keypair и PSK в памяти бота.
- Отправка готового .conf файлом в личный чат Telegram.
- Блокировка, разблокировка и удаление устройства.

WDTT/CSQTT — keyless-протоколы с отдельной выдачей паролей. Этот бот не создаёт их как WireGuard peer;
для них требуется отдельный сценарий управления и выдачи credentials.

## Переменные окружения

- TELEGRAM_BOT_TOKEN — токен от BotFather.
- TELEGRAM_ADMIN_IDS — числовые Telegram user ID через запятую, без @username.
- GATEWAY_URL — адрес management-api внутри Docker-сети.
- GATEWAY_API_KEY — тот же ключ, что задан в Gateway.
- HTTP_TIMEOUT — таймаут запросов, по умолчанию 30 секунд.

## Добавление сервиса в Docker Compose

Добавьте сервис рядом с management-api:

```yaml
  telegram-bot:
    build: ./telegram-bot
    restart: unless-stopped
    depends_on:
      - management-api
    environment:
      - TELEGRAM_BOT_TOKEN
      - TELEGRAM_ADMIN_IDS
      - GATEWAY_URL=http://management-api:8090
      - GATEWAY_API_KEY
```

Секреты задайте в .env с правами 0600. Telegram ID должен быть числовым ID пользователя, а не username.
Бот принимает команды только в личном чате и только от ID из TELEGRAM_ADMIN_IDS. Не добавляйте его в группы.

## Запуск

```bash
docker compose build management-api telegram-bot
docker compose up -d management-api telegram-bot
docker compose logs -f telegram-bot
```

## Защита конфигураций

Приватный ключ WireGuard/AWG генерируется в процессе бота и не записывается в БД или лог. Он отправляется
в Telegram как файл .conf. Обычные облачные чаты Telegram не являются end-to-end зашифрованным хранилищем:
файл останется в истории и будет доступен на устройствах аккаунта. Используйте только личный чат с
разрешённым администратором, включите 2FA Telegram и защиту устройства. Если Telegram не доставил файл,
бот пытается удалить только что созданный peer, чтобы не оставить устройство без конфига.
