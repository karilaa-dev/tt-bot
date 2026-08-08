import type { Database } from "./client.ts";

export type VideoPlatform = "tiktok" | "instagram";
export type MediaKind = "video" | "images";
export type DeliverySurface = "chat" | "inline";
export type DeliveryMode = "media" | "document";
export type TelegramMediaType = "photo" | "video";

export interface TelegramFileReference {
  position: number;
  media_type: TelegramMediaType;
  file_id: string;
  file_unique_id: string;
}

export interface VideoDetailsRecord {
  id: bigint;
  platform: VideoPlatform;
  platformVideoId: string;
  creatorUsername: string | null;
  contentType: string | null;
  canonicalLink: string | null;
  telegramBotId: bigint | null;
  telegramFiles: TelegramFileReference[] | null;
  likesDisplay: string | null;
  viewsDisplay: string | null;
  firstDownloadedAt: number | null;
  lastUsedAt: number | null;
  metadataRefreshedAt: number | null;
  fileIdsUpdatedAt: number | null;
  cacheVersion: bigint;
}

interface DetailsRow {
  pk_id: bigint | string;
  platform: VideoPlatform;
  platform_video_id: string;
  creator_username: string | null;
  content_type: string | null;
  canonical_link: string | null;
  telegram_bot_id: bigint | string | null;
  telegram_files: unknown;
  likes_display: string | null;
  views_display: string | null;
  first_downloaded_at: bigint | string | number | null;
  last_used_at: bigint | string | number | null;
  metadata_refreshed_at: bigint | string | number | null;
  file_ids_updated_at: bigint | string | number | null;
  cache_version: bigint | string;
}

export interface RecordDownloadInput {
  userId: number;
  platform: VideoPlatform;
  platformVideoId: string;
  sharedLink: string;
  mediaKind: MediaKind;
  deliverySurface: DeliverySurface;
  deliveryMode: DeliveryMode;
  cacheHit: boolean;
  creatorUsername?: string | null;
  contentType?: string | null;
  canonicalLink?: string | null;
  likesDisplay?: string | null;
  viewsDisplay?: string | null;
  metadataRefreshedAt?: number | null;
  telegramBotId?: number;
  telegramFiles?: TelegramFileReference[];
  downloadedAt?: number;
}

export async function getVideoDetails(db: Database, platform: VideoPlatform, platformVideoId: string): Promise<VideoDetailsRecord | null> {
  const rows = await db.sql<DetailsRow[]>`SELECT * FROM video_details
    WHERE platform = ${platform} AND platform_video_id = ${platformVideoId}`;
  return rows[0] ? mapDetails(rows[0]) : null;
}

/** Persist detail/cache changes and the successful request event atomically. */
export async function recordDownload(db: Database, input: RecordDownloadInput): Promise<VideoDetailsRecord> {
  const now = input.downloadedAt ?? Math.floor(Date.now() / 1000);
  return db.sql.begin(async (tx) => {
    const hasFiles = input.telegramFiles !== undefined;
    const filesJson = hasFiles ? JSON.stringify(input.telegramFiles) : null;
    const rows = await tx<DetailsRow[]>`INSERT INTO video_details (
        platform, platform_video_id, creator_username, content_type, canonical_link,
        telegram_bot_id, telegram_files, likes_display, views_display,
        first_downloaded_at, last_used_at, metadata_refreshed_at, file_ids_updated_at, cache_version
      ) VALUES (
        ${input.platform}, ${input.platformVideoId}, ${input.creatorUsername ?? null}, ${input.contentType ?? null},
        ${input.canonicalLink ?? null}, ${hasFiles ? input.telegramBotId ?? null : null},
        ${filesJson}::jsonb, ${input.likesDisplay ?? null}, ${input.viewsDisplay ?? null},
        ${now}, ${now}, ${input.metadataRefreshedAt ?? null}, ${hasFiles ? now : null}, ${hasFiles ? 1 : 0}
      )
      ON CONFLICT (platform, platform_video_id) DO UPDATE SET
        creator_username = COALESCE(EXCLUDED.creator_username, video_details.creator_username),
        content_type = COALESCE(EXCLUDED.content_type, video_details.content_type),
        canonical_link = COALESCE(EXCLUDED.canonical_link, video_details.canonical_link),
        telegram_bot_id = CASE WHEN ${hasFiles} THEN EXCLUDED.telegram_bot_id ELSE video_details.telegram_bot_id END,
        telegram_files = CASE WHEN ${hasFiles} THEN EXCLUDED.telegram_files ELSE video_details.telegram_files END,
        likes_display = CASE WHEN ${input.likesDisplay !== undefined} THEN EXCLUDED.likes_display ELSE video_details.likes_display END,
        views_display = CASE WHEN ${input.viewsDisplay !== undefined} THEN EXCLUDED.views_display ELSE video_details.views_display END,
        first_downloaded_at = COALESCE(video_details.first_downloaded_at, EXCLUDED.first_downloaded_at),
        last_used_at = EXCLUDED.last_used_at,
        metadata_refreshed_at = CASE WHEN ${input.metadataRefreshedAt !== undefined} THEN EXCLUDED.metadata_refreshed_at ELSE video_details.metadata_refreshed_at END,
        file_ids_updated_at = CASE WHEN ${hasFiles} THEN EXCLUDED.file_ids_updated_at ELSE video_details.file_ids_updated_at END,
        cache_version = video_details.cache_version + CASE WHEN ${hasFiles} THEN 1 ELSE 0 END
      RETURNING *`;
    const details = rows[0];
    if (!details) throw new Error("Failed to upsert video details");
    await tx`INSERT INTO videos (
        user_id, video_details_id, downloaded_at, shared_link, media_kind, delivery_surface, delivery_mode, cache_hit
      ) VALUES (
        ${input.userId}, ${details.pk_id}, ${now}, ${input.sharedLink}, ${input.mediaKind},
        ${input.deliverySurface}, ${input.deliveryMode}, ${input.cacheHit}
      )`;
    return mapDetails(details);
  });
}

/** Remove a known stale file set without erasing a concurrently replaced set. */
export async function invalidateTelegramFiles(db: Database, detailsId: bigint, cacheVersion: bigint): Promise<boolean> {
  const rows = await db.sql<Array<{ pk_id: bigint | string }>>`UPDATE video_details SET
      telegram_bot_id = NULL,
      telegram_files = NULL,
      file_ids_updated_at = NULL,
      cache_version = cache_version + 1
    WHERE pk_id = ${detailsId} AND cache_version = ${cacheVersion}
    RETURNING pk_id`;
  return rows.length === 1;
}

function mapDetails(row: DetailsRow): VideoDetailsRecord {
  return {
    id: BigInt(row.pk_id),
    platform: row.platform,
    platformVideoId: row.platform_video_id,
    creatorUsername: row.creator_username,
    contentType: row.content_type,
    canonicalLink: row.canonical_link,
    telegramBotId: row.telegram_bot_id === null ? null : BigInt(row.telegram_bot_id),
    telegramFiles: parseTelegramFiles(row.telegram_files),
    likesDisplay: row.likes_display,
    viewsDisplay: row.views_display,
    firstDownloadedAt: nullableNumber(row.first_downloaded_at),
    lastUsedAt: nullableNumber(row.last_used_at),
    metadataRefreshedAt: nullableNumber(row.metadata_refreshed_at),
    fileIdsUpdatedAt: nullableNumber(row.file_ids_updated_at),
    cacheVersion: BigInt(row.cache_version),
  };
}

function parseTelegramFiles(value: unknown): TelegramFileReference[] | null {
  if (typeof value === "string") {
    try { return parseTelegramFiles(JSON.parse(value)); } catch { return null; }
  }
  if (!Array.isArray(value) || value.length === 0) return null;
  const files: TelegramFileReference[] = [];
  for (let position = 0; position < value.length; position++) {
    const item = value[position];
    if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
    const row = item as Record<string, unknown>;
    if (row.position !== position || (row.media_type !== "photo" && row.media_type !== "video")
      || typeof row.file_id !== "string" || !row.file_id || typeof row.file_unique_id !== "string" || !row.file_unique_id) return null;
    files.push({ position, media_type: row.media_type, file_id: row.file_id, file_unique_id: row.file_unique_id });
  }
  return files;
}

function nullableNumber(value: bigint | string | number | null): number | null {
  return value === null ? null : Number(value);
}
