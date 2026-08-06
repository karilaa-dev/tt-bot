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
- Private chats have a three-item FIFO media queue; groups have ten. A slot remains occupied until delivery completes, one job runs at a time per chat, and at most 25 jobs run globally. The global waiting queue is unlimited.
- Legacy queue environment values of `0` are accepted during upgrades and mapped to the defaults above.
- `DB_POOL_SIZE` defaults to 10 PostgreSQL connections.

`tt-scrap` itself must set `TELEGRAM_BOT_TOKEN` to the same value as `BOT_TOKEN` and normally `TELEGRAM_API_BASE_URL=https://api.telegram.org`.

## Run with Docker

Start PostgreSQL for host-side development:

```bash
docker compose up -d db
```

Build and run the bot plus PostgreSQL:

```bash
docker compose up --build
```

The database migration is idempotent and retains the existing `users`, `videos`, and `music` schema.

> [!WARNING]
> The PostgreSQL 18 image stores its cluster below `/var/lib/postgresql`, so Compose now mounts `pgdata` there. Before upgrading an existing deployment that mounted the volume at `/var/lib/postgresql/data`, export the running database with `docker compose exec db sh -c 'pg_dumpall -U "$POSTGRES_USER"' > ttbot-backup.sql`. Recreate the database service with the new mount, then restore with `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER"' < ttbot-backup.sql`. The old Postgres 18 mount did not include the image's active `PGDATA`, so recreating that old container without a dump can lose its database.

## Development

```bash
bun install --frozen-lockfile
bun run typecheck
bun test
bun run start
```

The default test suite does not start or require PostgreSQL. Database integration tests are optional and run only when `TEST_DB_URL` or `TEST_DB_ADMIN_URL` is set.

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
