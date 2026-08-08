import type { RetryOptions, TtScrapClient } from "../clients/tt-scrap.ts";
import type { InstagramExtraction, TikTokExtraction } from "../clients/tt-scrap-types.ts";
import type { Database } from "../db/client.ts";
import {
  getVideoDetails,
  invalidateTelegramFiles,
  recordDownload,
  type DeliverySurface,
  type TelegramFileReference,
  type VideoDetailsRecord,
  type VideoPlatform,
} from "../db/videos.ts";
import { logger } from "../logging.ts";
import { formatStat } from "../ui/stats.ts";
import { PartialDeliveryError } from "../bot/errors.ts";

const TIKTOK_METADATA_TTL_SECONDS = 24 * 60 * 60;
const locks = new Map<string, Promise<void>>();

interface BaseRequestOptions {
  db: Database;
  scrap: TtScrapClient;
  link: string;
  userId: number;
  botId: number;
  fileMode: boolean;
  deliverySurface: DeliverySurface;
  retry?: RetryOptions;
  now?: number;
}

export interface PreparedMedia {
  platform: VideoPlatform;
  platformVideoId: string;
  sourceLink: string;
  canonicalLink: string;
  extraction: TikTokExtraction | InstagramExtraction | null;
  cachedFiles: TelegramFileReference[] | null;
  contentType: string;
  creatorUsername: string | null;
  likesDisplay: string | null;
  viewsDisplay: string | null;
  cacheVersion: bigint | null;
  detailsId: bigint | null;
}

export interface MediaDeliveryOutcome<T> {
  value: T;
  /** Present only for newly uploaded standard Telegram media. */
  telegramFiles?: TelegramFileReference[];
}

export interface CompletedMediaRequest<T> {
  value: T;
  prepared: PreparedMedia;
  cacheHit: boolean;
}

export type MediaDeliverer<T> = (prepared: PreparedMedia) => Promise<MediaDeliveryOutcome<T>>;

export async function executeTikTokMediaRequest<T>(options: BaseRequestOptions, deliver: MediaDeliverer<T>): Promise<CompletedMediaRequest<T>> {
  // Resolution is intentionally always first. It is cheap and gives the stable ID
  // needed for a database lookup before any extraction/download work.
  const resolution = await options.scrap.resolveTikTok(options.link);
  const key = `tiktok:${resolution.source_id}`;
  return withMediaLock(key, async () => {
    const now = options.now ?? Math.floor(Date.now() / 1000);
    const details = await getVideoDetails(options.db, "tiktok", resolution.source_id);
    let extraction: TikTokExtraction | null = null;
    let cachedFiles = validStoredFiles(details, options.botId, "tiktok");
    const stale = !details?.metadataRefreshedAt || now - details.metadataRefreshedAt >= TIKTOK_METADATA_TTL_SECONDS;
    if (options.fileMode || !cachedFiles || stale) {
      extraction = await options.scrap.extractTikTok(resolution.resolved_url, options.retry);
      if (cachedFiles && !filesMatchExtraction(cachedFiles, extraction)) {
        await invalidateKnownFiles(options.db, details);
        cachedFiles = null;
      }
    }
    const prepared = tikTokPrepared(options.link, resolution.resolved_url, resolution.source_id, details, extraction, options.fileMode ? null : cachedFiles);
    return perform(options, prepared, details, deliver, async () => {
      const refreshed = extraction ?? await options.scrap.extractTikTok(resolution.resolved_url, options.retry);
      return tikTokPrepared(options.link, resolution.resolved_url, resolution.source_id, details, refreshed, null);
    }, now);
  });
}

export async function executeInstagramMediaRequest<T>(options: BaseRequestOptions, deliver: MediaDeliverer<T>): Promise<CompletedMediaRequest<T>> {
  const localId = instagramIdFromUrl(options.link);
  if (!localId) throw new Error("Instagram URL has no recoverable post shortcode");
  return withMediaLock(`instagram:${localId}`, async () => {
    const now = options.now ?? Math.floor(Date.now() / 1000);
    const details = await getVideoDetails(options.db, "instagram", localId);
    let extraction: InstagramExtraction | null = null;
    let cachedFiles = validStoredFiles(details, options.botId, "instagram");
    if (options.fileMode || !cachedFiles) extraction = await options.scrap.extractInstagram(options.link, options.retry);
    if (extraction && cachedFiles && !filesMatchExtraction(cachedFiles, extraction)) {
      await invalidateKnownFiles(options.db, details);
      cachedFiles = null;
    }
    const platformId = extraction?.source_id ?? localId;
    const prepared = instagramPrepared(options.link, platformId, details, extraction, options.fileMode ? null : cachedFiles);
    return perform(options, prepared, details, deliver, async () => {
      const refreshed = extraction ?? await options.scrap.extractInstagram(options.link, options.retry);
      return instagramPrepared(options.link, refreshed.source_id, details, refreshed, null);
    }, now);
  });
}

async function perform<T>(
  options: BaseRequestOptions,
  initial: PreparedMedia,
  details: VideoDetailsRecord | null,
  deliver: MediaDeliverer<T>,
  refresh: () => Promise<PreparedMedia>,
  now: number,
): Promise<CompletedMediaRequest<T>> {
  let prepared = initial;
  let usedCache = prepared.cachedFiles !== null;
  let outcome: MediaDeliveryOutcome<T>;
  try {
    outcome = await deliver(prepared);
  } catch (error) {
    if (!usedCache) throw error;
    if (error instanceof PartialDeliveryError) {
      await invalidateKnownFiles(options.db, details);
      throw error;
    }
    if (!isConfirmedInvalidFileId(error)) throw error;
    await invalidateKnownFiles(options.db, details);
    prepared = await refresh();
    usedCache = false;
    // Exactly one upload attempt follows a confirmed unusable Telegram file ID.
    outcome = await deliver(prepared);
  }

  const extraction = prepared.extraction;
  const mediaKind = prepared.contentType === "video" ? "video" : "images";
  const metadataRefreshedAt = extraction ? now : undefined;
  try {
    await recordDownload(options.db, {
      userId: options.userId,
      platform: prepared.platform,
      platformVideoId: prepared.platformVideoId,
      sharedLink: options.link,
      mediaKind,
      deliverySurface: options.deliverySurface,
      deliveryMode: options.fileMode ? "document" : "media",
      cacheHit: usedCache,
      creatorUsername: extraction ? prepared.creatorUsername : undefined,
      contentType: extraction ? prepared.contentType : undefined,
      canonicalLink: prepared.canonicalLink,
      likesDisplay: extraction?.platform === "tiktok" ? prepared.likesDisplay : undefined,
      viewsDisplay: extraction?.platform === "tiktok" ? prepared.viewsDisplay : undefined,
      metadataRefreshedAt,
      ...(options.fileMode || !outcome.telegramFiles ? {} : { telegramBotId: options.botId, telegramFiles: outcome.telegramFiles }),
      downloadedAt: now,
    });
  } catch (error) {
    // Delivery has already succeeded. Reporting a media failure here could invite
    // a user retry and duplicate the Telegram upload, so retain the old behavior
    // of logging database failures without changing the successful response.
    logger.error("Can't persist video details/download history", error);
  }
  return { value: outcome.value, prepared, cacheHit: usedCache };
}

function tikTokPrepared(
  sourceLink: string,
  resolvedUrl: string,
  platformVideoId: string,
  details: VideoDetailsRecord | null,
  extraction: TikTokExtraction | null,
  cachedFiles: TelegramFileReference[] | null,
): PreparedMedia {
  return {
    platform: "tiktok",
    platformVideoId,
    sourceLink,
    canonicalLink: resolvedUrl,
    extraction,
    cachedFiles,
    contentType: extraction?.content_type ?? details?.contentType ?? inferContentType(cachedFiles),
    creatorUsername: extraction?.creator_username ?? details?.creatorUsername ?? null,
    likesDisplay: extraction?.likes == null ? details?.likesDisplay ?? null : formatStat(extraction.likes),
    viewsDisplay: extraction?.views == null ? details?.viewsDisplay ?? null : formatStat(extraction.views),
    cacheVersion: details?.cacheVersion ?? null,
    detailsId: details?.id ?? null,
  };
}

function instagramPrepared(
  sourceLink: string,
  platformVideoId: string,
  details: VideoDetailsRecord | null,
  extraction: InstagramExtraction | null,
  cachedFiles: TelegramFileReference[] | null,
): PreparedMedia {
  return {
    platform: "instagram",
    platformVideoId,
    sourceLink,
    canonicalLink: canonicalInstagramUrl(sourceLink),
    extraction,
    cachedFiles,
    contentType: extraction?.content_type ?? details?.contentType ?? inferContentType(cachedFiles),
    creatorUsername: extraction?.creator_username ?? details?.creatorUsername ?? null,
    likesDisplay: null,
    viewsDisplay: null,
    cacheVersion: details?.cacheVersion ?? null,
    detailsId: details?.id ?? null,
  };
}

function validStoredFiles(details: VideoDetailsRecord | null, botId: number, platform: VideoPlatform): TelegramFileReference[] | null {
  if (!details?.telegramFiles || details.telegramBotId !== BigInt(botId) || !details.contentType) return null;
  const files = details.telegramFiles;
  if (platform === "tiktok") {
    if (details.contentType === "video" && files.length === 1 && files[0]?.media_type === "video") return files;
    if (details.contentType === "slideshow" && files.every((file) => file.media_type === "photo")) return files;
    return null;
  }
  if (details.contentType === "video" && files.length === 1 && files[0]?.media_type === "video") return files;
  if (details.contentType === "image" && files.length === 1 && files[0]?.media_type === "photo") return files;
  if (details.contentType === "carousel" && files.length >= 2) return files;
  return null;
}

function filesMatchExtraction(files: TelegramFileReference[], extraction: TikTokExtraction | InstagramExtraction): boolean {
  const expected = extraction.platform === "tiktok"
    ? extraction.content_type === "video" ? ["video"] : extraction.media.map(() => "photo")
    : extraction.media.map((item) => item.media_type === "video" ? "video" : "photo");
  return files.length === expected.length && files.every((file, index) => file.media_type === expected[index]);
}

function inferContentType(files: TelegramFileReference[] | null): string {
  if (!files || files.length !== 1) return "carousel";
  return files[0]?.media_type === "video" ? "video" : "image";
}

async function invalidateKnownFiles(db: Database, details: VideoDetailsRecord | null): Promise<void> {
  if (!details?.telegramFiles) return;
  try { await invalidateTelegramFiles(db, details.id, details.cacheVersion); }
  catch (error) { logger.warn("Failed to invalidate unusable Telegram file IDs", error); }
}

export function isConfirmedInvalidFileId(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const value = error as { error_code?: unknown; description?: unknown; message?: unknown };
  if (value.error_code !== 400) return false;
  const description = String(value.description ?? value.message ?? "").toLowerCase();
  return /(?:wrong|invalid|unusable) file (?:id|identifier)|file_id.*(?:invalid|wrong)|failed to get http url content/u.test(description);
}

export function instagramIdFromUrl(value: string): string | null {
  try {
    const parts = new URL(value).pathname.split("/").filter(Boolean);
    return parts.length >= 2 && /^(?:p|reels?|tv)$/iu.test(parts[0]!) && /^[A-Za-z0-9_-]+$/u.test(parts[1]!) ? parts[1]! : null;
  } catch { return null; }
}

function canonicalInstagramUrl(value: string): string {
  const url = new URL(value);
  const parts = url.pathname.split("/").filter(Boolean);
  const route = parts[0]?.toLowerCase() === "reels" ? "reel" : parts[0]?.toLowerCase();
  return `https://www.instagram.com/${route}/${parts[1]}/`;
}

async function withMediaLock<T>(key: string, operation: () => Promise<T>): Promise<T> {
  const previous = locks.get(key) ?? Promise.resolve();
  let release!: () => void;
  const current = new Promise<void>((resolve) => { release = resolve; });
  locks.set(key, current);
  await previous;
  try { return await operation(); }
  finally {
    release();
    if (locks.get(key) === current) locks.delete(key);
  }
}
