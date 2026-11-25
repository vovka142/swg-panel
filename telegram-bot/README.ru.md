# Telegram bot для SWG Panel

Бот управляет пользователями и WG/AWG-устройствами через management-api Gateway.

## Возможности

- Список пользователей и устройств.
- Создание, переименование, блокировка, разблокировка и удаление пользователя.
- Просмотр устройств пользователя.
- Создание WG/AWG peer на выбранном узле и интерфейсе с автоматическим выделением IP.
- Генерация X25519 keypair и PSK в памяти бота и отправка готового .conf в Telegram.
- Блокировка и разблокировка устройства.
- Перевыпуск конфигурации существующего WG/AWG peer: бот создаёт новое устройство с новыми ключами и IP, отправляет конфиг и только после успешной доставки удаляет старое устройство.
- Удаление устройства.

WDTT/CSQTT — keyless-протоколы с отдельной выдачей паролей. Они не создаются как WireGuard peer и пока не поддерживаются этим ботом.

## Настройка

В корне репозитория добавлен docker-compose.management.yml. Он добавляет Gateway и бота в ту же Docker-сеть, что и swg-panel; порт Gateway наружу не публикуется. Gateway обращается к локальному HTTP listener панели по адресу http://swg-panel:8088 внутри Docker-сети.

Подготовьте env-файлы:

    cp .env.gateway.example .env.gateway
    cp .env.telegram.example .env.telegram
    chmod 600 .env.gateway .env.telegram

В .env.gateway задайте PANEL_USER, PANEL_PASSWORD и GATEWAY_API_KEY. Сгенерировать ключ можно командой openssl rand -hex 32. Если в панели включена 2FA, укажите PANEL_TOTP_SECRET (секрет TOTP в Base32, не шестизначный код). Используйте отдельную учётную запись панели с правами управления, если ваша установка поддерживает операторов.

В .env.telegram задайте TELEGRAM_BOT_TOKEN от BotFather, тот же GATEWAY_API_KEY и TELEGRAM_ADMIN_IDS — ваш числовой Telegram user ID. Не используйте @username для авторизации.

Запуск. В команде укажите тот же профиль, с которым работает панель: master или host.

    docker compose --profile master -f docker-compose.yml -f docker-compose.management.yml up -d --build management-api telegram-bot
    docker compose --profile master -f docker-compose.yml -f docker-compose.management.yml logs -f telegram-bot

Для профиля host замените --profile master на --profile host.

Откройте личный чат с ботом и отправьте /start. Если ваш ID ещё не добавлен в TELEGRAM_ADMIN_IDS, бот покажет ваш числовой Telegram ID. Добавьте его в .env.telegram и перезапустите контейнер. Бот принимает запросы только в личном чате и только от разрешённых ID. Не добавляйте бота в группы.

## Запуск на сервере с bare-metal панелью

Если `swg-panel-server` уже работает как systemd-служба на этом же сервере и слушает HTTP `127.0.0.1:8443`, запускайте Gateway и бота отдельным Compose-проектом из корня репозитория:

```bash
cp .env.gateway.example .env.gateway
cp .env.telegram.example .env.telegram
chmod 600 .env.gateway .env.telegram
nano .env.gateway
nano .env.telegram
docker compose -f docker-compose.management-host.yml up -d --build
```

В этом варианте оба контейнера используют host network, но Gateway слушает только `127.0.0.1:8090`. Панель не перезапускается и не заменяется контейнером. Для просмотра состояния используйте `docker compose -f docker-compose.management-host.yml ps` и `docker compose -f docker-compose.management-host.yml logs -f telegram-bot`.

## Защита конфигураций

Приватный ключ WireGuard/AWG генерируется в процессе бота и не записывается в БД или лог. Он отправляется в Telegram как файл .conf. Обычные облачные чаты Telegram не являются end-to-end зашифрованным хранилищем: файл останется в истории и будет доступен на устройствах аккаунта. Используйте только личный чат с разрешённым администратором, включите 2FA Telegram и защиту устройства.

При перевыпуске конфигурации бот создаёт замену, отправляет файл и затем удаляет старый peer. Если отправка не удалась, новый peer удаляется, а старый остаётся действующим.

Конфигурации WDTT/CSQTT и их пароли требуют отдельной реализации. Автоматическая публикация конфигов в зашифрованное хранилище панели также не выполняется: ключ шифрования остаётся на стороне браузера. Бот выдаёт конфиг напрямую в личный чат администратора.
