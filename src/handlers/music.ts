import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { addMusic } from "../db/music.ts";
import { text } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService } from "../services/delivery.ts";
import { resolveLanguage } from "../services/registration.ts";
import { musicKeyboard } from "../ui/keyboards.ts";
import { STATS_CALLBACK_PREFIX } from "../ui/stats.ts";
import { beginStatus, clearStatus, setReaction } from "./status.ts";
import { errorText } from "./tiktok.ts";

export function registerMusicHandlers(bot: Bot<BotContext>): void {
  bot.callbackQuery(STATS_CALLBACK_PREFIX, (ctx) => ctx.answerCallbackQuery());
  bot.callbackQuery("loading", (ctx) => ctx.answerCallbackQuery());

  bot.on("callback_query:data", async (ctx, next) => {
    if (!ctx.callbackQuery.data.startsWith("id/")) return next();
    const videoIdText = ctx.callbackQuery.data.slice(3);
    const message = ctx.callbackQuery.message;
    if (!/^\d+$/.test(videoIdText)) return ctx.answerCallbackQuery({ text: "Invalid TikTok sound ID", show_alert: true });
    if (!message) return ctx.answerCallbackQuery({ text: "This sound button is no longer available", show_alert: true });
    logger.debug(`Music callback received for ${videoIdText} in chat ${message.chat.id}`);
    const videoId = BigInt(videoIdText);
    await ctx.answerCallbackQuery();
    const group = message.chat.type !== "private";
    const lang = await resolveLanguage(ctx);
    try { await ctx.editMessageReplyMarkup({ reply_markup: { inline_keyboard: [] } }); } catch { /* double click */ }
    const status = await beginStatus(ctx, message);
    try {
      await ctx.api.sendChatAction(message.chat.id, "upload_document");
      if (!group) await setReaction(ctx, message, "👨‍💻");
      await new DeliveryService(ctx.scrap, ctx.api, ctx.config).deliverAudio(videoId, message.chat.id, message.message_id, lang, group);
      await clearStatus(ctx, message, status);
      try {
        await addMusic(ctx.db, message.chat.id, videoId);
        logger.info(`Music Download: CHAT ${message.chat.id} - MUSIC ${videoIdText}`);
      } catch (error) { logger.error("Can't write music download into database", error); }
    } catch (error) {
      logger.error(`Music handler failed for ${videoIdText}`, error);
      await clearStatus(ctx, message, status);
      if (!status) await setReaction(ctx, message, group ? null : "😢");
      try { await ctx.editMessageReplyMarkup({ reply_markup: musicKeyboard(videoIdText, lang) }); } catch { /* inaccessible */ }
      if (!group) await ctx.api.sendMessage(message.chat.id, errorText(error, lang), { parse_mode: "HTML", reply_parameters: { message_id: message.message_id } });
    }
  });
}
