import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { SQL } from "bun";
import { Database } from "../src/db/client.ts";
import { addMusic } from "../src/db/music.ts";
import { createUser, getUser, getUserIds, toggleUserMode, updateUserLanguage } from "../src/db/users.ts";
import { addVideo } from "../src/db/videos.ts";
import { createBot } from "../src/bot/create-bot.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import { QueueManager } from "../src/services/queue.ts";
import { testConfig } from "./helpers.ts";

const adminUrl = Bun.env.TEST_DB_URL || Bun.env.TEST_DB_ADMIN_URL;
const integration = adminUrl ? describe : describe.skip;
integration("PostgreSQL repositories", () => {
  let db: Database;
  let admin: SQL;
  const databaseName = `ttbot_test_${process.pid}_${Date.now()}`;
  beforeAll(async () => {
    admin = new SQL(adminUrl!);
    await admin.unsafe(`CREATE DATABASE "${databaseName}"`);
    const testUrl = new URL(adminUrl!);
    testUrl.pathname = `/${databaseName}`;
    db = new Database(testUrl.toString());
    await db.initialize();
  });
  afterAll(async () => {
    await db.close();
    await admin.unsafe(`DROP DATABASE "${databaseName}"`);
    await admin.close();
  });
  test("retains the legacy schema and full-width IDs", async () => {
    await Promise.all([createUser(db, 123, "en", "ref"), createUser(db, 123, "en", "ref")]);
    await toggleUserMode(db, 123); await updateUserLanguage(db, 123, "uk");
    await addVideo(db, 123, "https://tiktok.test/1", false); await addMusic(db, 123, 7669880788879543583n);
    expect(await getUser(db, 123)).toMatchObject({ userId: 123, lang: "uk", link: "ref", fileMode: true });
    expect(await getUserIds(db)).toEqual([123]);
    const rows = await db.sql<Array<{ video_id: bigint | string }>>`SELECT video_id FROM music`;
    expect(String(rows[0]?.video_id)).toBe("7669880788879543583");
  });

  test("handles start, mode, and TikTok media without a live Telegram request", async () => {
    const telegramCalls: Array<{ method: string; payload: Record<string, unknown> }> = [];
    const deliveries: Array<Record<string, unknown>> = [];
    const deliveryBodies: string[] = [];
    let nextMessageId = 100;
    const telegram = Bun.serve({ port: 0, async fetch(request) {
      const method = new URL(request.url).pathname.split("/").at(-1) || "";
      const payload = request.method === "POST" ? await request.json() as Record<string, unknown> : {};
      telegramCalls.push({ method, payload });
      if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
      if (["setMessageReaction", "sendChatAction"].includes(method)) return Response.json({ ok: true, result: true });
      const chatId = Number(payload.chat_id ?? 501);
      return Response.json({ ok: true, result: { message_id: nextMessageId++, date: 1, chat: { id: chatId, type: "private", first_name: "Test" }, text: String(payload.text ?? "") } });
    } });
    const scrapServer = Bun.serve({ port: 0, async fetch(request) {
      const path = new URL(request.url).pathname;
      const rawPayload = await request.text();
      const payload = JSON.parse(rawPayload) as Record<string, unknown>;
      if (path.endsWith("/extractions")) return Response.json({
        extraction_id: `extract-${deliveries.length + 1}`, platform: "tiktok", source_id: "7669880788879543583",
        source_url: "https://www.tiktok.com/@creator/video/7669880788879543583", resolved_url: "https://www.tiktok.com/@creator/video/7669880788879543583",
        content_type: "video", media: [], expires_at: new Date(Date.now() + 60_000).toISOString(), likes: 12, views: 34,
      });
      deliveries.push(payload);
      deliveryBodies.push(rawPayload);
      if (payload.delivery === "audio") return Response.json({ ok: true, result: {
        message_id: 800, date: 1, chat: { id: 501, type: "private", first_name: "Test" },
        audio: { file_id: "audio-id", file_unique_id: "au", duration: 1 },
      } });
      const document = payload.delivery === "document";
      return Response.json({ ok: true, result: {
        message_id: 700 + deliveries.length, date: 1, chat: { id: 501, type: "private", first_name: "Test" },
        ...(document
          ? { document: { file_id: "document-id", file_unique_id: "du", file_name: "video.mp4" } }
          : { video: { file_id: "video-id", file_unique_id: "vu", width: 1, height: 1, duration: 1 } }),
      } });
    } });
    try {
      const config = { ...testConfig(`http://127.0.0.1:${scrapServer.port}`), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
      const bot = createBot({ config, db, scrap: new TtScrapClient(config), queue: new QueueManager(config.maxUserQueueSize, config.maxGroupQueueSize) });
      await bot.init();
      const from = { id: 501, is_bot: false, first_name: "Tester", language_code: "en" };
      const chat = { id: 501, type: "private" as const, first_name: "Tester" };
      await bot.handleUpdate({ update_id: 1, message: { message_id: 1, date: 1, chat, from, text: "/start referral", entities: [{ type: "bot_command", offset: 0, length: 6 }] } });
      await bot.handleUpdate({ update_id: 2, message: { message_id: 2, date: 1, chat, from, text: "https://www.tiktok.com/@creator/video/7669880788879543583", entities: [{ type: "url", offset: 0, length: 62 }] } });
      await bot.handleUpdate({ update_id: 3, message: { message_id: 3, date: 1, chat, from, text: "/mode", entities: [{ type: "bot_command", offset: 0, length: 5 }] } });
      await bot.handleUpdate({ update_id: 4, message: { message_id: 4, date: 1, chat, from, text: "https://www.tiktok.com/@creator/video/7669880788879543583", entities: [{ type: "url", offset: 0, length: 62 }] } });
      await bot.handleUpdate({ update_id: 5, callback_query: {
        id: "callback-1", chat_instance: "test-instance", from, data: "id/7669880788879543583",
        message: { message_id: 701, date: 1, chat, from: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" }, video: { file_id: "video-id", file_unique_id: "vu", width: 1, height: 1, duration: 1 } },
      } });
      const otherFrom = { id: 502, is_bot: false, first_name: "First Message", language_code: "uk" };
      const otherChat = { id: 502, type: "private" as const, first_name: "First Message" };
      await bot.handleUpdate({ update_id: 6, message: { message_id: 6, date: 1, chat: otherChat, from: otherFrom, text: "hello" } });

      expect((await getUser(db, 501))?.link).toBe("referral");
      expect((await getUser(db, 501))?.fileMode).toBe(true);
      expect(await getUser(db, 502)).toMatchObject({ userId: 502, lang: "uk" });
      expect(deliveries.map((item) => item.delivery)).toEqual(["media", "document", "audio"]);
      expect(deliveries[0]).toMatchObject({ source: { extraction_id: "extract-1" }, telegram: { chat_id: 501, reply_parameters: { message_id: 2 } } });
      expect(deliveries[0]?.telegram).toMatchObject({ supports_streaming: true });
      expect(deliveries[0]?.telegram).not.toHaveProperty("disable_content_type_detection");
      expect(deliveries[1]?.telegram).toMatchObject({ disable_content_type_detection: true });
      expect(deliveries[1]?.telegram).not.toHaveProperty("supports_streaming");
      expect(deliveries[2]).toMatchObject({ delivery: "audio", telegram: { chat_id: 501, reply_parameters: { message_id: 701 } } });
      expect(deliveryBodies[2]).toContain('"video_id":7669880788879543583');
      expect(telegramCalls.some((call) => call.method === "sendMessage")).toBe(true);
      const rows = await db.sql<Array<{ count: number | bigint | string }>>`SELECT COUNT(*) AS count FROM videos WHERE user_id = 501`;
      expect(Number(rows[0]?.count)).toBe(2);
      const musicRows = await db.sql<Array<{ count: number | bigint | string }>>`SELECT COUNT(*) AS count FROM music WHERE user_id = 501`;
      expect(Number(musicRows[0]?.count)).toBe(1);
    } finally {
      telegram.stop(true);
      scrapServer.stop(true);
    }
  });

  test("routes Instagram extraction and delivery through tt-scrap", async () => {
    await createUser(db, 601, "en");
    const scrapCalls: Array<{ path: string; payload: Record<string, unknown> }> = [];
    const telegram = Bun.serve({ port: 0, async fetch(request) {
      const method = new URL(request.url).pathname.split("/").at(-1) || "";
      const payload = request.method === "POST" ? await request.json() as Record<string, unknown> : {};
      if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
      if (["setMessageReaction", "sendChatAction"].includes(method)) return Response.json({ ok: true, result: true });
      return Response.json({ ok: true, result: { message_id: 901, date: 1, chat: { id: Number(payload.chat_id ?? 601), type: "private", first_name: "Test" }, text: String(payload.text ?? "") } });
    } });
    const scrapServer = Bun.serve({ port: 0, async fetch(request) {
      const path = new URL(request.url).pathname;
      const payload = await request.json() as Record<string, unknown>;
      scrapCalls.push({ path, payload });
      if (path === "/v1/instagram/extractions") return Response.json({
        extraction_id: "instagram-e2e", platform: "instagram", source_url: "https://www.instagram.com/reel/ABC123", content_type: "video",
        media: [{ position: 0, media_type: "video", asset: { asset_id: "asset-1", kind: "video", position: 0, download_url: "/v1/assets/asset-1", filename: "video.mp4", expires_at: new Date(Date.now() + 60_000).toISOString() } }],
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      });
      return Response.json({ ok: true, result: { message_id: 902, date: 1, chat: { id: 601, type: "private", first_name: "Test" }, video: { file_id: "instagram-video", file_unique_id: "ig-vu", width: 1, height: 1, duration: 1 } } });
    } });
    try {
      const config = { ...testConfig(`http://127.0.0.1:${scrapServer.port}`), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
      const bot = createBot({ config, db, scrap: new TtScrapClient(config), queue: new QueueManager(config.maxUserQueueSize, config.maxGroupQueueSize) });
      await bot.init();
      const from = { id: 601, is_bot: false, first_name: "Instagram Tester", language_code: "en" };
      const chat = { id: 601, type: "private" as const, first_name: "Instagram Tester" };
      await bot.handleUpdate({ update_id: 10, message: { message_id: 10, date: 1, chat, from, text: "https://www.instagram.com/reel/ABC123" } });

      expect(scrapCalls.map((call) => call.path)).toEqual(["/v1/instagram/extractions", "/v1/instagram/telegram-deliveries"]);
      expect(scrapCalls[1]?.payload).toMatchObject({ source: { extraction_id: "instagram-e2e" }, delivery: "media", telegram: { chat_id: 601, supports_streaming: true, reply_parameters: { message_id: 10 } } });
      const rows = await db.sql<Array<{ count: number | bigint | string }>>`SELECT COUNT(*) AS count FROM videos WHERE user_id = 601 AND video_link LIKE '%instagram.com%'`;
      expect(Number(rows[0]?.count)).toBe(1);
    } finally {
      telegram.stop(true);
      scrapServer.stop(true);
    }
  });

  test("rejects a fourth private download and retries it after queue capacity returns", async () => {
    await createUser(db, 701, "en");
    const telegramCalls: Array<{ method: string; payload: Record<string, any> }> = [];
    let nextTelegramMessage = 1_000;
    const telegram = Bun.serve({ port: 0, async fetch(request) {
      const method = new URL(request.url).pathname.split("/").at(-1) || "";
      const payload = request.method === "POST" ? await request.json() as Record<string, any> : {};
      telegramCalls.push({ method, payload });
      if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
      if (["setMessageReaction", "sendChatAction", "deleteMessage", "answerCallbackQuery"].includes(method)) return Response.json({ ok: true, result: true });
      return Response.json({ ok: true, result: { message_id: nextTelegramMessage++, date: 1, chat: { id: Number(payload.chat_id ?? 701), type: "private", first_name: "Queue Tester" }, text: String(payload.text ?? "") } });
    } });
    let releaseFirst!: () => void;
    const firstGate = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let extractions = 0;
    const scrapServer = Bun.serve({ port: 0, async fetch(request) {
      const path = new URL(request.url).pathname;
      const payload = await request.json() as Record<string, any>;
      if (path === "/v1/tiktok/extractions") {
        extractions++;
        if (extractions === 1) await firstGate;
        return Response.json({
          extraction_id: `queue-${extractions}`, platform: "tiktok", source_id: String(7_000 + extractions),
          source_url: String(payload.url), resolved_url: String(payload.url), content_type: "video", media: [],
          expires_at: new Date(Date.now() + 60_000).toISOString(), likes: 1, views: 1,
        });
      }
      return Response.json({ ok: true, result: { message_id: 2_000 + extractions, date: 1, chat: { id: 701, type: "private", first_name: "Queue Tester" }, video: { file_id: `video-${extractions}`, file_unique_id: `vu-${extractions}`, width: 1, height: 1, duration: 1 } } });
    } });
    try {
      const config = { ...testConfig(`http://127.0.0.1:${scrapServer.port}`), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
      const queue = new QueueManager(3, 10);
      const bot = createBot({ config, db, scrap: new TtScrapClient(config), queue });
      await bot.init();
      const from = { id: 701, is_bot: false, first_name: "Queue Tester", language_code: "en" };
      const chat = { id: 701, type: "private" as const, first_name: "Queue Tester" };
      const original = (messageId: number) => ({ message_id: messageId, date: 1, chat, from, text: `https://www.tiktok.com/@creator/video/${7_000 + messageId}`, reply_to_message: undefined });
      const firstThree = [1, 2, 3].map((messageId) => bot.handleUpdate({ update_id: 20 + messageId, message: original(messageId) }));
      await Bun.sleep(5);
      expect(extractions).toBe(1);
      expect(queue.count(701)).toBe(3);

      await bot.handleUpdate({ update_id: 24, message: original(4) });
      const fullReply = [...telegramCalls].reverse().find((call) => call.method === "sendMessage");
      expect(fullReply?.payload.reply_markup).toMatchObject({ inline_keyboard: [[{ callback_data: "retry_video" }]] });
      expect(fullReply?.payload.reply_parameters).toEqual({ message_id: 4 });

      const fullMessage = { message_id: 1_100, date: 1, chat, from: { id: 999, is_bot: true, first_name: "Test Bot" }, text: "Queue full", reply_to_message: original(4) };
      const callsBeforeFullRetry = telegramCalls.length;
      await bot.handleUpdate({ update_id: 25, callback_query: { id: "retry-full", chat_instance: "queue", from, data: "retry_video", message: fullMessage } });
      expect(telegramCalls.slice(callsBeforeFullRetry).some((call) => call.method === "deleteMessage")).toBe(false);
      expect([...telegramCalls].reverse().find((call) => call.method === "answerCallbackQuery")?.payload.show_alert).toBe(true);

      releaseFirst();
      await Promise.all(firstThree);
      expect(extractions).toBe(3);
      expect(queue.count(701)).toBe(0);

      await bot.handleUpdate({ update_id: 26, callback_query: { id: "retry-open", chat_instance: "queue", from, data: "retry_video", message: fullMessage } });
      expect(extractions).toBe(4);
      expect(telegramCalls.some((call) => call.method === "deleteMessage" && call.payload.message_id === 1_100)).toBe(true);
    } finally {
      releaseFirst();
      telegram.stop(true);
      scrapServer.stop(true);
    }
  });
});
