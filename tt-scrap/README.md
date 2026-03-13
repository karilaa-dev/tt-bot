# TT Scrap API

Standalone FastAPI server for extracting TikTok video, slideshow, and music metadata.

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

### `GET /video`

Extract video or slideshow metadata from a TikTok URL.

| Parameter | Type   | Description                       |
|-----------|--------|-----------------------------------|
| `url`     | string | TikTok video or slideshow URL     |
| `raw`     | bool   | Return raw TikTok API data (default: false) |

### `GET /music`

Extract music metadata from a TikTok video.

| Parameter  | Type | Description            |
|------------|------|------------------------|
| `video_id` | int  | TikTok video ID        |
| `raw`      | bool | Return raw data (default: false) |

### `GET /health`

Health check. Returns `{"status": "ok"}`.

### `GET /docs`

Interactive OpenAPI documentation (Swagger UI).

## Environment Variables

| Variable                      | Default | Description                              |
|-------------------------------|---------|------------------------------------------|
| `URL_RESOLVE_MAX_RETRIES`     | `3`     | Max retries for short URL resolution     |
| `VIDEO_INFO_MAX_RETRIES`      | `3`     | Max retries for video info extraction    |
| `PROXY_FILE`                  | `""`    | Path to proxy file (one URL per line)    |
| `PROXY_INCLUDE_HOST`          | `false` | Include direct connection in proxy rotation |
| `LOG_LEVEL`                   | `INFO`  | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `YTDLP_COOKIES`              | `""`    | Path to Netscape-format cookies file     |
