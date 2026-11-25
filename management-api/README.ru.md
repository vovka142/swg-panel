# SWG Panel Management API Gateway

Отдельный HTTP API для автоматизации управления существующей панелью. Серверный бинарник панели не меняется:
Gateway авторизуется штатной учётной записью и вызывает внутренние маршруты /api/....

## Безопасность и ограничения

- Не публикуйте порт 8090 напрямую в интернет. Разместите Gateway за HTTPS reverse proxy и ограничьте доступ firewall.
- Внешние клиенты используют отдельный GATEWAY_API_KEY. Пароль администратора и cookie панели остаются внутри Gateway.
- Не отключайте проверку TLS панели в рабочей среде.
- Для 2FA задайте PANEL_TOTP_SECRET (TOTP secret, не одноразовый код). Без него автоматический вход в панель с включённой 2FA не пройдёт.
- Приватный ключ WireGuard/AWG генерируется клиентом. Gateway принимает pubkey и psk, но не генерирует и не возвращает приватный ключ.
- /v1/configs проксирует только legacy plaintext endpoint. При стандартном encrypted-хранилище конфиг зашифрован ключом, который остаётся в браузере, и Gateway не может его расшифровать.

## Добавление сервиса в Docker Compose

Добавьте рядом с панелью (имя сервиса и порт панели сверьте с вашим compose):

```yaml
  management-api:
    build: ./management-api
    restart: unless-stopped
    environment:
      PANEL_URL: http://swg-panel:8080
      PANEL_USER: ${PANEL_API_USER}
      PANEL_PASSWORD: ${PANEL_API_PASSWORD}
      GATEWAY_API_KEY: ${MANAGEMENT_API_KEY}
      PANEL_VERIFY_TLS: "true"
      PANEL_TOTP_SECRET: ${PANEL_TOTP_SECRET}
    ports:
      - "127.0.0.1:8090:8090"
```

Создайте длинный случайный MANAGEMENT_API_KEY. Значения PANEL_API_USER, PANEL_API_PASSWORD и MANAGEMENT_API_KEY
поместите в .env с правами 0600.

Запуск:

```bash
docker compose build management-api
docker compose up -d management-api
docker compose logs -f management-api
```

Swagger UI: http://127.0.0.1:8090/docs (локально или через SSH-туннель).

## Авторизация клиентов

Все маршруты, кроме /healthz, требуют заголовок:

```http
Authorization: Bearer <MANAGEMENT_API_KEY>
```

## Методы

| Метод | Путь | Назначение |
|---|---|---|
| GET | /v1/state | Полный snapshot панели |
| GET | /v1/users | Список пользователей |
| POST | /v1/users | Создать пользователя |
| PATCH | /v1/users/{id} | Изменить имя, тег, заметку |
| DELETE | /v1/users/{id} | Удалить пользователя |
| POST | /v1/users/{id}/block | Заблокировать пользователя и его пиры |
| POST | /v1/users/{id}/unblock | Разблокировать пользователя |
| GET | /v1/peers?user_id=... | Список пиров |
| GET | /v1/next-ip?nodes=...&iface=... | Запросить свободный IP |
| POST | /v1/peers | Создать пир |
| DELETE | /v1/peers/{id} | Удалить пир |
| POST | /v1/peers/{id}/block | Заблокировать пир |
| POST | /v1/peers/{id}/unblock | Разблокировать пир |
| GET | /v1/configs?pubkey=...&node=...&iface=... | Legacy plaintext config |

### Создать пользователя

```bash
curl -X POST http://127.0.0.1:8090/v1/users \
  -H "Authorization: Bearer $MANAGEMENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Ivan Petrov","tag":"staff","note":"Created by automation"}'
```

### Создать пир

Ключи формируются на стороне вызывающего клиента. targets должны ссылаться на существующие node ID и
интерфейсы; ip должен быть свободным адресом в подсети интерфейса.

```json
{
  "user_id": "u_xxxxx",
  "title": "iPhone",
  "pubkey": "<client-generated-public-key>",
  "psk": "<client-generated-preshared-key>",
  "targets": [
    {"node": "<node-id>", "iface": "awg0", "ip": "10.8.0.20", "type": "awg"}
  ]
}
```

Gateway передаёт payload штатному /api/peers/create. Он пока не выделяет IP автоматически и не строит WG/AWG
конфиг. Для production нужно дополнительно реализовать и проверить клиентский генератор конфигураций с учётом
параметров интерфейса, AWG и модели шифрования панели.

## Проверка

```bash
curl -fsS http://127.0.0.1:8090/healthz
curl -fsS http://127.0.0.1:8090/v1/users \
  -H "Authorization: Bearer $MANAGEMENT_API_KEY"
```
