import type { Database } from "./client.ts";
import type { Language } from "../locales.ts";

export interface UserRecord {
  userId: number;
  registeredAt: number | null;
  lang: Language;
  link: string | null;
  fileMode: boolean;
}

interface UserRow { user_id: bigint | number | string; registered_at: bigint | number | string | null; lang: string; link: string | null; file_mode: boolean }

function mapUser(row: UserRow): UserRecord {
  return { userId: Number(row.user_id), registeredAt: row.registered_at === null ? null : Number(row.registered_at), lang: row.lang as Language, link: row.link, fileMode: row.file_mode };
}

export async function getUser(db: Database, userId: number): Promise<UserRecord | null> {
  const rows = await db.sql<Array<UserRow>>`SELECT user_id, registered_at, lang, link, file_mode FROM users WHERE user_id = ${userId}`;
  return rows[0] ? mapUser(rows[0]) : null;
}

export async function createUser(db: Database, userId: number, lang: Language, link: string | null = null): Promise<UserRecord> {
  await db.sql`INSERT INTO users (user_id, registered_at, lang, link, file_mode)
    VALUES (${userId}, ${Math.floor(Date.now() / 1000)}, ${lang}, ${link}, FALSE)
    ON CONFLICT (user_id) DO NOTHING`;
  const user = await getUser(db, userId);
  if (!user) throw new Error(`Failed to create user ${userId}`);
  return user;
}

export async function updateUserMode(db: Database, userId: number, fileMode: boolean): Promise<void> {
  await db.sql`UPDATE users SET file_mode = ${fileMode} WHERE user_id = ${userId}`;
}

export async function updateUserLanguage(db: Database, userId: number, lang: Language): Promise<void> {
  await db.sql`UPDATE users SET lang = ${lang} WHERE user_id = ${userId}`;
}

export async function getUserIds(db: Database, onlyPositive = true): Promise<number[]> {
  const rows = onlyPositive
    ? await db.sql<Array<{ user_id: bigint | number | string }>>`SELECT user_id FROM users WHERE user_id > 0 ORDER BY user_id`
    : await db.sql<Array<{ user_id: bigint | number | string }>>`SELECT user_id FROM users ORDER BY user_id`;
  return rows.map((row) => Number(row.user_id));
}
