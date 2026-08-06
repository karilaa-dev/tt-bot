import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { addMusic } from "../db/music.ts";
import { logger } from "../logging.ts";
import { DeliveryService } from "../services/delivery.ts";
import { resolveLanguage } from "../services/registration.ts";
import { musicKeyboard } from "../ui/keyboards.ts";
import { STATS_CALLBACK_PREFIX } from "../ui/stats.ts";
import { queueRejectionAlert, replyForQueueRejection } from "./queue-rejection.ts";
import { beginStatus, clearStatus, setReaction } from "./status.ts";
import { errorText, shouldOfferRetry } from "./tiktok.ts";

const activeMusicDeliveries = new Set<string>();

export function registerMusicHandlers(bot: Bot<BotContext>): void {
  bot.callbackQuery(STATS_CALLBACK_PREFIX, (ctx) => ctx.answerCallbackQuery());
  bot.callbackQuery("loading", (ctx) => ctx.answerCallbackQuery());

  bot.on("callback_query:data", async (ctx, next) => {
    if (!ctx.callbackQuery.data.startsWith("id/")) return next();
    const videoIdText = ctx.callbackQuery.data.slice(3);
    const message = ctx.callbackQuery.message;
    if (!/^\d+$/.test(videoIdText)) return ctx.answerCallbackQuery({ text: "Invalid TikTok sound ID", show_alert: true });
    if (!message) return ctx.answerCallbackQuery({ text: "This sound button is no longer available", show_alert: true });
    const deliveryKey = `${message.chat.id}:${message.message_id}`;
    if (activeMusicDeliveries.has(deliveryKey)) return ctx.answerCallbackQuery({ text: "Sound delivery is already in progress…" });
    activeMusicDeliveries.add(deliveryKey);
    logger.debug(`Music callback received for ${videoIdText} in chat ${message.chat.id}`);
    const videoId = BigInt(videoIdText);
    const group = message.chat.type !== "private";
    const lang = await resolveLanguage(ctx);
    let status: Awaited<ReturnType<typeof beginStatus>> = null;
    try {
      const rejection = ctx.queue.rejectionReason(message.chat.id, group);
      if (rejection) {
        try { await ctx.editMessageReplyMarkup({ reply_markup: musicKeyboard(videoIdText, lang) }); } catch { /* already restored */ }
        await ctx.answerCallbackQuery({ text: queueRejectionAlert(ctx, rejection, lang), show_alert: true });
        return;
      }
      await ctx.answerCallbackQuery();
      try { await ctx.editMessageReplyMarkup({ reply_markup: { inline_keyboard: [] } }); } catch { /* already changed */ }
      status = await beginStatus(ctx, message);
      const queued = await ctx.queue.withSlot(message.chat.id, async () => {
        await ctx.api.sendChatAction(message.chat.id, "upload_document");
        if (!group) await setReaction(ctx, message, "👨‍💻");
        await new DeliveryService(ctx.scrap, ctx.config).deliverAudio(videoId, message.chat.id, message.message_id, lang, group);
        await clearStatus(ctx, message, status);
      }, { group });
      if (!queued.acquired) {
        await clearStatus(ctx, message, status);
        try { await ctx.editMessageReplyMarkup({ reply_markup: musicKeyboard(videoIdText, lang) }); } catch { /* inaccessible */ }
        await replyForQueueRejection(ctx, queued.reason, lang, message.message_id, group, false);
        return;
      }
      try {
        await addMusic(ctx.db, message.chat.id, videoId);
        logger.info(`Music Download: CHAT ${message.chat.id} - MUSIC ${videoIdText}`);
      } catch (error) { logger.error("Can't write music download into database", error); }
    } catch (error) {
      logger.error(`Music handler failed for ${videoIdText}`, error);
      await clearStatus(ctx, message, status);
      if (!status) await setReaction(ctx, message, group ? null : "😢");
      if (shouldOfferRetry(error)) {
        try { await ctx.editMessageReplyMarkup({ reply_markup: musicKeyboard(videoIdText, lang) }); } catch { /* inaccessible */ }
      }
      if (!group) await ctx.api.sendMessage(message.chat.id, errorText(error, lang), { parse_mode: "HTML", reply_parameters: { message_id: message.message_id } });
    } finally {
      activeMusicDeliveries.delete(deliveryKey);
    }
  });
}
