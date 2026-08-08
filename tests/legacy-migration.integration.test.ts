import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { SQL } from "bun";
import { LEGACY_REBUILD_MIGRATION_ID, runLegacyMigration } from "../src/db/legacy-migration.ts";

const adminUrl = Bun.env.TEST_DB_URL || Bun.env.TEST_DB_ADMIN_URL;
const integration = adminUrl ? describe : describe.skip;

integration("PostgreSQL legacy rebuild", () => {
  let admin: SQL;
  const databases: string[] = [];

  beforeAll(() => { admin = new SQL(adminUrl!); });
  afterAll(async () => {
    for (const name of databases) await admin.unsafe(`DROP DATABASE IF EXISTS "${name}" WITH (FORCE)`);
    await admin.close();
  });

  test("keeps unsafe DDL and transactions on a reserved Bun SQL connection", async () => {
    const sql = new SQL(adminUrl!);
    const reserved = await sql.reserve();
    try {
      const owner = await reserved<Array<{ pid: number }>>`SELECT pg_backend_pid() AS pid`;
      await reserved.unsafe("CREATE TEMP TABLE reserved_capability_probe (value INTEGER) ON COMMIT PRESERVE ROWS");
      await reserved.begin(async (tx) => {
        const transaction = await tx<Array<{ pid: number }>>`SELECT pg_backend_pid() AS pid`;
        expect(transaction[0]?.pid).toBe(owner[0]?.pid);
        await tx`INSERT INTO reserved_capability_probe (value) VALUES (1)`;
      });
      const rows = await reserved<Array<{ count: string }>>`SELECT COUNT(*)::text AS count FROM reserved_capability_probe`;
      expect(rows[0]?.count).toBe("1");
    } finally {
      reserved.release();
      await sql.close();
    }
  });

  test("resumes both batch phases, preserves every row, audits removed data, and cuts over idempotently", async () => {
    const fixture = await createFixture(admin, databases, "resume");
    const first = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, maxBatchesPerPhaseRun: 1 }));
    expect(first).toMatchObject({ status: "paused", phase: "identity" });

    const second = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "identity" }));
    expect(second).toMatchObject({ status: "paused", phase: "identity" });

    const third = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, maxBatchesPerPhaseRun: 1 }));
    expect(third).toMatchObject({ status: "paused", phase: "details" });

    const details = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "details" }));
    expect(details).toMatchObject({ status: "paused", phase: "details" });

    const copy = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, maxBatchesPerPhaseRun: 1 }));
    expect(copy).toMatchObject({ status: "paused", phase: "copy" });

    const completed = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }));
    expect(completed.status).toBe("complete");
    const again = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }));
    expect(again.status).toBe("complete");

    const sql = new SQL(fixture.url);
    try {
      const count = await sql<Array<{ count: string }>>`SELECT COUNT(*)::text AS count FROM videos`;
      expect(count[0]?.count).toBe("7");
      const audit = await sql<Array<{ status: string; evidence: Record<string, any> }>>`SELECT status, evidence FROM migration_audit WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
      expect(audit[0]?.status).toBe("complete");
      expect(audit[0]?.evidence.source_audit).toMatchObject({ processed_true_count: "2", images_true_count: "2", inline_true_count: "2" });
      expect(audit[0]?.evidence.removed_user_columns).toMatchObject({ nonzero_ad_count: "1", nonzero_ad_cooldown_count: "1" });
      expect(Number(audit[0]?.evidence.identity.unresolved_rows)).toBeGreaterThanOrEqual(2);
      expect(audit[0]?.evidence.verification).toMatchObject({ row_count: "7", orphaned_users: "0", orphaned_details: "0" });
      const removed = await sql<Array<{ column_name: string }>>`SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND ((table_name = 'videos' AND column_name IN ('video_link','is_images','is_processed','is_inline'))
          OR (table_name = 'users' AND column_name IN ('ad_count','ad_cooldown')))`;
      expect(removed).toHaveLength(0);
      const unresolved = await sql<Array<{ count: string }>>`SELECT COUNT(*)::text AS count FROM videos WHERE video_details_id IS NULL`;
      expect(Number(unresolved[0]?.count)).toBeGreaterThanOrEqual(2);
      const inserted = await sql<Array<{ pk_id: string }>>`INSERT INTO videos (user_id, downloaded_at, shared_link, media_kind, delivery_surface, delivery_mode)
        VALUES (1, 999, 'https://example.test/new', 'video', 'chat', 'media') RETURNING pk_id::text`;
      expect(inserted[0]?.pk_id).toBe("9");
    } finally { await sql.close(); }
  }, 30_000);

  test("verification failure prevents cutover", async () => {
    const fixture = await createFixture(admin, databases, "verification");
    await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "copy" }));
    const sql = new SQL(fixture.url);
    await sql`DELETE FROM videos_new WHERE pk_id = 4`;
    await sql.close();
    await expect(runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }))).rejects.toThrow("Verification failed");
    const check = new SQL(fixture.url);
    try {
      const columns = await check<Array<{ column_name: string }>>`SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'videos' AND column_name = 'video_link'`;
      expect(columns).toHaveLength(1);
      await check.begin(async (tx) => {
        await tx`DROP TABLE IF EXISTS videos_new`;
        await tx`DELETE FROM legacy_migration_state
          WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID} AND phase IN ('copy', 'constraints', 'verification')`;
      });
    } finally { await check.close(); }
    const recovered = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }));
    expect(recovered.status).toBe("complete");
  }, 30_000);

  test("does not repeat a completed details phase", async () => {
    const fixture = await createFixture(admin, databases, "details-resume");
    const paused = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "details" }));
    expect(paused).toMatchObject({ status: "paused", phase: "details" });

    const sql = new SQL(fixture.url);
    try {
      await sql.unsafe(`CREATE FUNCTION reject_repeated_detail_build() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'details phase repeated'; END $$`);
      await sql`CREATE TRIGGER reject_repeated_detail_build BEFORE INSERT ON video_details
        FOR EACH STATEMENT EXECUTE FUNCTION reject_repeated_detail_build()`;
    } finally { await sql.close(); }

    const completed = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }));
    expect(completed.status).toBe("complete");
  }, 30_000);

  test("resumes both detail aggregation and detail finalization from committed batches", async () => {
    const fixture = await createFixture(admin, databases, "details-batches");
    const seed = new SQL(fixture.url);
    try {
      // The typed URL and later /share/item URL for the same post land in
      // separate batches. The latter has no canonical candidate and must remain
      // unknown evidence rather than erase the unambiguous typed candidate.
      await seed`INSERT INTO videos (pk_id, user_id, downloaded_at, video_link, is_images, is_processed, is_inline)
        VALUES (3, 1, 103, 'https://www.tiktok.com/@creator/video/126', FALSE, FALSE, FALSE)`;
    } finally { await seed.close(); }
    await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "identity" }));

    let sawFinalizeCheckpoint = false;
    for (let attempt = 0; attempt < 6; attempt++) {
      const paused = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, maxBatchesPerPhaseRun: 1 }));
      expect(paused).toMatchObject({ status: "paused", phase: "details" });
      const sql = new SQL(fixture.url);
      try {
        const states = await sql<Array<{ phase: string; last_pk: string; counters: Record<string, unknown> }>>`SELECT
            phase, last_pk::text, counters
          FROM legacy_migration_state
          WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID} AND phase IN ('details_aggregate', 'details')`;
        const aggregate = states.find((state) => state.phase === "details_aggregate");
        const finalize = states.find((state) => state.phase === "details");
        if (aggregate?.counters.complete === true && finalize && finalize.counters.complete !== true) {
          expect(BigInt(finalize.last_pk)).toBeGreaterThan(0n);
          sawFinalizeCheckpoint = true;
          break;
        }
      } finally { await sql.close(); }
    }
    expect(sawFinalizeCheckpoint).toBe(true);

    const details = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "details" }));
    expect(details).toMatchObject({ status: "paused", phase: "details" });
    const sql = new SQL(fixture.url);
    try {
      const states = await sql<Array<{ phase: string; counters: Record<string, unknown> }>>`SELECT phase, counters
        FROM legacy_migration_state
        WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID} AND phase IN ('details_aggregate', 'details')`;
      expect(states).toHaveLength(2);
      expect(states.every((state) => state.counters.complete === true)).toBe(true);
      const detailRows = await sql<Array<{ count: string }>>`SELECT COUNT(*)::text AS count FROM video_details`;
      expect(detailRows[0]?.count).toBe("5");
      const canonical = await sql<Array<{ canonical_link: string | null }>>`SELECT canonical_link FROM video_details
        WHERE platform = 'tiktok' AND platform_video_id = '126'`;
      expect(canonical[0]?.canonical_link).toBe("https://www.tiktok.com/@_/video/126");
    } finally { await sql.close(); }
  }, 30_000);

  test("detects in-place source updates under the cutover lock", async () => {
    const fixture = await createFixture(admin, databases, "source-update");
    const paused = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2, stopAfterPhase: "verification" }));
    expect(paused).toMatchObject({ status: "paused", phase: "verification" });

    const sql = new SQL(fixture.url);
    try {
      await sql`UPDATE videos SET video_link = video_link || '?changed=1' WHERE pk_id = 1`;
    } finally { await sql.close(); }

    const failure = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }))
      .then(() => null, (error: unknown) => error);
    expect(failure).toBeInstanceOf(Error);
    expect(String(failure)).toContain("Source changed after verification; cutover aborted");
    const check = new SQL(fixture.url);
    try {
      const legacy = await check<Array<{ exists: boolean }>>`SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'videos' AND column_name = 'video_link'
      ) AS exists`;
      expect(legacy[0]?.exists).toBe(true);
    } finally { await check.close(); }
  }, 30_000);

  test("migrates TypeScript-era users tables without advertising columns", async () => {
    const fixture = await createFixture(admin, databases, "typescript", { advertisingColumns: false });
    const completed = await runLegacyMigration(fixture.url, migrationOptions({ batchSize: 2 }));
    expect(completed.status).toBe("complete");

    const sql = new SQL(fixture.url);
    try {
      const audit = await sql<Array<{ evidence: Record<string, any> }>>`SELECT evidence FROM migration_audit
        WHERE migration_id = ${LEGACY_REBUILD_MIGRATION_ID}`;
      expect(audit[0]?.evidence.removed_user_columns).toMatchObject({
        nonzero_ad_count: "0",
        nonzero_ad_cooldown_count: "0",
        ad_count_column_present: "false",
        ad_cooldown_column_present: "false",
      });
      const history = await sql<Array<{ count: string }>>`SELECT COUNT(*)::text AS count FROM videos`;
      expect(history[0]?.count).toBe("7");
    } finally { await sql.close(); }
  }, 30_000);
});

function migrationOptions(overrides: Record<string, unknown> = {}) {
  return { backupConfirmed: true, botStopped: true, availableBytes: 10_000_000_000n, ...overrides } as Parameters<typeof runLegacyMigration>[1];
}

async function createFixture(
  admin: SQL,
  databases: string[],
  suffix: string,
  options: { advertisingColumns?: boolean } = {},
): Promise<{ url: string }> {
  const name = `ttbot_legacy_${suffix}_${process.pid}_${Date.now()}`;
  databases.push(name);
  await admin.unsafe(`CREATE DATABASE "${name}"`);
  const url = new URL(adminUrl!); url.pathname = `/${name}`;
  const sql = new SQL(url.toString());
  await sql`CREATE TABLE users (
    user_id BIGINT PRIMARY KEY, registered_at BIGINT, lang VARCHAR NOT NULL DEFAULT 'en', link VARCHAR,
    file_mode BOOLEAN NOT NULL DEFAULT FALSE, ad_count INTEGER NOT NULL DEFAULT 0, ad_cooldown BIGINT NOT NULL DEFAULT 0
  )`;
  await sql`CREATE TABLE videos (
    pk_id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id), downloaded_at BIGINT,
    video_link VARCHAR NOT NULL, is_images BOOLEAN NOT NULL DEFAULT FALSE,
    is_processed BOOLEAN NOT NULL DEFAULT FALSE, is_inline BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await sql`CREATE TABLE music (
    pk_id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(user_id), downloaded_at BIGINT, video_id BIGINT NOT NULL
  )`;
  await sql`INSERT INTO users (user_id, registered_at, ad_count, ad_cooldown) VALUES (1, 1, 2, 0), (2, 2, 0, 10)`;
  if (options.advertisingColumns === false) {
    await sql`ALTER TABLE users DROP COLUMN ad_count`;
    await sql`ALTER TABLE users DROP COLUMN ad_cooldown`;
  }
  const longQuery = "x".repeat(700);
  await sql`INSERT INTO videos (pk_id, user_id, downloaded_at, video_link, is_images, is_processed, is_inline) VALUES
    (1, 1, 100, 'https://vm.tiktok.com/EXPIRED/', FALSE, FALSE, FALSE),
    (2, 1, 101, 'https://www.tiktok.com/@creator/video/123', FALSE, TRUE, FALSE),
    (4, 1, 102, 'https://www.tiktok.com/@creator/photo/124', TRUE, TRUE, TRUE),
    (5, 2, NULL, 'https://www.tiktok.com/@creator/video/125?item_id=999', FALSE, FALSE, FALSE),
    (6, 2, 104, 'https://www.instagram.com/reel/ABC123/', FALSE, FALSE, TRUE),
    (7, 2, 105, ${`https://www.instagram.com/p/POST_1/?${longQuery}`}, TRUE, FALSE, FALSE),
    (8, 2, 106, 'https://www.tiktok.com/share/item/126', FALSE, FALSE, FALSE)`;
  await sql`SELECT setval('videos_pk_id_seq', 8, TRUE)`;
  await sql.close();
  return { url: url.toString() };
}
