import { expect, test } from "bun:test";
import { SQL } from "bun";
import { runLegacyMigration } from "../../src/db/legacy-migration.ts";

const enabled = Bun.env.RUN_POSTGRES_MIGRATION_INTEGRATION === "1";
const integrationTest = enabled ? test : test.skip;

integrationTest("online legacy migration mirrors writes, resumes, and cuts over atomically", async () => {
  const adminUrl = requiredDatabaseUrl();
  const databaseName = `tt_bot_migration_${process.pid}_${crypto.randomUUID().replaceAll("-", "")}`;
  const databaseUrl = databaseUrlFor(adminUrl, databaseName);
  const admin = new SQL({ url: adminUrl, max: 1, connectionTimeout: 10, idleTimeout: 10 });
  let live: SQL | null = null;

  try {
    await admin.unsafe(`CREATE DATABASE "${databaseName}"`);
    live = new SQL({ url: databaseUrl, max: 4, connectionTimeout: 10, idleTimeout: 10 });
    await seedLegacyDatabase(live);

    let markReady!: () => void;
    const ready = new Promise<void>((resolve) => { markReady = resolve; });
    const firstRun = runLegacyMigration(databaseUrl, {
      preflightConfirmed: true,
      batchSize: 1,
      stopAfterPhase: "copy",
      onBotReady: markReady,
    });

    await ready;
    const detailRows = await live<Array<{ pk_id: bigint | string }>>`INSERT INTO video_details (
        platform, platform_video_id, content_type, canonical_link, first_downloaded_at, last_used_at
      ) VALUES ('tiktok', '9001', 'video', 'https://www.tiktok.com/@_/video/9001', 40, 40)
      RETURNING pk_id`;
    const detailsId = BigInt(detailRows[0]!.pk_id);
    await live`SELECT record_download_history(
      ${1}, ${detailsId}, ${40}, ${"https://vm.tiktok.com/ONLINE/"},
      ${"video"}, ${"chat"}, ${"document"}, ${true}
    )`;

    const paused = await firstRun;
    expect(paused).toMatchObject({ status: "paused", phase: "copy" });

    // The trigger is durable independently of the migration process, so a
    // direct legacy writer remains mirrored between an interrupted run and its
    // replacement process.
    await live`INSERT INTO videos (
      user_id, downloaded_at, video_link, is_images, is_processed, is_inline
    ) VALUES (
      1, 50, 'https://www.tiktok.com/@_/photo/9002', TRUE, FALSE, TRUE
    )`;

    let cutoverWrite: Promise<unknown> | null = null;
    const result = await runLegacyMigration(databaseUrl, {
      preflightConfirmed: true,
      batchSize: 1,
      onBeforeCutoverLock: async () => {
        let markWriterStarted!: () => void;
        const writerStarted = new Promise<void>((resolve) => { markWriterStarted = resolve; });
        cutoverWrite = live!.begin(async (tx) => {
          await tx`SELECT record_download_history(
            ${1}, ${detailsId}, ${60}, ${"https://vm.tiktok.com/CUTOVER/"},
            ${"video"}, ${"inline"}, ${"media"}, ${false}
          )`;
          markWriterStarted();
          // Keep the shared advisory lock open long enough for cutover to queue
          // behind this transaction, proving the lock order and post-snapshot
          // write path rather than merely racing them probabilistically.
          await Bun.sleep(75);
        });
        await writerStarted;
      },
    });
    await cutoverWrite;
    expect(result).toMatchObject({ status: "complete", phase: "cutover" });

    // Exercise the same stable function after the physical table has changed.
    await live`SELECT record_download_history(
      ${1}, ${detailsId}, ${70}, ${"https://www.tiktok.com/@_/video/9001"},
      ${"video"}, ${"chat"}, ${"media"}, ${true}
    )`;

    const columns = await live<Array<{ column_name: string }>>`SELECT column_name
      FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'videos'`;
    const columnNames = columns.map((row) => row.column_name);
    for (const expected of ["shared_link", "video_details_id", "media_kind", "delivery_surface", "delivery_mode", "cache_hit"]) {
      expect(columnNames).toContain(expected);
    }
    expect(columnNames).not.toContain("video_link");

    const history = await live<Array<{
      shared_link: string;
      video_details_id: bigint | string | null;
      delivery_mode: string | null;
      cache_hit: boolean;
    }>>`SELECT shared_link, video_details_id, delivery_mode, cache_hit FROM videos ORDER BY pk_id`;
    expect(history).toHaveLength(7);
    expect(history.find((row) => row.shared_link.endsWith("/ONLINE/"))).toMatchObject({
      video_details_id: detailsId,
      delivery_mode: "document",
      cache_hit: true,
    });
    expect(history.find((row) => row.shared_link.endsWith("/CUTOVER/"))).toMatchObject({
      video_details_id: detailsId,
      delivery_mode: "media",
      cache_hit: false,
    });

    const audit = await live<Array<{ status: string; evidence: Record<string, unknown> | string }>>`SELECT status, evidence
      FROM migration_audit WHERE migration_id = '002_media_cache_rebuild'`;
    expect(audit[0]?.status).toBe("complete");
    expect(readObject(audit[0]?.evidence).cutover).toMatchObject({ status: "complete", online: true });
    const staging = await live<Array<{ videos_new: string | null; identity: string | null; parser: string | null }>>`SELECT
      to_regclass('public.videos_new')::text AS videos_new,
      to_regclass('public.legacy_video_identity')::text AS identity,
      to_regprocedure('public.parse_legacy_video_identity(text)')::text AS parser`;
    expect(staging[0]).toEqual({ videos_new: null, identity: null, parser: null });
  } finally {
    if (live) await live.close();
    try { await admin.unsafe(`DROP DATABASE IF EXISTS "${databaseName}" WITH (FORCE)`); } finally { await admin.close(); }
  }
}, 30_000);

async function seedLegacyDatabase(sql: SQL): Promise<void> {
  await sql`CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,
    registered_at BIGINT,
    lang VARCHAR NOT NULL DEFAULT 'en',
    link VARCHAR,
    file_mode BOOLEAN NOT NULL DEFAULT FALSE,
    ad_count BIGINT NOT NULL DEFAULT 0,
    ad_cooldown BIGINT NOT NULL DEFAULT 0
  )`;
  await sql`CREATE TABLE videos (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    downloaded_at BIGINT,
    video_link VARCHAR NOT NULL,
    is_images BOOLEAN NOT NULL DEFAULT FALSE,
    is_processed BOOLEAN NOT NULL DEFAULT FALSE,
    is_inline BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await sql`CREATE TABLE music (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    downloaded_at BIGINT,
    video_id BIGINT NOT NULL
  )`;
  await sql`INSERT INTO users (user_id, registered_at, lang, file_mode) VALUES (1, 1, 'en', FALSE)`;
  await sql`INSERT INTO videos (user_id, downloaded_at, video_link, is_images, is_processed, is_inline) VALUES
    (1, 10, 'https://www.tiktok.com/@creator/video/1001', FALSE, FALSE, FALSE),
    (1, 20, 'https://www.instagram.com/p/ABC_1/', TRUE, FALSE, TRUE),
    (1, 30, 'https://vm.tiktok.com/UNRESOLVED/', FALSE, TRUE, FALSE)`;
}

function requiredDatabaseUrl(): string {
  const value = Bun.env.POSTGRES_MIGRATION_TEST_ADMIN_URL?.trim();
  if (!value) throw new Error("POSTGRES_MIGRATION_TEST_ADMIN_URL is required when migration integration tests are enabled");
  const parsed = new URL(value);
  if (!['postgres:', 'postgresql:'].includes(parsed.protocol)) throw new Error("POSTGRES_MIGRATION_TEST_ADMIN_URL must use PostgreSQL");
  return value;
}

function databaseUrlFor(adminUrl: string, databaseName: string): string {
  const url = new URL(adminUrl);
  url.pathname = `/${databaseName}`;
  return url.toString();
}

function readObject(value: unknown): Record<string, unknown> {
  if (typeof value === "string") return readObject(JSON.parse(value));
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
