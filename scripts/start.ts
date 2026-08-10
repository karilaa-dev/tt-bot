import { runLegacyMigration } from "../src/db/legacy-migration.ts";
import { runBot } from "../src/main.ts";

const migrationMode = Bun.env.MIGRATE_LEGACY_ON_START?.trim().toLowerCase();

if (migrationMode && migrationMode !== "confirmed") {
  throw new Error("MIGRATE_LEGACY_ON_START must be set to 'confirmed' or left unset");
}

if (migrationMode === "confirmed") {
  const databaseUrl = Bun.env.DB_URL?.trim();
  if (!databaseUrl) throw new Error("DB_URL is required");
  const availableRaw = Bun.env.LEGACY_MIGRATION_AVAILABLE_BYTES?.trim();
  if (availableRaw && !/^[0-9]+$/u.test(availableRaw)) {
    throw new Error("LEGACY_MIGRATION_AVAILABLE_BYTES must contain a positive integer when supplied");
  }

  console.log("[startup] Preparing the online legacy database migration");
  let markBotReady!: () => void;
  let rejectBotReady!: (error: unknown) => void;
  const botReady = new Promise<void>((resolve, reject) => {
    markBotReady = resolve;
    rejectBotReady = reject;
  });
  const migrationTask = runLegacyMigration(databaseUrl, {
    preflightConfirmed: true,
    availableBytes: availableRaw ? BigInt(availableRaw) : undefined,
    skipWhenMigrationNotNeeded: true,
    onBotReady: markBotReady,
    onProgress: (message) => console.log(`[legacy-migration] ${message}`),
  });
  // Mark the task handled immediately, while still passing the original promise
  // to runBot so a later failure shuts the serving process down cleanly.
  void migrationTask.catch((error) => rejectBotReady(error));
  void migrationTask.then((result) => {
    console.log(`[startup] Legacy migration ${result.status} at phase ${result.phase}`);
  }).catch(() => undefined);
  await botReady;
  console.log("[startup] Database write path is ready; starting the bot while any history backfill continues");
  await runBot({ allowLegacyMigration: true, backgroundTasks: [migrationTask] });
} else {
  await runBot();
}
