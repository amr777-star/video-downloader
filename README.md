# Video Downloader API

Сервис для скачивания видео из **TikTok**, **Instagram Reels** и **YouTube Shorts** без водяного знака.

Включает веб-интерфейс и REST API для интеграции с другими сервисами.

## Быстрый старт

### Docker (рекомендуется)

```bash
git clone https://github.com/amr777-star/video-downloader.git
cd video-downloader
cp .env.example .env
# Отредактируй .env — задай API_KEY
docker compose up -d
```

Сервис будет доступен на `http://localhost:8000`

### Без Docker

```bash
git clone https://github.com/amr777-star/video-downloader.git
cd video-downloader
pip install -r requirements.txt
```

**Зависимости системы:**
- Python 3.11+
- ffmpeg (`apt install ffmpeg` / `brew install ffmpeg` / `winget install ffmpeg`)

```bash
# Запуск
export API_KEY="your-secret-key"
python main.py
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `API_KEY` | _(пусто — без авторизации)_ | Ключ для защиты API. Передаётся в заголовке `X-API-Key` |
| `PORT` | `8000` | Порт сервера |
| `CORS_ORIGINS` | `*` | Разрешённые домены через запятую |
| `FILE_TTL` | `3600` | Время жизни скачанных файлов (секунды) |

## API

Все POST-эндпоинты принимают JSON. Если задан `API_KEY`, передавай заголовок `X-API-Key`.

### `GET /api/health`

Проверка работоспособности.

```bash
curl http://localhost:8000/api/health
```

```json
{ "status": "ok", "ytdlp_version": "2026.06.09" }
```

### `POST /api/info`

Метаданные видео без скачивания.

```bash
curl -X POST http://localhost:8000/api/info \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"url": "https://www.tiktok.com/@user/video/123"}'
```

```json
{
  "id": "123",
  "title": "Название видео",
  "duration": "15",
  "thumbnail": "https://...",
  "uploader": "username",
  "views": "50000",
  "platform": "tiktok"
}
```

### `POST /api/download`

Скачивает видео и возвращает ссылку на файл.

```bash
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"url": "https://www.tiktok.com/@user/video/123"}'
```

```json
{
  "filename": "tiktok_a1b2c3d4e5_123.mp4",
  "title": "Название видео",
  "duration": "15",
  "thumbnail": "https://...",
  "size": 2190000,
  "platform": "tiktok",
  "download_url": "/download/tiktok_a1b2c3d4e5_123.mp4"
}
```

Затем скачай файл:
```bash
curl -O http://localhost:8000/download/tiktok_a1b2c3d4e5_123.mp4
```

### `POST /api/download/direct`

Скачивает видео и сразу стримит файл в ответе (без промежуточного шага).

```bash
curl -X POST http://localhost:8000/api/download/direct \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key" \
  -d '{"url": "https://www.tiktok.com/@user/video/123"}' \
  -o video.mp4
```

Метаданные в заголовках ответа: `X-Video-Title`, `X-Video-Duration`.

## Интеграция с другим сервисом

### JavaScript / TypeScript

```ts
const VIDEO_API = "https://your-server.com";
const API_KEY = process.env.VIDEO_DOWNLOADER_KEY;

async function downloadVideo(url: string) {
  const res = await fetch(`${VIDEO_API}/api/download/direct`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
    },
    body: JSON.stringify({ url }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail);
  }

  const buffer = await res.arrayBuffer();
  return Buffer.from(buffer);
}
```

### Python

```python
import httpx

VIDEO_API = "https://your-server.com"
API_KEY = "your-secret-key"

async def download_video(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{VIDEO_API}/api/download/direct",
            json={"url": url},
            headers={"X-API-Key": API_KEY},
        )
        resp.raise_for_status()
        return resp.content
```

### n8n / Webhook

HTTP Request node:
- **Method:** POST
- **URL:** `https://your-server.com/api/download`
- **Headers:** `X-API-Key: your-key`, `Content-Type: application/json`
- **Body:** `{"url": "{{$json.video_url}}"}`

## Деплой на сервер

```bash
# На сервере
git clone https://github.com/amr777-star/video-downloader.git
cd video-downloader
cp .env.example .env
nano .env  # задай API_KEY

docker compose up -d
```

Для проксирования через nginx:

```nginx
location /video-api/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
    client_max_body_size 100M;
}
```

## Swagger-документация

После запуска доступна по адресу:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
