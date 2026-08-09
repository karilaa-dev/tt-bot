export {};

const migrationMode = Bun.env.MIGRATE_LEGACY_ON_START?.trim().toLowerCase();

if (migrationMode && migrationMode !== "confirmed") {
  throw new Error("MIGRATE_LEGACY_ON_START must be set to 'confirmed' or left unset");
}

if (migrationMode === "confirmed") {
  console.log("[startup] Running the resumable legacy database migration before starting the bot");
  await import("./migrate-legacy.ts");
  console.log("[startup] Legacy database migration complete; starting the bot");
}

await import("../src/main.ts");
