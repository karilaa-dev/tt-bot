import { SQL, type SQL as SQLType } from "bun";
import {
  createRecordDownloadHistoryFunction,
  createTelegramFilesValidator,
  HISTORY_CUTOVER_LOCK_KEY,
  MEDIA_CACHE_SCHEMA_VERSION,
} from "./migrations.ts";

export const LEGACY_REBUILD_MIGRATION_ID = "002_media_cache_rebuild";
const DEFAULT_BATCH_SIZE = 100_000;
const DEFAULT_LIVE_TABLE_BATCH_SIZE = 1_000;
const ADVISORY_LOCK_KEY = "tt-bot:002-media-cache-rebuild";

export interface LegacyMigrationOptions {
  /** Acknowledges that a restorable backup exists before the online rebuild. */
  preflightConfirmed: boolean;
  /** Optional exact free bytes on the PostgreSQL data filesystem. */
  availableBytes?: bigint;
  /** Container startup may continue when the database is already current or empty. */
  skipWhenMigrationNotNeeded?: boolean;
  batchSize?: number;
  /** Smaller batches for upserts into tables used by the running bot. */
  liveTableBatchSize?: number;
  /** Stop after the current committed batch when the serving process shuts down. */
  signal?: AbortSignal;
  /** Test hook: return after a committed phase without cutting over. */
  stopAfterPhase?: "audit" | "identity" | "details" | "copy" | "constraints" | "verification";
  /** Test hook for proving in-phase resumption after committed batches. */
  maxBatchesPerPhaseRun?: number;
  onProgress?: (message: string) => void;
  /** Called after live writes are mirrored and the bot may safely initialize. */
  onBotReady?: () => void;
  /** Test hook: runs after the safety audit and before live mirroring begins. */
  onBeforeBridge?: () => Promise<void>;
  /** Test hook: runs in a copy transaction after its source rows are locked. */
  onBeforeCopyBatchCommit?: () => Promise<void>;
  /** Test hook: runs after snapshot verification and before the cutover lock. */
  onBeforeCutoverLock?: (migrationBackendPid: number) => Promise<void>;
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
export type LegacyVideosSchema = "legacy" | "final" | "absent" | "unknown";

export function classifyLegacyVideosSchema(columnNames: Iterable<string>): LegacyVideosSchema {
  const columns = new Set(columnNames);
  if (columns.size === 0) return "absent";
  if (["video_link", "is_images", "is_processed", "is_inline"].every((name) => columns.has(name))) return "legacy";
  if (["shared_link", "video_details_id", "media_kind"].every((name) => columns.has(name))) return "final";
  return "unknown";
}

export async function runLegacyMigration(databaseUrl: string, options: LegacyMigrationOptions): Promise<LegacyMigrationResult> {
  if (!options.preflightConfirmed) {
    throw new Error(
      "Refusing migration: pass --confirm only after verifying a restorable backup",
    );
  }
  if (options.availableBytes !== undefined && options.availableBytes <= 0n) {
    throw new Error("Refusing migration: LEGACY_MIGRATION_AVAILABLE_BYTES must be greater than zero when supplied");
  }
  const batchSize = options.batchSize ?? DEFAULT_BATCH_SIZE;
  if (!Number.isSafeInteger(batchSize) || batchSize <= 0) throw new Error("Migration batch size must be a positive integer");
  const liveTableBatchSize = options.liveTableBatchSize ?? DEFAULT_LIVE_TABLE_BATCH_SIZE;
  if (!Number.isSafeInteger(liveTableBatchSize) || liveTableBatchSize <= 0) {
    throw new Error("Migration live-table batch size must be a positive integer");
  }
  const progress = options.onProgress ?? (() => undefined);
  // Final verification performs full-table aggregates that may not return any
  // protocol data for several minutes. Keep the reserved migration session
  // alive until the query completes so its advisory lock cannot be lost.
  const sql = new SQL({ url: databaseUrl, max: 4, idleTimeout: 0, connectionTimeout: 15, maxLifetime: 0 });
  return withReservedMigrationConnection(sql, async (lock) => {
    try {
      const acquired = await lock<Array<{ locked: boolean }>>`SELECT pg_try_advisory_lock(hashtextextended(${ADVISORY_LOCK_KEY}, 0)) AS locked`;
      if (!acquired[0]?.locked) throw new Error("Another legacy migration holds the PostgreSQL advisory lock");
      // Run every phase on the reserved session that owns the advisory lock. If
      // that session is lost, the migration fails with it instead of continuing
      // on another pooled connection after PostgreSQL has released the lock.
      return await migrate(lock, options, batchSize, liveTableBatchSize, progress);
    } finally {
      try { await lock`SELECT pg_advisory_unlock(hashtextextended(${ADVISORY_LOCK_KEY}, 0))`; } catch { /* connection may already be gone */ }
      await lock.release();
    }
  });
}

/** Keep pool cleanup outside reservation so initial connection failures cannot leak it. */
export async function withReservedMigrationConnection<Connection, Result>(
  pool: { reserve: () => Promise<Connection>; close: () => Promise<void> },
  operation: (connection: Connection) => Promise<Result>,
): Promise<Result> {
  try {
    const connection = await pool.reserve();
    return await operation(connection);
  } finally {
    await pool.close();
  }
}

async function migrate(
  sql: MigrationConnection,
  options: LegacyMigrationOptions,
  batchSize: number,
  liveTableBatchSize: number,
  progress: (message: string) => void,
): Promise<LegacyMigrationResult> {
  const shape = await sql<Array<{ column_name: string }>>`SELECT column_name
    FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'`;
  const schema = classifyLegacyVideosSchema(shape.map((row) => row.column_name));
  if (schema === "final") {
    const completed = await completedEvidence(sql);
    if (!completed && options.skipWhenMigrationNotNeeded) {
      options.onBotReady?.();
      return { status: "complete", phase: "not-needed", evidence: { reason: "videos schema is already current" } };
    }
    if (!completed) throw new Error("Final videos schema exists but the legacy migration has no completed audit row");
    // Repair the only safe partial-cutover remainder without rebuilding history.
    // The explicit command still confirms the backup and records exact values
    // before removing either column.
    await recoverFinalUserColumns(sql);
    options.onBotReady?.();
    return { status: "complete", phase: "cutover", evidence: await completedEvidence(sql) ?? completed };
  }
  if (schema === "absent" && options.skipWhenMigrationNotNeeded) {
    options.onBotReady?.();
    return { status: "complete", phase: "not-needed", evidence: { reason: "videos table does not exist yet" } };
  }
  if (schema !== "legacy") throw new Error("The videos table does not match the inspected v5.4.6 legacy schema");
  await validateLegacyShape(sql);

  // The expected legacy schema makes video_link NOT NULL, so the shape check
  // above can reject an unsafe source in constant time. Keep the exact scan as
  // durable evidence, but do not put it on the bot-readiness path.
  let evidence = await existingAuditEvidence(sql) ?? {};
  if ("source_audit" in evidence) assertLegacySourceAudit(readObject(evidence.source_audit));
  if (options.signal?.aborted) return paused("audit", evidence);

  await createControlTables(sql);
  const conflicting = await sql<Array<{ migration_id: string }>>`SELECT migration_id FROM migration_audit
    WHERE migration_id <> ${LEGACY_REBUILD_MIGRATION_ID} AND status NOT IN ('complete', 'failed') LIMIT 1`;
  if (conflicting.length) throw new Error(`Conflicting incomplete migration: ${conflicting[0]!.migration_id}`);
  const sizes = await sql<Array<{ source_bytes: bigint | string }>>`SELECT pg_total_relation_size('public.videos')::bigint AS source_bytes`;
  const sourceBytes = BigInt(sizes[0]?.source_bytes ?? 0);
  const requiredBytes = sourceBytes * 4n;
  if (options.availableBytes !== undefined && options.availableBytes < requiredBytes) {
    throw new Error(`Insufficient confirmed free space: ${options.availableBytes} bytes available, at least ${requiredBytes} required`);
  }
  if (options.availableBytes === undefined) {
    progress(`Ensure the PostgreSQL data filesystem has at least ${requiredBytes} free bytes (4x the videos relation)`);
  }
  const confirmedAvailableBytes = options.availableBytes?.toString() ?? null;
  const now = Math.floor(Date.now() / 1000);
  await sql`INSERT INTO migration_audit (migration_id, started_at, status, evidence)
    VALUES (${LEGACY_REBUILD_MIGRATION_ID}, ${now}, 'running', jsonb_build_object(
      'source_relation_bytes', ${sourceBytes.toString()}::text, 'required_free_bytes', ${requiredBytes.toString()}::text,
      'confirmed_available_bytes', ${confirmedAvailableBytes}::text, 'batch_size', ${batchSize}::integer,
      'live_table_batch_size', ${liveTableBatchSize}::integer,
      'operator_preflight_confirmed', TRUE
    )) ON CONFLICT (migration_id) DO NOTHING`;

  evidence = await auditEvidence(sql);
  await options.onBeforeBridge?.();

  // Install the final cache schema and a trigger-backed shadow write path before
  // the long scans. From this point onward the bot can serve against the legacy
  // history table while every committed change is mirrored into videos_new.
  await createIdentityParser(sql);
  await verifyIdentityParser(sql);
  await createTelegramFilesValidator(sql);
  await createVideoDetails(sql);
  await createVideosNew(sql);
  await ensureConstraint(sql, "videos_new_pkey");
  await createLegacyVideoSync(sql);
  await createRecordDownloadHistoryFunction(sql);

  // The safety audit predates the trigger by design. Capture a distinct,
  // durable upper bound only after trigger installation: earlier rows are now
  // covered by backfill, and every later write is covered by the trigger.
  evidence = await auditEvidence(sql);
  let backfillBound = readObject(evidence.backfill_bound);
  if (!("upper_pk" in backfillBound)) {
    const rows = await sql<Array<{ upper_pk: bigint | string }>>`SELECT COALESCE(MAX(pk_id), 0)::bigint AS upper_pk FROM videos`;
    backfillBound = {
      upper_pk: String(rows[0]?.upper_pk ?? 0),
      captured_at: String(Math.floor(Date.now() / 1000)),
      live_mirror_active: true,
    };
    await mergeEvidence(sql, { backfill_bound: backfillBound });
  }
  const upperPkValue = backfillBound.upper_pk;
  if (typeof upperPkValue !== "string" || !/^\d+$/u.test(upperPkValue)) {
    throw new Error("Refusing migration: backfill evidence has no valid upper primary key");
  }
  const upperPk = BigInt(upperPkValue);
  options.onBotReady?.();
  if (options.signal?.aborted) return paused("audit", await auditEvidence(sql));

  // The trigger and durable bound now cover every write, so the expensive
  // evidence scan can run alongside the serving bot. A resumed migration
  // reuses the first completed audit rather than repeating it.
  evidence = await auditEvidence(sql);
  if (!("source_audit" in evidence)) {
    progress("Running exact source audit in the background (one full server-side scan)");
    const initialAudit = { source: await sourceAudit(sql), user: await userAudit(sql) };
    assertLegacySourceAudit(initialAudit.source);
    await mergeEvidence(sql, { source_audit: initialAudit.source, removed_user_columns: initialAudit.user });
    evidence = await auditEvidence(sql);
  } else {
    assertLegacySourceAudit(readObject(evidence.source_audit));
  }
  if (options.stopAfterPhase === "audit" || options.signal?.aborted) return paused("audit", evidence);
  await mergeEvidence(sql, {
    identity_parser_self_test: { case_count: 15, verified_at: Math.floor(Date.now() / 1000) },
  });
  await sql`CREATE TABLE IF NOT EXISTS legacy_video_identity (
    legacy_pk BIGINT PRIMARY KEY,
    platform VARCHAR NOT NULL,
    platform_video_id VARCHAR NOT NULL,
    url_content_type VARCHAR,
    legacy_content_type VARCHAR NOT NULL,
    canonical_candidate TEXT
  )`;
  const identityComplete = await runIdentityBatches(
    sql, upperPk, batchSize, progress, options.maxBatchesPerPhaseRun, options.signal,
  );
  if (!identityComplete) return paused("identity", await auditEvidence(sql));
  await sql`CREATE INDEX IF NOT EXISTS legacy_video_identity_platform_id_idx
    ON legacy_video_identity (platform, platform_video_id)`;
  const identity = await identityAudit(sql);
  await mergeEvidence(sql, { identity });
  if (options.stopAfterPhase === "identity" || options.signal?.aborted) {
    return paused("identity", await auditEvidence(sql));
  }

  if (!await phaseComplete(sql, "details")) {
    await createLegacyDetailAggregate(sql);
    const aggregateComplete = await runDetailAggregateBatches(
      sql, upperPk, batchSize, progress, options.maxBatchesPerPhaseRun, options.signal,
    );
    if (!aggregateComplete) return paused("details", await auditEvidence(sql));
    const detailsComplete = await runDetailFinalizeBatches(
      sql, liveTableBatchSize, progress, options.maxBatchesPerPhaseRun, options.signal,
    );
    if (!detailsComplete) return paused("details", await auditEvidence(sql));
  }
  if (options.stopAfterPhase === "details" || options.signal?.aborted) {
    return paused("details", await auditEvidence(sql));
  }

  const copyComplete = await runCopyBatches(
    sql, upperPk, batchSize, progress, options.maxBatchesPerPhaseRun,
    options.signal, options.onBeforeCopyBatchCommit,
  );
  if (!copyComplete) return paused("copy", await auditEvidence(sql));
  if (options.stopAfterPhase === "copy" || options.signal?.aborted) {
    return paused("copy", await auditEvidence(sql));
  }

  if (!await phaseComplete(sql, "constraints")) {
    if (options.signal?.aborted) return paused("constraints", await auditEvidence(sql));
    progress("Building indexes and validating final constraints");
    await buildFinalConstraints(sql);
    await markPhase(sql, "constraints", upperPk, {});
  }
  if (options.stopAfterPhase === "constraints" || options.signal?.aborted) {
    return paused("constraints", await auditEvidence(sql));
  }

  progress("Verifying exact source/destination aggregates from one stable snapshot");
  if (options.stopAfterPhase === "verification") {
    const verification = await verifyRebuildSnapshot(sql);
    await mergeEvidence(sql, { verification });
    await markPhase(sql, "verification", BigInt(verification.source.max_pk ?? "0"), verification as unknown as Record<string, unknown>);
    return paused("verification", await auditEvidence(sql));
  }

  progress("Performing atomic cutover after online verification");
  const cutoverComplete = await verifyAndCutover(sql, options.onBeforeCutoverLock, options.signal);
  if (!cutoverComplete) return paused("verification", await auditEvidence(sql));
  return { status: "complete", phase: "cutover", evidence: await auditEvidence(sql) };
}

async function validateLegacyShape(sql: SQLType): Promise<void> {
  const required: Record<string, string[]> = {
    videos: ["pk_id", "user_id", "downloaded_at", "video_link", "is_images", "is_processed", "is_inline"],
    // ad_count/ad_cooldown existed in the Python schema but not in databases
    // created by the TypeScript bot. Audit either column when it is present,
    // while allowing both legacy variants to use the same online rebuild.
    users: ["user_id", "registered_at", "lang", "link", "file_mode"],
    music: ["pk_id", "user_id", "downloaded_at", "video_id"],
  };
  const rows = await sql<Array<{ table_name: string; column_name: string; is_nullable: string }>>`SELECT
      table_name, column_name, is_nullable
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name IN ('videos', 'users', 'music')`;
  for (const [table, names] of Object.entries(required)) {
    const found = new Set(rows.filter((row) => row.table_name === table).map((row) => row.column_name));
    const missing = names.filter((name) => !found.has(name));
    if (missing.length) throw new Error(`Legacy ${table} table is missing required columns: ${missing.join(", ")}`);
  }
  const videoLink = rows.find((row) => row.table_name === "videos" && row.column_name === "video_link");
  if (videoLink?.is_nullable !== "NO") {
    throw new Error("Legacy videos.video_link must be NOT NULL before the online migration can start");
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
        pk_id::bigint, user_id::bigint, downloaded_at::bigint, video_link::text,
        (CASE WHEN is_images THEN 'images' ELSE 'video' END)::varchar,
        (CASE WHEN is_inline THEN 'inline' ELSE 'chat' END)::varchar,
        NULL::varchar, FALSE::boolean
      )::text, 0)::numeric), 0)::text AS row_fingerprint,
      COALESCE(MAX(length(video_link)), 0)::text AS max_shared_link_length
    FROM videos`;
  return rows[0] ?? {};
}

export function assertLegacySourceAudit(source: Record<string, unknown>): void {
  const nullLinks = source.video_link_null_count;
  if (typeof nullLinks !== "string" || !/^\d+$/u.test(nullLinks)) {
    throw new Error("Refusing migration: source audit has no valid video_link NULL count");
  }
  if (BigInt(nullLinks) > 0n) {
    throw new Error(
      `Refusing migration: source audit found ${nullLinks} videos rows with a NULL video_link; `
      + "shared_link is required and legacy history rows cannot be discarded",
    );
  }
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

async function recoverFinalUserColumns(sql: SQLType): Promise<void> {
  await sql.begin(async (tx) => {
    await tx`LOCK TABLE users IN ACCESS EXCLUSIVE MODE`;
    const audit = await userAudit(tx);
    if (audit.ad_count_column_present !== "true" && audit.ad_cooldown_column_present !== "true") return;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_count`;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_cooldown`;
    const recoveredAt = Math.floor(Date.now() / 1000);
    await tx`UPDATE migration_audit SET evidence = evidence || jsonb_build_object(
        'post_cutover_user_column_recovery', ${{
          ...audit,
          recovered_at: String(recoveredAt),
        }}::jsonb
      )
      WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
  });
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
    parsed := regexp_match(path, '^/@[^/]*/(video|photo)/([0-9]+)(?:/|$)', 'i');
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

/**
 * Exercise the actual PostgreSQL parser before it scans legacy history. This is
 * deliberately a migration preflight instead of a second TypeScript parser,
 * so the tested implementation and the implementation used for 47M rows cannot
 * drift apart and no network/database integration test is needed in CI.
 */
async function verifyIdentityParser(sql: SQLType): Promise<void> {
  const mismatches = await sql<Array<{ value: string }>>`WITH cases(
      value, expected_platform, expected_id, expected_type, expected_canonical, expected_conflict
    ) AS (VALUES
      ('https://www.tiktok.com/@creator/video/123', 'tiktok'::varchar, '123'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/123'::text, FALSE),
      ('https://www.tiktok.com/@/video/124', 'tiktok'::varchar, '124'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/124'::text, FALSE),
      ('https://www.tiktok.com/@creator/photo/125', 'tiktok'::varchar, '125'::varchar, 'images'::varchar, 'https://www.tiktok.com/@_/photo/125'::text, FALSE),
      ('https://m.tiktok.com/v/126.html', 'tiktok'::varchar, '126'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/126'::text, FALSE),
      ('https://www.tiktok.com/embed/127', 'tiktok'::varchar, '127'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/127'::text, FALSE),
      ('https://www.tiktok.com/embed/v2/128', 'tiktok'::varchar, '128'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/128'::text, FALSE),
      ('https://www.tiktok.com/player/v1/129', 'tiktok'::varchar, '129'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/129'::text, FALSE),
      ('https://www.tiktok.com/share/video/130', 'tiktok'::varchar, '130'::varchar, 'video'::varchar, 'https://www.tiktok.com/@_/video/130'::text, FALSE),
      ('https://www.tiktok.com/share/item/131', 'tiktok'::varchar, '131'::varchar, NULL::varchar, NULL::text, FALSE),
      ('https://www.tiktok.com/?item_id=132', 'tiktok'::varchar, '132'::varchar, NULL::varchar, NULL::text, FALSE),
      ('https://www.tiktok.com/?share_item_id=133', 'tiktok'::varchar, '133'::varchar, NULL::varchar, NULL::text, FALSE),
      ('https://www.tiktok.com/@creator/video/134?item_id=999', NULL::varchar, NULL::varchar, NULL::varchar, NULL::text, TRUE),
      ('https://vm.tiktok.com/TOKEN/', NULL::varchar, NULL::varchar, NULL::varchar, NULL::text, FALSE),
      ('https://www.instagram.com/p/ABC_1/', 'instagram'::varchar, 'ABC_1'::varchar, NULL::varchar, 'https://www.instagram.com/p/ABC_1/'::text, FALSE),
      ('https://www.instagram.com/reels/XYZ-2/', 'instagram'::varchar, 'XYZ-2'::varchar, 'video'::varchar, 'https://www.instagram.com/reel/XYZ-2/'::text, FALSE)
    )
    SELECT c.value
    FROM cases c
    CROSS JOIN LATERAL parse_legacy_video_identity(c.value) parsed
    WHERE parsed.platform IS DISTINCT FROM c.expected_platform
      OR parsed.platform_video_id IS DISTINCT FROM c.expected_id
      OR parsed.url_content_type IS DISTINCT FROM c.expected_type
      OR parsed.canonical_candidate IS DISTINCT FROM c.expected_canonical
      OR parsed.conflict IS DISTINCT FROM c.expected_conflict`;
  if (mismatches.length) {
    throw new Error(`Legacy identity parser self-test failed for: ${mismatches.map((row) => row.value).join(", ")}`);
  }
}

/** Mirror every legacy history mutation into the final shadow table. */
async function createLegacyVideoSync(sql: SQLType): Promise<void> {
  await sql.unsafe(`CREATE OR REPLACE FUNCTION sync_legacy_video_to_shadow()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
DECLARE
  parsed_platform VARCHAR;
  parsed_video_id VARCHAR;
  parsed_conflict BOOLEAN;
  detail_id BIGINT;
  preserve_existing_detail BOOLEAN := FALSE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    DELETE FROM videos_new WHERE pk_id = OLD.pk_id;
    RETURN OLD;
  END IF;

  IF TG_OP = 'UPDATE' AND OLD.pk_id <> NEW.pk_id THEN
    DELETE FROM videos_new WHERE pk_id = OLD.pk_id;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    preserve_existing_detail := NEW.video_link IS NOT DISTINCT FROM OLD.video_link;
  END IF;

  SELECT platform, platform_video_id, conflict
  INTO parsed_platform, parsed_video_id, parsed_conflict
  FROM parse_legacy_video_identity(NEW.video_link);

  detail_id := NULL;
  IF parsed_platform IS NOT NULL AND NOT parsed_conflict THEN
    -- Live legacy rows only need an identity placeholder. The historical
    -- aggregation fills stable metadata, while live bot upserts remain the
    -- authoritative source for cache and extraction fields.
    INSERT INTO video_details (
      platform, platform_video_id, first_downloaded_at, last_used_at
    ) VALUES (
      parsed_platform, parsed_video_id, NEW.downloaded_at, NEW.downloaded_at
    )
    ON CONFLICT (platform, platform_video_id) DO UPDATE SET
      first_downloaded_at = LEAST(video_details.first_downloaded_at, EXCLUDED.first_downloaded_at),
      last_used_at = GREATEST(video_details.last_used_at, EXCLUDED.last_used_at)
    RETURNING pk_id INTO detail_id;
  END IF;

  INSERT INTO videos_new (
    pk_id, user_id, video_details_id, downloaded_at, shared_link,
    media_kind, delivery_surface, delivery_mode, cache_hit
  ) VALUES (
    NEW.pk_id, NEW.user_id, detail_id, NEW.downloaded_at, NEW.video_link,
    CASE WHEN NEW.is_images THEN 'images' ELSE 'video' END,
    CASE WHEN NEW.is_inline THEN 'inline' ELSE 'chat' END,
    NULL, FALSE
  )
  ON CONFLICT (pk_id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    video_details_id = CASE WHEN preserve_existing_detail
      THEN COALESCE(videos_new.video_details_id, EXCLUDED.video_details_id)
      ELSE EXCLUDED.video_details_id
    END,
    downloaded_at = EXCLUDED.downloaded_at,
    shared_link = EXCLUDED.shared_link,
    media_kind = EXCLUDED.media_kind,
    delivery_surface = EXCLUDED.delivery_surface;
  RETURN NEW;
END
$function$`);
  await sql.unsafe(`CREATE OR REPLACE FUNCTION prevent_legacy_video_truncate()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
BEGIN
  RAISE EXCEPTION 'TRUNCATE of legacy videos is blocked while its online shadow migration is active';
END
$function$`);
  await sql.begin(async (tx) => {
    // Keep the replacement under one table lock so an external legacy writer
    // cannot commit in the drop/create gap during a resumed migration.
    await tx`DROP TRIGGER IF EXISTS legacy_video_shadow_sync ON videos`;
    await tx`DROP TRIGGER IF EXISTS legacy_video_truncate_guard ON videos`;
    await tx`CREATE TRIGGER legacy_video_shadow_sync
      AFTER INSERT OR UPDATE OR DELETE ON videos
      FOR EACH ROW EXECUTE FUNCTION sync_legacy_video_to_shadow()`;
    await tx`CREATE TRIGGER legacy_video_truncate_guard
      BEFORE TRUNCATE ON videos
      FOR EACH STATEMENT EXECUTE FUNCTION prevent_legacy_video_truncate()`;
    // ALWAYS triggers still fire for replication-role sessions, closing the
    // only normal PostgreSQL path that can bypass an enabled origin trigger.
    await tx`ALTER TABLE videos ENABLE ALWAYS TRIGGER legacy_video_shadow_sync`;
    await tx`ALTER TABLE videos ENABLE ALWAYS TRIGGER legacy_video_truncate_guard`;
  });
}

async function runIdentityBatches(
  sql: SQLType,
  upperPk: bigint,
  batchSize: number,
  progress: (message: string) => void,
  maxBatches?: number,
  signal?: AbortSignal,
): Promise<boolean> {
  let state = await stateFor(sql, "identity");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (signal?.aborted) return false;
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
        ...counters,
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

async function createLegacyDetailAggregate(sql: SQLType): Promise<void> {
  await sql`CREATE TABLE IF NOT EXISTS legacy_video_detail_aggregate (
    pk_id BIGSERIAL UNIQUE NOT NULL,
    platform VARCHAR NOT NULL,
    platform_video_id VARCHAR NOT NULL,
    legacy_content_type_min VARCHAR NOT NULL,
    legacy_content_type_max VARCHAR NOT NULL,
    url_content_conflict BOOLEAN NOT NULL,
    canonical_candidate_min TEXT,
    canonical_candidate_max TEXT,
    first_downloaded_at BIGINT,
    last_downloaded_at BIGINT,
    PRIMARY KEY (platform, platform_video_id)
  )`;
}

async function runDetailAggregateBatches(
  sql: SQLType,
  upperPk: bigint,
  batchSize: number,
  progress: (message: string) => void,
  maxBatches?: number,
  signal?: AbortSignal,
): Promise<boolean> {
  const state = await stateFor(sql, "details_aggregate");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (signal?.aborted) return false;
    if (maxBatches !== undefined && batchesThisRun >= maxBatches) return false;
    const boundary = await sql<BoundaryRow[]>`SELECT MAX(legacy_pk) AS end_pk FROM (
      SELECT legacy_pk FROM legacy_video_identity
      WHERE legacy_pk > ${lastPk} AND legacy_pk <= ${upperPk}
      ORDER BY legacy_pk LIMIT ${batchSize}
    ) batch`;
    if (boundary[0]?.end_pk === null || boundary[0]?.end_pk === undefined) break;
    const endPk = BigInt(boundary[0].end_pk);
    await sql.begin(async (tx) => {
      // A null canonical candidate means that this URL did not encode a media
      // type; it is unknown evidence, not a conflict. Preserve the original
      // COUNT(DISTINCT canonical_candidate) FILTER (WHERE ... IS NOT NULL)
      // semantics explicitly while merging evidence across committed batches.
      const metrics = await tx<Array<{ total: number | string; groups: number | string }>>`WITH batch_rows AS (
          SELECT i.*, v.downloaded_at
          FROM legacy_video_identity i JOIN videos v ON v.pk_id = i.legacy_pk
          WHERE i.legacy_pk > ${lastPk} AND i.legacy_pk <= ${endPk}
        ), aggregated AS (
          SELECT platform, platform_video_id,
            MIN(legacy_content_type) AS legacy_content_type_min,
            MAX(legacy_content_type) AS legacy_content_type_max,
            BOOL_OR(url_content_type IS NOT NULL AND url_content_type <> legacy_content_type) AS url_content_conflict,
            MIN(canonical_candidate) FILTER (WHERE canonical_candidate IS NOT NULL) AS canonical_candidate_min,
            MAX(canonical_candidate) FILTER (WHERE canonical_candidate IS NOT NULL) AS canonical_candidate_max,
            MIN(downloaded_at) AS first_downloaded_at,
            MAX(downloaded_at) AS last_downloaded_at
          FROM batch_rows GROUP BY platform, platform_video_id
        ), upserted AS (
          INSERT INTO legacy_video_detail_aggregate (
            platform, platform_video_id, legacy_content_type_min, legacy_content_type_max,
            url_content_conflict, canonical_candidate_min, canonical_candidate_max,
            first_downloaded_at, last_downloaded_at
          ) SELECT platform, platform_video_id, legacy_content_type_min, legacy_content_type_max,
            url_content_conflict, canonical_candidate_min, canonical_candidate_max,
            first_downloaded_at, last_downloaded_at
          FROM aggregated
          ON CONFLICT (platform, platform_video_id) DO UPDATE SET
            legacy_content_type_min = LEAST(legacy_video_detail_aggregate.legacy_content_type_min, EXCLUDED.legacy_content_type_min),
            legacy_content_type_max = GREATEST(legacy_video_detail_aggregate.legacy_content_type_max, EXCLUDED.legacy_content_type_max),
            url_content_conflict = legacy_video_detail_aggregate.url_content_conflict OR EXCLUDED.url_content_conflict,
            canonical_candidate_min = CASE
              WHEN legacy_video_detail_aggregate.canonical_candidate_min IS NULL THEN EXCLUDED.canonical_candidate_min
              WHEN EXCLUDED.canonical_candidate_min IS NULL THEN legacy_video_detail_aggregate.canonical_candidate_min
              ELSE LEAST(legacy_video_detail_aggregate.canonical_candidate_min, EXCLUDED.canonical_candidate_min)
            END,
            canonical_candidate_max = CASE
              WHEN legacy_video_detail_aggregate.canonical_candidate_max IS NULL THEN EXCLUDED.canonical_candidate_max
              WHEN EXCLUDED.canonical_candidate_max IS NULL THEN legacy_video_detail_aggregate.canonical_candidate_max
              ELSE GREATEST(legacy_video_detail_aggregate.canonical_candidate_max, EXCLUDED.canonical_candidate_max)
            END,
            first_downloaded_at = LEAST(legacy_video_detail_aggregate.first_downloaded_at, EXCLUDED.first_downloaded_at),
            last_downloaded_at = GREATEST(legacy_video_detail_aggregate.last_downloaded_at, EXCLUDED.last_downloaded_at)
          RETURNING 1
        ) SELECT (SELECT COUNT(*) FROM batch_rows) AS total, COUNT(*) AS groups FROM upserted`;
      counters = {
        ...counters,
        total: counters.total + Number(metrics[0]?.total ?? 0),
        groups: counters.groups + Number(metrics[0]?.groups ?? 0),
        batches: counters.batches + 1,
      };
      await upsertState(tx, "details_aggregate", endPk, counters);
    });
    lastPk = endPk;
    batchesThisRun++;
    progress(`Details aggregation: completed through legacy pk ${lastPk}`);
  }
  await upsertState(sql, "details_aggregate", lastPk, { ...counters, complete: true });
  return true;
}

async function runDetailFinalizeBatches(
  sql: SQLType,
  batchSize: number,
  progress: (message: string) => void,
  maxBatches?: number,
  signal?: AbortSignal,
): Promise<boolean> {
  const upperRows = await sql<Array<{ max_pk: bigint | string | null }>>`SELECT MAX(pk_id) AS max_pk FROM legacy_video_detail_aggregate`;
  const upperPk = BigInt(upperRows[0]?.max_pk ?? 0);
  const state = await stateFor(sql, "details");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (signal?.aborted) return false;
    if (maxBatches !== undefined && batchesThisRun >= maxBatches) return false;
    const boundary = await sql<BoundaryRow[]>`SELECT MAX(pk_id) AS end_pk FROM (
      SELECT pk_id FROM legacy_video_detail_aggregate
      WHERE pk_id > ${lastPk} AND pk_id <= ${upperPk}
      ORDER BY pk_id LIMIT ${batchSize}
    ) batch`;
    if (boundary[0]?.end_pk === null || boundary[0]?.end_pk === undefined) break;
    const endPk = BigInt(boundary[0].end_pk);
    await sql.begin(async (tx) => {
      const inserted = await tx<Array<{ count: number | string }>>`WITH finalized AS (
          INSERT INTO video_details (
            platform, platform_video_id, content_type, canonical_link, first_downloaded_at, last_used_at
          ) SELECT platform, platform_video_id,
            CASE WHEN legacy_content_type_min = legacy_content_type_max AND NOT url_content_conflict
              THEN CASE
                WHEN platform = 'tiktok' AND legacy_content_type_min = 'images' THEN 'slideshow'
                WHEN platform = 'instagram' AND legacy_content_type_min = 'images' THEN 'image'
                ELSE 'video'
              END
              ELSE NULL
            END,
            CASE WHEN canonical_candidate_min = canonical_candidate_max AND NOT url_content_conflict
              THEN canonical_candidate_min ELSE NULL END,
            first_downloaded_at, last_downloaded_at
          FROM legacy_video_detail_aggregate
          WHERE pk_id > ${lastPk} AND pk_id <= ${endPk}
          ON CONFLICT (platform, platform_video_id) DO UPDATE SET
            content_type = COALESCE(video_details.content_type, EXCLUDED.content_type),
            canonical_link = COALESCE(video_details.canonical_link, EXCLUDED.canonical_link),
            first_downloaded_at = LEAST(video_details.first_downloaded_at, EXCLUDED.first_downloaded_at),
            last_used_at = GREATEST(video_details.last_used_at, EXCLUDED.last_used_at)
          RETURNING 1
        ) SELECT COUNT(*) AS count FROM finalized`;
      counters = {
        ...counters,
        total: counters.total + Number(inserted[0]?.count ?? 0),
        batches: counters.batches + 1,
      };
      await upsertState(tx, "details", endPk, counters);
    });
    lastPk = endPk;
    batchesThisRun++;
    progress(`Details finalization: completed through aggregate pk ${lastPk}`);
  }
  if (signal?.aborted) return false;
  await dropInvalidConcurrentIndex(sql, "video_details_last_used_idx");
  await sql`CREATE INDEX CONCURRENTLY IF NOT EXISTS video_details_last_used_idx ON video_details (last_used_at DESC)`;
  await upsertState(sql, "details", lastPk, { ...counters, complete: true });
  return true;
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

async function runCopyBatches(
  sql: SQLType,
  upperPk: bigint,
  batchSize: number,
  progress: (message: string) => void,
  maxBatches?: number,
  signal?: AbortSignal,
  onBeforeBatchCommit?: () => Promise<void>,
): Promise<boolean> {
  const state = await stateFor(sql, "copy");
  let lastPk = BigInt(state?.last_pk ?? 0);
  let counters = numberCounters(state?.counters);
  let batchesThisRun = 0;
  while (lastPk < upperPk) {
    if (signal?.aborted) return false;
    if (maxBatches !== undefined && batchesThisRun >= maxBatches) return false;
    const boundary = await sql<BoundaryRow[]>`SELECT MAX(pk_id) AS end_pk FROM (
      SELECT pk_id FROM videos WHERE pk_id > ${lastPk} AND pk_id <= ${upperPk} ORDER BY pk_id LIMIT ${batchSize}
    ) batch`;
    if (boundary[0]?.end_pk === null || boundary[0]?.end_pk === undefined) break;
    const endPk = BigInt(boundary[0].end_pk);
    await sql.begin(async (tx) => {
      const inserted = await tx<Array<{ count: number | string }>>`WITH batch_rows AS MATERIALIZED (
        SELECT v.pk_id, v.user_id, d.pk_id AS video_details_id, v.downloaded_at, v.video_link,
          v.is_images, v.is_inline
        FROM videos v
        LEFT JOIN legacy_video_identity i ON i.legacy_pk = v.pk_id
        LEFT JOIN video_details d ON d.platform = i.platform AND d.platform_video_id = i.platform_video_id
        WHERE v.pk_id > ${lastPk} AND v.pk_id <= ${endPk}
        FOR NO KEY UPDATE OF v
      ), copied AS (
        INSERT INTO videos_new (pk_id, user_id, video_details_id, downloaded_at, shared_link, media_kind, delivery_surface, delivery_mode, cache_hit)
        SELECT row.pk_id, row.user_id, row.video_details_id, row.downloaded_at, row.video_link,
          CASE WHEN row.is_images THEN 'images' ELSE 'video' END,
          CASE WHEN row.is_inline THEN 'inline' ELSE 'chat' END,
          NULL, FALSE
        FROM batch_rows row
        ON CONFLICT DO NOTHING RETURNING 1
      ) SELECT COUNT(*) AS count FROM copied`;
      await onBeforeBatchCommit?.();
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
  // These indexes are built while the sync trigger is still accepting writes.
  await dropInvalidConcurrentIndex(sql, "videos_new_user_downloaded_idx");
  await sql`CREATE INDEX CONCURRENTLY IF NOT EXISTS videos_new_user_downloaded_idx ON videos_new (user_id, downloaded_at DESC)`;
  await dropInvalidConcurrentIndex(sql, "videos_new_downloaded_brin_idx");
  await sql`CREATE INDEX CONCURRENTLY IF NOT EXISTS videos_new_downloaded_brin_idx ON videos_new USING BRIN (downloaded_at)`;
  await dropInvalidConcurrentIndex(sql, "videos_new_details_idx");
  await sql`CREATE INDEX CONCURRENTLY IF NOT EXISTS videos_new_details_idx ON videos_new (video_details_id) WHERE video_details_id IS NOT NULL`;
  await sql`ANALYZE video_details`;
  await sql`ANALYZE videos_new`;
}

type ConcurrentIndexName =
  | "video_details_last_used_idx"
  | "videos_new_user_downloaded_idx"
  | "videos_new_downloaded_brin_idx"
  | "videos_new_details_idx";

async function dropInvalidConcurrentIndex(sql: SQLType, name: ConcurrentIndexName): Promise<void> {
  const rows = await sql<Array<{ valid: boolean }>>`SELECT index_state.indisvalid AS valid
    FROM pg_index index_state
    JOIN pg_class index_class ON index_class.oid = index_state.indexrelid
    JOIN pg_namespace index_namespace ON index_namespace.oid = index_class.relnamespace
    WHERE index_namespace.nspname = 'public' AND index_class.relname = ${name}`;
  if (rows[0] && !rows[0].valid) await sql.unsafe(`DROP INDEX CONCURRENTLY public.${name}`);
}

interface VerificationEvidence {
  source: Record<string, string>;
  destination: Record<string, string>;
  integrity: Record<string, string>;
  verified_at: string;
}

async function verifyRebuildSnapshot(sql: SQLType): Promise<VerificationEvidence> {
  return await sql.begin("isolation level repeatable read read only", verifyRebuild);
}

async function verifyRebuild(sql: SQLType): Promise<VerificationEvidence> {
  const source = await sourceAudit(sql);
  const rows = await sql<Array<Record<string, string>>>`SELECT
      COUNT(*)::text AS row_count, COALESCE(MIN(pk_id), 0)::text AS min_pk, COALESCE(MAX(pk_id), 0)::text AS max_pk,
      COALESCE(SUM(pk_id::numeric), 0)::text AS pk_sum,
      COALESCE(SUM(user_id::numeric), 0)::text AS user_id_sum,
      COALESCE(SUM(COALESCE(downloaded_at, 0)::numeric), 0)::text AS downloaded_at_sum,
      COALESCE(SUM(hashtextextended(jsonb_build_array(
        pk_id::bigint, user_id::bigint, downloaded_at::bigint, shared_link::text,
        media_kind::varchar, delivery_surface::varchar, NULL::varchar, FALSE::boolean
      )::text, 0)::numeric), 0)::text AS row_fingerprint,
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
      (SELECT COUNT(*) FROM legacy_video_identity i
        JOIN videos source_video ON source_video.pk_id = i.legacy_pk
        LEFT JOIN video_details d ON d.platform = i.platform AND d.platform_video_id = i.platform_video_id
        WHERE d.pk_id IS NULL)::text AS unmapped_current_staged_rows,
      (SELECT COUNT(*) FROM videos source_video
        CROSS JOIN LATERAL parse_legacy_video_identity(source_video.video_link) parsed
        LEFT JOIN videos_new shadow_video ON shadow_video.pk_id = source_video.pk_id
        WHERE parsed.platform IS NOT NULL AND NOT parsed.conflict
          AND shadow_video.video_details_id IS NULL)::text AS unlinked_parseable_history_rows,
      (SELECT COUNT(*) FROM legacy_video_identity)::text AS staged_rows`;
  const checks = integrity[0] ?? {};
  for (const key of [
    "orphaned_users", "orphaned_details", "duplicate_primary_keys",
    "unmapped_current_staged_rows", "unlinked_parseable_history_rows",
  ]) {
    if (checks[key] !== "0") throw new Error(`Verification failed: ${key}=${checks[key]}`);
  }
  return { source, destination, integrity: checks, verified_at: String(Math.floor(Date.now() / 1000)) };
}

async function verifyAndCutover(
  sql: SQLType,
  onBeforeCutoverLock?: (migrationBackendPid: number) => Promise<void>,
  signal?: AbortSignal,
): Promise<boolean> {
  if (signal?.aborted) return false;
  return await sql.begin("isolation level repeatable read", async (tx) => {
    // The trigger writes source and shadow rows in the same transaction, so one
    // repeatable-read snapshot can compare them without pausing the bot.
    const verification = await verifyRebuild(tx);
    const upperPk = BigInt(verification.source.max_pk ?? "0");
    const backend = await tx<Array<{ pid: number }>>`SELECT pg_backend_pid() AS pid`;
    await onBeforeCutoverLock?.(backend[0]!.pid);
    if (signal?.aborted) return false;

    // Gate schema-aware bot calls first. Direct legacy writers do not take this
    // advisory lock; the table lock waits for their trigger-backed transaction
    // and queues any new writes without creating a reverse lock dependency.
    await tx`SELECT pg_advisory_xact_lock(hashtextextended(${HISTORY_CUTOVER_LOCK_KEY}, 0))`;
    await tx`LOCK TABLE videos, videos_new, users IN ACCESS EXCLUSIVE MODE`;
    const trigger = await tx<Array<{ enabled: boolean }>>`SELECT
        COUNT(*) = 2 AND COALESCE(bool_and(tgenabled = 'A'), FALSE) AS enabled
      FROM pg_trigger
      WHERE tgrelid = 'public.videos'::regclass
        AND tgname IN ('legacy_video_shadow_sync', 'legacy_video_truncate_guard')`;
    if (!trigger[0]?.enabled) throw new Error("Legacy live-write sync trigger is not enabled; cutover aborted");

    await mergeEvidence(tx, { verification });
    await markPhase(tx, "verification", upperPk, verification as unknown as Record<string, unknown>);
    await tx`ALTER SEQUENCE videos_pk_id_seq OWNED BY NONE`;
    await tx`ALTER TABLE videos RENAME TO videos_legacy_002`;
    await tx`ALTER TABLE videos_new RENAME TO videos`;
    await tx`ALTER TABLE videos ALTER COLUMN pk_id SET DEFAULT nextval('videos_pk_id_seq')`;
    await tx`ALTER SEQUENCE videos_pk_id_seq OWNED BY videos.pk_id`;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_count`;
    await tx`ALTER TABLE users DROP COLUMN IF EXISTS ad_cooldown`;
    await tx`DROP TABLE videos_legacy_002`;
    await tx`DROP TABLE legacy_video_identity`;
    await tx`DROP TABLE IF EXISTS legacy_video_detail_aggregate`;
    await tx`DROP FUNCTION sync_legacy_video_to_shadow()`;
    await tx`DROP FUNCTION prevent_legacy_video_truncate()`;
    await tx`DROP FUNCTION parse_legacy_video_identity(TEXT)`;
    await tx`ALTER TABLE videos RENAME CONSTRAINT videos_new_pkey TO videos_pkey`;
    await tx`ALTER INDEX videos_new_user_downloaded_idx RENAME TO videos_user_downloaded_idx`;
    await tx`ALTER INDEX videos_new_downloaded_brin_idx RENAME TO videos_downloaded_brin_idx`;
    await tx`ALTER INDEX videos_new_details_idx RENAME TO videos_details_idx`;
    const completedAt = Math.floor(Date.now() / 1000);
    await tx`INSERT INTO schema_migrations (version, applied_at) VALUES (${MEDIA_CACHE_SCHEMA_VERSION}, ${completedAt}) ON CONFLICT (version) DO NOTHING`;
    await tx`UPDATE migration_audit SET status = 'complete', completed_at = ${completedAt},
      evidence = evidence || jsonb_build_object('cutover', jsonb_build_object(
        'status', 'complete', 'completed_at', ${completedAt}::bigint, 'online', TRUE,
        'legacy_table_dropped', TRUE, 'identity_staging_dropped', TRUE, 'detail_staging_dropped', TRUE
      ))
      WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
    await upsertState(tx, "cutover", upperPk, { complete: true });
    return true;
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

async function existingAuditEvidence(sql: SQLType): Promise<Record<string, unknown> | null> {
  const relation = await sql<Array<{ name: string | null }>>`SELECT to_regclass('public.migration_audit')::text AS name`;
  if (!relation[0]?.name) return null;
  const rows = await sql<EvidenceRow[]>`SELECT status, evidence FROM migration_audit WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
  return rows[0] ? readObject(rows[0].evidence) : null;
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
function numberCounters(value: unknown): { total: number; parsed: number; conflicts: number; groups: number; batches: number; [key: string]: number } {
  const row = readObject(value);
  return {
    total: Number(row.total ?? 0),
    parsed: Number(row.parsed ?? 0),
    conflicts: Number(row.conflicts ?? 0),
    groups: Number(row.groups ?? 0),
    batches: Number(row.batches ?? 0),
  };
}
