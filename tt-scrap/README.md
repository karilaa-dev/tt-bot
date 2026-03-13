# Media Scraper API

Standalone FastAPI server for extracting video, slideshow, and music metadata from social media platforms. Built with a service-based architecture — each platform is a self-contained plugin under `app/services/`.

Currently supported: **TikTok**

## Running with uv

```bash
cd tt-scrap

# Install dependencies
uv sync

# Start the server
uv run uvicorn app.app:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uv run uvicorn app.app:app --reload
```

## Running with Docker

```bash
cd tt-scrap

# Build
docker build -t tt-scrap .

# Run
docker run -p 8000:8000 tt-scrap

# Run with environment variables
docker run -p 8000:8000 \
  -e PROXY_FILE=/data/proxies.txt \
  -e LOG_LEVEL=DEBUG \
  -v /path/to/proxies.txt:/data/proxies.txt \
  tt-scrap
```

## API Endpoints

Routes are namespaced per service: `/{service}/...`

### TikTok

#### `GET /tiktok/video`

Extract video or slideshow metadata from a TikTok URL.

| Parameter | Type   | Description                       |
|-----------|--------|-----------------------------------|
| `url`     | string | TikTok video or slideshow URL     |
| `raw`     | bool   | Return raw TikTok API data (default: false) |

#### `GET /tiktok/music`

Extract music metadata from a TikTok video.

| Parameter  | Type | Description            |
|------------|------|------------------------|
| `video_id` | int  | TikTok video ID        |
| `raw`      | bool | Return raw data (default: false) |

### Shared

#### `GET /health`

Health check. Returns `{"status": "ok"}`.

#### `GET /docs`

Interactive OpenAPI documentation (Swagger UI).

## Environment Variables

### Global

| Variable             | Default | Description                              |
|----------------------|---------|------------------------------------------|
| `PROXY_FILE`         | `""`    | Path to proxy file (one URL per line)    |
| `PROXY_INCLUDE_HOST` | `false` | Include direct connection in proxy rotation |
| `LOG_LEVEL`          | `INFO`  | Logging level (DEBUG, INFO, WARNING, ERROR) |

### TikTok (`TIKTOK_` prefix)

| Variable                          | Default | Description                              |
|-----------------------------------|---------|------------------------------------------|
| `TIKTOK_URL_RESOLVE_MAX_RETRIES`  | `3`     | Max retries for short URL resolution     |
| `TIKTOK_VIDEO_INFO_MAX_RETRIES`   | `3`     | Max retries for video info extraction    |
| `YTDLP_COOKIES`                   | `""`    | Path to Netscape-format cookies file     |

## Adding a New Service

1. Create `app/services/<name>/` with `client.py`, `parser.py`, `routes.py`
2. Implement the `BaseClient` protocol (see `app/base_client.py`)
3. Create a factory function returning a `ServiceEntry`
4. Register it in `app/app.py` lifespan
