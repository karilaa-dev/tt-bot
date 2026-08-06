import { expect, test } from "bun:test";
import { createBot } from "../src/bot/create-bot.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { Database } from "../src/db/client.ts";
import { QueueManager } from "../src/services/queue.ts";
import { testConfig } from "./helpers.ts";

test("a busy sound download shows an alert and leaves the sound button retryable", async () => {
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
      },
    } });

    const alert = telegramCalls.find((call) => call.method === "answerCallbackQuery")?.payload;
    expect(alert).toMatchObject({ show_alert: true });
    expect(String(alert?.text)).toContain("1 videos processing");
    expect(String(alert?.text)).not.toContain("<b>");
    const restored = telegramCalls.find((call) => call.method === "editMessageReplyMarkup")?.payload;
    expect(restored).toMatchObject({ reply_markup: { inline_keyboard: [[{ callback_data: "id/7669880788879543583" }]] } });
    expect(telegramCalls.some((call) => call.method === "sendMessage")).toBe(false);
    expect(JSON.stringify(telegramCalls)).not.toContain("retry_video");
  } finally {
    release();
    await active;
    telegram.stop(true);
  }
});
