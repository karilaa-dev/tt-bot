import { expect, test } from "bun:test";
import type { BotContext } from "../src/bot/context.ts";
import { replyForQueueRejection } from "../src/handlers/queue-rejection.ts";
import { text } from "../src/locales.ts";

test("queue capacity stays silent in groups but shutdown cancellations notify every chat", async () => {
  const replies: Array<{ message: string; options: Record<string, unknown> }> = [];
  const ctx = {
    chat: { id: -100500, type: "supergroup" },
    queue: { count: () => 10 },
    reply: async (message: string, options: Record<string, unknown>) => { replies.push({ message, options }); },
  } as unknown as BotContext;

  await replyForQueueRejection(ctx, "capacity", "en", 7, true);
  expect(replies).toHaveLength(0);

  await replyForQueueRejection(ctx, "shutdown", "en", 7, true);
  expect(replies).toHaveLength(1);
  expect(replies[0]).toMatchObject({
    message: text("en", "error_shutdown"),
    options: { parse_mode: "HTML", reply_parameters: { message_id: 7 } },
  });

  await replyForQueueRejection(ctx, "capacity", "en", 8, false);
  expect(replies).toHaveLength(2);
  expect(replies[1]?.message).toContain("10 videos processing");
  expect(replies[1]?.options).toHaveProperty("reply_markup");
});
