# Деплой SHX CRAFT в Dokploy

Проект подготовлен как статическая веб-игра без базы данных. Контейнер отдаёт игру через Nginx на внутреннем порту `80`.

## Локальная проверка

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up --build
```

Открой:

```text
http://localhost:8080
```

Остановить:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

## Деплой в Dokploy

1. Запушь изменения в GitHub/GitLab репозиторий.
2. В Dokploy создай новый проект или открой существующий.
3. Добавь сервис типа `Docker Compose`.
4. Подключи репозиторий и ветку `main`.
5. В качестве compose-файла укажи `docker-compose.yml`.
6. Включи Auto Deploy/Webhook, чтобы после push Dokploy автоматически пересобирал и перезапускал игру.
7. Вкладка `Domains` -> `Add Domain`:
   - Host: твой готовый поддомен, например `game.example.com`
   - Path: `/`
   - Container Port: `80`
   - HTTPS: включить
   - Certificate: `letsencrypt`
8. Нажми Deploy.

Для Docker Compose в Dokploy домен лучше добавлять через вкладку `Domains`: Dokploy сам добавит нужные Traefik labels при деплое.

## CI и автодеплой после push

В `.github/workflows/ci.yml` уже есть проверка:

- валидирует `docker-compose.yml`;
- собирает Docker image;
- запускает контейнер;
- проверяет `/healthz`, главную страницу и `src/main.js`;
- после успешного push в `main` может дернуть Dokploy webhook.

Чтобы GitHub Actions сам запускал деплой в Dokploy, добавь в настройках репозитория секрет:

```text
DOKPLOY_DEPLOY_WEBHOOK
```

Значение секрета — webhook URL из Dokploy. Если используешь встроенный Auto Deploy в Dokploy через Git-провайдера, этот секрет можно не добавлять.

## Что должно получиться

После успешного деплоя поддомен открывает `index.html`, игра загружает `style.css`, модули из `src/`, текстуры из `assets/textures/` и музыку из `assets/audio/`.

База данных, volume и переменные окружения для игры не нужны.
