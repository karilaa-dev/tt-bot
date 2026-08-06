import type { BotContext } from "../bot/context.ts";
import { type Language, text } from "../locales.ts";
import type { QueueRejectionReason } from "../services/queue.ts";
import { retryKeyboard } from "../ui/keyboards.ts";

export async function replyForQueueRejection(
  ctx: BotContext,
  reason: QueueRejectionReason,
  lang: Language,
  messageId: number,
  group: boolean,
): Promise<void> {
  if (!ctx.chat || (reason === "capacity" && group)) return;
  const message = reason === "shutdown"
    ? text(lang, "error_shutdown")
    : text(lang, "error_queue_full").replace("{0}", String(ctx.queue.count(ctx.chat.id)));
  await ctx.reply(message, {
    parse_mode: "HTML",
    reply_parameters: { message_id: messageId },
    ...(reason === "capacity" ? { reply_markup: retryKeyboard(lang) } : {}),
  });
}
