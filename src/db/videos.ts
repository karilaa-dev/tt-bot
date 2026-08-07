import type { Database } from "./client.ts";

export async function addVideo(db: Database, userId: number, link: string, isImages: boolean, isProcessed = false, isInline = false): Promise<void> {
  await db.sql`INSERT INTO videos (user_id, downloaded_at, video_link, is_images, is_processed, is_inline)
    VALUES (${userId}, ${Math.floor(Date.now() / 1000)}, ${link}, ${isImages}, ${isProcessed}, ${isInline})`;
}
