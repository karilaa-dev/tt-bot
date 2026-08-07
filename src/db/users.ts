import type { Database } from "./client.ts";
import type { Language } from "../locales.ts";

export interface UserRecord {
  userId: number;
  registeredAt: number | null;
  lang: Language;
  link: string | null;
  fileMode: boolean;
}

export interface UserRegistration {
  user: UserRecord;
  created: boolean;
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
  return (await registerUser(db, userId, lang, link)).user;
}

export async function registerUser(db: Database, userId: number, lang: Language, link: string | null = null): Promise<UserRegistration> {
  const rows = await db.sql<Array<UserRow>>`INSERT INTO users (user_id, registered_at, lang, link, file_mode)
    VALUES (${userId}, ${Math.floor(Date.now() / 1000)}, ${lang}, ${link}, FALSE)
    ON CONFLICT (user_id) DO NOTHING
    RETURNING user_id, registered_at, lang, link, file_mode`;
  const inserted = rows[0];
  if (inserted) return { user: mapUser(inserted), created: true };
  const existing = await getUser(db, userId);
  if (!existing) throw new Error(`Failed to register user ${userId}`);
  return { user: existing, created: false };
}

export async function toggleUserMode(db: Database, userId: number): Promise<UserRecord> {
  const rows = await db.sql<Array<UserRow>>`UPDATE users SET file_mode = NOT file_mode
    WHERE user_id = ${userId}
    RETURNING user_id, registered_at, lang, link, file_mode`;
  const user = rows[0];
  if (!user) throw new Error(`Cannot toggle mode for unregistered chat ${userId}`);
  return mapUser(user);
}

export async function updateUserLanguage(db: Database, userId: number, lang: Language): Promise<UserRecord> {
  const rows = await db.sql<Array<UserRow>>`UPDATE users SET lang = ${lang}
    WHERE user_id = ${userId}
    RETURNING user_id, registered_at, lang, link, file_mode`;
  const user = rows[0];
  if (!user) throw new Error(`Cannot update language for unregistered chat ${userId}`);
  return mapUser(user);
}

export async function getUserIds(db: Database, onlyPositive = false): Promise<number[]> {
  const rows = onlyPositive
    ? await db.sql<Array<{ user_id: bigint | number | string }>>`SELECT user_id FROM users WHERE user_id > 0 ORDER BY user_id`
    : await db.sql<Array<{ user_id: bigint | number | string }>>`SELECT user_id FROM users ORDER BY user_id`;
  return rows.map((row) => Number(row.user_id));
}
