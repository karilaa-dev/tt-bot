import { expect, test } from "bun:test";
import type { Database } from "../src/db/client.ts";
import { createBot } from "../src/bot/create-bot.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import { cleanupInlineSlideshows, createInlineSlideshow } from "../src/handlers/inline-slideshow.ts";
import { inlineRetryCallbackData } from "../src/handlers/inline.ts";
import { QueueManager } from "../src/services/queue.ts";
import { testConfig } from "./helpers.ts";

interface MemoryUserRow {
  user_id: number;
  registered_at: number;
  lang: string;
  link: string | null;
  file_mode: boolean;
}

interface TelegramCall {
  method: string;
  payload: Record<string, unknown>;
}

test("registers deep links, first-link users, and group chats without PostgreSQL", async () => {
  const memory = memoryDatabase();
  const telegramCalls: TelegramCall[] = [];
  const scrapCalls: Array<{ path: string; payload: Record<string, unknown> }> = [];
  let nextMessageId = 100;

  const telegram = Bun.serve({ port: 0, async fetch(request) {
    const method = new URL(request.url).pathname.split("/").at(-1) || "";
    const payload = request.method === "POST" ? await request.json() as Record<string, unknown> : {};
    telegramCalls.push({ method, payload });
    if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
    if (method === "editMessageMedia" && payload.inline_message_id === "viewer-invalid-slideshow") {
      return Response.json({ ok: false, error_code: 400, description: "Bad Request: wrong remote file identifier specified: Wrong string length" }, { status: 400 });
    }
    if (["answerCallbackQuery", "answerInlineQuery", "editMessageMedia", "sendChatAction", "setMessageReaction"].includes(method)) return Response.json({ ok: true, result: true });
    const chatId = Number(payload.chat_id ?? 0);
    const chat = chatId < 0
      ? { id: chatId, type: "supergroup", title: "Test Group" }
      : { id: chatId, type: "private", first_name: "Tester" };
    return Response.json({ ok: true, result: { message_id: nextMessageId++, date: 1, chat, text: String(payload.text ?? "") } });
  } });

  const scrap = Bun.serve({ port: 0, async fetch(request) {
    const path = new URL(request.url).pathname;
    const payload = await request.json() as Record<string, unknown>;
    scrapCalls.push({ path, payload });
    if (path === "/v1/tiktok/resolutions") {
      return Response.json({
        platform: "tiktok", source_id: "7669880788879543583", source_url: String(payload.url),
        resolved_url: "https://www.tiktok.com/@_/video/7669880788879543583",
      });
    }
    if (path === "/v1/tiktok/extractions") {
      const url = String(payload.url);
      return Response.json({
        extraction_id: `extract-${scrapCalls.length}`,
        platform: "tiktok",
        source_id: "7669880788879543583",
        source_url: url,
        resolved_url: url,
        content_type: "video",
        creator_username: "creator",
        media: [{ asset_id: "tiktok-video", kind: "video", position: 0, download_url: "/v1/assets/tiktok-video", filename: "video.mp4", expires_at: new Date(Date.now() + 60_000).toISOString() }],
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        likes: 12,
        views: 34,
      });
    }
    if (path === "/v1/instagram/extractions") {
      return Response.json({
        extraction_id: `instagram-${scrapCalls.length}`,
        platform: "instagram",
        source_id: "ABC123",
        creator_username: "creator",
        source_url: String(payload.url),
        content_type: "video",
        media: [{
          position: 0,
          media_type: "video",
          asset: { asset_id: "instagram-video", kind: "video", position: 0, download_url: "/v1/assets/instagram-video", filename: "video.mp4", expires_at: new Date(Date.now() + 60_000).toISOString() },
        }],
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      });
    }
    const telegramPayload = payload.telegram as { chat_id: number };
    const chatId = telegramPayload.chat_id;
    return Response.json({ ok: true, result: {
      message_id: nextMessageId++,
      date: 1,
      chat: chatId < 0 ? { id: chatId, type: "supergroup", title: "Test Group" } : { id: chatId, type: "private", first_name: "Tester" },
      video: { file_id: "video-id", file_unique_id: "video-unique", width: 1, height: 1, duration: 1 },
    } });
  } });

  try {
    const config = { ...testConfig(`http://127.0.0.1:${scrap.port}`), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
    const bot = createBot({ config, db: memory.db, scrap: new TtScrapClient(config), queue: new QueueManager(3, 10, 25) });
    await bot.init();

    const deepLinkUser = { id: 101, is_bot: false, first_name: "Deep Link", language_code: "en" };
    await bot.handleUpdate({ update_id: 1, inline_query: { id: "inline-1", from: deepLinkUser, query: "", offset: "" } });
    const inlineAnswer = telegramCalls.find((call) => call.method === "answerInlineQuery");
    expect(inlineAnswer?.payload.button).toMatchObject({ start_parameter: "inline" });
    expect(memory.users.has(101)).toBe(false);

    await bot.handleUpdate({ update_id: 2, message: {
      message_id: 2,
      date: 1,
      chat: { id: 101, type: "private", first_name: "Deep Link" },
      from: deepLinkUser,
      text: "/start Inline",
      entities: [{ type: "bot_command", offset: 0, length: 6 }],
    } });
    expect(memory.users.get(101)).toMatchObject({ user_id: 101, link: "inline" });
    expect(sendMessagesFor(telegramCalls, 101)).toHaveLength(2);

    await bot.handleUpdate({ update_id: 3, message: {
      message_id: 3,
      date: 1,
      chat: { id: 101, type: "private", first_name: "Deep Link" },
      from: deepLinkUser,
      text: "/start replacement",
      entities: [{ type: "bot_command", offset: 0, length: 6 }],
    } });
    expect(memory.users.get(101)?.link).toBe("inline");
    expect(sendMessagesFor(telegramCalls, 101)).toHaveLength(4);

    const firstLinkUser = { id: 102, is_bot: false, first_name: "First Link", language_code: "uk" };
    await bot.handleUpdate({ update_id: 4, message: {
      message_id: 4,
      date: 1,
      chat: { id: 102, type: "private", first_name: "First Link" },
      from: firstLinkUser,
      text: "https://m.tiktok.com/v/7669880788879543583.html",
    } });
    expect(memory.users.get(102)).toMatchObject({ user_id: 102, lang: "uk", link: null });
    expect(sendMessagesFor(telegramCalls, 102)).toHaveLength(2);
    expect(memory.videos.some((video) => video.userId === 102)).toBe(true);
    expect(scrapCalls.find((call) => call.path === "/v1/tiktok/extractions")?.payload.url)
      .toBe("https://www.tiktok.com/@_/video/7669880788879543583");

    const groupChat = { id: -100500, type: "supergroup" as const, title: "Test Group" };
    const groupUser = { id: 103, is_bot: false, first_name: "Group User", language_code: "en" };
    await bot.handleUpdate({ update_id: 5, message: { message_id: 5, date: 1, chat: groupChat, from: groupUser, text: "ordinary group message" } });
    expect(memory.users.has(groupChat.id)).toBe(false);

    await bot.handleUpdate({ update_id: 6, message: {
      message_id: 6,
      date: 1,
      chat: groupChat,
      from: groupUser,
      text: "https://www.tiktok.com/@creator/video/7669880788879543583",
    } });
    expect(memory.users.get(groupChat.id)).toMatchObject({ user_id: groupChat.id, lang: "en" });
    expect(sendMessagesFor(telegramCalls, groupChat.id)).toHaveLength(2);
    expect(memory.videos.some((video) => video.userId === groupChat.id)).toBe(true);
    expect(scrapCalls.filter((call) => call.path === "/v1/tiktok/extractions")).toHaveLength(1);

    const instagramGroup = { id: -100501, type: "group" as const, title: "Instagram Group" };
    await bot.handleUpdate({ update_id: 7, message: {
      message_id: 7,
      date: 1,
      chat: instagramGroup,
      from: groupUser,
      text: "https://www.instagram.com/reel/ABC123",
    } });
    expect(memory.users.get(instagramGroup.id)).toMatchObject({ user_id: instagramGroup.id, lang: "en" });
    expect(sendMessagesFor(telegramCalls, instagramGroup.id)).toHaveLength(2);
    expect(memory.videos.some((video) => video.userId === instagramGroup.id)).toBe(true);
    expect(scrapCalls.some((call) => call.path === "/v1/instagram/telegram-deliveries")).toBe(true);

    const callsBeforeUnauthorizedRetries = scrapCalls.length;
    const originalGroupMessage = {
      message_id: 8,
      date: 1,
      chat: groupChat,
      from: groupUser,
      text: "https://www.tiktok.com/@creator/video/7669880788879543583",
      reply_to_message: undefined,
    };
    await bot.handleUpdate({ update_id: 8, callback_query: {
      id: "unauthorized-chat-retry",
      chat_instance: "group-instance",
      from: firstLinkUser,
      data: "retry_video",
      message: { message_id: 108, date: 1, chat: groupChat, from: { id: 999, is_bot: true, first_name: "Test Bot" }, text: "Retry", reply_to_message: originalGroupMessage },
    } });
    const inlineRetry = inlineRetryCallbackData("https://www.tiktok.com/@creator/video/7669880788879543583", false, groupUser.id)!;
    await bot.handleUpdate({ update_id: 9, callback_query: {
      id: "unauthorized-inline-retry",
      chat_instance: "inline-instance",
      from: firstLinkUser,
      data: inlineRetry,
      inline_message_id: "inline-retry-message",
    } });
    await bot.handleUpdate({ update_id: 10, callback_query: {
      id: "legacy-inline-retry",
      chat_instance: "inline-instance",
      from: groupUser,
      data: "ir:tt:www.tiktok.com/@user/video/7669880788879543583",
      inline_message_id: "legacy-inline-retry-message",
    } });
    expect(scrapCalls).toHaveLength(callsBeforeUnauthorizedRetries);

    await bot.handleUpdate({ update_id: 11, callback_query: {
      id: "invalid-inline-retry-host",
      chat_instance: "inline-instance",
      from: groupUser,
      data: `ir:tt:${groupUser.id.toString(36)}:example.com/video/7669880788879543583`,
      inline_message_id: "invalid-inline-retry-message",
    } });
    await bot.handleUpdate({ update_id: 12, callback_query: {
      id: "invalid-slideshow-refresh-host",
      chat_instance: "inline-instance",
      from: groupUser,
      data: "sr:103:0:example.com/video/7669880788879543583",
      inline_message_id: "invalid-slideshow-message",
    } });
    expect(scrapCalls).toHaveLength(callsBeforeUnauthorizedRetries);

    const historyBeforeSlideshowRefresh = memory.videos.length;
    await bot.handleUpdate({ update_id: 13, callback_query: {
      id: "slideshow-refresh",
      chat_instance: "inline-instance",
      from: groupUser,
      data: "sr:103:0:m.tiktok.com/v/7669880788879543583.html",
      inline_message_id: "inline-slideshow-message",
    } });
    expect(scrapCalls.filter((call) => call.path === "/v1/tiktok/extractions").at(-1)?.payload.url)
      .toBe("https://www.tiktok.com/@_/video/7669880788879543583");
    expect(memory.videos).toHaveLength(historyBeforeSlideshowRefresh);

    createInlineSlideshow(bot.api, "viewer-invalid-slideshow", [
      { type: "photo", fileId: "broken-photo-1" },
      { type: "photo", fileId: "broken-photo-2" },
    ], "en", "https://www.tiktok.com/@creator/photo/7669880788879543583", {
      userId: groupUser.id,
      fullName: groupUser.first_name,
    }, null, null, { detailsId: 1n, cacheVersion: 1n });
    const invalidationsBeforeViewerNavigation = memory.invalidations;
    const scrapCallsBeforeViewerNavigation = scrapCalls.length;
    await bot.handleUpdate({ update_id: 14, callback_query: {
      id: "viewer-navigation",
      chat_instance: "inline-instance",
      from: firstLinkUser,
      data: "slide:next",
      inline_message_id: "viewer-invalid-slideshow",
    } });
    expect(memory.invalidations).toBe(invalidationsBeforeViewerNavigation);
    expect(scrapCalls).toHaveLength(scrapCallsBeforeViewerNavigation);
  } finally {
    cleanupInlineSlideshows();
    telegram.stop(true);
    scrap.stop(true);
  }
});

function sendMessagesFor(calls: TelegramCall[], chatId: number): TelegramCall[] {
  return calls.filter((call) => call.method === "sendMessage" && Number(call.payload.chat_id) === chatId);
}

function memoryDatabase(): {
  db: Database;
  users: Map<number, MemoryUserRow>;
  videos: Array<{ userId: number; link: string }>;
  readonly invalidations: number;
} {
  const users = new Map<number, MemoryUserRow>();
  const videos: Array<{ userId: number; link: string }> = [];
  const details = new Map<string, Record<string, unknown>>();
  let invalidations = 0;
  const sql = async (strings: TemplateStringsArray, ...values: unknown[]): Promise<unknown[]> => {
    const query = strings.join("?").replace(/\s+/gu, " ").trim();
    if (query.startsWith("SELECT user_id, registered_at, lang, link, file_mode FROM users")) {
      const user = users.get(Number(values[0]));
      return user ? [user] : [];
    }
    if (query.startsWith("SELECT * FROM video_details")) {
      const row = details.get(`${values[0]}:${values[1]}`);
      return row ? [row] : [];
    }
    if (query.startsWith("INSERT INTO video_details")) {
      const row = {
        pk_id: videos.length + 1, platform: values[0], platform_video_id: values[1], creator_username: values[2],
        content_type: values[3], canonical_link: values[4], telegram_bot_id: values[5],
        telegram_files: values[6] instanceof Uint8Array
          ? JSON.parse(new TextDecoder().decode(values[6]))
          : Array.isArray(values[6]) ? values[6] : null,
        likes_display: values[7], views_display: values[8], first_downloaded_at: values[9], last_used_at: values[10],
        metadata_refreshed_at: values[11], file_ids_updated_at: values[12], cache_version: values[13],
      };
      details.set(`${values[0]}:${values[1]}`, row);
      return [row];
    }
    if (query.startsWith("INSERT INTO users")) {
      const userId = Number(values[0]);
      if (users.has(userId)) return [];
      const user: MemoryUserRow = {
        user_id: userId,
        registered_at: Number(values[1]),
        lang: String(values[2]),
        link: values[3] === null ? null : String(values[3]),
        file_mode: false,
      };
      users.set(userId, user);
      return [user];
    }
    if (query.startsWith("INSERT INTO videos")) {
      videos.push({ userId: Number(values[0]), link: String(values[3]) });
      return [];
    }
    if (query.startsWith("UPDATE video_details SET telegram_bot_id = NULL")) {
      invalidations++;
      return [{ pk_id: values[0] }];
    }
    throw new Error(`Unexpected in-memory SQL query: ${query}`);
  };
  Object.assign(sql, { begin: async (operation: (transaction: typeof sql) => Promise<unknown>) => operation(sql) });
  return { db: { sql } as unknown as Database, users, videos, get invalidations() { return invalidations; } };
}
