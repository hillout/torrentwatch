# TorrentWatch

**TorrentWatch** — форк [Monitorrent](https://github.com/werwolfby/monitorrent) с современным UI и поддержкой **kinozal.guru** через **FlareSolverr**.

Базовая версия: Monitorrent **1.4.0**.

## Что изменилось относительно upstream

- Ребрендинг UI: **TorrentWatch** (светлая/тёмная/system тема, IBM Plex Sans, radar favicon)
- Трекер **kinozal.guru** вместо устаревшего kinozal.tv
- Обход Cloudflare через **FlareSolverr** (`FLARESOLVERR_URL`) + кэш `cf_clearance`
- Скачивание раздач с основного домена (обход 520 на `dl.kinozal.guru`)
- Миграция существующих топиков/URL с `kinozal.tv` → `kinozal.guru`

## Возможности (как у Monitorrent)

### Трекеры

LostFilm, Rutor, Free-Torrents, RuTracker, Tapochek, Unionpeer, NNMClub, AniDub, **Kinozal.guru**, HDClub, AniLibria, Toloka и др.

### Клиенты

Папка на диске, Transmission, Deluge, uTorrent, qBittorrent.

### Уведомления

Telegram, Pushover, Email, Pushbullet, Pushall.

---

## Быстрый старт (Docker Compose)

Готовый образ: [`ghcr.io/hillout/torrentwatch`](https://github.com/hillout/torrentwatch/pkgs/container/torrentwatch)  
(собирается GitHub Actions на каждый push в `main` и по тегам).

### Требования

- Docker + Docker Compose
- ~512 MB RAM (FlareSolverr может потреблять больше при решении CF)

### Установка (готовый образ)

Минимальный вариант — только compose-файл из репозитория:

```bash
mkdir torrentwatch && cd torrentwatch
curl -fsSL -o docker-compose.yml \
  https://raw.githubusercontent.com/hillout/torrentwatch/main/docker-compose.yml
mkdir -p data
touch data/monitorrent.db

docker compose pull
docker compose up -d
```

Или клонируйте репозиторий и поднимите тот же стек:

```bash
git clone https://github.com/hillout/torrentwatch.git
cd torrentwatch
mkdir -p data && touch data/monitorrent.db
docker compose up -d
```

Откройте в браузере: [http://localhost:6687](http://localhost:6687)

- **Логин:** пароль по умолчанию — `monitorrent`
- Сразу смените пароль в **Settings → Authentication** или отключите auth

### Сервисы

| Сервис         | Порт  | Назначение                          |
|----------------|-------|-------------------------------------|
| `torrentwatch` | 6687  | Веб-интерфейс и API                 |
| `flaresolverr` | —     | Обход Cloudflare для kinozal.guru   |

Переменная окружения:

```yaml
FLARESOLVERR_URL=http://flaresolverr:8191/v1
```

Опционально: `TZ`, `TORRENTWATCH_PORT` (по умолчанию `6687`).

### Обновление

```bash
docker compose pull
docker compose up -d
```

База данных в `./data/monitorrent.db` сохраняется между обновлениями.

### Локальная сборка из исходников

Для разработки или своих правок используйте `docker-compose.build.yml`:

```bash
git clone https://github.com/hillout/torrentwatch.git
cd torrentwatch
mkdir -p data && touch data/monitorrent.db
docker compose -f docker-compose.build.yml up -d --build
```

---

## Docker без Compose

```bash
# 1) FlareSolverr
docker run -d --name flaresolverr \
  -e LOG_LEVEL=info \
  --restart unless-stopped \
  ghcr.io/flaresolverr/flaresolverr:latest

# 2) TorrentWatch (в одной docker-сети с flaresolverr)
docker network create tw-net
docker network connect tw-net flaresolverr

mkdir -p data && touch data/monitorrent.db
docker run -d --name torrentwatch \
  --network tw-net \
  -e FLARESOLVERR_URL=http://flaresolverr:8191/v1 \
  -p 6687:6687 \
  -v "$PWD/data/monitorrent.db:/var/www/monitorrent/monitorrent.db" \
  --restart unless-stopped \
  ghcr.io/hillout/torrentwatch:latest
```

---

## Ручная установка (разработка)

### Backend

Требования: **Python 3.9+**, pip.

```bash
git clone https://github.com/hillout/torrentwatch.git
cd torrentwatch
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps firefox

export FLARESOLVERR_URL=http://127.0.0.1:8191/v1
python server.py
```

Веб-сервер: порт **6687**.

> Для kinozal.guru всё равно нужен запущенный FlareSolverr.

### Frontend (пересборка UI)

Требования: **Node.js** (для gulp 3 удобнее Node 10–14) и npm.

```bash
npm install
npx gulp          # dev build в dist/
# или
npx gulp release  # release zip + dist/
```

После `gulp` статика попадает в `dist/` (это же копируется в Docker-образ).

---

## Настройка kinozal.guru

1. Запустите стек с FlareSolverr.
2. **Settings → Trackers → kinozal.guru** — укажите логин/пароль трекера.
3. Нажмите проверку credentials.
4. Добавьте раздачу URL вида  
   `https://kinozal.guru/details.php?id=XXXXX`  
   (старые ссылки `kinozal.tv` мигрируются автоматически).

Первый запрос через FlareSolverr может занять 30–60 с; далее используется кэш Cloudflare-cookie.

---

## Конфигурация

| Переменная          | По умолчанию                         | Описание                    |
|---------------------|--------------------------------------|-----------------------------|
| `FLARESOLVERR_URL`  | _(пусто; в compose задаётся)_        | Endpoint FlareSolverr API   |
| `TZ`                | `Europe/Moscow` (в compose)          | Часовой пояс контейнера     |

Данные приложения хранятся в SQLite: `monitorrent.db`.

---

## Traefik / reverse proxy (пример)

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.torrentwatch.rule=Host(`torrentwatch.example.com`)
  - traefik.http.routers.torrentwatch.entrypoints=websecure
  - traefik.http.routers.torrentwatch.tls=true
  - traefik.http.services.torrentwatch.loadbalancer.server.port=6687
```

Рекомендуется закрыть UI через SSO/OIDC (Gatekeeper, Authelia и т.п.) и сменить пароль приложения.

---

## Разработка и вклад

1. Форкните репозиторий
2. Создайте ветку: `git checkout -b feature/my-change`
3. Закоммитьте изменения
4. Откройте Pull Request

Исходный проект: [werwolfby/monitorrent](https://github.com/werwolfby/monitorrent).

---

## Лицензия

Сохранена лицензия upstream: **WTFPL** — см. [LICENSE.md](LICENSE.md).

TorrentWatch — независимый форк; Monitorrent и его авторы не связаны с этим репозиторием.
