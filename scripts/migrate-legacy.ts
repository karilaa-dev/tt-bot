import { runLegacyMigration } from "../src/db/legacy-migration.ts";

const databaseUrl = Bun.env.DB_URL?.trim();
if (!databaseUrl) throw new Error("DB_URL is required");
const availableRaw = Bun.env.LEGACY_MIGRATION_AVAILABLE_BYTES?.trim();
if (!availableRaw || !/^[0-9]+$/u.test(availableRaw)) {
  throw new Error("LEGACY_MIGRATION_AVAILABLE_BYTES is required; set it to verified free bytes on the PostgreSQL data filesystem");
}
const result = await runLegacyMigration(databaseUrl, {
  backupConfirmed: Bun.env.LEGACY_MIGRATION_BACKUP_CONFIRMED === "yes",
  botStopped: Bun.env.LEGACY_MIGRATION_BOT_STOPPED === "yes",
  availableBytes: BigInt(availableRaw),
  onProgress: (message) => console.log(`[legacy-migration] ${message}`),
});
console.log(JSON.stringify(result, null, 2));
