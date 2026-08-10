import { runLegacyMigration } from "../src/db/legacy-migration.ts";

const databaseUrl = Bun.env.DB_URL?.trim();
if (!databaseUrl) throw new Error("DB_URL is required");
const availableRaw = Bun.env.LEGACY_MIGRATION_AVAILABLE_BYTES?.trim();
if (availableRaw && !/^[0-9]+$/u.test(availableRaw)) {
  throw new Error("LEGACY_MIGRATION_AVAILABLE_BYTES must contain a positive integer when supplied");
}
const commandConfirmed = Bun.argv.slice(2).includes("--confirm");
const startupConfirmed = Bun.env.MIGRATE_LEGACY_ON_START?.trim().toLowerCase() === "confirmed";
const result = await runLegacyMigration(databaseUrl, {
  preflightConfirmed: commandConfirmed || startupConfirmed,
  availableBytes: availableRaw ? BigInt(availableRaw) : undefined,
  skipWhenMigrationNotNeeded: true,
  onProgress: (message) => console.log(`[legacy-migration] ${message}`),
});
console.log(JSON.stringify(result, null, 2));
