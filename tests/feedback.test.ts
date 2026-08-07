import { expect, test } from "bun:test";
import type { BotContext } from "../src/bot/context.ts";
import { createBot } from "../src/bot/create-bot.ts";
import { TtScrapError } from "../src/bot/errors.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { Database } from "../src/db/client.ts";
import { text } from "../src/locales.ts";
import { sendAdminDiagnostic } from "../src/services/admin-diagnostics.ts";
import { QueueManager } from "../src/services/queue.ts";
import { testConfig } from "./helpers.ts";

test("private messages still reach handlers after a transient user lookup failure", async () => {
  const telegramCalls: Array<{ method: string; payload: Record<string, unknown> }> = [];
  const telegram = Bun.serve({ port: 0, async fetch(request) {
    const method = new URL(request.url).pathname.split("/").at(-1) || "";
    const payload = request.method === "POST" ? await request.json() as Record<string, unknown> : {};
    telegramCalls.push({ method, payload });
    if (method === "getMe") return Response.json({ ok: true, result: { id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot" } });
    return Response.json({ ok: true, result: {
      message_id: 100,
      date: 1,
      chat: { id: Number(payload.chat_id), type: "private", first_name: "Tester" },
      text: String(payload.text ?? ""),
    } });
  } });
  let lookups = 0;
  let databaseUnavailable = false;
  const db = { sql: async (strings: TemplateStringsArray) => {
    const query = strings.join("?").replace(/\s+/gu, " ").trim();
    if (!query.startsWith("SELECT user_id, registered_at, lang, link, file_mode FROM users")) throw new Error(`Unexpected query: ${query}`);
    lookups++;
    if (lookups === 1 || databaseUnavailable) throw new Error("temporary database failure");
    return [{ user_id: 101, registered_at: 1, lang: "uk", link: null, file_mode: false }];
  } } as unknown as Database;

  try {
    const config = { ...testConfig("http://127.0.0.1:1"), telegramApiRoot: `http://127.0.0.1:${telegram.port}` };
    const bot = createBot({ config, db, scrap: new TtScrapClient(config), queue: new QueueManager(3, 10, 25) });
    await bot.init();
    await bot.handleUpdate({ update_id: 1, message: {
      message_id: 1,
      date: 1,
      chat: { id: 101, type: "private", first_name: "Tester" },
      from: { id: 101, is_bot: false, first_name: "Tester", language_code: "uk" },
      text: "hello",
    } });

    expect(lookups).toBe(2);
    expect(telegramCalls.find((call) => call.method === "sendMessage")?.payload.text).toBe(text("uk", "send_link_prompt"));

    databaseUnavailable = true;
    try {
      await bot.handleUpdate({ update_id: 2, message: {
        message_id: 2,
        date: 1,
        chat: { id: 101, type: "private", first_name: "Tester" },
        from: { id: 101, is_bot: false, first_name: "Tester", language_code: "uk" },
        text: "/mode",
        entities: [{ type: "bot_command", offset: 0, length: 5 }],
      } });
    } catch (error) {
      await bot.errorHandler(error as Parameters<typeof bot.errorHandler>[0]);
    }
    expect(telegramCalls.filter((call) => call.method === "sendMessage").at(-1)?.payload.text).toBe(text("uk", "error"));
  } finally {
    telegram.stop(true);
  }
});

test("detailed diagnostics are privately delivered only to configured admins", async () => {
  const messages: Array<{ chatId: number; message: string }> = [];
  const context = (userId: number) => ({
    from: { id: userId },
    config: { adminIds: new Set([101]) },
    api: { sendMessage: async (chatId: number, message: string) => { messages.push({ chatId, message }); } },
  }) as unknown as BotContext;
  const error = new TtScrapError("upstream_extraction_error", "internal <detail>", "request-secret", 502);

  await sendAdminDiagnostic(context(202), error);
  expect(messages).toHaveLength(0);

  await sendAdminDiagnostic(context(101), error);
  expect(messages).toHaveLength(1);
  expect(messages[0]).toMatchObject({ chatId: 101 });
  expect(messages[0]?.message).toContain("internal &lt;detail&gt;");
  expect(messages[0]?.message).toContain("request_id=request-secret");
});
