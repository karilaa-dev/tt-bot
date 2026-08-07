import type { Database } from "./client.ts";

export async function addMusic(db: Database, userId: number, videoId: bigint): Promise<void> {
  await db.sql`INSERT INTO music (user_id, downloaded_at, video_id)
    VALUES (${userId}, ${Math.floor(Date.now() / 1000)}, ${videoId})`;
}
