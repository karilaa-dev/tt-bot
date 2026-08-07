import { expect, test } from "bun:test";
import type { SQL } from "bun";
import { runMigrations } from "../src/db/migrations.ts";

test("runs each schema migration as a separate SQL statement", async () => {
  const statements: string[] = [];
  const execute = async (strings: TemplateStringsArray): Promise<unknown[]> => {
    const statement = strings.join("?").replace(/\s+/gu, " ").trim();
    statements.push(statement);
    if (!statement.startsWith("SELECT table_name, column_name, data_type")) return [];
    return [
      ...columns("users", { user_id: "bigint", registered_at: "bigint", lang: "character varying", link: "character varying", file_mode: "boolean" }),
      ...columns("videos", { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_link: "character varying", is_images: "boolean", is_processed: "boolean", is_inline: "boolean" }),
      ...columns("music", { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_id: "bigint" }),
    ];
  };
  const sql = Object.assign(execute, {
    file: () => { throw new Error("runMigrations must not rely on multi-statement SQL files"); },
  }) as unknown as SQL;

  await runMigrations(sql);

  const creates = statements.filter((statement) => statement.startsWith("CREATE TABLE"));
  expect(creates).toHaveLength(4);
  expect(creates.map((statement) => statement.match(/^CREATE TABLE IF NOT EXISTS (\w+)/u)?.[1])).toEqual([
    "schema_migrations", "users", "videos", "music",
  ]);
  expect(statements.at(-1)).toStartWith("INSERT INTO schema_migrations");
});

function columns(tableName: string, definitions: Record<string, string>): Array<{ table_name: string; column_name: string; data_type: string }> {
  return Object.entries(definitions).map(([column_name, data_type]) => ({ table_name: tableName, column_name, data_type }));
}
