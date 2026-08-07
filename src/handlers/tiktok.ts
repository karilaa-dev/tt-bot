import type { Bot } from "grammy";
import type { InputMediaDocument, InputMediaPhoto, Message } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { PartialDeliveryError, TtScrapError } from "../bot/errors.ts";
import { addVideo } from "../db/videos.ts";
import { type Language, text } from "../locales.ts";
import { logger } from "../logging.ts";
import { sendAdminDiagnostic } from "../services/admin-diagnostics.ts";
import { DeliveryService, allMessages, fileIdFromMessage, lastBatch } from "../services/delivery.ts";
import { resolveDownloadPreferences, resolveLanguage } from "../services/registration.ts";
import { resultCaption } from "../ui/captions.ts";
import { musicKeyboard } from "../ui/keyboards.ts";
import { queueRejectionAlert, replyForQueueRejection } from "./queue-rejection.ts";
import { beginStatus, clearStatus, setReaction } from "./status.ts";
import { canonicalHttpsUrl, parsePublicUrl, urlCandidates } from "./urls.ts";

const retryingVideos = new Set<string>();

export function findTikTokUrl(value: string, entities: Message["entities"] = []): string | null {
  for (const candidate of urlCandidates(value, entities)) {
    const match = matchTikTok(candidate);
    if (match) return match;
  }
  return null;
}

function matchTikTok(value: string): string | null {
  const url = parsePublicUrl(value);
  if (!url) return null;
  if (!isTikTokHost(url.hostname)) return null;
  const host = normalizedTikTokHost(url.hostname);
  const path = url.pathname.replace(/\/+$/u, "") || "/";
  const isShortLink = (host === "vm.tiktok.com" || host === "vt.tiktok.com") && /^\/[A-Za-z0-9_-]+$/u.test(path);
  const isPostLink = /^\/@[A-Za-z0-9._-]+\/(?:video|photo)\/[0-9]+$/u.test(path)
    || /^\/t\/[A-Za-z0-9_-]+$/u.test(path)
    || /^\/v\/[0-9]+(?:\.html)?$/u.test(path)
    || /^\/embed(?:\/v2)?\/[0-9]+$/u.test(path)
    || /^\/player\/v1\/[0-9]+$/u.test(path)
    || /^\/share\/(?:video|item)\/[0-9]+$/u.test(path);
  if (isShortLink || isPostLink) return canonicalHttpsUrl(url);
  const itemId = url.searchParams.get("item_id") ?? url.searchParams.get("share_item_id");
  return path === "/" && itemId && /^[0-9]+$/u.test(itemId) ? `https://www.tiktok.com/@_/video/${itemId}` : null;
}

export function tikTokExtractionUrl(link: string): string {
  const url = parsePublicUrl(link);
  if (!url || !isTikTokHost(url.hostname)) return link;
  const pathMatch = url.pathname.match(/^\/(?:v|embed(?:\/v2)?|player\/v1|share\/(?:video|item))\/([0-9]+)(?:\.html)?\/?$/u);
  const queryId = url.searchParams.get("item_id") ?? url.searchParams.get("share_item_id");
  const videoId = pathMatch?.[1] ?? (queryId && /^[0-9]+$/u.test(queryId) ? queryId : null);
  return videoId ? `https://www.tiktok.com/@_/video/${videoId}` : link;
}

function isTikTokHost(hostname: string): boolean {
  const host = normalizedTikTokHost(hostname);
  return host === "tiktok.com" || host.endsWith(".tiktok.com");
}

function normalizedTikTokHost(hostname: string): string {
  return hostname.replace(/\.$/u, "").toLowerCase();
}

export function registerTikTokHandlers(bot: Bot<BotContext>): void {
  bot.on("message:text", async (ctx) => {
    const message = ctx.message;
    const group = ctx.chat.type !== "private";
    const link = findTikTokUrl(message.text, message.entities);
    if (!link) {
      if (!group) {
        const lang = await resolveLanguage(ctx);
        const hasUrl = message.entities?.some((entity) => entity.type === "url" || entity.type === "text_link") ?? false;
        await ctx.reply(text(lang, hasUrl ? "non_tiktok_link" : "send_link_prompt"), { parse_mode: "HTML" });
      }
      return;
    }
    const { lang, fileMode } = await resolveDownloadPreferences(ctx);

    const status = await beginStatus(ctx, message);
    try {
      const queued = await ctx.queue.withSlot(ctx.chat.id, async () => {
        const extraction = await ctx.scrap.extractTikTok(tikTokExtractionUrl(link), { attempts: 4 });
        if (!status) await setReaction(ctx, message, "👨‍💻");
        await ctx.api.sendChatAction(ctx.chat.id, extraction.content_type === "video" ? "upload_video" : "upload_photo");
        const delivery = new DeliveryService(ctx.scrap, ctx.config);
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
        return extraction;
      }, { group });
      if (!queued.acquired) {
        await clearStatus(ctx, message, status);
        await replyForQueueRejection(ctx, queued.reason, lang, message.message_id, group);
        return;
      }
      const extraction = queued.value;
      try {
        await addVideo(ctx.db, ctx.chat.id, link, extraction.content_type === "slideshow");
        logger.info(`Video Download: CHAT ${ctx.chat.id} - VIDEO ${link}`);
      } catch (error) { logger.error("Can't write video download into database", error); }
    } catch (error) {
      logger.error(`TikTok handler failed for ${link}`, error);
      await clearStatus(ctx, message, status);
      if (!status) await setReaction(ctx, message, "😢");
      if (!group) await ctx.reply(errorText(error, lang), { parse_mode: "HTML", reply_parameters: { message_id: message.message_id } });
      await sendAdminDiagnostic(ctx, error);
    }
  });

  bot.callbackQuery("retry_video", async (ctx) => {
    const original = ctx.callbackQuery.message?.reply_to_message;
    if (!original?.text) return ctx.answerCallbackQuery({ text: "Original message not found", show_alert: true });
    if (!original.from || ctx.from.id !== original.from.id) return ctx.answerCallbackQuery();
    const retryKey = `${original.chat.id}:${original.message_id}`;
    if (retryingVideos.has(retryKey)) return ctx.answerCallbackQuery({ text: "Already retrying…" });
    retryingVideos.add(retryKey);
    try {
      const group = original.chat.type !== "private";
      const rejection = ctx.queue.rejectionReason(original.chat.id, group);
      if (rejection) {
        const lang = await resolveLanguage(ctx);
        return ctx.answerCallbackQuery({ text: queueRejectionAlert(ctx, rejection, lang), show_alert: true });
      }
      try { if (ctx.callbackQuery.message) await ctx.api.deleteMessage(ctx.callbackQuery.message.chat.id, ctx.callbackQuery.message.message_id); } catch { /* already deleted */ }
      await ctx.answerCallbackQuery();
      // Re-inject the original update through the bot so normal routing and context setup apply.
      await bot.handleUpdate({ update_id: Date.now(), message: original } as Parameters<typeof bot.handleUpdate>[0]);
    } finally {
      retryingVideos.delete(retryKey);
    }
  });
}

function identity(message: Message): { userId?: number; username?: string; fullName?: string } {
  if (!message.from) return {};
  const result: { userId?: number; username?: string; fullName?: string } = { userId: message.from.id, fullName: [message.from.first_name, message.from.last_name].filter(Boolean).join(" ") };
  if (message.from.username) result.username = message.from.username;
  return result;
}
export function errorText(error: unknown, lang: Language, instagram = false): string {
  if (error instanceof PartialDeliveryError) return text(lang, "error_partial_delivery");
  if (!(error instanceof TtScrapError)) return text(lang, "error");
  if (error.code === "telegram_delivery_ambiguous") return text(lang, "error_delivery_unknown");
  const key = error.code === "content_deleted" || (instagram && error.code === "content_private") ? (instagram ? "error_instagram_not_found" : "error_deleted")
    : error.code === "content_private" ? "error_private"
    : error.code === "invalid_link" ? "link_error"
    : error.code === "upstream_rate_limited" ? "error_rate_limit"
    : error.code === "region_blocked" ? "error_region"
    : ["content_too_long", "asset_too_large"].includes(error.code) ? "error_too_long"
    : ["upstream_network_error", "upstream_extraction_error", "upstream_timeout", "telegram_network_error", "telegram_timeout"].includes(error.code) ? "error_network"
    : "error";
  return text(lang, key);
}
export function shouldOfferRetry(error: unknown): boolean {
  return !(error instanceof PartialDeliveryError)
    && !(error instanceof TtScrapError && error.code === "telegram_delivery_ambiguous");
}
