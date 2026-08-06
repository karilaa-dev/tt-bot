import type { SQL } from "bun";

const expectedColumns: Record<string, Record<string, string>> = {
  users: { user_id: "bigint", registered_at: "bigint", lang: "character varying", link: "character varying", file_mode: "boolean" },
  videos: { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_link: "character varying", is_images: "boolean", is_processed: "boolean", is_inline: "boolean" },
  music: { pk_id: "bigint", user_id: "bigint", downloaded_at: "bigint", video_id: "bigint" },
};

export async function runMigrations(sql: SQL): Promise<void> {
  await sql`CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR PRIMARY KEY,
    applied_at BIGINT NOT NULL
  )`;
  await sql`CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    registered_at BIGINT,
    lang VARCHAR NOT NULL DEFAULT 'en',
    link VARCHAR,
    file_mode BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await sql`CREATE TABLE IF NOT EXISTS videos (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    downloaded_at BIGINT,
    video_link VARCHAR NOT NULL,
    is_images BOOLEAN NOT NULL DEFAULT FALSE,
    is_processed BOOLEAN NOT NULL DEFAULT FALSE,
    is_inline BOOLEAN NOT NULL DEFAULT FALSE
  )`;
  await sql`CREATE TABLE IF NOT EXISTS music (
    pk_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id),
    downloaded_at BIGINT,
    video_id BIGINT NOT NULL
  )`;

  const rows = await sql<Array<{ table_name: string; column_name: string; data_type: string }>>`
    SELECT table_name, column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name IN ('users', 'videos', 'music')
  `;
  const found = new Map<string, Map<string, string>>();
  for (const row of rows) {
    const columns = found.get(row.table_name) ?? new Map<string, string>();
    columns.set(row.column_name, row.data_type);
    found.set(row.table_name, columns);
  }
  for (const [table, columns] of Object.entries(expectedColumns)) {
    const actual = found.get(table) ?? new Map<string, string>();
    const missing = Object.keys(columns).filter((column) => !actual.has(column));
    if (missing.length) throw new Error(`Database table ${table} is missing columns: ${missing.join(', ')}`);
    const mismatched = Object.entries(columns).filter(([column, expected]) => actual.get(column) !== expected);
    if (mismatched.length) throw new Error(`Database table ${table} has incompatible column types: ${mismatched.map(([column, expected]) => `${column}=${actual.get(column)} (expected ${expected})`).join(", ")}`);
  }
  await sql`INSERT INTO schema_migrations (version, applied_at)
    VALUES ('001_existing_schema', ${Math.floor(Date.now() / 1000)})
    ON CONFLICT (version) DO NOTHING`;
}
