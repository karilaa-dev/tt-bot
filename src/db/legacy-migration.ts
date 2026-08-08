import { SQL, type SQL as SQLType } from "bun";
import { createTelegramFilesValidator, MEDIA_CACHE_SCHEMA_VERSION } from "./migrations.ts";

export const LEGACY_REBUILD_MIGRATION_ID = "002_media_cache_rebuild";
const DEFAULT_BATCH_SIZE = 100_000;
const ADVISORY_LOCK_KEY = "tt-bot:002-media-cache-rebuild";

export interface LegacyMigrationOptions {
  backupConfirmed: boolean;
  botStopped: boolean;
  availableBytes: bigint;
  batchSize?: number;
  /** Test hook: return after a committed phase without cutting over. */
  stopAfterPhase?: "audit" | "identity" | "details" | "copy" | "constraints" | "verification";
  /** Test hook for proving in-phase resumption after committed batches. */
  maxBatchesPerPhaseRun?: number;
  onProgress?: (message: string) => void;
}

export interface LegacyMigrationResult {
  status: "complete" | "paused";
  phase: string;
  evidence: Record<string, unknown>;
}

interface StateRow { last_pk: bigint | string; counters: Record<string, unknown> | string }
interface BoundaryRow { end_pk: bigint | string | null }
interface EvidenceRow { status: string; evidence: Record<string, unknown> | string }
type MigrationConnection = Awaited<ReturnType<SQLType["reserve"]>>;

export async function runLegacyMigration(databaseUrl: string, options: LegacyMigrationOptions): Promise<LegacyMigrationResult> {
  if (!options.backupConfirmed) throw new Error("Refusing migration: a completed and verified external backup must be confirmed");
  if (!options.botStopped) throw new Error("Refusing migration: confirm that the bot and legacy stats processes are stopped");
  if (options.availableBytes <= 0n) throw new Error("Refusing migration: available database-filesystem bytes must be supplied");
  const batchSize = options.batchSize ?? DEFAULT_BATCH_SIZE;
  if (!Number.isSafeInteger(batchSize) || batchSize <= 0) throw new Error("Migration batch size must be a positive integer");
  const progress = options.onProgress ?? (() => undefined);
  const sql = new SQL({ url: databaseUrl, max: 4, idleTimeout: 60, connectionTimeout: 15, maxLifetime: 0 });
  const lock = await sql.reserve();
  try {
    const acquired = await lock<Array<{ locked: boolean }>>`SELECT pg_try_advisory_lock(hashtextextended(${ADVISORY_LOCK_KEY}, 0)) AS locked`;
    if (!acquired[0]?.locked) throw new Error("Another legacy migration holds the PostgreSQL advisory lock");
    // Run every phase on the reserved session that owns the advisory lock. If
    // that session is lost, the migration fails with it instead of continuing
    // on another pooled connection after PostgreSQL has released the lock.
    return await migrate(lock, options, batchSize, progress);
  } finally {
    try { await lock`SELECT pg_advisory_unlock(hashtextextended(${ADVISORY_LOCK_KEY}, 0))`; } catch { /* connection may already be gone */ }
    await lock.release();
    await sql.close();
  }
}

async function migrate(sql: MigrationConnection, options: LegacyMigrationOptions, batchSize: number, progress: (message: string) => void): Promise<LegacyMigrationResult> {
  const shape = await sql<Array<{ column_name: string; data_type: string }>>`SELECT column_name, data_type
    FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'`;
  const columns = new Map(shape.map((row) => [row.column_name, row.data_type]));
  const legacy = columns.has("video_link") && columns.has("is_images") && columns.has("is_processed") && columns.has("is_inline");
  const final = columns.has("shared_link") && columns.has("video_details_id") && columns.has("media_kind");
  if (final && !legacy) {
    const completed = await completedEvidence(sql);
    if (!completed) throw new Error("Final videos schema exists but the legacy migration has no completed audit row");
    return { status: "complete", phase: "cutover", evidence: completed };
  }
  if (!legacy) throw new Error("The videos table does not match the inspected v5.4.6 legacy schema");
  await validateLegacyShape(sql);
  await createControlTables(sql);
  const conflicting = await sql<Array<{ migration_id: string }>>`SELECT migration_id FROM migration_audit
    WHERE migration_id <> ${LEGACY_REBUILD_MIGRATION_ID} AND status NOT IN ('complete', 'failed') LIMIT 1`;
  if (conflicting.length) throw new Error(`Conflicting incomplete migration: ${conflicting[0]!.migration_id}`);
  const sizes = await sql<Array<{ source_bytes: bigint | string }>>`SELECT pg_total_relation_size('public.videos')::bigint AS source_bytes`;
  const sourceBytes = BigInt(sizes[0]?.source_bytes ?? 0);
  const requiredBytes = sourceBytes * 4n;
  if (options.availableBytes < requiredBytes) {
    throw new Error(`Insufficient confirmed free space: ${options.availableBytes} bytes available, at least ${requiredBytes} required`);
  }
  const now = Math.floor(Date.now() / 1000);
  await sql`INSERT INTO migration_audit (migration_id, started_at, status, evidence)
    VALUES (${LEGACY_REBUILD_MIGRATION_ID}, ${now}, 'running', jsonb_build_object(
      'source_relation_bytes', ${sourceBytes.toString()}::text, 'required_free_bytes', ${requiredBytes.toString()}::text,
      'confirmed_available_bytes', ${options.availableBytes.toString()}::text, 'batch_size', ${batchSize}::integer
    )) ON CONFLICT (migration_id) DO NOTHING`;

  let evidence = await auditEvidence(sql);
  if (!("source_audit" in evidence)) {
    progress("Running exact source audit (one full server-side scan)");
    const source = await sourceAudit(sql);
    const user = await userAudit(sql);
    await mergeEvidence(sql, { source_audit: source, removed_user_columns: user });
    evidence = await auditEvidence(sql);
  }
  if (options.stopAfterPhase === "audit") return paused("audit", evidence);

  const upperPk = BigInt(readObject(evidence.source_audit).max_pk as string);
  await createIdentityParser(sql);
  await sql`CREATE TABLE IF NOT EXISTS legacy_video_identity (
    legacy_pk BIGINT PRIMARY KEY,
    platform VARCHAR NOT NULL,
    platform_video_id VARCHAR NOT NULL,
    url_content_type VARCHAR,
    legacy_content_type VARCHAR NOT NULL,
    canonical_candidate TEXT
  )`;
  const identityComplete = await runIdentityBatches(sql, upperPk, batchSize, progress, options.maxBatchesPerPhaseRun);
  if (!identityComplete) return paused("identity", await auditEvidence(sql));
  await sql`CREATE INDEX IF NOT EXISTS legacy_video_identity_platform_id_idx
    ON legacy_video_identity (platform, platform_video_id)`;
  const identity = await identityAudit(sql);
  await mergeEvidence(sql, { identity });
  if (options.stopAfterPhase === "identity") return paused("identity", await auditEvidence(sql));

  await createTelegramFilesValidator(sql);
  await createVideoDetails(sql);
  if (!await phaseComplete(sql, "details")) {
    progress("Building locally recoverable legacy video details");
    await buildLegacyDetails(sql);
    await markPhase(sql, "details", upperPk, {});
  }
  if (options.stopAfterPhase === "details") return paused("details", await auditEvidence(sql));

  await createVideosNew(sql);
  const copyComplete = await runCopyBatches(sql, upperPk, batchSize, progress, options.maxBatchesPerPhaseRun);
  if (!copyComplete) return paused("copy", await auditEvidence(sql));
  if (options.stopAfterPhase === "copy") return paused("copy", await auditEvidence(sql));

  if (!await phaseComplete(sql, "constraints")) {
    progress("Building indexes and validating final constraints");
    await buildFinalConstraints(sql);
    await markPhase(sql, "constraints", upperPk, {});
  }
  if (options.stopAfterPhase === "constraints") return paused("constraints", await auditEvidence(sql));

  progress("Verifying exact source/destination aggregates");
  const verification = await verifyRebuild(sql, evidence);
  await mergeEvidence(sql, { verification });
  await markPhase(sql, "verification", upperPk, verification);
  if (options.stopAfterPhase === "verification") return paused("verification", await auditEvidence(sql));

  progress("Performing atomic cutover and dropping the verified legacy table");
  await cutover(sql, evidence, upperPk);
  return { status: "complete", phase: "cutover", evidence: await auditEvidence(sql) };
}

async function validateLegacyShape(sql: SQLType): Promise<void> {
  const required: Record<string, string[]> = {
    videos: ["pk_id", "user_id", "downloaded_at", "video_link", "is_images", "is_processed", "is_inline"],
    // ad_count/ad_cooldown existed in the Python schema but not in databases
    // created by the TypeScript bot. Audit either column when it is present,
    // while allowing both legacy variants to use the same offline rebuild.
    users: ["user_id", "registered_at", "lang", "link", "file_mode"],
    music: ["pk_id", "user_id", "downloaded_at", "video_id"],
  };
  const rows = await sql<Array<{ table_name: string; column_name: string }>>`SELECT table_name, column_name FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name IN ('videos', 'users', 'music')`;
  for (const [table, names] of Object.entries(required)) {
    const found = new Set(rows.filter((row) => row.table_name === table).map((row) => row.column_name));
    const missing = names.filter((name) => !found.has(name));
    if (missing.length) throw new Error(`Legacy ${table} table is missing required columns: ${missing.join(", ")}`);
  }
  const sequence = await sql<Array<{ name: string | null }>>`SELECT to_regclass('public.videos_pk_id_seq')::text AS name`;
  if (!sequence[0]?.name) throw new Error("Legacy videos_pk_id_seq sequence was not found");
}

async function createControlTables(sql: SQLType): Promise<void> {
  await sql`CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY, applied_at BIGINT NOT NULL)`;
  await sql`CREATE TABLE IF NOT EXISTS migration_audit (
    migration_id VARCHAR PRIMARY KEY, started_at BIGINT NOT NULL, completed_at BIGINT,
    status VARCHAR NOT NULL, evidence JSONB NOT NULL DEFAULT '{}'::jsonb
  )`;
  await sql`CREATE TABLE IF NOT EXISTS legacy_migration_state (
    migration_id VARCHAR NOT NULL, phase VARCHAR NOT NULL, last_pk BIGINT NOT NULL DEFAULT 0,
    counters JSONB NOT NULL DEFAULT '{}'::jsonb, updated_at BIGINT NOT NULL,
    PRIMARY KEY (migration_id, phase)
  )`;
}

async function sourceAudit(sql: SQLType): Promise<Record<string, string>> {
  const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*)::text AS row_count,
      COALESCE(MIN(pk_id), 0)::text AS min_pk,
      COALESCE(MAX(pk_id), 0)::text AS max_pk,
      COUNT(*) FILTER (WHERE is_processed)::text AS processed_true_count,
      COUNT(*) FILTER (WHERE is_images)::text AS images_true_count,
      COUNT(*) FILTER (WHERE is_inline)::text AS inline_true_count,
      COUNT(*) FILTER (WHERE downloaded_at IS NULL)::text AS downloaded_at_null_count,
      COUNT(*) FILTER (WHERE video_link IS NULL)::text AS video_link_null_count,
      COALESCE(SUM(pk_id::numeric), 0)::text AS pk_sum,
      COALESCE(SUM(user_id::numeric), 0)::text AS user_id_sum,
      COALESCE(SUM(COALESCE(downloaded_at, 0)::numeric), 0)::text AS downloaded_at_sum,
      COALESCE(SUM(hashtextextended(jsonb_build_array(
        pk_id, user_id, downloaded_at, video_link,
        CASE WHEN is_images THEN 'images' ELSE 'video' END,
        CASE WHEN is_inline THEN 'inline' ELSE 'chat' END,
        NULL, FALSE
      )::text, 0)::numeric), 0)::text AS row_fingerprint,
      COALESCE(MAX(length(video_link)), 0)::text AS max_shared_link_length
    FROM videos`;
  return rows[0] ?? {};
}

async function userAudit(sql: SQLType): Promise<Record<string, string>> {
  const columns = await sql<Array<{ column_name: string }>>`SELECT column_name
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users'
      AND column_name IN ('ad_count', 'ad_cooldown')`;
  const present = new Set(columns.map((row) => row.column_name));
  const hasAdCount = present.has("ad_count");
  const hasAdCooldown = present.has("ad_cooldown");
  let counts: Record<string, string>;
  if (hasAdCount && hasAdCooldown) {
    const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*) FILTER (WHERE ad_count <> 0)::text AS nonzero_ad_count,
      COUNT(*) FILTER (WHERE ad_cooldown <> 0)::text AS nonzero_ad_cooldown_count
      FROM users`;
    counts = rows[0] ?? {};
  } else if (hasAdCount) {
    const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*) FILTER (WHERE ad_count <> 0)::text AS nonzero_ad_count,
      '0'::text AS nonzero_ad_cooldown_count FROM users`;
    counts = rows[0] ?? {};
  } else if (hasAdCooldown) {
    const rows = await sql<Array<Record<string, string>>>`SELECT
      '0'::text AS nonzero_ad_count,
      COUNT(*) FILTER (WHERE ad_cooldown <> 0)::text AS nonzero_ad_cooldown_count
      FROM users`;
    counts = rows[0] ?? {};
  } else {
    counts = { nonzero_ad_count: "0", nonzero_ad_cooldown_count: "0" };
  }
  return {
    ...counts,
    ad_count_column_present: String(hasAdCount),
    ad_cooldown_column_present: String(hasAdCooldown),
  };
}

async function createIdentityParser(sql: SQLType): Promise<void> {
  await sql.unsafe(`CREATE OR REPLACE FUNCTION parse_legacy_video_identity(value TEXT)
RETURNS TABLE(platform VARCHAR, platform_video_id VARCHAR, url_content_type VARCHAR, canonical_candidate TEXT, conflict BOOLEAN)
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $function$
DECLARE
  parsed TEXT[]; host TEXT; path TEXT; query TEXT; path_id TEXT; query_id TEXT; second_query_id TEXT; kind TEXT;
BEGIN
  platform := NULL; platform_video_id := NULL; url_content_type := NULL; canonical_candidate := NULL; conflict := FALSE;
  parsed := regexp_match(value, '^https?://([^/?#]+)(/[^?#]*)?(?:[?]([^#]*))?', 'i');
  IF parsed IS NULL THEN RETURN NEXT; RETURN; END IF;
  host := lower(split_part(parsed[1], ':', 1)); path := COALESCE(parsed[2], '/'); query := COALESCE(parsed[3], '');
  IF host = 'tiktok.com' OR host ~ '[.]tiktok[.]com$' THEN
    parsed := regexp_match(path, '^/@[^/]+/(video|photo)/([0-9]+)(?:/|$)', 'i');
    IF parsed IS NOT NULL THEN kind := CASE WHEN lower(parsed[1]) = 'photo' THEN 'images' ELSE 'video' END; path_id := parsed[2]; END IF;
    IF path_id IS NULL THEN parsed := regexp_match(path, '^/v/([0-9]+)(?:[.]html)?(?:/|$)', 'i'); IF parsed IS NOT NULL THEN path_id := parsed[1]; kind := 'video'; END IF; END IF;
    IF path_id IS NULL THEN parsed := regexp_match(path, '^/embed/(?:v2/)?([0-9]+)(?:/|$)', 'i'); IF parsed IS NOT NULL THEN path_id := parsed[1]; kind := 'video'; END IF; END IF;
    IF path_id IS NULL THEN parsed := regexp_match(path, '^/player/v1/([0-9]+)(?:/|$)', 'i'); IF parsed IS NOT NULL THEN path_id := parsed[1]; kind := 'video'; END IF; END IF;
    IF path_id IS NULL THEN parsed := regexp_match(path, '^/share/(video|item)/([0-9]+)(?:/|$)', 'i'); IF parsed IS NOT NULL THEN path_id := parsed[2]; kind := CASE WHEN lower(parsed[1]) = 'video' THEN 'video' ELSE NULL END; END IF; END IF;
    parsed := regexp_match('&' || query || '&', '&item_id=([0-9]+)&', 'i'); IF parsed IS NOT NULL THEN query_id := parsed[1]; END IF;
    parsed := regexp_match('&' || query || '&', '&share_item_id=([0-9]+)&', 'i'); IF parsed IS NOT NULL THEN second_query_id := parsed[1]; END IF;
    IF query_id IS NOT NULL AND second_query_id IS NOT NULL AND query_id <> second_query_id THEN conflict := TRUE; RETURN NEXT; RETURN; END IF;
    query_id := COALESCE(query_id, second_query_id);
    IF path_id IS NOT NULL AND query_id IS NOT NULL AND path_id <> query_id THEN conflict := TRUE; RETURN NEXT; RETURN; END IF;
    platform_video_id := COALESCE(path_id, query_id);
    IF platform_video_id IS NULL THEN RETURN NEXT; RETURN; END IF;
    platform := 'tiktok'; url_content_type := kind;
    IF kind IS NOT NULL THEN canonical_candidate := 'https://www.tiktok.com/@_/' || CASE WHEN kind = 'images' THEN 'photo' ELSE 'video' END || '/' || platform_video_id; END IF;
    RETURN NEXT; RETURN;
  END IF;
  IF host = 'instagram.com' OR host ~ '[.]instagram[.]com$' THEN
    parsed := regexp_match(path, '^/(p|reel|reels|tv)/([A-Za-z0-9_-]+)(?:/|$)', 'i');
    IF parsed IS NULL THEN RETURN NEXT; RETURN; END IF;
    platform := 'instagram'; platform_video_id := parsed[2];
    kind := lower(parsed[1]); IF kind = 'reels' THEN kind := 'reel'; END IF;
    IF kind IN ('reel', 'tv') THEN url_content_type := 'video'; END IF;
    canonical_candidate := 'https://www.instagram.com/' || kind || '/' || platform_video_id || '/';
    RETURN NEXT; RETURN;
  END IF;
  RETURN NEXT;
END
$function$`);
}

async function runIdentityBatches(sql: SQLType, upperPk: bigint, batchSize: number, progress: (message: string) => void, maxBatches?: number): Promise<boolean> {
  let state = await stateFor(sql, "identity");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (maxBatches !== undefined && batchesThisRun >= maxBatches) return false;
    const boundary = await sql<BoundaryRow[]>`SELECT MAX(pk_id) AS end_pk FROM (
      SELECT pk_id FROM videos WHERE pk_id > ${lastPk} AND pk_id <= ${upperPk} ORDER BY pk_id LIMIT ${batchSize}
    ) batch`;
    if (boundary[0]?.end_pk === null || boundary[0]?.end_pk === undefined) break;
    const endPk = BigInt(boundary[0].end_pk);
    await sql.begin(async (tx) => {
      const metrics = await tx<Array<{ total: number | string; parsed: number | string; conflicts: number | string }>>`WITH classified AS (
          SELECT v.pk_id, v.is_images, p.* FROM videos v
          CROSS JOIN LATERAL parse_legacy_video_identity(v.video_link) p
          WHERE v.pk_id > ${lastPk} AND v.pk_id <= ${endPk}
        ), inserted AS (
          INSERT INTO legacy_video_identity (legacy_pk, platform, platform_video_id, url_content_type, legacy_content_type, canonical_candidate)
          SELECT pk_id, platform, platform_video_id, url_content_type,
            CASE WHEN is_images THEN 'images' ELSE 'video' END, canonical_candidate
          FROM classified WHERE platform IS NOT NULL AND NOT conflict
          ON CONFLICT (legacy_pk) DO NOTHING RETURNING 1
        ) SELECT COUNT(*) AS total,
          COUNT(*) FILTER (WHERE platform IS NOT NULL AND NOT conflict) AS parsed,
          COUNT(*) FILTER (WHERE conflict) AS conflicts FROM classified`;
      const metric = metrics[0]!;
      counters = {
        total: counters.total + Number(metric.total), parsed: counters.parsed + Number(metric.parsed),
        conflicts: counters.conflicts + Number(metric.conflicts), batches: counters.batches + 1,
      };
      await upsertState(tx, "identity", endPk, counters);
    });
    lastPk = endPk;
    batchesThisRun++;
    progress(`Identity phase: completed through pk ${lastPk}`);
  }
  await upsertState(sql, "identity", lastPk, { ...counters, complete: true });
  return true;
}

async function identityAudit(sql: SQLType): Promise<Record<string, string>> {
  const state = await stateFor(sql, "identity");
  const counters = numberCounters(state?.counters);
  const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*)::text AS staged_rows,
      COUNT(DISTINCT platform_video_id) FILTER (WHERE platform = 'tiktok')::text AS distinct_tiktok_ids,
      COUNT(DISTINCT platform_video_id) FILTER (WHERE platform = 'instagram')::text AS distinct_instagram_ids
    FROM legacy_video_identity`;
  return { ...(rows[0] ?? {}), scanned_rows: String(counters.total), parsed_rows: String(counters.parsed), unresolved_rows: String(counters.total - counters.parsed), conflict_rows: String(counters.conflicts) };
}

async function createVideoDetails(sql: SQLType): Promise<void> {
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
}

async function buildLegacyDetails(sql: SQLType): Promise<void> {
  await sql`INSERT INTO video_details (
      platform, platform_video_id, content_type, canonical_link, first_downloaded_at, last_used_at
    ) SELECT i.platform, i.platform_video_id,
      CASE
        WHEN COUNT(DISTINCT i.legacy_content_type) = 1
          AND NOT BOOL_OR(i.url_content_type IS NOT NULL AND i.url_content_type <> i.legacy_content_type)
        THEN CASE
          WHEN i.platform = 'tiktok' AND MIN(i.legacy_content_type) = 'images' THEN 'slideshow'
          WHEN i.platform = 'instagram' AND MIN(i.legacy_content_type) = 'images' THEN 'image'
          ELSE 'video'
        END
        ELSE NULL
      END,
      CASE WHEN COUNT(DISTINCT i.canonical_candidate) FILTER (WHERE i.canonical_candidate IS NOT NULL) = 1
        AND NOT BOOL_OR(i.url_content_type IS NOT NULL AND i.url_content_type <> i.legacy_content_type)
        THEN MIN(i.canonical_candidate) ELSE NULL END,
      MIN(v.downloaded_at), MAX(v.downloaded_at)
    FROM legacy_video_identity i JOIN videos v ON v.pk_id = i.legacy_pk
    GROUP BY i.platform, i.platform_video_id
    ON CONFLICT (platform, platform_video_id) DO UPDATE SET
      first_downloaded_at = LEAST(video_details.first_downloaded_at, EXCLUDED.first_downloaded_at),
      last_used_at = GREATEST(video_details.last_used_at, EXCLUDED.last_used_at)`;
  await sql`CREATE INDEX IF NOT EXISTS video_details_last_used_idx ON video_details (last_used_at DESC)`;
}

async function createVideosNew(sql: SQLType): Promise<void> {
  await sql`CREATE TABLE IF NOT EXISTS videos_new (
    pk_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    video_details_id BIGINT,
    downloaded_at BIGINT,
    shared_link TEXT NOT NULL,
    media_kind VARCHAR NOT NULL,
    delivery_surface VARCHAR NOT NULL,
    delivery_mode VARCHAR,
    cache_hit BOOLEAN NOT NULL DEFAULT FALSE
  )`;
}

async function runCopyBatches(sql: SQLType, upperPk: bigint, batchSize: number, progress: (message: string) => void, maxBatches?: number): Promise<boolean> {
  const state = await stateFor(sql, "copy");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (maxBatches !== undefined && batchesThisRun >= maxBatches) return false;
    const boundary = await sql<BoundaryRow[]>`SELECT MAX(pk_id) AS end_pk FROM (
      SELECT pk_id FROM videos WHERE pk_id > ${lastPk} AND pk_id <= ${upperPk} ORDER BY pk_id LIMIT ${batchSize}
    ) batch`;
    if (boundary[0]?.end_pk === null || boundary[0]?.end_pk === undefined) break;
    const endPk = BigInt(boundary[0].end_pk);
    await sql.begin(async (tx) => {
      const inserted = await tx<Array<{ count: number | string }>>`WITH copied AS (
        INSERT INTO videos_new (pk_id, user_id, video_details_id, downloaded_at, shared_link, media_kind, delivery_surface, delivery_mode, cache_hit)
        SELECT v.pk_id, v.user_id, d.pk_id, v.downloaded_at, v.video_link,
          CASE WHEN v.is_images THEN 'images' ELSE 'video' END,
          CASE WHEN v.is_inline THEN 'inline' ELSE 'chat' END,
          NULL, FALSE
        FROM videos v
        LEFT JOIN legacy_video_identity i ON i.legacy_pk = v.pk_id
        LEFT JOIN video_details d ON d.platform = i.platform AND d.platform_video_id = i.platform_video_id
        WHERE v.pk_id > ${lastPk} AND v.pk_id <= ${endPk}
        ON CONFLICT DO NOTHING RETURNING 1
      ) SELECT COUNT(*) AS count FROM copied`;
      counters = { ...counters, total: counters.total + Number(inserted[0]?.count ?? 0), batches: counters.batches + 1 };
      await upsertState(tx, "copy", endPk, counters);
    });
    lastPk = endPk;
    batchesThisRun++;
    progress(`Copy phase: completed through pk ${lastPk}`);
  }
  await upsertState(sql, "copy", lastPk, { ...counters, complete: true });
  return true;
}

async function buildFinalConstraints(sql: SQLType): Promise<void> {
  await ensureConstraint(sql, "videos_new_pkey");
  await ensureConstraint(sql, "videos_new_media_kind_check");
  await ensureConstraint(sql, "videos_new_delivery_surface_check");
  await ensureConstraint(sql, "videos_new_delivery_mode_check");
  await ensureConstraint(sql, "videos_new_user_id_fkey");
  await ensureConstraint(sql, "videos_new_video_details_id_fkey");
  await sql`ALTER TABLE videos_new VALIDATE CONSTRAINT videos_new_media_kind_check`;
  await sql`ALTER TABLE videos_new VALIDATE CONSTRAINT videos_new_delivery_surface_check`;
  await sql`ALTER TABLE videos_new VALIDATE CONSTRAINT videos_new_delivery_mode_check`;
  await sql`ALTER TABLE videos_new VALIDATE CONSTRAINT videos_new_user_id_fkey`;
  await sql`ALTER TABLE videos_new VALIDATE CONSTRAINT videos_new_video_details_id_fkey`;
  await sql`CREATE INDEX IF NOT EXISTS videos_new_user_downloaded_idx ON videos_new (user_id, downloaded_at DESC)`;
  await sql`CREATE INDEX IF NOT EXISTS videos_new_downloaded_brin_idx ON videos_new USING BRIN (downloaded_at)`;
  await sql`CREATE INDEX IF NOT EXISTS videos_new_details_idx ON videos_new (video_details_id) WHERE video_details_id IS NOT NULL`;
  await sql`ANALYZE video_details`;
  await sql`ANALYZE videos_new`;
}

async function verifyRebuild(sql: SQLType, evidence: Record<string, unknown>): Promise<Record<string, string>> {
  const source = readObject(evidence.source_audit) as Record<string, string>;
  const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*)::text AS row_count, COALESCE(MIN(pk_id), 0)::text AS min_pk, COALESCE(MAX(pk_id), 0)::text AS max_pk,
      COALESCE(SUM(pk_id::numeric), 0)::text AS pk_sum,
      COALESCE(SUM(user_id::numeric), 0)::text AS user_id_sum,
      COALESCE(SUM(COALESCE(downloaded_at, 0)::numeric), 0)::text AS downloaded_at_sum,
      COALESCE(SUM(hashtextextended(jsonb_build_array(pk_id, user_id, downloaded_at, shared_link, media_kind, delivery_surface, delivery_mode, cache_hit)::text, 0)::numeric), 0)::text AS row_fingerprint,
      COUNT(*) FILTER (WHERE media_kind = 'images')::text AS images_count,
      COUNT(*) FILTER (WHERE delivery_surface = 'inline')::text AS inline_count,
      COUNT(*) FILTER (WHERE video_details_id IS NOT NULL)::text AS linked_details_count
    FROM videos_new`;
  const destination = rows[0] ?? {};
  const comparisons: Array<[string, string]> = [
    ["row_count", "row_count"], ["min_pk", "min_pk"], ["max_pk", "max_pk"], ["pk_sum", "pk_sum"],
    ["user_id_sum", "user_id_sum"], ["downloaded_at_sum", "downloaded_at_sum"], ["row_fingerprint", "row_fingerprint"],
    ["images_true_count", "images_count"], ["inline_true_count", "inline_count"],
  ];
  for (const [sourceKey, destinationKey] of comparisons) {
    if (source[sourceKey] !== destination[destinationKey]) throw new Error(`Verification failed: ${sourceKey} ${source[sourceKey]} != ${destination[destinationKey]}`);
  }
  const integrity = await sql<Array<Record<string, string>>>`SELECT
      (SELECT COUNT(*) FROM videos_new v LEFT JOIN users u ON u.user_id = v.user_id WHERE u.user_id IS NULL)::text AS orphaned_users,
      (SELECT COUNT(*) FROM videos_new v LEFT JOIN video_details d ON d.pk_id = v.video_details_id WHERE v.video_details_id IS NOT NULL AND d.pk_id IS NULL)::text AS orphaned_details,
      (SELECT COUNT(*) FROM (SELECT pk_id FROM videos_new GROUP BY pk_id HAVING COUNT(*) > 1) duplicates)::text AS duplicate_primary_keys,
      (SELECT COUNT(*) FROM legacy_video_identity i LEFT JOIN video_details d ON d.platform = i.platform AND d.platform_video_id = i.platform_video_id WHERE d.pk_id IS NULL)::text AS unmapped_staged_rows,
      (SELECT COUNT(*) FROM legacy_video_identity)::text AS staged_rows`;
  const checks = integrity[0] ?? {};
  for (const key of ["orphaned_users", "orphaned_details", "duplicate_primary_keys", "unmapped_staged_rows"]) {
    if (checks[key] !== "0") throw new Error(`Verification failed: ${key}=${checks[key]}`);
  }
  if (destination.linked_details_count !== checks.staged_rows) throw new Error("Verification failed: staged identity/history detail-link count mismatch");
  return { ...destination, ...checks, verified_at: String(Math.floor(Date.now() / 1000)) };
}

async function cutover(sql: SQLType, evidence: Record<string, unknown>, upperPk: bigint): Promise<void> {
  const source = readObject(evidence.source_audit) as Record<string, string>;
  await sql.begin(async (tx) => {
    await tx`LOCK TABLE videos, videos_new, users IN ACCESS EXCLUSIVE MODE`;
    const current = await tx<Array<{ row_count: string; max_pk: string }>>`SELECT COUNT(*)::text AS row_count, COALESCE(MAX(pk_id), 0)::text AS max_pk FROM videos`;
    if (current[0]?.row_count !== source.row_count || current[0]?.max_pk !== source.max_pk || current[0]?.max_pk !== upperPk.toString()) {
      throw new Error("Source changed after verification; cutover aborted");
    }
    await tx`ALTER SEQUENCE videos_pk_id_seq OWNED BY NONE`;
    await tx`ALTER TABLE videos RENAME TO videos_legacy_002`;
    await tx`ALTER TABLE videos_new RENAME TO videos`;
    await tx`ALTER TABLE videos ALTER COLUMN pk_id SET DEFAULT nextval('videos_pk_id_seq')`;
    await tx`ALTER SEQUENCE videos_pk_id_seq OWNED BY videos.pk_id`;
    await tx`SELECT setval('videos_pk_id_seq', GREATEST(${upperPk}, 1), ${upperPk > 0n})`;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_count`;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_cooldown`;
    await tx`DROP TABLE videos_legacy_002`;
    await tx`DROP TABLE legacy_video_identity`;
    await tx`DROP FUNCTION parse_legacy_video_identity(TEXT)`;
    await tx`ALTER TABLE videos RENAME CONSTRAINT videos_new_pkey TO videos_pkey`;
    await tx`ALTER INDEX videos_new_user_downloaded_idx RENAME TO videos_user_downloaded_idx`;
    await tx`ALTER INDEX videos_new_downloaded_brin_idx RENAME TO videos_downloaded_brin_idx`;
    await tx`ALTER INDEX videos_new_details_idx RENAME TO videos_details_idx`;
    const completedAt = Math.floor(Date.now() / 1000);
    await tx`INSERT INTO schema_migrations (version, applied_at) VALUES (${MEDIA_CACHE_SCHEMA_VERSION}, ${completedAt}) ON CONFLICT (version) DO NOTHING`;
    await tx`UPDATE migration_audit SET status = 'complete', completed_at = ${completedAt},
      evidence = evidence || jsonb_build_object('cutover', jsonb_build_object('status', 'complete', 'completed_at', ${completedAt}::bigint, 'legacy_table_dropped', TRUE, 'identity_staging_dropped', TRUE))
      WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
    await upsertState(tx, "cutover", upperPk, { complete: true });
  });
}

type FinalConstraintName =
  | "videos_new_pkey"
  | "videos_new_media_kind_check"
  | "videos_new_delivery_surface_check"
  | "videos_new_delivery_mode_check"
  | "videos_new_user_id_fkey"
  | "videos_new_video_details_id_fkey";

async function ensureConstraint(sql: SQLType, name: FinalConstraintName): Promise<void> {
  const found = await sql<Array<{ found: boolean }>>`SELECT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = ${name} AND conrelid = 'public.videos_new'::regclass
  ) AS found`;
  if (found[0]?.found) return;
  switch (name) {
    case "videos_new_pkey":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_pkey PRIMARY KEY (pk_id)`;
      break;
    case "videos_new_media_kind_check":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_media_kind_check CHECK (media_kind IN ('video', 'images')) NOT VALID`;
      break;
    case "videos_new_delivery_surface_check":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_delivery_surface_check CHECK (delivery_surface IN ('chat', 'inline')) NOT VALID`;
      break;
    case "videos_new_delivery_mode_check":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_delivery_mode_check CHECK (delivery_mode IN ('media', 'document')) NOT VALID`;
      break;
    case "videos_new_user_id_fkey":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(user_id) NOT VALID`;
      break;
    case "videos_new_video_details_id_fkey":
      await sql`ALTER TABLE videos_new ADD CONSTRAINT videos_new_video_details_id_fkey FOREIGN KEY (video_details_id) REFERENCES video_details(pk_id) NOT VALID`;
      break;
  }
}

async function stateFor(sql: SQLType, phase: string): Promise<StateRow | null> {
  const rows = await sql<StateRow[]>`SELECT last_pk, counters FROM legacy_migration_state WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID} AND phase = ${phase}`;
  return rows[0] ?? null;
}

async function phaseComplete(sql: SQLType, phase: string): Promise<boolean> {
  const state = await stateFor(sql, phase);
  return readObject(state?.counters).complete === true;
}

async function markPhase(sql: SQLType, phase: string, lastPk: bigint, counters: Record<string, unknown>): Promise<void> {
  await upsertState(sql, phase, lastPk, { ...counters, complete: true });
}

async function upsertState(sql: SQLType, phase: string, lastPk: bigint, counters: Record<string, unknown>): Promise<void> {
  await sql`INSERT INTO legacy_migration_state (migration_id, phase, last_pk, counters, updated_at)
    VALUES (${LEGACY_REBUILD_MIGRATION_ID}, ${phase}, ${lastPk}, ${counters}::jsonb, ${Math.floor(Date.now() / 1000)})
    ON CONFLICT (migration_id, phase) DO UPDATE SET last_pk = EXCLUDED.last_pk, counters = EXCLUDED.counters, updated_at = EXCLUDED.updated_at`;
}

async function mergeEvidence(sql: SQLType, value: Record<string, unknown>): Promise<void> {
  await sql`UPDATE migration_audit SET evidence = evidence || ${value}::jsonb WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
}

async function auditEvidence(sql: SQLType): Promise<Record<string, unknown>> {
  const rows = await sql<EvidenceRow[]>`SELECT status, evidence FROM migration_audit WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
  return readObject(rows[0]?.evidence);
}

async function completedEvidence(sql: SQLType): Promise<Record<string, unknown> | null> {
  try {
    const rows = await sql<EvidenceRow[]>`SELECT status, evidence FROM migration_audit WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
    return rows[0]?.status === "complete" ? readObject(rows[0].evidence) : null;
  } catch { return null; }
}

function paused(phase: string, evidence: Record<string, unknown>): LegacyMigrationResult { return { status: "paused", phase, evidence }; }
function readObject(value: unknown): Record<string, unknown> {
  if (typeof value === "string") { try { return readObject(JSON.parse(value)); } catch { return {}; } }
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function numberCounters(value: unknown): { total: number; parsed: number; conflicts: number; batches: number; [key: string]: number } {
  const row = readObject(value);
  return { total: Number(row.total ?? 0), parsed: Number(row.parsed ?? 0), conflicts: Number(row.conflicts ?? 0), batches: Number(row.batches ?? 0) };
}
