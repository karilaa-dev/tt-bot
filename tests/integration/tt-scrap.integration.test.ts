import { expect, test } from "bun:test";
import { resolve } from "node:path";
import type { Bot } from "grammy";
import type { BotContext } from "../../src/bot/context.ts";
import { createBot } from "../../src/bot/create-bot.ts";
import type { RetryOptions } from "../../src/clients/tt-scrap.ts";
import { TtScrapClient } from "../../src/clients/tt-scrap.ts";
import type {
  InstagramDeliveryRequest,
  InstagramExtraction,
  InstagramTelegramMethod,
  TelegramDeliveryResult,
  TikTokDeliveryRequest,
  TikTokExtraction,
  TikTokResolution,
} from "../../src/clients/tt-scrap-types.ts";
import type { AppConfig } from "../../src/config.ts";
import { getVideoDetails, recordDownload, type TelegramFileReference, type VideoPlatform } from "../../src/db/videos.ts";
import { cleanupInlineSlideshows } from "../../src/handlers/inline-slideshow.ts";
import { findInstagramUrl } from "../../src/handlers/links.ts";
import { findTikTokUrl } from "../../src/handlers/tiktok.ts";
import { albumBatches } from "../../src/services/cached-delivery.ts";
import { QueueManager } from "../../src/services/queue.ts";
import { testConfig } from "../helpers.ts";
import { FakeTelegramApi, type TelegramTestCall } from "./fake-telegram.ts";
import { IntegrationMemoryDatabase, type IntegrationDetailsRow, type IntegrationHistoryRow } from "./memory-database.ts";

type MediaCase = "video" | "single_image" | "gallery";
type ExpectedContentType = TikTokExtraction["content_type"] | InstagramExtraction["content_type"];
type ExpectedMediaType = "photo" | "video";

interface MediaFixture {
  name: string;
  platform: VideoPlatform;
  mediaCase: MediaCase;
  link: string;
  expectedContentType: ExpectedContentType;
  expectedMediaTypes: ExpectedMediaType[];
}

interface FixtureManifest {
  fixtures: MediaFixture[];
}

interface ScrapSnapshot {
  resolutions: number;
  tiktokExtractions: number;
  instagramExtractions: number;
  tiktokDeliveries: number;
  instagramDeliveries: number;
}

const enabled = Bun.env.RUN_TT_SCRAP_INTEGRATION === "1";
const integrationTest = enabled ? test : test.skip;
const USER_ID = 700_001;
const STORAGE_CHAT_ID = -100_700_001;
const BOT_ID = 123_456_789;
const DEFAULT_BOT_TOKEN = `${BOT_ID}:integration-test-token-not-a-real-secret`;

test("integration Telegram recorder captures JSON and multipart delivery shapes", async () => {
  const telegram = new FakeTelegramApi(0, BOT_ID);
  try {
    const jsonResponse = await fetch(`${telegram.baseUrl}/bot${DEFAULT_BOT_TOKEN}/sendMediaGroup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: USER_ID, media: [{ type: "photo", media: "cached-1" }, { type: "video", media: "cached-2" }] }),
    });
    expect(jsonResponse.ok).toBe(true);
    expect(telegram.calls[0]).toMatchObject({ method: "sendMediaGroup", multipart: false });
    expect(telegram.calls[0]?.messages).toHaveLength(2);

    const form = new FormData();
    form.set("chat_id", String(USER_ID));
    form.set("caption", "media caption");
    form.set("reply_parameters", JSON.stringify({ message_id: 42 }));
    form.set("photo", new File(["image"], "fixture.jpg", { type: "image/jpeg" }));
    const multipartResponse = await fetch(`${telegram.baseUrl}/bot${DEFAULT_BOT_TOKEN}/sendPhoto`, { method: "POST", body: form });
    expect(multipartResponse.ok).toBe(true);
    expect(telegram.calls[1]).toMatchObject({
      method: "sendPhoto",
      multipart: true,
      payload: { caption: "media caption", reply_parameters: { message_id: 42 } },
    });
    expect(telegram.calls[1]?.messages[0]?.caption).toBe("media caption");

    telegram.failNextCachedMedia();
    const invalidResponse = await fetch(`${telegram.baseUrl}/bot${DEFAULT_BOT_TOKEN}/sendPhoto`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: USER_ID, photo: "expired-file-id" }),
    });
    expect(invalidResponse.status).toBe(400);
    expect(await invalidResponse.json()).toMatchObject({ error_code: 400, description: expect.stringContaining("wrong file_id") });
  } finally {
    telegram.stop();
  }
});

test("integration memory database preserves standard IDs across document history", async () => {
  const memory = new IntegrationMemoryDatabase();
  memory.seedUser(USER_ID);
  const files: TelegramFileReference[] = [{ position: 0, media_type: "photo", file_id: "photo-id", file_unique_id: "photo-unique" }];
  await recordDownload(memory.db, {
    userId: USER_ID,
    platform: "instagram",
    platformVideoId: "ABC123",
    sharedLink: "https://www.instagram.com/p/ABC123",
    mediaKind: "images",
    deliverySurface: "chat",
    deliveryMode: "media",
    cacheHit: false,
    contentType: "image",
    canonicalLink: "https://www.instagram.com/p/ABC123/",
    metadataRefreshedAt: 100,
    telegramBotId: BOT_ID,
    telegramFiles: files,
    downloadedAt: 100,
  });
  await recordDownload(memory.db, {
    userId: USER_ID,
    platform: "instagram",
    platformVideoId: "ABC123",
    sharedLink: "https://www.instagram.com/p/ABC123",
    mediaKind: "images",
    deliverySurface: "chat",
    deliveryMode: "document",
    cacheHit: false,
    contentType: "image",
    canonicalLink: "https://www.instagram.com/p/ABC123/",
    metadataRefreshedAt: 200,
    downloadedAt: 200,
  });
  const details = await getVideoDetails(memory.db, "instagram", "ABC123");
  expect(details?.telegramFiles).toEqual(files);
  expect(details?.telegramBotId).toBe(BigInt(BOT_ID));
  expect(details?.metadataRefreshedAt).toBe(200);
  expect(memory.history.map((row) => row.deliveryMode)).toEqual(["media", "document"]);
});

integrationTest("real tt-scrap preserves cache state and Telegram response contracts", async () => {
  const fixtures = await loadFixtures();
  const fakeTelegramPort = positivePort("TT_SCRAP_INTEGRATION_TELEGRAM_PORT", 18_181);
  const telegram = new FakeTelegramApi(fakeTelegramPort, BOT_ID);
  let managed: ReturnType<typeof Bun.spawn> | null = null;

  try {
    const apiKey = Bun.env.TT_SCRAP_INTEGRATION_EXTERNAL_BASE_URL
      ? requiredEnv("TT_SCRAP_API_KEY")
      : "integration-test-api-key-not-a-secret";
    const botToken = Bun.env.TT_SCRAP_INTEGRATION_BOT_TOKEN?.trim() || DEFAULT_BOT_TOKEN;
    const externalBase = Bun.env.TT_SCRAP_INTEGRATION_EXTERNAL_BASE_URL?.trim();
    const ttScrapBaseUrl = externalBase || `http://127.0.0.1:${positivePort("TT_SCRAP_INTEGRATION_SERVER_PORT", 18_180)}`;

    if (!externalBase) managed = startManagedTtScrap(ttScrapBaseUrl, telegram.baseUrl, apiKey, botToken);
    await waitUntilReady(ttScrapBaseUrl, managed);

    const config = integrationConfig(ttScrapBaseUrl, telegram.baseUrl, apiKey, botToken);
    const scrap = new RecordingTtScrapClient(config);
    expect(await scrap.healthReady()).toBe(true);

    for (const fixture of fixtures) {
      try {
        await verifyChatAndDocumentMatrix(fixture, config, scrap, telegram);
        await verifyInlineMatrix(fixture, config, scrap, telegram);
      } catch (error) {
        throw new Error(`Real tt-scrap fixture failed: ${fixture.name}`, { cause: error });
      }
    }
  } finally {
    cleanupInlineSlideshows();
    telegram.stop();
    if (managed) {
      managed.kill();
      await managed.exited;
    }
  }
}, 3_600_000);

async function verifyChatAndDocumentMatrix(
  fixture: MediaFixture,
  config: AppConfig,
  scrap: RecordingTtScrapClient,
  telegram: FakeTelegramApi,
): Promise<void> {
  const memory = new IntegrationMemoryDatabase();
  memory.seedUser(USER_ID);
  const bot = await integrationBot(config, memory, scrap);
  const normalizedLink = normalizeFixtureLink(fixture);

  const freshScrap = scrap.snapshot();
  const freshTelegram = telegram.mark();
  await sendChatLink(bot, fixture.link);
  const freshHistory = lastHistory(memory);
  expectHistory(freshHistory, fixture, "chat", "media", false, normalizedLink);
  expectScrapDelta(scrap, freshScrap, fixture.platform, { resolution: 1, extraction: 1, delivery: 1 });
  let details = detailsForHistory(memory, freshHistory);
  expectDetails(details, fixture, BOT_ID, true);
  expectExtraction(scrap, fixture);
  expectChatResponse(telegram.since(freshTelegram), fixture, normalizedLink, "media", true, config.botToken);

  const storedFiles = structuredClone(details.telegram_files);
  const cachedScrap = scrap.snapshot();
  const cachedTelegram = telegram.mark();
  await sendChatLink(bot, fixture.link);
  expectHistory(lastHistory(memory), fixture, "chat", "media", true, normalizedLink);
  expectScrapDelta(scrap, cachedScrap, fixture.platform, { resolution: 1, extraction: 0, delivery: 0 });
  expectChatResponse(telegram.since(cachedTelegram), fixture, normalizedLink, "media", false, config.botToken);
  details = detailsForHistory(memory, lastHistory(memory));
  expect(details.telegram_files).toEqual(storedFiles);

  if (fixture.mediaCase === "video") await verifyLinkFormats(bot, memory, scrap, telegram, fixture, details.platform_video_id);
  details = detailsForHistory(memory, lastHistory(memory));

  if (fixture.platform === "tiktok") {
    details.metadata_refreshed_at = 0;
    const staleScrap = scrap.snapshot();
    const staleTelegram = telegram.mark();
    await sendChatLink(bot, fixture.link);
    expectHistory(lastHistory(memory), fixture, "chat", "media", true, normalizedLink);
    expectScrapDelta(scrap, staleScrap, fixture.platform, { resolution: 1, extraction: 1, delivery: 0 });
    expectChatResponse(telegram.since(staleTelegram), fixture, normalizedLink, "media", false, config.botToken);
    details = detailsForHistory(memory, lastHistory(memory));
    expect(details.metadata_refreshed_at).toBeGreaterThan(0);
  }

  const beforeInvalidFiles = structuredClone(details.telegram_files);
  const invalidations = memory.invalidations;
  const recoveryScrap = scrap.snapshot();
  const recoveryTelegram = telegram.mark();
  telegram.failNextCachedMedia();
  await sendChatLink(bot, fixture.link);
  expectHistory(lastHistory(memory), fixture, "chat", "media", false, normalizedLink);
  expectScrapDelta(scrap, recoveryScrap, fixture.platform, { resolution: 1, extraction: 1, delivery: 1 });
  expect(memory.invalidations).toBe(invalidations + 1);
  const recoveryCalls = telegram.since(recoveryTelegram);
  expect(recoveryCalls.filter((call) => isMediaMethod(call.method) && !call.multipart)).toHaveLength(1);
  expectChatResponse(recoveryCalls.filter((call) => !isMediaMethod(call.method) || call.multipart), fixture, normalizedLink, "media", true, config.botToken);
  details = detailsForHistory(memory, lastHistory(memory));
  expect(details.telegram_files).not.toEqual(beforeInvalidFiles);

  memory.setFileMode(USER_ID, true);
  const filesBeforeDocument = structuredClone(details.telegram_files);
  const documentScrap = scrap.snapshot();
  const documentTelegram = telegram.mark();
  await sendChatLink(bot, fixture.link);
  expectHistory(lastHistory(memory), fixture, "chat", "document", false, normalizedLink);
  expectScrapDelta(scrap, documentScrap, fixture.platform, { resolution: 1, extraction: 1, delivery: 1 });
  expectChatResponse(telegram.since(documentTelegram), fixture, normalizedLink, "document", true, config.botToken);
  expect(detailsForHistory(memory, lastHistory(memory)).telegram_files).toEqual(filesBeforeDocument);
}

async function verifyInlineMatrix(
  fixture: MediaFixture,
  config: AppConfig,
  scrap: RecordingTtScrapClient,
  telegram: FakeTelegramApi,
): Promise<void> {
  const memory = new IntegrationMemoryDatabase();
  memory.seedUser(USER_ID);
  const bot = await integrationBot(config, memory, scrap);
  const normalizedLink = normalizeFixtureLink(fixture);

  const freshScrap = scrap.snapshot();
  const freshTelegram = telegram.mark();
  await chooseInlineResult(bot, fixture, `${fixture.name}-fresh`);
  const freshHistory = lastHistory(memory);
  expectHistory(freshHistory, fixture, "inline", "media", false, normalizedLink);
  expectScrapDelta(scrap, freshScrap, fixture.platform, { resolution: 1, extraction: 1, delivery: 1 });
  const details = detailsForHistory(memory, freshHistory);
  expectDetails(details, fixture, BOT_ID, true);
  expectInlineResponse(telegram.since(freshTelegram), fixture, normalizedLink, true, config.botToken);

  const storedFiles = structuredClone(details.telegram_files);
  const cachedScrap = scrap.snapshot();
  const cachedTelegram = telegram.mark();
  await chooseInlineResult(bot, fixture, `${fixture.name}-cached`);
  expectHistory(lastHistory(memory), fixture, "inline", "media", true, normalizedLink);
  expectScrapDelta(scrap, cachedScrap, fixture.platform, { resolution: 1, extraction: 0, delivery: 0 });
  expectInlineResponse(telegram.since(cachedTelegram), fixture, normalizedLink, false, config.botToken);
  expect(detailsForHistory(memory, lastHistory(memory)).telegram_files).toEqual(storedFiles);
}

async function verifyLinkFormats(
  bot: Bot<BotContext>,
  memory: IntegrationMemoryDatabase,
  scrap: RecordingTtScrapClient,
  telegram: FakeTelegramApi,
  fixture: MediaFixture,
  sourceId: string,
): Promise<void> {
  const variants = fixture.platform === "tiktok"
    ? [
        `https://www.tiktok.com/@/video/${sourceId}`,
        `https://m.tiktok.com/v/${sourceId}.html`,
        `https://www.tiktok.com/embed/${sourceId}`,
        `https://www.tiktok.com/player/v1/${sourceId}?controls=0`,
        `https://www.tiktok.com/?item_id=${sourceId}`,
      ]
    : instagramVariants(fixture.link);
  for (const link of variants) {
    const calls = scrap.snapshot();
    const telegramMark = telegram.mark();
    await sendChatLink(bot, link);
    const normalized = fixture.platform === "tiktok" ? findTikTokUrl(link) : findInstagramUrl(link);
    expect(normalized).not.toBeNull();
    expectHistory(lastHistory(memory), fixture, "chat", "media", true, normalized!);
    expectScrapDelta(scrap, calls, fixture.platform, { resolution: 1, extraction: 0, delivery: 0 });
    expectChatResponse(telegram.since(telegramMark), fixture, normalized!, "media", false, bot.token);
  }
}

function expectChatResponse(
  calls: TelegramTestCall[],
  fixture: MediaFixture,
  normalizedLink: string,
  mode: "media" | "document",
  throughTtScrap: boolean,
  token: string,
): void {
  const mediaCalls = calls.filter((call) => ["sendVideo", "sendPhoto", "sendDocument", "sendMediaGroup"].includes(call.method));
  const captionCalls = calls.filter((call) => call.method === "sendMessage");
  expect(mediaCalls.length).toBeGreaterThan(0);
  expect(mediaCalls.every((call) => call.multipart === throughTtScrap)).toBe(true);
  expect(mediaCalls.every((call) => call.token === token)).toBe(true);

  if (fixture.expectedMediaTypes.length === 1) {
    const expectedMethod = mode === "document" ? "sendDocument" : fixture.expectedMediaTypes[0] === "video" ? "sendVideo" : "sendPhoto";
    expect(mediaCalls).toHaveLength(1);
    expect(mediaCalls[0]?.method).toBe(expectedMethod);
    expect(String(mediaCalls[0]?.payload.caption ?? "")).toContain(normalizedLink);
    expect(mediaCalls[0]?.payload.parse_mode).toBe("HTML");
    expect(captionCalls).toHaveLength(0);
    return;
  }

  expect(mediaCalls.every((call) => call.method === "sendMediaGroup")).toBe(true);
  expect(mediaCalls).toHaveLength(albumBatches(fixture.expectedMediaTypes).length);
  const items = mediaCalls.flatMap((call) => Array.isArray(call.payload.media) ? call.payload.media : []);
  expect(items).toHaveLength(fixture.expectedMediaTypes.length);
  const expectedTypes = mode === "document" ? fixture.expectedMediaTypes.map(() => "document") : fixture.expectedMediaTypes;
  expect(items.map((item) => isRecord(item) ? item.type : null)).toEqual(expectedTypes);
  expect(items.every((item) => !isRecord(item) || item.caption === undefined)).toBe(true);
  expect(mediaCalls.every((call) => call.messages.length >= 2 && call.messages.length <= 10)).toBe(true);
  expect(captionCalls).toHaveLength(1);
  expect(String(captionCalls[0]?.payload.text ?? "")).toContain(normalizedLink);
  expect(captionCalls[0]?.payload.parse_mode).toBe("HTML");
  const reply = captionCalls[0]?.payload.reply_parameters;
  expect(isRecord(reply) ? reply.message_id : null).toBe(mediaCalls.at(-1)?.messages[0]?.message_id);
}

function expectInlineResponse(
  calls: TelegramTestCall[],
  fixture: MediaFixture,
  normalizedLink: string,
  staged: boolean,
  token: string,
): void {
  const stagedCalls = calls.filter((call) => ["sendVideo", "sendPhoto", "sendMediaGroup"].includes(call.method));
  expect(stagedCalls.every((call) => call.multipart)).toBe(true);
  expect(stagedCalls.every((call) => call.token === token)).toBe(true);
  if (staged) {
    expect(stagedCalls.length).toBeGreaterThan(0);
    expect(stagedCalls.every((call) => Number(call.payload.chat_id) === STORAGE_CHAT_ID)).toBe(true);
    expect(stagedCalls).toHaveLength(fixture.expectedMediaTypes.length === 1 ? 1 : albumBatches(fixture.expectedMediaTypes).length);
  } else {
    expect(stagedCalls).toHaveLength(0);
  }

  const edits = calls.filter((call) => call.method === "editMessageMedia");
  expect(edits).toHaveLength(1);
  expect(edits[0]?.multipart).toBe(false);
  const media = edits[0]?.payload.media;
  expect(isRecord(media) ? media.type : null).toBe(fixture.expectedMediaTypes[0]);
  expect(isRecord(media) ? String(media.caption ?? "") : "").toContain(normalizedLink);
  expect(isRecord(media) ? media.parse_mode : null).toBe("HTML");
  const keyboard = edits[0]?.payload.reply_markup;
  const buttonLabels = inlineButtonLabels(keyboard);
  if (fixture.expectedMediaTypes.length > 1) expect(buttonLabels).toContain(`📸 1/${fixture.expectedMediaTypes.length}`);
  else expect(buttonLabels.some((label) => label.startsWith("📸 "))).toBe(false);
  expect(calls.some((call) => call.method === "sendMessage")).toBe(false);
}

function expectHistory(
  history: IntegrationHistoryRow,
  fixture: MediaFixture,
  surface: "chat" | "inline",
  mode: "media" | "document",
  cacheHit: boolean,
  sharedLink: string,
): void {
  expect(history).toMatchObject({
    userId: USER_ID,
    sharedLink,
    mediaKind: fixture.expectedContentType === "video" ? "video" : "images",
    deliverySurface: surface,
    deliveryMode: mode,
    cacheHit,
  });
}

function expectDetails(details: IntegrationDetailsRow, fixture: MediaFixture, botId: number, expectFiles: boolean): void {
  expect(details.platform).toBe(fixture.platform);
  expect(details.content_type).toBe(fixture.expectedContentType);
  expect(details.telegram_bot_id).toBe(expectFiles ? BigInt(botId) : null);
  expect(details.telegram_files?.map((file) => file.media_type)).toEqual(fixture.expectedMediaTypes);
  expect(details.telegram_files?.map((file) => file.position)).toEqual(fixture.expectedMediaTypes.map((_, index) => index));
  expect(details.telegram_files?.every((file) => file.file_id.length > 0 && file.file_unique_id.length > 0)).toBe(true);
  if (fixture.platform === "tiktok") {
    expect(details.likes_display).not.toBeNull();
    expect(details.views_display).not.toBeNull();
  }
}

function expectExtraction(scrap: RecordingTtScrapClient, fixture: MediaFixture): void {
  const extraction = fixture.platform === "tiktok" ? scrap.lastTikTokExtraction : scrap.lastInstagramExtraction;
  expect(extraction?.content_type).toBe(fixture.expectedContentType);
  const types = extraction?.platform === "tiktok"
    ? extraction.media.map((item) => item.kind === "video" ? "video" : "photo")
    : extraction?.media.map((item) => item.media_type === "video" ? "video" : "photo");
  expect(types).toEqual(fixture.expectedMediaTypes);
}

function expectScrapDelta(
  scrap: RecordingTtScrapClient,
  before: ScrapSnapshot,
  platform: VideoPlatform,
  expected: { resolution: number; extraction: number; delivery: number },
): void {
  const after = scrap.snapshot();
  expect(after.resolutions - before.resolutions).toBe(platform === "tiktok" ? expected.resolution : 0);
  expect(after.tiktokExtractions - before.tiktokExtractions).toBe(platform === "tiktok" ? expected.extraction : 0);
  expect(after.instagramExtractions - before.instagramExtractions).toBe(platform === "instagram" ? expected.extraction : 0);
  expect(after.tiktokDeliveries - before.tiktokDeliveries).toBe(platform === "tiktok" ? expected.delivery : 0);
  expect(after.instagramDeliveries - before.instagramDeliveries).toBe(platform === "instagram" ? expected.delivery : 0);
}

async function integrationBot(config: AppConfig, memory: IntegrationMemoryDatabase, scrap: RecordingTtScrapClient): Promise<Bot<BotContext>> {
  const bot = createBot({ config, db: memory.db, scrap, queue: new QueueManager(3, 10, 25) });
  await bot.init();
  return bot;
}

let updateId = 100;
async function sendChatLink(bot: Bot<BotContext>, link: string): Promise<void> {
  const id = updateId++;
  await bot.handleUpdate({ update_id: id, message: {
    message_id: id,
    date: 1,
    chat: { id: USER_ID, type: "private", first_name: "Integration User" },
    from: { id: USER_ID, is_bot: false, first_name: "Integration User", username: "integration_user", language_code: "en" },
    text: link,
  } });
}

async function chooseInlineResult(bot: Bot<BotContext>, fixture: MediaFixture, suffix: string): Promise<void> {
  const id = updateId++;
  await bot.handleUpdate({ update_id: id, chosen_inline_result: {
    result_id: fixture.platform === "tiktok" ? "tt_download" : "ig_download",
    from: { id: USER_ID, is_bot: false, first_name: "Integration User", username: "integration_user", language_code: "en" },
    query: fixture.link,
    inline_message_id: `integration-${suffix}-${id}`,
  } });
}

function detailsForHistory(memory: IntegrationMemoryDatabase, history: IntegrationHistoryRow): IntegrationDetailsRow {
  const details = [...memory.details.values()].find((row) => row.pk_id === history.detailsId);
  if (!details) throw new Error(`No details row for history ${history.detailsId}`);
  return details;
}

function lastHistory(memory: IntegrationMemoryDatabase): IntegrationHistoryRow {
  const row = memory.history.at(-1);
  if (!row) throw new Error("The bot did not record download history");
  return row;
}

function normalizeFixtureLink(fixture: MediaFixture): string {
  const value = fixture.platform === "tiktok" ? findTikTokUrl(fixture.link) : findInstagramUrl(fixture.link);
  if (!value) throw new Error(`Fixture link is not routed by the bot: ${fixture.name}`);
  return value;
}

function instagramVariants(link: string): string[] {
  const normalized = findInstagramUrl(link);
  if (!normalized) return [];
  const url = new URL(normalized);
  const bareHost = `https://instagram.com${url.pathname}/`;
  return [bareHost, `${bareHost}?igsh=integration-test`];
}

function inlineButtonLabels(value: unknown): string[] {
  if (!isRecord(value) || !Array.isArray(value.inline_keyboard)) return [];
  return value.inline_keyboard.flatMap((row) => Array.isArray(row) ? row : [])
    .map((button) => isRecord(button) && typeof button.text === "string" ? button.text : "")
    .filter(Boolean);
}

async function loadFixtures(): Promise<MediaFixture[]> {
  const path = resolve(Bun.env.TT_SCRAP_INTEGRATION_FIXTURES?.trim() || "tests/integration/tt-scrap.fixtures.local.json");
  if (!await Bun.file(path).exists()) {
    throw new Error(`Missing real-media fixture manifest: ${path}. Copy tests/integration/tt-scrap.fixtures.example.json and replace every URL.`);
  }
  const value: unknown = await Bun.file(path).json();
  if (!isRecord(value) || !Array.isArray(value.fixtures)) throw new Error("Integration fixture manifest must contain a fixtures array");
  const fixtures = value.fixtures.map(parseFixture);
  const required = new Set([
    "tiktok:video",
    "tiktok:single_image",
    "tiktok:gallery",
    "instagram:video",
    "instagram:single_image",
    "instagram:gallery",
  ]);
  for (const fixture of fixtures) required.delete(`${fixture.platform}:${fixture.mediaCase}`);
  if (required.size) throw new Error(`Integration fixture manifest is missing: ${[...required].join(", ")}`);
  return fixtures;
}

function parseFixture(value: unknown, index: number): MediaFixture {
  if (!isRecord(value)) throw new Error(`Fixture ${index} must be an object`);
  const fixture = value as unknown as MediaFixture;
  if (typeof fixture.name !== "string" || !fixture.name.trim()) throw new Error(`Fixture ${index} needs a name`);
  if (fixture.platform !== "tiktok" && fixture.platform !== "instagram") throw new Error(`${fixture.name}: invalid platform`);
  if (!["video", "single_image", "gallery"].includes(fixture.mediaCase)) throw new Error(`${fixture.name}: invalid mediaCase`);
  if (typeof fixture.link !== "string" || !normalizeFixtureLink(fixture)) throw new Error(`${fixture.name}: link is not supported by the bot`);
  if (!Array.isArray(fixture.expectedMediaTypes) || !fixture.expectedMediaTypes.every((type) => type === "photo" || type === "video")) {
    throw new Error(`${fixture.name}: expectedMediaTypes must contain photo/video values`);
  }
  if (fixture.mediaCase === "video" && (fixture.expectedMediaTypes.length !== 1 || fixture.expectedMediaTypes[0] !== "video")) throw new Error(`${fixture.name}: video must expect one video`);
  if (fixture.mediaCase === "single_image" && (fixture.expectedMediaTypes.length !== 1 || fixture.expectedMediaTypes[0] !== "photo")) throw new Error(`${fixture.name}: single_image must expect one photo`);
  if (fixture.mediaCase === "gallery" && fixture.expectedMediaTypes.length < 2) throw new Error(`${fixture.name}: gallery must expect at least two items`);
  const validContent = fixture.platform === "tiktok"
    ? fixture.expectedContentType === (fixture.mediaCase === "video" ? "video" : "slideshow")
    : fixture.expectedContentType === (fixture.mediaCase === "video" ? "video" : fixture.mediaCase === "single_image" ? "image" : "carousel");
  if (!validContent) throw new Error(`${fixture.name}: expectedContentType does not match platform/mediaCase`);
  return fixture;
}

function integrationConfig(ttScrapBaseUrl: string, telegramApiRoot: string, apiKey: string, botToken: string): AppConfig {
  const config = testConfig(ttScrapBaseUrl);
  config.botToken = botToken;
  config.ttScrapApiKey = apiKey;
  config.telegramApiRoot = telegramApiRoot;
  config.storageChannelId = STORAGE_CHAT_ID;
  config.ttScrapRequestTimeoutMs = 90_000;
  config.ttScrapDeliveryTimeoutMs = 620_000;
  return config;
}

function startManagedTtScrap(baseUrl: string, telegramApiRoot: string, apiKey: string, botToken: string): ReturnType<typeof Bun.spawn> {
  const repo = resolve(Bun.env.TT_SCRAP_REPO?.trim() || "../tt-scrap");
  const port = new URL(baseUrl).port;
  return Bun.spawn(["uv", "run", "uvicorn", "tt_scrap.main:app", "--host", "127.0.0.1", "--port", port, "--workers", "1"], {
    cwd: repo,
    env: {
      ...process.env,
      TT_SCRAP_API_KEY: apiKey,
      TELEGRAM_BOT_TOKEN: botToken,
      TELEGRAM_API_BASE_URL: telegramApiRoot,
      LOG_LEVEL: Bun.env.TT_SCRAP_INTEGRATION_LOG_LEVEL?.trim() || "WARNING",
      PYTHONUNBUFFERED: "1",
    },
    stdout: "inherit",
    stderr: "inherit",
  });
}

async function waitUntilReady(baseUrl: string, managed: ReturnType<typeof Bun.spawn> | null): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (managed && await processExited(managed)) throw new Error(`Managed tt-scrap exited before becoming ready (${await managed.exited})`);
    try {
      const response = await fetch(`${baseUrl}/health/ready`, { signal: AbortSignal.timeout(1_000) });
      if (response.ok) return;
    } catch { /* server is still starting */ }
    await Bun.sleep(250);
  }
  throw new Error(`tt-scrap did not become ready at ${baseUrl}`);
}

async function processExited(process: ReturnType<typeof Bun.spawn>): Promise<boolean> {
  return Promise.race([process.exited.then(() => true), Bun.sleep(0).then(() => false)]);
}

function positivePort(name: string, fallback: number): number {
  const value = Number(Bun.env[name]?.trim() || fallback);
  if (!Number.isSafeInteger(value) || value < 1 || value > 65_535) throw new Error(`${name} must be a valid TCP port`);
  return value;
}

function requiredEnv(name: string): string {
  const value = Bun.env[name]?.trim();
  if (!value) throw new Error(`${name} is required with TT_SCRAP_INTEGRATION_EXTERNAL_BASE_URL`);
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMediaMethod(method: string): boolean {
  return ["sendVideo", "sendPhoto", "sendDocument", "sendMediaGroup"].includes(method);
}

class RecordingTtScrapClient extends TtScrapClient {
  private resolutions = 0;
  private tiktokExtractions = 0;
  private instagramExtractions = 0;
  private tiktokDeliveries = 0;
  private instagramDeliveries = 0;
  lastTikTokExtraction: TikTokExtraction | null = null;
  lastInstagramExtraction: InstagramExtraction | null = null;

  override async resolveTikTok(url: string, options: RetryOptions = {}): Promise<TikTokResolution> {
    this.resolutions++;
    return super.resolveTikTok(url, options);
  }

  override async extractTikTok(url: string, options: RetryOptions = {}): Promise<TikTokExtraction> {
    this.tiktokExtractions++;
    const result = await super.extractTikTok(url, options);
    this.lastTikTokExtraction = result;
    return result;
  }

  override async extractInstagram(url: string, options: RetryOptions = {}): Promise<InstagramExtraction> {
    this.instagramExtractions++;
    const result = await super.extractInstagram(url, options);
    this.lastInstagramExtraction = result;
    return result;
  }

  override async deliverTikTok(request: TikTokDeliveryRequest): Promise<TelegramDeliveryResult> {
    this.tiktokDeliveries++;
    return super.deliverTikTok(request);
  }

  override async deliverInstagram(request: InstagramDeliveryRequest, expectedMethod: InstagramTelegramMethod): Promise<TelegramDeliveryResult> {
    this.instagramDeliveries++;
    return super.deliverInstagram(request, expectedMethod);
  }

  snapshot(): ScrapSnapshot {
    return {
      resolutions: this.resolutions,
      tiktokExtractions: this.tiktokExtractions,
      instagramExtractions: this.instagramExtractions,
      tiktokDeliveries: this.tiktokDeliveries,
      instagramDeliveries: this.instagramDeliveries,
    };
  }
}
