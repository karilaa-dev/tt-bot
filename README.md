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

New databases are initialized with separate download-history (`videos`) and reusable-media (`video_details`) tables. A database from the Python v5.4.6 release must be rebuilt explicitly while the main bot is stopped; normal startup refuses to modify that legacy schema. Maintenance mode does not connect to PostgreSQL and may be used to notify users during the outage.

> [!WARNING]
> The PostgreSQL 18 image stores its cluster below `/var/lib/postgresql`, so Compose now mounts `pgdata` there. Before upgrading an existing deployment that mounted the volume at `/var/lib/postgresql/data`, export the running database with `docker compose exec db sh -c 'pg_dumpall -U "$POSTGRES_USER"' > ttbot-backup.sql`. Recreate the database service with the new mount, then restore with `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER"' < ttbot-backup.sql`. The old Postgres 18 mount did not include the image's active `PGDATA`, so recreating that old container without a dump can lose its database.

## Development

```bash
bun install --frozen-lockfile
bun run typecheck
bun test
bun run start
```

The test suite is self-contained and does not connect to PostgreSQL. Exercise the offline migration against a verified database copy during rollout rather than from automated tests.

Instagram standard-media cache entries intentionally have no periodic expiry. They are refreshed only after Telegram rejects a stored file ID or after document delivery detects a changed media shape; the 24-hour metadata refresh applies only to TikTok.

Maintenance mode is available separately:

```bash
bun run maintenance
```

Refresh generated OpenAPI types from a running `tt-scrap` instance with:

```bash
TT_SCRAP_BASE_URL=http://127.0.0.1:8000 bun run api:generate
```

For a checked-out adjacent `tt-scrap` repository, generation can use its exported schema without starting a server:

```bash
TT_SCRAP_OPENAPI_FILE=../tt-scrap/openapi.json bun run api:generate
```

## Offline v5.4.6 database rebuild

The rebuild preserves every history row, extracts only IDs already embedded in legacy URLs, and never follows old TikTok redirect tokens. Identity parsing, detail aggregation/finalization, and history copying are resumable in 100,000-primary-key batches. The rebuild records its source audit, parsing totals, checksums, verification, and cutover status in `migration_audit`.

Before running it, deploy the matching `tt-scrap` API, stop the bot and any legacy stats process, and create a verified external PostgreSQL backup. A rehearsal on a production-sized copy is recommended. The migration prints its conservative free-space requirement (four times the source `videos` relation size); when you know the database filesystem's exact free bytes, set `LEGACY_MIGRATION_AVAILABLE_BYTES` and it will enforce that limit too.

Do not start `bun run start` against the legacy schema; it intentionally exits with instructions to run the offline rebuild. `bun run maintenance` remains available because it does not access PostgreSQL. Aside from that optional notifier, `bun run db:migrate-legacy` must be the only application process accessing the database during the rebuild.

If startup finds an already rebuilt `videos` table but legacy `users.ad_count` or `users.ad_cooldown` columns remain, the same offline command audits their exact nonzero counts, removes only those columns, and records the recovery in `migration_audit`; it does not rebuild history again.

Run from a shell with the deployment's existing `DB_URL`:

```bash
bun run db:migrate-legacy --confirm
```

`--confirm` acknowledges that the processes are stopped and a restorable backup is available. Re-running the same command resumes the last committed batch. On a fresh database or one already using the current schema, it exits successfully without rebuilding anything; an unrecognized partial schema still fails. Before scanning history, the migration exercises the actual PL/pgSQL identity parser against every supported URL family and conflict behavior; there is no duplicate application-side legacy parser to drift from it. After exact verification, cutover is atomic and the old table is dropped in that transaction, as required by the selected immediate-drop policy. Post-commit rollback therefore uses the required external backup.

### Run the migration from a Dokploy Railpack application

The repository's `railpack.json` makes Railpack start `scripts/start.ts` directly, so no custom start command or Dockerfile build is needed. In Dokploy:

1. Set the application build type to **Railpack** and use one replica.
2. Stop the existing bot application (and any separate stats process), then create and verify the database backup.
3. Add `MIGRATE_LEGACY_ON_START=confirmed` to the application's environment.
4. Deploy this revision and watch its logs. The Railpack container runs the resumable migration and starts the bot only after it completes.
5. Remove `MIGRATE_LEGACY_ON_START` after the audit reports `complete`, then redeploy normally.

If the container is interrupted, leave the old bot stopped and redeploy with the same variable; completed batches are not repeated. Do not run multiple migration replicas.
On a brand-new database or one that already has the current schema, this startup mode skips the legacy rebuild and continues with normal bot initialization. An unrecognized partial `videos` schema still fails safely.

If verification fails, the legacy source table is left active and unchanged. Diagnose and correct the cause before retrying. Because a completed copy phase is intentionally not repeated, reset only the disposable destination copy and its downstream phase markers before re-running the command:

```sql
BEGIN;
DROP TABLE IF EXISTS videos_new;
DELETE FROM legacy_migration_state
WHERE migration_id = '002_media_cache_rebuild'
  AND phase IN ('copy', 'constraints', 'verification');
COMMIT;
```

Do not delete the source audit, identity, or details phase state: those completed phases remain reusable. Run this recovery only while the bot and stats processes are still stopped and the verified backup remains available.

Review the durable evidence before starting the bot:

```sql
SELECT status, started_at, completed_at, evidence
FROM migration_audit
WHERE migration_id = '002_media_cache_rebuild';
```

## Telegram media cache

Standard video/photo deliveries store ordered, bot-scoped Telegram `file_id` and `file_unique_id` values. TikTok always resolves a link before lookup. Fresh TikTok cache hits avoid extraction for 24 hours; stale hits use full extraction because the current API exposes refreshed creator and rounded likes/views there, while still reusing IDs if the media shape is unchanged. Instagram cache hits skip extraction without the TikTok periodic refresh rule; a changed shape observed in document mode triggers a one-time validation on the next standard-media request.

Document mode always extracts and uploads, records history and refreshed details, never stores document IDs, and never erases a standard-media cache. If that extraction reveals a changed media shape, the retained cache is marked stale so the next standard-media request validates and replaces it. A confirmed invalid Telegram file identifier invalidates that exact cache version and permits one extraction/upload retry; ambiguous transport errors and partially delivered albums are never blindly resent.

Cached albums intentionally mirror tt-scrap's `_album_batches` delivery contract: Telegram groups contain 2-10 items, batches prefer 10 items, and an 11-item tail splits as 9+2. The matching tt-scrap slideshow handler must also select `sendPhoto` for one standard image and `sendDocument` for one document so captions and controls stay on that item. Changes to either cross-service contract must update and deploy tt-scrap and the bot together; the bot's delivery/cache tests lock its side to the agreed behavior.

## Instagram delivery

The bot extracts Instagram posts and reels with `POST /v1/instagram/extractions`, then sends the returned `extraction_id` to `POST /v1/instagram/telegram-deliveries`. Single photos, videos, mixed carousels, document mode, group limits, multi-batch results, and inline carousel navigation are supported. The bot never downloads Instagram media bytes itself.
