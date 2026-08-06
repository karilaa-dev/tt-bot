import type { Bot } from "grammy";
import type { InputMediaDocument, InputMediaPhoto, InputMediaVideo, MessageEntity } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { addVideo } from "../db/videos.ts";
import { type Language, text } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, fileIdFromMessage, lastBatch } from "../services/delivery.ts";
import { registerAndWelcome, resolveLanguage } from "../services/registration.ts";
import { resultCaption } from "../ui/captions.ts";
import { retryKeyboard } from "../ui/keyboards.ts";
import { beginStatus, clearStatus, setReaction } from "./status.ts";
import { errorText } from "./tiktok.ts";
import { canonicalHttpsUrl, parsePublicUrl, urlCandidates } from "./urls.ts";

export function findInstagramUrl(value: string, entities: MessageEntity[] | undefined = []): string | null {
  for (const candidate of urlCandidates(value, entities)) {
    const match = matchInstagram(candidate);
    if (match) return match;
  }
  return null;
}
function matchInstagram(value: string): string | null {
  const url = parsePublicUrl(value);
  if (!url || !["instagram.com", "www.instagram.com"].includes(url.hostname.toLowerCase())) return null;
  if (!/^\/(?:p|reels?|tv)\/[A-Za-z0-9_-]+\/?$/u.test(url.pathname)) return null;
  return canonicalHttpsUrl(url);
}

export function registerLinkHandlers(bot: Bot<BotContext>): void {
  bot.on("message:text", async (ctx, next) => {
    const link = findInstagramUrl(ctx.message.text, ctx.message.entities);
    if (!link) return next();
    const group = ctx.chat.type !== "private";
    const user = await ctx.getUserRecord();
    let lang: Language;
    let fileMode: boolean;
    if (!user) { lang = await resolveLanguage(ctx, true); fileMode = false; await registerAndWelcome(ctx, lang); }
    else { lang = user.lang; fileMode = user.fileMode; }
    const status = await beginStatus(ctx, ctx.message);
    try {
      const queued = await ctx.queue.withSlot(ctx.chat.id, async () => {
        const extraction = await ctx.scrap.extractInstagram(link, { attempts: 4 });
        if (!status) await setReaction(ctx, ctx.message, "👨‍💻");
        await ctx.api.sendChatAction(ctx.chat.id, extraction.content_type === "video" ? "upload_video" : "upload_photo");
        const delivery = new DeliveryService(ctx.scrap, ctx.config);
        let result;
        if (group && extraction.content_type !== "video" && extraction.media.length > 10) {
          const staged = await delivery.stageInstagram(extraction, link, identity(ctx), fileMode);
          const stagedMessages = allMessages(staged).slice(0, 10);
          const sent = fileMode
            ? await ctx.api.sendMediaGroup(ctx.chat.id, stagedMessages.map((item, index): InputMediaDocument => ({ type: "document", media: requiredFileId(item, index), disable_content_type_detection: true })), { disable_notification: true, reply_parameters: { message_id: ctx.message.message_id } })
            : await ctx.api.sendMediaGroup(ctx.chat.id, stagedMessages.map((item, index): InputMediaPhoto | InputMediaVideo => item.video
              ? { type: "video", media: requiredFileId(item, index), supports_streaming: true }
              : { type: "photo", media: requiredFileId(item, index) }), { disable_notification: true, reply_parameters: { message_id: ctx.message.message_id } });
          result = { calls: [{ method: "sendMediaGroup", statusCode: 200, result: sent }] };
        } else {
          result = await delivery.deliverInstagram(extraction, link, ctx.chat.id, ctx.message.message_id, lang, fileMode);
        }
        if (extraction.content_type !== "video") {
          const final = lastBatch(result)[0];
          if (final) await ctx.api.sendMessage(ctx.chat.id, resultCaption(lang, link, group), { parse_mode: "HTML", link_preview_options: { is_disabled: true }, reply_parameters: { message_id: final.message_id } });
        }
        await clearStatus(ctx, ctx.message, status);
        return extraction;
      }, { group });
      if (!queued.acquired) {
        await clearStatus(ctx, ctx.message, status);
        if (queued.reason === "capacity") await ctx.reply(text(lang, "error_queue_full").replace("{0}", String(ctx.queue.count(ctx.chat.id))), { parse_mode: "HTML", reply_markup: retryKeyboard(lang), reply_parameters: { message_id: ctx.message.message_id } });
        return;
      }
      const extraction = queued.value;
      try {
        await addVideo(ctx.db, ctx.chat.id, link, extraction.content_type !== "video");
        logger.info(`Instagram Download: CHAT ${ctx.chat.id} - URL ${link}`);
      } catch (error) { logger.error("Can't write Instagram download into database", error); }
    } catch (error) {
      logger.error(`Instagram handler failed for ${link}`, error);
      await clearStatus(ctx, ctx.message, status);
      if (!status) await setReaction(ctx, ctx.message, "😢");
      if (!group) await ctx.reply(errorText(error, lang, true), { parse_mode: "HTML", reply_parameters: { message_id: ctx.message.message_id } });
    }
  });
}

function identity(ctx: BotContext): { userId?: number; username?: string; fullName?: string } {
  if (!ctx.from) return {};
  return { userId: ctx.from.id, fullName: [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" "), ...(ctx.from.username ? { username: ctx.from.username } : {}) };
}
function requiredFileId(message: Parameters<typeof fileIdFromMessage>[0], index: number): string {
  const fileId = fileIdFromMessage(message);
  if (!fileId) throw new Error(`Staged Instagram item ${index} has no Telegram file ID`);
  return fileId;
}
