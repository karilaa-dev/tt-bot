import { expect, test } from "bun:test";
import { createBot } from "../src/bot/create-bot.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { Database } from "../src/db/client.ts";
import { QueueManager } from "../src/services/queue.ts";
import { testConfig } from "./helpers.ts";

test("queue alerts preserve the full sound keyboard and distinguish shutdown", async () => {
  const telegramCalls: Array<{ method: string; payload: Record<string, unknown> }> = [];
  const telegram = Bun.serve({ port: 0, async fetch(request) {
    const method = new URL(request.url).pathname.split("/").at(-1) || "";
    const payload = request.method === "POST" ? await request.json() as Record<string, unknown> : {};
    telegramCalls.push({ method, payload });
    if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
    if (method === "answerCallbackQuery") return Response.json({ ok: true, result: true });
    return Response.json({ ok: true, result: {
      message_id: 10,
      date: 1,
      chat: { id: 501, type: "private", first_name: "Tester" },
      video: { file_id: "video-id", file_unique_id: "video-unique", width: 1, height: 1, duration: 1 },
    } });
  } });
  const db = { sql: async () => [{ user_id: 501, registered_at: 1, lang: "en", link: null, file_mode: false }] } as unknown as Database;
  const queue = new QueueManager(1, 10, 25);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const active = queue.withSlot(501, async () => { await gate; });
  const originalKeyboard = { inline_keyboard: [
    [{ text: "❤️ 12", callback_data: "stats_noop" }, { text: "👁 34", callback_data: "stats_noop" }],
    [{ text: "🎵 Get Sound", callback_data: "id/7669880788879543583" }],
  ] };

  try {
    await Bun.sleep(0);
    const config = { ...testConfig("http://127.0.0.1:1"), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
    const bot = createBot({ config, db, scrap: new TtScrapClient(config), queue });
    await bot.init();
    await bot.handleUpdate({ update_id: 1, callback_query: {
      id: "sound-busy",
      chat_instance: "sound-test",
      from: { id: 501, is_bot: false, first_name: "Tester", language_code: "en" },
      data: "id/7669880788879543583",
      message: {
        message_id: 10,
        date: 1,
        chat: { id: 501, type: "private", first_name: "Tester" },
        from: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" },
        video: { file_id: "video-id", file_unique_id: "video-unique", width: 1, height: 1, duration: 1 },
        reply_markup: originalKeyboard,
      },
    } });

    const alert = telegramCalls.find((call) => call.method === "answerCallbackQuery")?.payload;
    expect(alert).toMatchObject({ show_alert: true });
    expect(String(alert?.text)).toContain("1 videos processing");
    expect(String(alert?.text)).not.toContain("<b>");
    expect(telegramCalls.some((call) => call.method === "editMessageReplyMarkup")).toBe(false);
    expect(telegramCalls.some((call) => call.method === "sendMessage")).toBe(false);
    expect(JSON.stringify(telegramCalls)).not.toContain("retry_video");

    queue.shutdown();
    const original = {
      message_id: 11,
      date: 1,
      chat: { id: 501, type: "private" as const, first_name: "Tester" },
      from: { id: 501, is_bot: false, first_name: "Tester", language_code: "en" },
      text: "https://www.tiktok.com/@creator/video/7669880788879543583",
      reply_to_message: undefined,
    };
    await bot.handleUpdate({ update_id: 2, callback_query: {
      id: "video-retry-shutdown",
      chat_instance: "retry-test",
      from: original.from,
      data: "retry_video",
      message: {
        message_id: 12,
        date: 1,
        chat: original.chat,
        from: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" },
        text: "Retry",
        reply_to_message: original,
      },
    } });
    const shutdownAlert = telegramCalls.filter((call) => call.method === "answerCallbackQuery").at(-1)?.payload;
    expect(shutdownAlert).toMatchObject({ show_alert: true });
    expect(String(shutdownAlert?.text)).toContain("bot is restarting");
    expect(String(shutdownAlert?.text)).not.toContain("0 videos processing");
  } finally {
    release();
    await active;
    telegram.stop(true);
  }
});
