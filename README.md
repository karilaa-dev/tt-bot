# tt-bot

## Running with Docker

1. Build the image (uses uv for dependency management):
   ```bash
   docker build -t tt-bot .
   ```
2. Create a `.env` file based on `.env.example` and fill in the required settings.
   - Always set: `BOT_TOKEN`
   - If you will use a local Telegram Bot API server (recommended with Docker Compose below): keep `TG_SERVER=http://telegram-bot-api:8081` and add `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` to your `.env`.
   - If you will use the public Telegram API endpoint without the local server: set `TG_SERVER=https://api.telegram.org` and you do not need `TELEGRAM_API_ID/HASH`.
3. Run the container with the environment file:
   ```bash
   docker run --rm --env-file .env tt-bot
   ```
   Note: When running a single container like this, ensure `TG_SERVER` is reachable from the container. If you kept `TG_SERVER=http://telegram-bot-api:8081`, you must also run a `telegram-bot-api` container and place both on the same network, or switch `TG_SERVER` to `https://api.telegram.org`.

## Docker Compose

Docker Compose brings up three services by default:
- `bot` – this project’s Telegram bot
- `telegram-bot-api` – a local Telegram Bot API server (faster and avoids public rate limits)
- `db` – optional PostgreSQL database used by the bot (enabled by default in the compose file)

Before starting, copy `.env.example` to `.env` and set at least these variables:
- BOT_TOKEN
- TELEGRAM_API_ID and TELEGRAM_API_HASH (required for the `telegram-bot-api` service)
- Optionally adjust `DB_URL` if you don’t want to use the compose-managed Postgres

To run everything:

```bash
docker compose up
```

Only the bot service will start if you specify it explicitly:

```bash
docker compose up bot
```

If you start only `bot`, ensure `TG_SERVER` points to a reachable endpoint (either also start `telegram-bot-api` or set `TG_SERVER=https://api.telegram.org`).

Notes:
- By default the local Bot API listens on port 8081 inside the compose network and isn’t exposed to your host. The bot talks to it via `TG_SERVER=http://telegram-bot-api:8081`. If you want to access it from your host for debugging, add a `ports:` mapping to the `telegram-bot-api` service (e.g. `- "8081:8081"`).
- The Compose file also defines a PostgreSQL service. You can override its default credentials by setting `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` in your `.env` or shell environment.

## Local development with uv

This project uses uv for dependency management. To run locally without Docker:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Ensure ~/.local/bin is on your PATH, then:
uv sync
uv run python main.py
```

Tips for local runs:
- Create a `.env` from `.env.example` and set `BOT_TOKEN`.
- If you are not running a local Telegram Bot API server, set `TG_SERVER=https://api.telegram.org`.
- If you are running the compose stack for the local Bot API and DB concurrently, you can keep `TG_SERVER=http://telegram-bot-api:8081` and `DB_URL=postgresql+asyncpg://postgres:postgres@db/ttbot-db`.

Database initialization: the app will auto-create tables on startup using SQLAlchemy; no manual migrations are needed for first run.
