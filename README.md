# tt-bot

Telegram bot for TikTok and Instagram links, implemented in strict TypeScript with [Bun](https://bun.sh/) and [grammY](https://grammy.dev/).

TikTok and Instagram extraction, media preparation, and Telegram upload are delegated to `tt-scrap`. The service must use the same Telegram bot token as this bot so returned file IDs and callback buttons belong to the polling bot.

## Configuration

Copy `.env.example` to `.env` and configure:

- `BOT_TOKEN`, `DB_URL`, and `TT_SCRAP_API_KEY` are required.
- `TT_SCRAP_BASE_URL` points to the API. The local service discovered in this workspace listens at `http://127.0.0.1:8000`.
- Compose uses `http://host.docker.internal:8000` so its container can reach that host service.
- `TG_SERVER` defaults to `https://api.telegram.org`. It may be changed to a compatible custom Telegram Bot API root, but no local server is bundled.
- `STORAGE_CHANNEL_ID` is required for inline delivery and group slideshows containing more than ten items.

`tt-scrap` itself must set `TELEGRAM_BOT_TOKEN` to the same value as `BOT_TOKEN` and normally `TELEGRAM_API_BASE_URL=https://api.telegram.org`.

## Run with Docker

Start PostgreSQL for tests or host-side development:

```bash
docker compose up -d db
```

Build and run the bot plus PostgreSQL:

```bash
docker compose up --build
```

The database migration is idempotent and retains the existing `users`, `videos`, and `music` schema.

## Development

```bash
bun install --frozen-lockfile
bun run typecheck
bun test
bun run start
```

Maintenance mode is available separately:

```bash
bun run maintenance
```

Refresh generated OpenAPI types from a running `tt-scrap` instance with:

```bash
TT_SCRAP_BASE_URL=http://127.0.0.1:8000 bun run api:generate
```

## Instagram delivery

The bot extracts Instagram posts and reels with `POST /v1/instagram/extractions`, then sends the returned `extraction_id` to `POST /v1/instagram/telegram-deliveries`. Single photos, videos, mixed carousels, document mode, group limits, multi-batch results, and inline carousel navigation are supported. The bot never downloads Instagram media bytes itself.
