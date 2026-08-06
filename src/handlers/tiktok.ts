import type { Bot } from "grammy";
import type { InputMediaDocument, InputMediaPhoto, Message } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { TtScrapError } from "../bot/errors.ts";
import { getUser } from "../db/users.ts";
import { addVideo } from "../db/videos.ts";
import { type Language, text } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, fileIdFromMessage, lastBatch } from "../services/delivery.ts";
import { registerAndWelcome, resolveLanguage } from "../services/registration.ts";
import { resultCaption } from "../ui/captions.ts";
import { musicKeyboard, retryKeyboard } from "../ui/keyboards.ts";
import { beginStatus, clearStatus, setReaction } from "./status.ts";

const webRegex = /https?:\/\/www\.tiktok\.com\/@[^\s]+?\/video\/[0-9]+/i;
const photoRegex = /https?:\/\/www\.tiktok\.com\/@[^\s]+?\/photo\/[0-9]+/i;
const mobileRegex = /https?:\/\/[^\s]+tiktok\.com\/[^\s]+/i;

export function findTikTokUrl(value: string, entities: Message["entities"] = []): string | null {
  const direct = matchTikTok(value);
  if (direct) return direct;
  for (const entity of entities ?? []) {
    const candidate = entity.type === "text_link" ? entity.url : entity.type === "url" ? value.slice(entity.offset, entity.offset + entity.length) : null;
    if (candidate) {
      const embedded = matchTikTok(candidate);
      if (embedded) return embedded;
    }
  }
  return null;
}

function matchTikTok(value: string): string | null {
  const match = value.match(webRegex)?.[0] ?? value.match(photoRegex)?.[0] ?? value.match(mobileRegex)?.[0] ?? null;
  return match?.replace(/[.,)]+$/, "") ?? null;
}

export function registerTikTokHandlers(bot: Bot<BotContext>): void {
  bot.on("message:text", async (ctx) => {
    const message = ctx.message;
    const group = ctx.chat.type !== "private";
    let user = await getUser(ctx.db, ctx.chat.id);
    let lang: Language;
    let fileMode: boolean;
    if (!user) {
      lang = await resolveLanguage(ctx, true);
      fileMode = false;
      await registerAndWelcome(ctx, lang);
      user = await getUser(ctx.db, ctx.chat.id);
    } else { lang = user.lang; fileMode = user.fileMode; }

    const link = findTikTokUrl(message.text, message.entities);
    if (!link) {
      if (!group) {
        const hasUrl = message.entities?.some((entity) => entity.type === "url" || entity.type === "text_link") ?? false;
        await ctx.reply(text(lang, hasUrl ? "non_tiktok_link" : "send_link_prompt"), { parse_mode: "HTML" });
      }
      return;
    }

    if (ctx.config.maxUserQueueSize > 0 && ctx.queue.count(ctx.chat.id) >= ctx.config.maxUserQueueSize) {
      if (!group) await ctx.reply(text(lang, "error_queue_full").replace("{0}", String(ctx.queue.count(ctx.chat.id))), { parse_mode: "HTML", reply_markup: retryKeyboard(lang), reply_parameters: { message_id: message.message_id } });
      return;
    }

    const status = await beginStatus(ctx, message);
    try {
      const queued = await ctx.queue.withSlot(ctx.chat.id, () => ctx.scrap.extractTikTok(link));
      if (!queued.acquired) {
        await clearStatus(ctx, message, status);
        if (!group) await ctx.reply(text(lang, "error_queue_full").replace("{0}", String(ctx.queue.count(ctx.chat.id))), { parse_mode: "HTML", reply_markup: retryKeyboard(lang), reply_parameters: { message_id: message.message_id } });
        return;
      }
      const extraction = queued.value;
      if (!status) await setReaction(ctx, message, "👨‍💻");
      await ctx.api.sendChatAction(ctx.chat.id, extraction.content_type === "video" ? "upload_video" : "upload_photo");
      const delivery = new DeliveryService(ctx.scrap, ctx.api, ctx.config);
      let result;
      if (group && extraction.content_type === "slideshow" && extraction.media.length > 10) {
        const staged = await delivery.stageTikTok(extraction, link, identity(message), fileMode);
        const stagedMessages = allMessages(staged).slice(0, 10);
        const fileIds = stagedMessages.map((item, index) => {
          const fileId = fileIdFromMessage(item);
          if (!fileId) throw new Error(`Staged slideshow item ${index} has no Telegram file ID`);
          return fileId;
        });
        const sent = fileMode
          ? await ctx.api.sendMediaGroup(ctx.chat.id, fileIds.map((media) => ({ type: "document", media, disable_content_type_detection: true } satisfies InputMediaDocument)), { disable_notification: true, reply_parameters: { message_id: message.message_id } })
          : await ctx.api.sendMediaGroup(ctx.chat.id, fileIds.map((media) => ({ type: "photo", media } satisfies InputMediaPhoto)), { disable_notification: true, reply_parameters: { message_id: message.message_id } });
        result = { calls: [{ method: "sendMediaGroup", statusCode: 200, result: sent }] };
      } else {
        result = await delivery.deliverTikTokToChat(extraction, link, ctx.chat.id, message.message_id, lang, fileMode);
      }
      if (extraction.content_type === "slideshow") {
        const final = lastBatch(result)[0];
        if (final) await ctx.api.sendMessage(ctx.chat.id, resultCaption(lang, link, group), {
          parse_mode: "HTML", link_preview_options: { is_disabled: true }, reply_parameters: { message_id: final.message_id },
          reply_markup: musicKeyboard(extraction.source_id, lang, extraction.likes, extraction.views),
        });
      }
      await clearStatus(ctx, message, status);
      try {
        await addVideo(ctx.db, ctx.chat.id, link, extraction.content_type === "slideshow");
        logger.info(`Video Download: CHAT ${ctx.chat.id} - VIDEO ${link}`);
      } catch (error) { logger.error("Can't write video download into database", error); }
    } catch (error) {
      logger.error(`TikTok handler failed for ${link}`, error);
      await clearStatus(ctx, message, status);
      if (!status) await setReaction(ctx, message, "😢");
      if (!group) await ctx.reply(errorText(error, lang), { parse_mode: "HTML", reply_parameters: { message_id: message.message_id } });
      if (ctx.config.secondAdminIds.has(ctx.chat.id) && error instanceof Error) await ctx.reply(`<code>${escapeCode(adminDiagnostic(error))}</code>`, { parse_mode: "HTML" });
    }
  });

  bot.callbackQuery("retry_video", async (ctx) => {
    const original = ctx.callbackQuery.message?.reply_to_message;
    if (!original?.text) return ctx.answerCallbackQuery({ text: "Original message not found", show_alert: true });
    try { if (ctx.callbackQuery.message) await ctx.api.deleteMessage(ctx.callbackQuery.message.chat.id, ctx.callbackQuery.message.message_id); } catch { /* already deleted */ }
    await ctx.answerCallbackQuery();
    // Re-inject the original update through the bot so normal routing and context setup apply.
    await bot.handleUpdate({ update_id: Date.now(), message: original } as Parameters<typeof bot.handleUpdate>[0]);
  });
}

function identity(message: Message): { userId?: number; username?: string; fullName?: string } {
  if (!message.from) return {};
  const result: { userId?: number; username?: string; fullName?: string } = { userId: message.from.id, fullName: [message.from.first_name, message.from.last_name].filter(Boolean).join(" ") };
  if (message.from.username) result.username = message.from.username;
  return result;
}
export function errorText(error: unknown, lang: Language, instagram = false): string {
  if (!(error instanceof TtScrapError)) return text(lang, "error");
  const key = error.code === "content_deleted" || (instagram && error.code === "content_private") ? (instagram ? "error_instagram_not_found" : "error_deleted")
    : error.code === "content_private" ? "error_private"
    : error.code === "invalid_link" ? "link_error"
    : error.code === "upstream_rate_limited" ? "error_rate_limit"
    : error.code === "region_blocked" ? "error_region"
    : ["content_too_long", "asset_too_large"].includes(error.code) ? "error_too_long"
    : ["upstream_network_error", "upstream_extraction_error", "upstream_timeout", "telegram_network_error", "telegram_timeout", "telegram_delivery_ambiguous"].includes(error.code) ? "error_network"
    : "error";
  return text(lang, key);
}
function escapeCode(value: string): string { return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;"); }
function adminDiagnostic(error: Error): string {
  const summary = `${error.name}: ${error.message}`;
  const request = error instanceof TtScrapError ? `\ncode=${error.code}\nrequest_id=${error.requestId}` : "";
  const stack = error.stack && !error.stack.startsWith(summary) ? `\n${error.stack}` : "";
  return `${summary}${request}${stack}`;
}
