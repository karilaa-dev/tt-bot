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

New databases are initialized with separate download-history (`videos`) and reusable-media (`video_details`) tables. A database from the Python v5.4.6 release requires an explicitly confirmed online rebuild. Confirmed startup installs a live-write bridge, starts the bot, and backfills legacy history in the background; ordinary startup still refuses to modify a legacy schema.

> [!WARNING]
> The PostgreSQL 18 image stores its cluster below `/var/lib/postgresql`, so Compose now mounts `pgdata` there. Before upgrading an existing deployment that mounted the volume at `/var/lib/postgresql/data`, export the running database with `docker compose exec db sh -c 'pg_dumpall -U "$POSTGRES_USER"' > ttbot-backup.sql`. Recreate the database service with the new mount, then restore with `docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER"' < ttbot-backup.sql`. The old Postgres 18 mount did not include the image's active `PGDATA`, so recreating that old container without a dump can lose its database.

## Development

```bash
bun install --frozen-lockfile
bun run typecheck
bun test
bun run start
```

The regular local test suite is self-contained and skips external PostgreSQL. CI provisions PostgreSQL 18 and runs the online migration integration test against a uniquely created disposable database, including interruption/resumption and a write that spans snapshot verification and cutover. To run that check against a local development server:

```bash
POSTGRES_MIGRATION_TEST_ADMIN_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  bun run test:integration:migration
```

Still rehearse the migration against a verified production-sized database copy before rollout; the CI fixture validates concurrency semantics, not production volume or timing.

### Real tt-scrap integration tests

The opt-in integration suite runs the real bot handlers against a real tt-scrap
process. It starts a local fake Telegram Bot API so no messages reach real users and
uses an in-memory database boundary, so it does not connect to PostgreSQL. Media
resolution, extraction, downloads, preparation, and tt-scrap delivery are real and
therefore require live public posts and the upstream credentials used by tt-scrap.

Create the ignored local fixture manifest and replace every placeholder with a live
post. `expectedMediaTypes` must describe every item in source order; use `photo` for
images and `video` for videos:

```bash
cp tests/integration/tt-scrap.fixtures.example.json \
  tests/integration/tt-scrap.fixtures.local.json
```

By default the test starts the adjacent `../tt-scrap` checkout on port `18180`,
using that checkout's `.env` for TikTok/Instagram credentials. It overrides only
the tt-scrap API key and Telegram settings with test-only values:

```bash
bun run test:integration:tt-scrap
```

Set `TT_SCRAP_REPO` when the checkout is elsewhere. Ports and the fixture path may
also be changed:

```bash
TT_SCRAP_REPO=/path/to/tt-scrap \
TT_SCRAP_INTEGRATION_SERVER_PORT=19180 \
TT_SCRAP_INTEGRATION_TELEGRAM_PORT=19181 \
TT_SCRAP_INTEGRATION_FIXTURES=/path/to/fixtures.json \
bun run test:integration:tt-scrap
```

To use an already running service, it must use the same bot token as the test and
must point its `TELEGRAM_API_BASE_URL` to the fake Telegram port before it starts.
The default test token is
`123456789:integration-test-token-not-a-real-secret`; override it on both sides with
`TT_SCRAP_INTEGRATION_BOT_TOKEN` if needed. Then run:

```bash
TT_SCRAP_INTEGRATION_EXTERNAL_BASE_URL=http://127.0.0.1:8000 \
TT_SCRAP_API_KEY=your-api-key \
bun run test:integration:tt-scrap
```

The matrix covers TikTok video, one-image slideshow, and multi-image slideshow plus
Instagram video, image, and mixed carousel. For every fixture it verifies:

- A never-downloaded chat request uploads through tt-scrap, stores ordered file IDs,
  and records `cache_hit = false`.
- A repeated request reuses the stored IDs and records `cache_hit = true` without a
  new extraction or tt-scrap delivery.
- A TikTok cache older than 24 hours performs a real metadata extraction, refreshes
  its rounded stats, and still records a cache hit while reusing valid IDs.
- A confirmed invalid cached ID is invalidated once, re-extracted, uploaded again
  through tt-scrap, and recorded as a cache miss with replacement IDs.
- Document mode always extracts and uploads, records `delivery_mode = document`, and
  leaves standard-media file IDs unchanged.
- A first inline request stages through tt-scrap and persists its IDs; the next inline
  request uses the cache. Multi-item inline results show one item with navigation,
  while single-item results have no slideshow navigation.
- Videos and one-image posts carry the caption on the media message. A gallery uses
  Telegram media groups followed by one caption text message in chat. Inline results
  always edit one inline media message and put its caption on that media.
- TikTok ID-bearing route variants (`/@/video`, `/v`, `/embed`, `/player/v1`, and
  `item_id`) and Instagram host/tracking variants map back to the same cache record.

Normal `bun test` does not make live tt-scrap calls; it reports this suite as skipped.

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

## Online v5.4.6 database rebuild

The rebuild preserves every history row, extracts only IDs already embedded in legacy URLs, and never follows old TikTok redirect tokens. It first performs a read-only source safety audit, then creates the final cache and shadow-history tables and installs always-enabled triggers that mirror every legacy insert, update, and delete while rejecting `TRUNCATE`. Once that bridge is ready, the bot starts and identity parsing, detail aggregation, and history copying continue in resumable 100,000-primary-key batches. Finalization into the live `video_details` cache uses smaller 1,000-row transactions to limit lock contention with bot requests.

Before running it, deploy the matching `tt-scrap` API and create a verified external PostgreSQL backup. Stop or upgrade any separate legacy stats process before cutover because its old `videos` queries are not compatible with the final schema. A rehearsal on a production-sized copy is recommended. The migration prints its conservative free-space requirement (four times the source `videos` relation size); when you know the database filesystem's exact free bytes, set `LEGACY_MIGRATION_AVAILABLE_BYTES` and it will enforce that limit too.

Ordinary `bun run start` still exits on a legacy schema. Set `MIGRATE_LEGACY_ON_START=confirmed` to use the guarded online path: startup waits for the read-only safety audit and live-write bridge, then the bot serves while the rebuild continues. A migration error is fatal to the serving process so it cannot silently outrun a broken shadow copy. On shutdown, the migration finishes only its current transaction, records no partial batch, closes its pool, and resumes from the last checkpoint on the next deployment.

If startup finds an already rebuilt `videos` table but legacy `users.ad_count` or `users.ad_cooldown` columns remain, the same command audits their exact nonzero counts, removes only those columns, and records the recovery in `migration_audit`; it does not rebuild history again.

Run from a shell with the deployment's existing `DB_URL`:

```bash
bun run db:migrate-legacy --confirm
```

`--confirm` acknowledges that a restorable backup is available. The standalone command also tolerates active legacy writers once its sync trigger is installed, but the confirmed startup mode is preferred because it starts the new bot at the safe readiness point and treats later migration failure as fatal. Re-running either path resumes the last committed batch. On a fresh database or one already using the current schema, it exits successfully without rebuilding anything; an unrecognized partial schema still fails.

Before scanning history, the migration exercises the actual PL/pgSQL identity parser against every supported URL family and conflict behavior; there is no duplicate application-side legacy parser to drift from it. Final source/destination verification uses one repeatable-read snapshot while the sync trigger keeps accepting writes. Cutover then waits for in-flight history writers and briefly takes an exclusive lock only for the atomic table swap. The old table is dropped in that transaction, so post-commit rollback still uses the required external backup.

### Run the migration from a Dokploy Railpack application

The repository's `railpack.json` makes Railpack start `scripts/start.ts` directly, so no custom start command or Dockerfile build is needed. In Dokploy:

1. Set the application build type to **Railpack** and use one replica.
2. Create and verify the database backup. Stop any separate legacy stats process.
3. Add `MIGRATE_LEGACY_ON_START=confirmed` to the application's environment.
4. Deploy this revision and watch its logs. The bot starts as soon as live-write sync is ready, while the resumable history backfill continues in the same container.
5. Remove `MIGRATE_LEGACY_ON_START` after the audit reports `complete`, then redeploy normally.

If the container is interrupted, redeploy with the same variable; completed batches are not repeated and the durable triggers keep the shadow table synchronized and protected from truncation. Do not run multiple migration replicas.
On a brand-new database or one that already has the current schema, this startup mode skips the legacy rebuild and continues with normal bot initialization. An unrecognized partial `videos` schema still fails safely.

If verification fails, the legacy source table is left active and unchanged. Diagnose and correct the cause before retrying. Because a completed copy phase is intentionally not repeated, remove only backfilled rows at or below the durable watermark and reset its downstream phase markers before re-running the command. Never drop or truncate `videos_new`: rows above the watermark were written by the live trigger, and it is the only table that can retain their final-only fields such as `delivery_mode` and `cache_hit`.

```sql
BEGIN;
DELETE FROM videos_new
WHERE pk_id <= (
  SELECT (evidence->'backfill_bound'->>'upper_pk')::bigint
  FROM migration_audit
  WHERE migration_id = '002_media_cache_rebuild'
);
DELETE FROM legacy_migration_state
WHERE migration_id = '002_media_cache_rebuild'
  AND phase IN ('copy', 'constraints', 'verification');
COMMIT;
```

Do not delete the source audit, bound, identity, details, or live rows above the bound: those completed phases and trigger-mirrored rows remain reusable. Run this recovery only while the failed application is stopped and the verified backup remains available; redeployment reinstalls the sync trigger before starting the bot.

Review the durable evidence before removing the one-time startup flag:

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
