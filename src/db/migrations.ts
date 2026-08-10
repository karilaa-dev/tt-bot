import type { SQL } from "bun";

export const MEDIA_CACHE_SCHEMA_VERSION = "002_media_cache";
export const LEGACY_MIGRATION_COMMAND = "bun run db:migrate-legacy --confirm";
export const HISTORY_CUTOVER_LOCK_KEY = "tt-bot:video-history-cutover";

export interface RunMigrationsOptions {
  /** The online rebuild has installed the final cache schema and live-write bridge. */
  allowLegacyMigration?: boolean;
}

const expectedColumns: Record<string, Record<string, string>> = {
  users: { user_id: "bigint", registered_at: "bigint", lang: "character varying", link: "character varying", file_mode: "boolean" },
  video_details: {
    pk_id: "bigint", platform: "character varying", platform_video_id: "character varying",
    creator_username: "character varying", content_type: "character varying", canonical_link: "text",
    telegram_bot_id: "bigint", telegram_files: "jsonb", likes_display: "character varying",
    views_display: "character varying", first_downloaded_at: "bigint", last_used_at: "bigint",
    metadata_refreshed_at: "bigint", file_ids_updated_at: "bigint", cache_version: "bigint",
  },
  videos: {
    pk_id: "bigint", user_id: "bigint", video_details_id: "bigint", downloaded_at: "bigint",
    shared_link: "text", media_kind: "character varying", delivery_surface: "character varying",
    delivery_mode: "character varying", cache_hit: "boolean",
  },
  music: { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_id: "bigint" },
};

/**
 * Initialize a new database or validate the post-rebuild schema.
 *
 * Deliberately do not start a legacy rebuild here. The confirmed startup path
 * prepares its online bridge first and only then allows the bot to initialize.
 */
export async function runMigrations(sql: SQL, options: RunMigrationsOptions = {}): Promise<void> {
  const existing = await columnsFor(sql, ["users", "videos", "music", "video_details"]);
  const videos = existing.get("videos");
  if (videos?.has("video_link") || videos?.has("is_images") || videos?.has("is_processed") || videos?.has("is_inline")) {
    if (options.allowLegacyMigration) {
      validateOnlineMigrationSchema(existing);
      return;
    }
    throw new Error(
      `Legacy videos schema detected. Create a verified backup, then run: ${LEGACY_MIGRATION_COMMAND}`,
    );
  }

  await sql`CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR PRIMARY KEY,
    applied_at BIGINT NOT NULL
  )`;
  await sql`CREATE TABLE IF NOT EXISTS migration_audit (
    migration_id VARCHAR PRIMARY KEY,
    started_at BIGINT NOT NULL,
    completed_at BIGINT,
    status VARCHAR NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb
  )`;
  await sql`CREATE TABLE IF NOT EXISTS legacy_migration_state (
    migration_id VARCHAR NOT NULL,
    phase VARCHAR NOT NULL,
    last_pk BIGINT NOT NULL DEFAULT 0,
    counters JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at BIGINT NOT NULL,
    PRIMARY KEY (migration_id, phase)
  )`;
  await sql`CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    registered_at BIGINT,
    lang VARCHAR NOT NULL DEFAULT 'en',
    link VARCHAR,
    file_mode BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await createTelegramFilesValidator(sql);
  await sql`CREATE TABLE IF NOT EXISTS video_details (
    pk_id BIGSERIAL PRIMARY KEY,
    platform VARCHAR NOT NULL CHECK (platform IN ('tiktok', 'instagram')),
    platform_video_id VARCHAR NOT NULL,
    creator_username VARCHAR,
    content_type VARCHAR,
    canonical_link TEXT,
    telegram_bot_id BIGINT,
    telegram_files JSONB,
    likes_display VARCHAR,
    views_display VARCHAR,
    first_downloaded_at BIGINT,
    last_used_at BIGINT,
    metadata_refreshed_at BIGINT,
    file_ids_updated_at BIGINT,
    cache_version BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT video_details_platform_id_key UNIQUE (platform, platform_video_id),
    CONSTRAINT video_details_telegram_pair_check CHECK ((telegram_bot_id IS NULL) = (telegram_files IS NULL)),
    CONSTRAINT video_details_telegram_files_check CHECK (is_valid_telegram_files(telegram_files))
  )`;
  await sql`CREATE INDEX IF NOT EXISTS video_details_last_used_idx ON video_details (last_used_at DESC)`;
  await sql`CREATE TABLE IF NOT EXISTS videos (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    video_details_id BIGINT REFERENCES video_details(pk_id),
    downloaded_at BIGINT,
    shared_link TEXT NOT NULL,
    media_kind VARCHAR NOT NULL CHECK (media_kind IN ('video', 'images')),
    delivery_surface VARCHAR NOT NULL CHECK (delivery_surface IN ('chat', 'inline')),
    delivery_mode VARCHAR CHECK (delivery_mode IN ('media', 'document')),
    cache_hit BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await sql`CREATE INDEX IF NOT EXISTS videos_user_downloaded_idx ON videos (user_id, downloaded_at DESC)`;
  await sql`CREATE INDEX IF NOT EXISTS videos_downloaded_brin_idx ON videos USING BRIN (downloaded_at)`;
  await sql`CREATE INDEX IF NOT EXISTS videos_details_idx ON videos (video_details_id) WHERE video_details_id IS NOT NULL`;
  await createRecordDownloadHistoryFunction(sql);
  await sql`CREATE TABLE IF NOT EXISTS music (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    downloaded_at BIGINT,
    video_id BIGINT NOT NULL
  )`;

  const found = await columnsFor(sql, Object.keys(expectedColumns));
  validateColumns(found);
  const removedUserColumns = ["ad_count", "ad_cooldown"].filter((column) => found.get("users")?.has(column));
  if (removedUserColumns.length) {
    throw new Error(`Database users table still has legacy columns (${removedUserColumns.join(", ")}); run ${LEGACY_MIGRATION_COMMAND}`);
  }
  await sql`INSERT INTO schema_migrations (version, applied_at)
    VALUES (${MEDIA_CACHE_SCHEMA_VERSION}, ${Math.floor(Date.now() / 1000)})
    ON CONFLICT (version) DO NOTHING`;
}

/**
 * Keep one stable history-write API while the physical videos table is swapped.
 * The shared transaction lock prevents a call from choosing a schema on one
 * side of the cutover and executing on the other side.
 */
export async function createRecordDownloadHistoryFunction(sql: SQL): Promise<void> {
  await sql.unsafe(`CREATE OR REPLACE FUNCTION record_download_history(
  requested_user_id BIGINT,
  requested_video_details_id BIGINT,
  requested_downloaded_at BIGINT,
  requested_shared_link TEXT,
  requested_media_kind VARCHAR,
  requested_delivery_surface VARCHAR,
  requested_delivery_mode VARCHAR,
  requested_cache_hit BOOLEAN
)
RETURNS VOID
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
  legacy_schema BOOLEAN;
  inserted_pk BIGINT;
BEGIN
  PERFORM pg_advisory_xact_lock_shared(hashtextextended('${HISTORY_CUTOVER_LOCK_KEY}', 0));
  SELECT EXISTS (
    SELECT 1 FROM pg_attribute
    WHERE attrelid = 'public.videos'::regclass AND attname = 'video_link' AND NOT attisdropped
  ) INTO legacy_schema;

  IF legacy_schema THEN
    INSERT INTO videos (user_id, downloaded_at, video_link, is_images, is_processed, is_inline)
    VALUES (
      requested_user_id, requested_downloaded_at, requested_shared_link,
      requested_media_kind = 'images', FALSE, requested_delivery_surface = 'inline'
    )
    RETURNING pk_id INTO inserted_pk;

    -- The legacy row cannot represent these final-schema fields. Its sync
    -- trigger creates the shadow row in the same transaction, so enrich it now.
    UPDATE videos_new SET
      video_details_id = requested_video_details_id,
      delivery_mode = requested_delivery_mode,
      cache_hit = requested_cache_hit
    WHERE pk_id = inserted_pk;
  ELSE
    INSERT INTO videos (
      user_id, video_details_id, downloaded_at, shared_link,
      media_kind, delivery_surface, delivery_mode, cache_hit
    ) VALUES (
      requested_user_id, requested_video_details_id, requested_downloaded_at, requested_shared_link,
      requested_media_kind, requested_delivery_surface, requested_delivery_mode, requested_cache_hit
    );
  END IF;
END
$function$`);
}

export async function createTelegramFilesValidator(sql: SQL): Promise<void> {
  await sql.unsafe(`CREATE OR REPLACE FUNCTION is_valid_telegram_files(value JSONB)
RETURNS BOOLEAN
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $function$
DECLARE
  item JSONB;
  expected_position INTEGER := 0;
BEGIN
  IF value IS NULL THEN RETURN TRUE; END IF;
  IF jsonb_typeof(value) IS DISTINCT FROM 'array' THEN RETURN FALSE; END IF;
  IF jsonb_array_length(value) = 0 THEN RETURN FALSE; END IF;
  FOR item IN SELECT element FROM jsonb_array_elements(value) AS entries(element) LOOP
    IF jsonb_typeof(item) IS DISTINCT FROM 'object' THEN RETURN FALSE; END IF;
    IF jsonb_typeof(item->'position') IS DISTINCT FROM 'number'
      OR item->>'position' IS DISTINCT FROM expected_position::TEXT
      OR COALESCE(item->>'media_type', '') NOT IN ('photo', 'video')
      OR jsonb_typeof(item->'file_id') IS DISTINCT FROM 'string'
      OR COALESCE(length(item->>'file_id'), 0) = 0
      OR jsonb_typeof(item->'file_unique_id') IS DISTINCT FROM 'string'
      OR COALESCE(length(item->>'file_unique_id'), 0) = 0
    THEN RETURN FALSE; END IF;
    expected_position := expected_position + 1;
  END LOOP;
  RETURN TRUE;
END
$function$`);
}

async function columnsFor(sql: SQL, tables: string[]): Promise<Map<string, Map<string, string>>> {
  const rows = await sql<Array<{ table_name: string; column_name: string; data_type: string }>>`
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name IN ('users', 'videos', 'music', 'video_details')
  `;
  const found = new Map<string, Map<string, string>>();
  for (const row of rows) {
    if (!tables.includes(row.table_name)) continue;
    const columns = found.get(row.table_name) ?? new Map<string, string>();
    columns.set(row.column_name, row.data_type);
    found.set(row.table_name, columns);
  }
  return found;
}

function validateOnlineMigrationSchema(found: Map<string, Map<string, string>>): void {
  for (const table of ["users", "video_details", "music"]) {
    const expected = expectedColumns[table]!;
    const actual = found.get(table) ?? new Map<string, string>();
    const missing = Object.keys(expected).filter((column) => !actual.has(column));
    if (missing.length) {
      throw new Error(`Online legacy migration is not ready; database table ${table} is missing columns: ${missing.join(", ")}`);
    }
    const mismatched = Object.entries(expected).filter(([column, type]) => actual.get(column) !== type);
    if (mismatched.length) {
      throw new Error(`Online legacy migration has incompatible ${table} column types: ${mismatched.map(([column, type]) => `${column}=${actual.get(column)} (expected ${type})`).join(", ")}`);
    }
  }
}

function validateColumns(found: Map<string, Map<string, string>>): void {
  for (const [table, columns] of Object.entries(expectedColumns)) {
    const actual = found.get(table) ?? new Map<string, string>();
    const missing = Object.keys(columns).filter((column) => !actual.has(column));
    if (missing.length) throw new Error(`Database table ${table} is missing columns: ${missing.join(", ")}`);
    const mismatched = Object.entries(columns).filter(([column, expected]) => actual.get(column) !== expected);
    if (mismatched.length) {
      throw new Error(`Database table ${table} has incompatible column types: ${mismatched.map(([column, expected]) => `${column}=${actual.get(column)} (expected ${expected})`).join(", ")}`);
    }
  }
}
