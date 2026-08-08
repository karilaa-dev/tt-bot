import { describe, expect, test } from "bun:test";
import type { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { TikTokExtraction } from "../src/clients/tt-scrap-types.ts";
import type { Database } from "../src/db/client.ts";
import type { TelegramFileReference } from "../src/db/videos.ts";
import { albumBatches } from "../src/services/cached-delivery.ts";
import { executeInstagramMediaRequest, executeTikTokMediaRequest } from "../src/services/media-cache.ts";

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

  test("treats a Telegram bot-ID mismatch as a miss", async () => {
    const memory = fakeDatabase(detailsRow({ telegram_bot_id: 111, metadata_refreshed_at: now - 10, telegram_files: [videoFile] }));
    const scrap = fakeScrap();
    await executeTikTokMediaRequest(request(memory.db, scrap.client), async (prepared) => {
      expect(prepared.cachedFiles).toBeNull();
      return { value: "uploaded", telegramFiles: [videoFile] };
    });
    expect(scrap.tiktokExtractions).toBe(1);
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

  test("Instagram cache hits skip extraction and retain mixed ordered media", async () => {
    const mixed: TelegramFileReference[] = [
      { position: 0, media_type: "photo", file_id: "p", file_unique_id: "pu" },
      { position: 1, media_type: "video", file_id: "v", file_unique_id: "vu" },
    ];
    const memory = fakeDatabase(detailsRow({ platform: "instagram", platform_video_id: "ABC123", content_type: "carousel", telegram_files: mixed }));
    const scrap = fakeScrap();
    await executeInstagramMediaRequest({ ...request(memory.db, scrap.client), link: "https://www.instagram.com/p/ABC123/" }, async (prepared) => {
      expect(prepared.cachedFiles).toEqual(mixed);
      return { value: "sent" };
    });
    expect(scrap.instagramExtractions).toBe(0);
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

  test("partitions eleven-item albums as 9+2", () => {
    expect(albumBatches(Array.from({ length: 11 }, (_, index) => index)).map((batch) => batch.length)).toEqual([9, 2]);
  });
});

function request(db: Database, scrap: TtScrapClient) {
  return { db, scrap, link: "https://www.tiktok.com/t/SHORT/", userId: 7, botId: 999, fileMode: false, deliverySurface: "chat" as const, now };
}

function fakeScrap(): { client: TtScrapClient; resolutions: number; tiktokExtractions: number; instagramExtractions: number } {
  const counts = { resolutions: 0, tiktokExtractions: 0, instagramExtractions: 0 };
  const extraction: TikTokExtraction = {
    extraction_id: "extraction", platform: "tiktok", source_id: "123", source_url: "source",
    resolved_url: "https://www.tiktok.com/@creator/video/123", creator_username: "creator", content_type: "video",
    likes: 1_234, views: 999_950, media: [{ asset_id: "a", kind: "video", position: 0, download_url: "/a", filename: "a.mp4", expires_at: new Date().toISOString() }],
    expires_at: new Date().toISOString(),
  };
  const client = {
    async resolveTikTok(url: string) { counts.resolutions++; return { platform: "tiktok" as const, source_id: "123", source_url: url, resolved_url: extraction.resolved_url }; },
    async extractTikTok() { counts.tiktokExtractions++; return extraction; },
    async extractInstagram(url: string) {
      counts.instagramExtractions++;
      return { extraction_id: "ig", platform: "instagram" as const, source_id: "ABC123", source_url: url, creator_username: "creator", content_type: "video" as const, media: [{ position: 0, media_type: "video" as const, asset: extraction.media[0]! }], expires_at: new Date().toISOString() };
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

function fakeDatabase(initial: Record<string, unknown> | null): {
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
        telegram_files: hasFiles ? JSON.parse(String(values[6])) : existing?.telegram_files ?? null,
        likes_display: values[7] ?? existing?.likes_display ?? null,
        views_display: values[8] ?? existing?.views_display ?? null,
        first_downloaded_at: existing?.first_downloaded_at ?? values[9], last_used_at: values[10],
        metadata_refreshed_at: values[11] ?? existing?.metadata_refreshed_at ?? null,
        file_ids_updated_at: hasFiles ? values[12] : existing?.file_ids_updated_at ?? null,
        cache_version: BigInt(String(existing?.cache_version ?? 0)) + (hasFiles ? 1n : 0n),
      };
      return [row];
    }
    if (query.startsWith("INSERT INTO videos")) {
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
