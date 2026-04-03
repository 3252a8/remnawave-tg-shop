# Telegram-бот для продажи подписок Remnawave

Этот Telegram-бот предназначен для автоматизации продажи и управления подписками для панели **Remnawave**. Он интегрируется с API Remnawave для управления пользователями и подписками, а также использует различные платежные системы для приема платежей.

## ✨ Ключевые возможности

### Для пользователей:
-   **Регистрация и выбор языка:** Поддержка русского и английского языков.
-   **Веб-портал:** Вход и регистрация по email, привязка Telegram позже и полный пользовательский функционал в браузере.
-   **Просмотр подписки:** Пользователи могут видеть статус своей подписки, дату окончания и ссылку на конфигурацию.
-   **Мои устройства:** Опциональный раздел для просмотра и отключения подключенных устройств (активируется через переменную `MY_DEVICES_SECTION_ENABLED`).
-   **Пробная подписка:** Система пробных подписок для новых пользователей (активируется вручную по кнопке).
-   **Промокоды:** Возможность применять промокоды для получения скидок или бонусных дней.
-   **Реферальная программа:** Пользователи могут приглашать друзей и получать за это бонусные дни подписки.
    -   **Оплата:** Поддержка оплаты через YooKassa, FreeKassa (REST API), Platega, SeverPay, CryptoPay и Telegram Stars.

### Для администраторов:
-   **Защищенная админ-панель:** Доступ только для администраторов, указанных в `ADMIN_IDS`.
-   **Статистика:** Просмотр статистики использования бота (общее количество пользователей, забаненные, активные подписки), недавние платежи и статус синхронизации с панелью.
-   **Управление пользователями:** Блокировка/разблокировка пользователей, просмотр списка забаненных и детальной информации о пользователе.
-   **Рассылка:** Отправка сообщений всем пользователям, пользователям с активной или истекшей подпиской.
-   **Управление промокодами:** Создание и просмотр промокодов.
-   **Синхронизация с панелью:** Ручной запуск синхронизации пользователей и подписок с панелью Remnawave.
-   **Логи действий:** Просмотр логов всех действий пользователей.

## 🚀 Технологии

-   **Python 3.12**
-   **Aiogram 3.x:** Асинхронный фреймворк для Telegram ботов.
-   **aiohttp:** Для запуска веб-сервера (вебхуки).
-   **SQLAlchemy 2.x & asyncpg:** Асинхронная работа с базой данных PostgreSQL.
-   **YooKassa, FreeKassa API, Platega, SeverPay, aiocryptopay:** Интеграции с платежными системами.
-   **Pydantic:** Для управления настройками из `.env` файла.
-   **Docker & Docker Compose:** Для контейнеризации и развертывания.
-   **SvelteKit + TypeScript:** Отдельный браузерный портал для управления аккаунтом без Telegram.

## 🌐 Веб-портал

Портал разворачивается в отдельном контейнере `remnawave-tg-shop-web` и использует тот же backend и ту же базу данных, что и бот. Через него доступны:
- вход и регистрация по email;
- последующая привязка Telegram-аккаунта;
- просмотр и покупка подписок;
- промокоды и реферальная программа;
- история платежей, способы оплаты и автопродление;
- список устройств, если включён `MY_DEVICES_SECTION_ENABLED`.

В текущем `docker-compose.yml` портал проброшен на `127.0.0.1:3252`, а внутренняя точка входа контейнера остаётся `3000`.

### Как это работает

1. Пользователь вводит email на странице портала.
2. Если email ещё не привязан, аккаунт создаётся автоматически.
3. Код подтверждения отправляется через Brevo SMTP.
4. После входа можно привязать Telegram-аккаунт, а затем пользоваться и ботом, и веб-порталом под одним аккаунтом.
5. Если бот уже прислал `telegram_code`, портал умеет войти по нему автоматически.

### Переменные окружения

| Переменная | Назначение |
| --- | --- |
| `WEB_APP_URL` | Публичный HTTPS-адрес портала. Нужен для ссылок из бота и для Telegram-deep-link входа. |
| `WEB_API_URL` | Внутренний URL backend-контейнера, который использует SvelteKit-сервер. |
| `WEB_SESSION_COOKIE_*` | Параметры cookie для браузерной сессии портала. `Secure=True` нужен для HTTPS. |
| `WEB_AUTH_CODE_TTL_MINUTES` | Время жизни кода входа по email/Telegram. |
| `WEB_AUTH_CODE_RESEND_COOLDOWN_SECONDS` | Антиспам-таймаут повторной отправки email-кода. |
| `WEB_TELEGRAM_LINK_CODE_TTL_MINUTES` | Время жизни кода привязки Telegram. |
| `BREVO_SMTP_*` | Настройки SMTP для отправки email-кодов входа и привязки. |

### Подключение Brevo SMTP

1. Зарегистрируйте или откройте аккаунт в [Brevo](https://www.brevo.com/).
2. Подтвердите адрес отправителя или домен в разделе SMTP/Senders.
3. Создайте SMTP-ключ и заполните в `.env` поля `BREVO_SMTP_USERNAME` и `BREVO_SMTP_PASSWORD`.
4. Оставьте `BREVO_SMTP_HOST=smtp-relay.brevo.com`, `BREVO_SMTP_PORT=587`, `BREVO_SMTP_USE_TLS=True`, `BREVO_SMTP_USE_SSL=False`.
5. При необходимости укажите `BREVO_FROM_EMAIL` и `BREVO_FROM_NAME` для красивого поля `From`.
6. Перезапустите backend и web-контейнеры, чтобы портал начал отправлять коды входа и привязки.

### SSL и размещение

- Если у вас уже есть внешний reverse proxy, направьте `portal.domain.tld` на контейнер `remnawave-tg-shop-web` и терминируйте SSL там.
- Если хотите TLS прямо внутри контейнера, смонтируйте сертификат и ключ в web-контейнер и укажите `WEB_SSL_CERT_PATH` / `WEB_SSL_KEY_PATH`.
- Для локальной отладки без HTTPS выставьте `WEB_SESSION_COOKIE_SECURE=False`, иначе браузер не сохранит cookie на plain HTTP.
- Если портал и backend живут на разных поддоменах, проверьте `WEB_SESSION_COOKIE_DOMAIN` и не используйте `SameSite=None` без `Secure=True`.

### Корнер-кейсы

- Email уже занят другим аккаунтом: портал вернёт ошибку и не перезапишет чужой email.
- Код входа или привязки истёк: нужно запросить новый.
- Есть cooldown на повторную отправку email-кода.
- Забаненные пользователи не могут войти через портал.
- Telegram Stars доступны только при уже привязанном Telegram-аккаунте.
- Автопродление YooKassa требует привязанной карты.
- Если Brevo SMTP не настроен, email-login, регистрация и привязка email автоматически отключаются.
- Если `WEB_APP_URL` не задан, бот не сможет сгенерировать portal-ссылки и deep-link для Telegram login.
- Если Telegram уже привязан к другому аккаунту, backend не создаёт дубль и применяет правила слияния/переиспользования существующей привязки.
- Если браузер не видит cookie после логина, почти всегда не совпадают `WEB_SESSION_COOKIE_SECURE`, `WEB_SESSION_COOKIE_DOMAIN` или схема HTTPS на внешнем прокси.

## ⚙️ Установка и запуск

### Предварительные требования

-   Установленные Docker и Docker Compose.
-   Рабочая панель Remnawave.
-   Токен Telegram-бота.
-   Данные для подключения к платежным системам (YooKassa, CryptoPay и т.д.).

### Шаги установки

1.  **Клонируйте репозиторий:**
    ```bash
    git clone https://github.com/3252a8/remnawave-tg-shop
    cd remnawave-tg-shop
    ```

2.  **Создайте и настройте файл `.env`:**
    Скопируйте `.env.example` в `.env` и заполните своими данными.
    ```bash
    cp .env.example .env
    nano .env 
    ```
    Ниже перечислены ключевые переменные.

    <details>
    <summary><b>Основные настройки</b></summary>

    | Переменная | Описание | Пример |
    | --- | --- | --- |
    | `BOT_TOKEN` | **Обязательно.** Токен вашего Telegram-бота. | `1234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11` |
    | `ADMIN_IDS` | **Обязательно.** ID администраторов в Telegram через запятую. | `12345678,98765432` |
    | `DEFAULT_LANGUAGE` | Язык по умолчанию для новых пользователей. | `ru` |
    | `SUPPORT_LINK` | (Опционально) Ссылка на поддержку. | `https://t.me/your_support` |
    | `SUBSCRIPTION_MINI_APP_URL` | (Опционально) URL Mini App для показа подписки. | `https://t.me/your_bot/app` |
    | `MY_DEVICES_SECTION_ENABLED` | Включить раздел «Мои устройства» в меню подписки (`true`/`false`). | `false` |
    | `REQUIRED_CHANNEL_ID` | (Опционально) ID канала, на который пользователь должен подписаться перед использованием. Оставьте пустым, если проверка не нужна. | `-1001234567890` |
    | `REQUIRED_CHANNEL_LINK` | (Опционально) Публичная ссылка или invite на канал для кнопки «Проверить подписку». | `https://t.me/your_channel` |
    </details>

    <details>
    <summary><b>Настройки платежей и вебхуков</b></summary>

    | Переменная | Описание |
    | --- | --- |
    | `WEBHOOK_BASE_URL`| **Обязательно.** Базовый URL для вебхуков, например `https://your.domain.com`. |
    | `WEB_SERVER_HOST` | Хост для веб-сервера. | `0.0.0.0` |
    | `WEB_SERVER_PORT` | Порт для веб-сервера. | `8080` |
    | `PAYMENT_METHODS_ORDER` | (Опционально) Порядок отображения кнопок оплаты через запятую. Поддерживаемые ключи: `severpay`, `freekassa`, `platega`, `yookassa`, `stars`, `cryptopay`. Первый будет сверху. |
    | `YOOKASSA_ENABLED` | Включить/выключить YooKassa (`true`/`false`). |
    | `YOOKASSA_SHOP_ID` | ID вашего магазина в YooKassa. |
    | `YOOKASSA_SECRET_KEY`| Секретный ключ магазина YooKassa. |
    | `YOOKASSA_AUTOPAYMENTS_ENABLED` | Включить автопродление (сохранение карт, автосписания, управление способами оплаты). |
    | `YOOKASSA_AUTOPAYMENTS_REQUIRE_CARD_BINDING` | Требовать обязательную привязку карты при оплате с автосписанием. Установите `false`, чтобы пользователю показывался чекбокс «Сохранить карту». |
    | `NALOGO_INN` | ИНН для авторизации в nalog.ru (самозанятый). |
    | `NALOGO_PASSWORD` | Пароль для авторизации в nalog.ru (самозанятый). |
    | `CRYPTOPAY_ENABLED` | Включить/выключить CryptoPay (`true`/`false`). |
    | `CRYPTOPAY_TOKEN` | Токен из вашего CryptoPay App. |
    | `FREEKASSA_ENABLED` | Включить/выключить FreeKassa (`true`/`false`). |
    | `FREEKASSA_MERCHANT_ID` | ID вашего магазина в FreeKassa. |
    | `FREEKASSA_API_KEY` | API-ключ для запросов к FreeKassa REST API. |
    | `FREEKASSA_SECOND_SECRET` | Секретное слово №2 — используется для проверки уведомлений от FreeKassa. |
    | `FREEKASSA_PAYMENT_URL` | (Опционально, legacy SCI) Базовый URL платёжной формы FreeKassa. По умолчанию `https://pay.freekassa.ru/`. |
    | `FREEKASSA_PAYMENT_IP` | Внешний IP вашего сервера, который будет передаваться в запрос оплаты. |
    | `FREEKASSA_PAYMENT_METHOD_ID` | ID метода оплаты через магазин FreeKassa. По умолчанию `44`. |
    | `STARS_ENABLED` | Включить/выключить Telegram Stars (`true`/`false`). |
    | `PLATEGA_ENABLED`| Включить/выключить Platega (`true`/`false`). |
    | `PLATEGA_MERCHANT_ID`| MerchantId из личного кабинета Platega. |
    | `PLATEGA_SECRET`| API секрет для запросов Platega. |
    | `PLATEGA_PAYMENT_METHOD`| ID способа оплаты (2 — SBP QR, 10 — РФ карты, 12 — международные карты, 13 — crypto). |
    | `PLATEGA_RETURN_URL`| (Опционально) URL редиректа после успешной оплаты. По умолчанию ссылка на бота. |
    | `PLATEGA_FAILED_URL`| (Опционально) URL редиректа при ошибке/отмене. По умолчанию как `PLATEGA_RETURN_URL`. |
    | `SEVERPAY_ENABLED` | Включить/выключить SeverPay (`true`/`false`). |
    | `SEVERPAY_MID` | MID магазина в SeverPay. |
    | `SEVERPAY_TOKEN` | Секрет/токен для подписи запросов SeverPay. |
    | `SEVERPAY_BASE_URL` | (Опционально) Базовый URL API SeverPay. По умолчанию `https://severpay.io/api/merchant`. |
    | `SEVERPAY_RETURN_URL` | (Опционально) URL редиректа после оплаты (по умолчанию ссылка на бота). |
    | `SEVERPAY_LIFETIME_MINUTES` | (Опционально) Время жизни платежной ссылки в минутах (30–4320). |
    </details>

    <details>
    <summary><b>Настройки подписок</b></summary>

    Для каждого периода (1, 3, 6, 12 месяцев) можно настроить доступность и цены:
    - `1_MONTH_ENABLED`: `true` или `false`
    - `RUB_PRICE_1_MONTH`: Цена в рублях
    - `STARS_PRICE_1_MONTH`: Цена в Telegram Stars
    Аналогичные переменные есть для `3_MONTHS`, `6_MONTHS`, `12_MONTHS`.
    </details>

    <details>
    <summary><b>Настройки панели Remnawave</b></summary>
    
    | Переменная | Описание |
    | --- | --- |
    | `PANEL_API_URL` | URL API вашей панели Remnawave. |
    | `PANEL_API_KEY` | API ключ для доступа к панели. |
    | `PANEL_WEBHOOK_SECRET`| Секретный ключ для проверки вебхуков от панели. |
    | `USER_SQUAD_UUIDS` | ID отрядов для новых пользователей. |
    | `USER_EXTERNAL_SQUAD_UUID` | Опционально. UUID внешнего отряда (External Squad) из [документации Remnawave](https://docs.rw/api), куда автоматически добавляются новые пользователи. |
    | `USER_TRAFFIC_LIMIT_GB`| Лимит трафика в ГБ (0 - безлимит). |
    | `USER_HWID_DEVICE_LIMIT`| Лимит устройств (HWID) для новых пользователей (0 - безлимит). |

    > Раздел "Мои устройства" становится доступен пользователям только при включении `MY_DEVICES_SECTION_ENABLED`. Значение лимита устройств при создании записей в панели берётся из `USER_HWID_DEVICE_LIMIT`.
    </details>

    <details>
    <summary><b>Настройки пробного периода</b></summary>

    | Переменная | Описание |
    | --- | --- |
    | `TRIAL_ENABLED` | Включить/выключить пробный период (`true`/`false`). |
    | `TRIAL_DURATION_DAYS`| Длительность пробного периода в днях. |
    | `TRIAL_TRAFFIC_LIMIT_GB`| Лимит трафика для пробного периода в ГБ. |
    </details>

3.  **Запустите контейнеры:**
    ```bash
    docker compose up -d
    ```
    Эта команда скачает образы и запустит backend, web-портал и базу данных в фоновом режиме.

4.  **Настройка вебхуков (Обязательно):**
    Вебхуки являются **обязательным** компонентом для работы бота, так как они используются для получения уведомлений от платежных систем (YooKassa, FreeKassa, CryptoPay, Platega, SeverPay) и панели Remnawave.

    Вам понадобится обратный прокси (например, Nginx) для обработки HTTPS-трафика и перенаправления запросов на контейнер с ботом.

    **Пути для перенаправления:**
    -   `https://<ваш_домен>/webhook/yookassa` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/yookassa`
    -   `https://<ваш_домен>/webhook/freekassa` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/freekassa`
    -   `https://<ваш_домен>/webhook/platega` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/platega`
    -   `https://<ваш_домен>/webhook/severpay` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/severpay`
    -   `https://<ваш_домен>/webhook/cryptopay` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/cryptopay`
    -   `https://<ваш_домен>/webhook/panel` → `http://remnawave-tg-shop:<WEB_SERVER_PORT>/webhook/panel`
    -   **Для Telegram:** Бот автоматически установит вебхук, если в `.env` указан `WEBHOOK_BASE_URL`. Путь будет `https://<ваш_домен>/<BOT_TOKEN>`.

    Где `remnawave-tg-shop` — это имя сервиса из `docker-compose.yml`, а `<WEB_SERVER_PORT>` — порт, указанный в `.env`.

5.  **Просмотр логов:**
    ```bash
    docker compose logs -f remnawave-tg-shop remnawave-tg-shop-web
    ```

    > 💡 Если включена проверка подписки на канал (`REQUIRED_CHANNEL_ID`), добавьте бота администратором в этот канал. Пользователь увидит кнопку «Проверить подписку», и, после первого успешного подтверждения, дальнейшие действия блокироваться не будут.

## Подробная инструкция для развертывания на сервере с панелью Remnawave

### 1. Клонирование репозитория

```bash
git clone https://github.com/3252a8/remnawave-tg-shop && cd remnawave-tg-shop
```

### 2. Настройка переменных окружения

```bash
cp .env.example .env && nano .env
```

**Обязательные поля для заполнения:**
- `BOT_TOKEN` - токен телеграмм бота, например, `234567890:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`
- `ADMIN_IDS` - TG ID администраторов, например, `12345678,98765432` и т.д. (через запятую без пробелов)
- `WEBHOOK_BASE_URL` - Обязательно. Базовый URL для вебхуков, например `https://webhook.domain.com`
- `PANEL_API_URL` - URL API вашей панели Remnawave (например, `http://remnawave:3000/api` или `https://panel.domain.com/api`)
- `PANEL_API_KEY` - API ключ для доступа к панели (генерируется из UI-интерфейса панели)
- `PANEL_WEBHOOK_SECRET` - Секретный ключ для проверки вебхуков от панели (берётся из `.env` самой панели)
- `USER_SQUAD_UUIDS` - ID отрядов для новых пользователей

### 3. Настройка Reverse Proxy (Nginx)

Перейдите в директорию конфигурации Nginx панели Remnawave:

```bash
cd /opt/remnawave/nginx && nano nginx.conf
```

Добавьте в `nginx.conf` следующую конфигурацию:

```nginx
upstream remnawave-tg-shop {
    server remnawave-tg-shop:8080;
}

map $http_upgrade $connection_upgrade {
    default upgrade;
    "" close;
}

server {
    server_name webhook.domain.com; # Домен для отправки Webhook'ов
    listen 443 ssl;
    http2 on;

    ssl_certificate "/etc/nginx/ssl/webhook_fullchain.pem";
    ssl_certificate_key "/etc/nginx/ssl/webhook_privkey.key";
    ssl_trusted_certificate "/etc/nginx/ssl/webhook_fullchain.pem";

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    proxy_intercept_errors on;
    error_page 400 404 500 502 @redirect;

    location / {
        proxy_pass http://remnawave-tg-shop$request_uri;
    }

    location @redirect {
        return 404;
    }
}
```

### 4. Выпуск SSL-сертификата для домена webhook

Убедитесь, что установлены необходимые компоненты, а также откройте 80 порт:

```bash
sudo apt-get install cron socat
curl https://get.acme.sh | sh -s email=EMAIL && source ~/.bashrc
ufw allow 80/tcp && ufw reload
```

Выпустите сертификат:

```bash
acme.sh --set-default-ca --server letsencrypt
acme.sh --issue --standalone -d 'webhook.domain.com' \
  --key-file /opt/remnawave/nginx/webhook_privkey.key \
  --fullchain-file /opt/remnawave/nginx/webhook_fullchain.pem
```

### 5. Добавление сертификатов в Docker Compose Nginx

Отредактируйте `docker-compose.yml` панели Nginx:

```bash
cd /opt/remnawave/nginx && nano docker-compose.yml
```

Добавьте две строки в секцию `volumes`:

```yaml
services:
    remnawave-nginx:
        image: nginx:1.26
        container_name: remnawave-nginx
        hostname: remnawave-nginx
        volumes:
            - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
            - ./fullchain.pem:/etc/nginx/ssl/fullchain.pem:ro
            - ./privkey.key:/etc/nginx/ssl/privkey.key:ro
            - ./subdomain_fullchain.pem:/etc/nginx/ssl/subdomain_fullchain.pem:ro
            - ./subdomain_privkey.key:/etc/nginx/ssl/subdomain_privkey.key:ro
            - ./webhook_fullchain.pem:/etc/nginx/ssl/webhook_fullchain.pem:ro     # Добавьте эту строку
            - ./webhook_privkey.key:/etc/nginx/ssl/webhook_privkey.key:ro         # Добавьте эту строку
        restart: always
        ports:
            - '0.0.0.0:443:443'
        networks:
            - remnawave-network

networks:
    remnawave-network:
        name: remnawave-network
        driver: bridge
        external: true
```

### 6. Запуск бота и перезапуск Nginx

Запустите бота:

```bash
cd /root/remnawave-tg-shop && docker compose up -d && docker compose logs -f -t
```

Перезапустите Nginx:

```bash
cd /opt/remnawave/nginx && docker compose down && docker compose up -d && docker compose logs -f -t
```

## 🐳 Docker

Файлы `Dockerfile` и `docker-compose.yml` уже настроены для локальной сборки и запуска проекта. При этом обоим сервисам уже заданы имена GHCR-образов. Если нужен полностью pull-only запуск из GHCR, используйте `docker-compose-remote-server.yml`.

Образы публикуются в GitHub Container Registry по путям `ghcr.io/3252a8/remnawave-tg-shop` и `ghcr.io/3252a8/remnawave-tg-shop-web`. GitHub Actions выкладывают теги `latest` и `0.1.0`: `latest` обновляется из `main`, а `0.1.0` появляется при сборке тега `v0.1.0`.

Чтобы закрепить версию на сервере, можно запустить:
```bash
IMAGE_TAG=0.1.0 docker compose -f docker-compose-remote-server.yml up -d
```

## 📁 Структура проекта

```
.
├── bot/
│   ├── filters/          # Пользовательские фильтры Aiogram
│   ├── handlers/         # Обработчики сообщений и колбэков
│   ├── keyboards/        # Клавиатуры
│   ├── middlewares/      # Промежуточные слои (i18n, проверка бана)
│   ├── services/         # Бизнес-логика (платежи, API панели)
│   ├── states/           # Состояния FSM
│   └── main_bot.py       # Основная логика бота
├── config/
│   └── settings.py       # Настройки Pydantic
├── db/
│   ├── dal/              # Слой доступа к данным (DAL)
│   ├── database_setup.py # Настройка БД
│   └── models.py         # Модели SQLAlchemy
├── locales/              # Файлы локализации (ru, en)
├── web/                  # Отдельный SvelteKit-портал
│   ├── src/              # Клиент, SSR и API-прокси
│   ├── Dockerfile        # Сборка web-контейнера
│   └── server.js         # Node entrypoint с optional TLS
├── .env.example          # Пример файла с переменными окружения
├── Dockerfile            # Инструкции для сборки Docker-образа
├── docker-compose.yml    # Файл для оркестрации контейнеров
├── requirements.txt      # Зависимости Python
└── main.py               # Точка входа в приложение
```

## 🔮 Планы на будущее

-   Расширенные типы промокодов (например, скидки в процентах).

## ❤️ Поддержка
- Карты РФ и зарубежные: [Tribute](https://t.me/tribute/app?startapp=dqdg)
- Crypto: `USDT TRC-20 TT3SqBbfU4vYm6SUwUVNZsy278m2xbM4GE`
