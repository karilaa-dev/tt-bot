import { describe, expect, test } from "bun:test";
import type { Api } from "grammy";
import { PartialDeliveryError } from "../src/bot/errors.ts";
import type { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { InstagramExtraction, TikTokExtraction } from "../src/clients/tt-scrap-types.ts";
import type { Database } from "../src/db/client.ts";
import type { TelegramFileReference } from "../src/db/videos.ts";
import { albumBatches, deliverCachedInstagramToChat, deliverCachedTikTokToChat } from "../src/services/cached-delivery.ts";
import { executeInstagramMediaRequest, executeTikTokMediaRequest, isConfirmedInvalidFileId, type CacheIdentity } from "../src/services/media-cache.ts";

const now = 2_000_000;
const videoFile: TelegramFileReference = { position: 0, media_type: "video", file_id: "cached-video", file_unique_id: "cached-unique" };

describe("Telegram media cache", () => {
  test("resolves every TikTok request and skips fresh extraction on a bot-scoped hit", async () => {
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: now - 10, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    const completed = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.cachedFiles).toEqual([videoFile]);
      expect(prepared.likesDisplay).toBe("1.2K");
      return { value: "sent" };
    });
    expect(scrap.resolutions).toBe(1);
    expect(scrap.tiktokExtractions).toBe(0);
    expect(completed.cacheHit).toBe(true);
    expect(memory.history[0]).toMatchObject({ cacheHit: true, mode: "media" });
  });

  test("refreshes 24-hour TikTok metadata but reuses IDs when the media shape matches", async () => {
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: now - 86_400, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    const completed = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.extraction?.platform).toBe("tiktok");
      expect(prepared.cachedFiles).toEqual([videoFile]);
      expect(prepared.viewsDisplay).toBe("1M");
      return { value: "sent" };
    });
    expect(scrap.tiktokExtractions).toBe(1);
    expect(completed.cacheHit).toBe(true);
  });

  test("uses valid TikTok IDs when a stale metadata refresh fails", async () => {
    const refreshedAt = now - 86_400;
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: refreshedAt, telegram_files: [videoFile] }));
    const failure = new Error("upstream unavailable");
    const scrap = fakeScrap({ tiktokExtractionError: failure });
    const completed = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.extraction).toBeNull();
      expect(prepared.cachedFiles).toEqual([videoFile]);
      expect(prepared.likesDisplay).toBe("1.2K");
      return { value: "sent" };
    });
    expect(scrap.tiktokExtractions).toBe(1);
    expect(completed.cacheHit).toBe(true);
    expect(memory.row.metadata_refreshed_at).toBe(refreshedAt);
    expect(memory.history[0]).toMatchObject({ cacheHit: true, mode: "media" });
  });

  test("treats a Telegram bot-ID mismatch as a miss", async () => {
    const memory = fakeDatabase(detailsRow({ telegram_bot_id: 111, metadata_refreshed_at: now - 10, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      return { value: "uploaded", telegramFiles: [videoFile] };
    });
    expect(scrap.tiktokExtractions).toBe(1);
  });

  test("updates the shared cache identity after first uploads and replacements", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap();
    let firstIdentity: CacheIdentity | undefined;
    const first = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      firstIdentity = prepared.cacheIdentity;
      expect(firstIdentity).toEqual({ detailsId: null, cacheVersion: null });
      return { value: "first", telegramFiles: [videoFile] };
    });
    expect(firstIdentity).toBe(first.prepared.cacheIdentity);
    expect(firstIdentity).toEqual({ detailsId: 1n, cacheVersion: 1n });

    memory.row.telegram_bot_id = 111;
    let replacementIdentity: CacheIdentity | undefined;
    const replacement = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      replacementIdentity = prepared.cacheIdentity;
      expect(replacementIdentity).toEqual({ detailsId: 1n, cacheVersion: 1n });
      return { value: "replacement", telegramFiles: [{ ...videoFile, file_id: "replacement" }] };
    });
    expect(replacementIdentity).toBe(replacement.prepared.cacheIdentity);
    expect(replacementIdentity).toEqual({ detailsId: 1n, cacheVersion: 2n });
  });

  test("persists first inline video and slideshow uploads with reusable file IDs", async () => {
    for (const contentType of ["video", "slideshow"] as const) {
      const memory = fakeDatabase(null);
      const scrap = fakeScrap({ tiktokContentType: contentType });
      const uploaded = contentType === "video" ? [videoFile] : photoFiles(2);
      await executeTikTokMediaRequest({ ...request(memory.db, scrap.client), deliverySurface: "inline" }, async (prepared) => {
        expect(prepared.cachedFiles).toBeNull();
        return { value: "inline-sent", telegramFiles: uploaded };
      });
      expect(memory.row.telegram_files).toEqual(uploaded);
      expect(memory.history).toEqual([expect.objectContaining({
        surface: "inline", mode: "media", kind: contentType === "video" ? "video" : "images", cacheHit: false,
      })]);
    }
  });

  test("puts cached single-image captions on the photo", async () => {
    const calls: Array<{ method: string; options: Record<string, unknown> }> = [];
    const api = {
      async sendPhoto(_chatId: number, _fileId: string, options: Record<string, unknown>) {
        calls.push({ method: "sendPhoto", options });
        return { message_id: 1, date: 1, chat: { id: 7, type: "private", first_name: "Test" }, photo: [] };
      },
    } as unknown as Api;
    const file = photoFiles(1);
    await deliverCachedTikTokToChat({
      api, files: file, chatId: 7, replyTo: 1, lang: "en", sourceLink: "https://www.tiktok.com/@a/photo/123",
      group: false, sourceId: "123", contentType: "slideshow", likesDisplay: "1K", viewsDisplay: "2K",
    });
    await deliverCachedInstagramToChat({
      api, files: file, chatId: 7, replyTo: 2, lang: "en", sourceLink: "https://www.instagram.com/p/ABC123/",
      group: false, contentType: "image",
    });
    expect(calls).toHaveLength(2);
    expect(calls[0]?.options).toMatchObject({ parse_mode: "HTML", reply_markup: { inline_keyboard: expect.any(Array) } });
    expect(calls[0]?.options.caption).toContain("tiktok.com");
    expect(calls[1]?.options).toMatchObject({ parse_mode: "HTML" });
    expect(calls[1]?.options.caption).toContain("instagram.com");
  });

  test("repairs cache details without recording a navigation click as a download", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap();
    const completed = await executeTikTokMediaRequest({ ...request(memory.db, scrap.client), recordHistory: false }, async () => ({
      value: "repaired", telegramFiles: [videoFile],
    }));
    expect(completed.prepared.cacheIdentity).toEqual({ detailsId: 1n, cacheVersion: 1n });
    expect(memory.row.telegram_files).toEqual([videoFile]);
    expect(memory.history).toHaveLength(0);
  });

  test("retains reusable IDs when the download-history insert fails", async () => {
    const historyError = new Error("missing users row");
    const memory = fakeDatabase(null, { historyError });
    const scrap = fakeScrap();
    let uploads = 0;
    const deliver = async (prepared: Parameters<Parameters<typeof executeTikTokMediaRequest<string>>[1]>[0]) => {
      if (!prepared.cachedFiles) uploads++;
      return prepared.cachedFiles ? { value: "cached" } : { value: "uploaded", telegramFiles: [videoFile] };
    };

    const first = await executeTikTokMediaRequest(request(memory.db, scrap.client), deliver);
    const second = await executeTikTokMediaRequest(request(memory.db, scrap.client), deliver);

    expect(first.prepared.cacheIdentity).toEqual({ detailsId: 1n, cacheVersion: 1n });
    expect(memory.row.telegram_files).toEqual([videoFile]);
    expect(memory.history).toHaveLength(0);
    expect(second.cacheHit).toBe(true);
    expect(scrap.tiktokExtractions).toBe(1);
    expect(uploads).toBe(1);
  });

  test("document mode always extracts, never stores document IDs, and preserves standard IDs", async () => {
    const initial = detailsRow({ metadata_refreshed_at: now - 10, telegram_files: [videoFile] });
    const memory = fakeDatabase(initial);
    const scrap = fakeScrap();
    await executeTikTokMediaRequest({ ...request(memory.db, scrap.client), fileMode: true }, async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      return { value: "document-sent" };
    });
    expect(scrap.tiktokExtractions).toBe(1);
    expect(memory.row.telegram_files).toEqual([videoFile]);
    expect(memory.history[0]).toMatchObject({ cacheHit: false, mode: "document" });
  });

  test("TikTok document mode preserves changed standard IDs but forces the next media request to validate them", async () => {
    const stored = photoFiles(3);
    const memory = fakeDatabase(detailsRow({
      content_type: "slideshow", metadata_refreshed_at: now - 10, telegram_files: stored,
    }));
    const scrap = fakeScrap({ tiktokContentType: "slideshow" });
    await executeTikTokMediaRequest({ ...request(memory.db, scrap.client), fileMode: true }, async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      expect(prepared.contentType).toBe("slideshow");
      return { value: "document-sent" };
    });
    expect(memory.invalidations).toBe(0);
    expect(memory.row.telegram_files).toEqual(stored);
    expect(memory.row.metadata_refreshed_at).toBeNull();

    await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      return { value: "media-sent", telegramFiles: photoFiles(2) };
    });
    expect(scrap.tiktokExtractions).toBe(2);
    expect(memory.invalidations).toBe(1);
    expect(memory.row.telegram_files).toEqual(photoFiles(2));
  });

  test("confirmed invalid IDs are invalidated and retried through extraction exactly once", async () => {
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: now - 10, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    let attempts = 0;
    const uploaded: TelegramFileReference = { position: 0, media_type: "video", file_id: "replacement", file_unique_id: "replacement-u" };
    const completed = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      attempts++;
      if (prepared.cachedFiles) throw { error_code: 400, description: "Bad Request: wrong file identifier/HTTP URL specified" };
      return { value: "uploaded", telegramFiles: [uploaded] };
    });
    expect(attempts).toBe(2);
    expect(scrap.tiktokExtractions).toBe(1);
    expect(memory.invalidations).toBe(1);
    expect(memory.row.telegram_files).toEqual([uploaded]);
    expect(completed.cacheHit).toBe(false);
  });

  test("does not invalidate or retry rate limits and ambiguous cache-send failures", async () => {
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: now - 10, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    let attempts = 0;
    await expect(executeTikTokMediaRequest(request(memory.db, scrap.client), async () => {
      attempts++; throw { error_code: 429, description: "Too Many Requests" };
    })).rejects.toMatchObject({ error_code: 429 });
    expect(attempts).toBe(1);
    expect(memory.invalidations).toBe(0);
    expect(scrap.tiktokExtractions).toBe(0);
  });

  test("recognizes Telegram's remote file identifier wording", () => {
    expect(isConfirmedInvalidFileId({
      error_code: 400,
      description: "Bad Request: wrong remote file identifier specified: Wrong string length",
    })).toBe(true);
  });

  test("preserves cached albums after a transient partial delivery", async () => {
    const files = photoFiles(11);
    const memory = fakeDatabase(detailsRow({ content_type: "slideshow", telegram_files: files }));
    const scrap = fakeScrap();
    const failure = { error_code: 429, description: "Too Many Requests" };
    let batches = 0;
    const api = { async sendMediaGroup() {
      batches++;
      if (batches === 2) throw failure;
      return [{ message_id: 1, date: 1, chat: { id: 7, type: "private", first_name: "Test" } }];
    } } as unknown as Api;
    await expect(executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => ({
      value: await deliverCachedTikTokToChat({
        api, files: prepared.cachedFiles!, chatId: 7, replyTo: 1, lang: "en", sourceLink: prepared.sourceLink,
        group: false, sourceId: prepared.platformVideoId, contentType: prepared.contentType,
        likesDisplay: prepared.likesDisplay, viewsDisplay: prepared.viewsDisplay,
      }),
    }))).rejects.toMatchObject({ name: "PartialDeliveryError", deliveryError: failure });
    expect(batches).toBe(2);
    expect(memory.invalidations).toBe(0);
    expect(memory.row.telegram_files).toEqual(files);
    expect(scrap.tiktokExtractions).toBe(0);
  });

  test("invalidates but never retries a partially delivered album with a confirmed bad file ID", async () => {
    const files = photoFiles(11);
    const memory = fakeDatabase(detailsRow({ content_type: "slideshow", telegram_files: files }));
    const scrap = fakeScrap();
    let deliveries = 0;
    await expect(executeTikTokMediaRequest(request(memory.db, scrap.client), async () => {
      deliveries++;
      throw new PartialDeliveryError(1, "telegram-file-cache", { error_code: 400, description: "Bad Request: wrong file identifier" });
    })).rejects.toBeInstanceOf(PartialDeliveryError);
    expect(deliveries).toBe(1);
    expect(memory.invalidations).toBe(1);
    expect(scrap.tiktokExtractions).toBe(0);
  });

  test("Instagram cache hits have no TTL and retain mixed ordered media", async () => {
    const mixed: TelegramFileReference[] = [
      { position: 0, media_type: "photo", file_id: "p", file_unique_id: "pu" },
      { position: 1, media_type: "video", file_id: "v", file_unique_id: "vu" },
    ];
    const memory = fakeDatabase(detailsRow({
      platform: "instagram", platform_video_id: "ABC123", content_type: "carousel",
      metadata_refreshed_at: now - 365 * 24 * 60 * 60, telegram_files: mixed,
    }));
    const scrap = fakeScrap();
    await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/" }, async (prepared) => {
      expect(prepared.cachedFiles).toEqual(mixed);
      return { value: "sent" };
    });
    expect(scrap.instagramExtractions).toBe(0);
  });

  test("Instagram document mode preserves changed standard IDs but makes the next media request validate them", async () => {
    const mixed: TelegramFileReference[] = [
      { position: 0, media_type: "photo", file_id: "p", file_unique_id: "pu" },
      { position: 1, media_type: "video", file_id: "v", file_unique_id: "vu" },
    ];
    const memory = fakeDatabase(detailsRow({ platform: "instagram", platform_video_id: "ABC123", content_type: "carousel", telegram_files: mixed }));
    const scrap = fakeScrap({ instagramMediaTypes: ["image", "video", "image"] });
    await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/", fileMode: true }, async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      expect(prepared.contentType).toBe("carousel");
      return { value: "document-sent" };
    });
    expect(memory.invalidations).toBe(0);
    expect(memory.row.telegram_files).toEqual(mixed);
    expect(memory.row.metadata_refreshed_at).toBeNull();

    const uploaded: TelegramFileReference[] = [
      { position: 0, media_type: "photo", file_id: "new-p0", file_unique_id: "new-pu0" },
      { position: 1, media_type: "video", file_id: "new-v1", file_unique_id: "new-vu1" },
      { position: 2, media_type: "photo", file_id: "new-p2", file_unique_id: "new-pu2" },
    ];
    await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/" }, async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      return { value: "media-sent", telegramFiles: uploaded };
    });
    expect(scrap.instagramExtractions).toBe(2);
    expect(memory.invalidations).toBe(1);
    expect(memory.row.telegram_files).toEqual(uploaded);
  });

  test("delivers a mismatched Instagram extraction ID without caching its metadata or Telegram file ID", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap({ instagramSourceId: "DIFFERENT" });
    let deliveries = 0;
    const completed = await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/" }, async (prepared) => {
      deliveries++;
      expect(prepared.extractionCacheAllowed).toBe(false);
      expect(prepared.creatorUsername).toBeNull();
      return { value: "sent", telegramFiles: [videoFile] };
    });
    expect(completed.value).toBe("sent");
    expect(deliveries).toBe(1);
    expect(memory.history).toHaveLength(1);
    expect(memory.row).toMatchObject({
      platform_video_id: "ABC123",
      creator_username: null,
      content_type: null,
      metadata_refreshed_at: null,
      telegram_bot_id: null,
      telegram_files: null,
    });

    await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/" }, async () => ({
      value: "sent-again",
      telegramFiles: [videoFile],
    }));
    expect(scrap.instagramExtractions).toBe(2);
  });

  test("does not replace valid TikTok cache data when extraction returns another post", async () => {
    const refreshedAt = now - 86_400;
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: refreshedAt, telegram_files: [videoFile] }));
    const scrap = fakeScrap({ tiktokSourceId: "DIFFERENT", tiktokContentType: "slideshow" });
    const completed = await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.extractionCacheAllowed).toBe(false);
      expect(prepared.cachedFiles).toEqual([videoFile]);
      expect(prepared.contentType).toBe("video");
      expect(prepared.creatorUsername).toBe("old-creator");
      expect(prepared.likesDisplay).toBe("1.2K");
      return { value: "sent" };
    });
    expect(completed.cacheHit).toBe(true);
    expect(memory.invalidations).toBe(0);
    expect(memory.row).toMatchObject({
      creator_username: "old-creator",
      content_type: "video",
      likes_display: "1.2K",
      views_display: "1M",
      metadata_refreshed_at: refreshedAt,
      telegram_files: [videoFile],
    });
  });

  test("never delivers a mismatched extraction after a cached ID becomes invalid", async () => {
    const memory = fakeDatabase(detailsRow({ metadata_refreshed_at: now - 86_400, telegram_files: [videoFile] }));
    const scrap = fakeScrap({ tiktokSourceId: "DIFFERENT" });
    let deliveries = 0;

    await expect(executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      deliveries++;
      if (prepared.cachedFiles) {
        throw { error_code: 400, description: "Bad Request: wrong remote file identifier specified" };
      }
      return { value: "wrong-post" };
    })).rejects.toThrow("different tiktok source ID during invalid-file recovery");

    expect(deliveries).toBe(1);
    expect(scrap.tiktokExtractions).toBe(2);
    expect(memory.invalidations).toBe(1);
  });

  test("coalesces concurrent misses so only the first request uploads", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap();
    let uploads = 0;
    const deliver = async (prepared: Parameters<Parameters<typeof executeTikTokMediaRequest<string>>[1]>[0]) => {
      if (!prepared.cachedFiles) uploads++;
      await Bun.sleep(2);
      return prepared.cachedFiles ? { value: "cached" } : { value: "uploaded", telegramFiles: [videoFile] };
    };
    const [first, second] = await Promise.all([
      executeTikTokMediaRequest(request(memory.db, scrap.client), deliver),
      executeTikTokMediaRequest(request(memory.db, scrap.client), deliver),
    ]);
    expect(scrap.resolutions).toBe(2);
    expect(scrap.tiktokExtractions).toBe(1);
    expect(uploads).toBe(1);
    expect([first.cacheHit, second.cacheHit]).toEqual([false, true]);
  });

  test("bounds lock waits and proceeds independently when the holder is stuck", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap();
    let releaseFirst!: () => void;
    let markStarted!: () => void;
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const firstStarted = new Promise<void>((resolve) => { markStarted = resolve; });
    let deliveries = 0;
    const deliver = async () => {
      deliveries++;
      if (deliveries === 1) {
        markStarted();
        await firstGate;
      }
      return { value: deliveries, telegramFiles: [videoFile] };
    };
    const options = { ...request(memory.db, scrap.client), lockWaitTimeoutMs: 5 };
    const first = executeTikTokMediaRequest(options, deliver);
    await firstStarted;
    const second = await executeTikTokMediaRequest(options, deliver);
    expect(second.value).toBe(2);
    expect(deliveries).toBe(2);
    releaseFirst();
    await first;
    expect(scrap.tiktokExtractions).toBe(2);
  });

  test("does not serialize the same post across unrelated requesters", async () => {
    const memory = fakeDatabase(null);
    const scrap = fakeScrap();
    let releaseFirst!: () => void;
    let markStarted!: () => void;
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const firstStarted = new Promise<void>((resolve) => { markStarted = resolve; });
    const first = executeTikTokMediaRequest(request(memory.db, scrap.client), async () => {
      markStarted();
      await firstGate;
      return { value: "first", telegramFiles: [videoFile] };
    });
    await firstStarted;
    const secondPromise = executeTikTokMediaRequest({ ...request(memory.db, scrap.client), userId: 8 }, async () => ({
      value: "second", telegramFiles: [videoFile],
    }));
    const raced = await Promise.race([secondPromise.then(() => "completed" as const), Bun.sleep(30).then(() => "waiting" as const)]);
    releaseFirst();
    await Promise.all([first, secondPromise]);
    expect(raced).toBe("completed");
    expect(scrap.tiktokExtractions).toBe(2);
  });

  test("mirrors tt-scrap's valid album partitioning contract", () => {
    const expected = new Map<number, number[]>([
      [2, [2]],
      [10, [10]],
      [11, [9, 2]],
      [12, [10, 2]],
      [20, [10, 10]],
      [21, [10, 9, 2]],
    ]);
    for (const [count, sizes] of expected) {
      expect(albumBatches(Array.from({ length: count }, (_, index) => index)).map((batch) => batch.length)).toEqual(sizes);
    }
  });
});

function request(db: Database, scrap: TtScrapClient) {
  return { db, scrap, link: "https://www.tiktok.com/t/SHORT/", userId: 7, botId: 999, fileMode: false, deliverySurface: "chat" as const, now };
}

function photoFiles(count: number): TelegramFileReference[] {
  return Array.from({ length: count }, (_, position) => ({ position, media_type: "photo", file_id: `photo-${position}`, file_unique_id: `photo-unique-${position}` }));
}

function fakeScrap(options: { tiktokContentType?: TikTokExtraction["content_type"]; tiktokExtractionError?: unknown; tiktokSourceId?: string; instagramSourceId?: string; instagramMediaTypes?: Array<"image" | "video"> } = {}): { client: TtScrapClient; resolutions: number; tiktokExtractions: number; instagramExtractions: number } {
  const counts = { resolutions: 0, tiktokExtractions: 0, instagramExtractions: 0 };
  const tiktokContentType = options.tiktokContentType ?? "video";
  const extraction: TikTokExtraction = {
    extraction_id: "extraction", platform: "tiktok", source_id: options.tiktokSourceId ?? "123", source_url: "source",
    resolved_url: `https://www.tiktok.com/@creator/${tiktokContentType === "video" ? "video" : "photo"}/123`, creator_username: "creator", content_type: tiktokContentType,
    likes: 1_234, views: 999_950, media: tiktokContentType === "video"
      ? [{ asset_id: "a", kind: "video", position: 0, download_url: "/a", filename: "a.mp4", expires_at: new Date().toISOString() }]
      : [0, 1].map((position) => ({ asset_id: `a-${position}`, kind: "image" as const, position, download_url: `/a-${position}`, filename: `a-${position}.jpg`, expires_at: new Date().toISOString() })),
    expires_at: new Date().toISOString(),
  };
  const instagramMediaTypes = options.instagramMediaTypes ?? ["video"];
  const instagramExtraction: InstagramExtraction = {
    extraction_id: "ig", platform: "instagram", source_id: options.instagramSourceId ?? "ABC123", source_url: "https://www.instagram.com/p/ABC123/",
    creator_username: "creator", content_type: instagramMediaTypes.length === 1 ? instagramMediaTypes[0]! : "carousel",
    media: instagramMediaTypes.map((mediaType, position) => ({
      position,
      media_type: mediaType,
      asset: {
        asset_id: `ig-${position}`,
        kind: mediaType,
        position,
        download_url: `/ig-${position}`,
        filename: `ig-${position}.${mediaType === "video" ? "mp4" : "jpg"}`,
        expires_at: new Date().toISOString(),
      },
    })),
    expires_at: new Date().toISOString(),
  };
  const client = {
    mediaRequestBudgetMs() { return 800_000; },
    async resolveTikTok(url: string) { counts.resolutions++; return { platform: "tiktok" as const, source_id: "123", source_url: url, resolved_url: extraction.resolved_url }; },
    async extractTikTok() {
      counts.tiktokExtractions++;
      if (options.tiktokExtractionError !== undefined) throw options.tiktokExtractionError;
      return extraction;
    },
    async extractInstagram(url: string) {
      counts.instagramExtractions++;
      return { ...instagramExtraction, source_url: url };
    },
  } as unknown as TtScrapClient;
  return Object.assign(counts, { client });
}

function detailsRow(overrides: Record<string, unknown>) {
  return {
    pk_id: 1, platform: "tiktok", platform_video_id: "123", creator_username: "old-creator", content_type: "video",
    canonical_link: "https://www.tiktok.com/@creator/video/123", telegram_bot_id: 999, telegram_files: [videoFile],
    likes_display: "1.2K", views_display: "1M", first_downloaded_at: now - 100, last_used_at: now - 10,
    metadata_refreshed_at: now - 10, file_ids_updated_at: now - 10, cache_version: 1,
    ...overrides,
  };
}

function fakeDatabase(initial: Record<string, unknown> | null, options: { historyError?: unknown } = {}): {
  db: Database; row: Record<string, unknown>; history: Array<Record<string, unknown>>; invalidations: number;
} {
  let row: Record<string, unknown> | null = initial ? { ...initial } : null;
  const history: Array<Record<string, unknown>> = [];
  let invalidations = 0;
  const sql = async (strings: TemplateStringsArray, ...values: unknown[]): Promise<unknown[]> => {
    const query = strings.join("?").replace(/\s+/gu, " ").trim();
    if (query.startsWith("SELECT * FROM video_details")) {
      return row && row.platform === values[0] && row.platform_video_id === values[1] ? [row] : [];
    }
    if (query.startsWith("UPDATE video_details SET telegram_bot_id = NULL")) {
      if (row && BigInt(String(row.pk_id)) === BigInt(String(values[0])) && BigInt(String(row.cache_version)) === BigInt(String(values[1]))) {
        invalidations++; row.telegram_bot_id = null; row.telegram_files = null; row.file_ids_updated_at = null; row.cache_version = BigInt(String(row.cache_version)) + 1n;
        return [{ pk_id: row.pk_id }];
      }
      return [];
    }
    if (query.startsWith("INSERT INTO video_details")) {
      const hasFiles = values[6] !== null;
      const existing = row;
      row = {
        pk_id: existing?.pk_id ?? 1, platform: values[0], platform_video_id: values[1],
        creator_username: values[2] ?? existing?.creator_username ?? null,
        content_type: values[3] ?? existing?.content_type ?? null,
        canonical_link: values[4] ?? existing?.canonical_link ?? null,
        telegram_bot_id: hasFiles ? values[5] : existing?.telegram_bot_id ?? null,
        telegram_files: hasFiles
          ? values[6] instanceof Uint8Array ? JSON.parse(new TextDecoder().decode(values[6])) : values[6]
          : existing?.telegram_files ?? null,
        likes_display: values[7] ?? existing?.likes_display ?? null,
        views_display: values[8] ?? existing?.views_display ?? null,
        first_downloaded_at: existing?.first_downloaded_at ?? values[9], last_used_at: values[10],
        metadata_refreshed_at: values[18] ? values[11] : existing?.metadata_refreshed_at ?? null,
        file_ids_updated_at: hasFiles ? values[12] : existing?.file_ids_updated_at ?? null,
        cache_version: BigInt(String(existing?.cache_version ?? 0)) + (hasFiles ? 1n : 0n),
      };
      return [row];
    }
    if (query.startsWith("INSERT INTO videos")) {
      if (options.historyError !== undefined) throw options.historyError;
      history.push({ userId: values[0], detailsId: values[1], downloadedAt: values[2], link: values[3], kind: values[4], surface: values[5], mode: values[6], cacheHit: values[7] });
      return [];
    }
    throw new Error(`Unexpected SQL: ${query}`);
  };
  Object.assign(sql, { begin: async (operation: (transaction: typeof sql) => Promise<unknown>) => operation(sql) });
  return {
    db: { sql } as unknown as Database,
    get row() { return row ?? {}; }, history,
    get invalidations() { return invalidations; },
  };
}
