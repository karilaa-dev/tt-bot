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
  retryButton = true,
): Promise<void> {
  if (!ctx.chat || (reason === "capacity" && group)) return;
  const message = queueRejectionText(ctx, reason, lang);
  await ctx.reply(message, {
    parse_mode: "HTML",
    reply_parameters: { message_id: messageId },
    ...(reason === "capacity" && retryButton ? { reply_markup: retryKeyboard(lang) } : {}),
  });
}

export function queueRejectionAlert(ctx: BotContext, reason: QueueRejectionReason, lang: Language): string {
  return queueRejectionText(ctx, reason, lang).replace(/<[^>]+>/gu, "").replace(/\s+/gu, " ").trim();
}

function queueRejectionText(ctx: BotContext, reason: QueueRejectionReason, lang: Language): string {
  if (reason === "shutdown") return text(lang, "error_shutdown");
  const count = ctx.chat ? ctx.queue.count(ctx.chat.id) : 0;
  return text(lang, "error_queue_full").replace("{0}", String(count));
}
