import { expect, test } from "bun:test";
import type { SQL } from "bun";
import { LEGACY_MIGRATION_COMMAND, runMigrations } from "../src/db/migrations.ts";

test("normal startup rejects a legacy rebuild without mutating it", async () => {
  const statements: string[] = [];
  const sql = fakeSql(statements, [
    ...columns("videos", { pk_id: "bigint", video_link: "character varying", is_images: "boolean", is_processed: "boolean", is_inline: "boolean" }),
  ]);
  await expect(runMigrations(sql)).rejects.toThrow(LEGACY_MIGRATION_COMMAND);
  expect(statements).toHaveLength(1);
  expect(statements[0]).toStartWith("SELECT table_name, column_name, data_type");
});

test("initializes the final cache schema as separate statements", async () => {
  const statements: string[] = [];
  let informationQueries = 0;
  const finalColumns = [
    ...columns("users", { user_id: "bigint", registered_at: "bigint", lang: "character varying", link: "character varying", file_mode: "boolean" }),
    ...columns("video_details", {
      pk_id: "bigint", platform: "character varying", platform_video_id: "character varying", creator_username: "character varying",
      content_type: "character varying", canonical_link: "text", telegram_bot_id: "bigint", telegram_files: "jsonb",
      likes_display: "character varying", views_display: "character varying", first_downloaded_at: "bigint", last_used_at: "bigint",
      metadata_refreshed_at: "bigint", file_ids_updated_at: "bigint", cache_version: "bigint",
    }),
    ...columns("videos", {
      pk_id: "bigint", user_id: "bigint", video_details_id: "bigint", downloaded_at: "bigint", shared_link: "text",
      media_kind: "character varying", delivery_surface: "character varying", delivery_mode: "character varying", cache_hit: "boolean",
    }),
    ...columns("music", { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_id: "bigint" }),
  ];
  const execute = async (strings: TemplateStringsArray): Promise<unknown[]> => {
    const statement = strings.join("?").replace(/\s+/gu, " ").trim();
    statements.push(statement);
    if (statement.startsWith("SELECT table_name, column_name, data_type")) return informationQueries++ === 0 ? [] : finalColumns;
    return [];
  };
  const sql = Object.assign(execute, { unsafe: async (statement: string) => { statements.push(statement.replace(/\s+/gu, " ").trim()); return []; } }) as unknown as SQL;

  await runMigrations(sql);

  expect(statements.some((statement) => statement.startsWith("CREATE TABLE IF NOT EXISTS video_details"))).toBe(true);
  expect(statements.some((statement) => statement.startsWith("CREATE TABLE IF NOT EXISTS videos") && statement.includes("shared_link TEXT NOT NULL"))).toBe(true);
  expect(statements.at(-1)).toStartWith("INSERT INTO schema_migrations");
});

function fakeSql(statements: string[], informationRows: unknown[]): SQL {
  const execute = async (strings: TemplateStringsArray): Promise<unknown[]> => {
    const statement = strings.join("?").replace(/\s+/gu, " ").trim();
    statements.push(statement);
    return statement.startsWith("SELECT table_name, column_name, data_type") ? informationRows : [];
  };
  return Object.assign(execute, { unsafe: async () => [] }) as unknown as SQL;
}

function columns(tableName: string, definitions: Record<string, string>): Array<{ table_name: string; column_name: string; data_type: string }> {
  return Object.entries(definitions).map(([column_name, data_type]) => ({ table_name: tableName, column_name, data_type }));
}
