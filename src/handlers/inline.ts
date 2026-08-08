import type { Bot } from "grammy";
import type { InlineKeyboardMarkup, InlineQueryResultArticle } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { type Language, text } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, inlineMediaFromFiles, inlineMediaFromMessage, inlineMediaPayload, telegramFilesFromResult, type InlineMediaReference } from "../services/delivery.ts";
import { executeInstagramMediaRequest, executeTikTokMediaRequest } from "../services/media-cache.ts";
import { resolveLanguage } from "../services/registration.ts";
import { loadingKeyboard, statsKeyboard } from "../ui/keyboards.ts";
import { createInlineSlideshow } from "./inline-slideshow.ts";
import { findInstagramUrl } from "./links.ts";
import { errorText, findTikTokUrl, shouldOfferRetry } from "./tiktok.ts";

const retrying = new Set<string>();

export function registerInlineHandlers(bot: Bot<BotContext>): void {
  bot.on("inline_query", async (ctx) => {
    const query = ctx.inlineQuery.query.trim();
    const lang = await languageForInline(ctx, ctx.from.id);
    if (!await ctx.getUserRecord(ctx.from.id)) {
      await ctx.answerInlineQuery([], { cache_time: 0, is_personal: true, button: { text: text(lang, "inline_start_bot"), start_parameter: "inline" } });
      return;
    }
    if (query.length < 12) return void await ctx.answerInlineQuery([], { cache_time: 0 });
    const loading = loadingKeyboard.inline_keyboard;
    let result: InlineQueryResultArticle;
    if (findTikTokUrl(query)) result = article("tt_download", text(lang, "inline_download_video"), text(lang, "inline_download_video_description"), text(lang, "inline_download_video_text"), "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/tiktok-light.png", loading);
    else if (findInstagramUrl(query)) result = article("ig_download", text(lang, "inline_download_instagram"), text(lang, "inline_download_instagram_description"), text(lang, "inline_download_video_text"), "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/instagram.png", loading);
    else result = article("wrong_link", text(lang, "inline_wrong_link_title"), text(lang, "inline_wrong_link_description"), text(lang, "inline_wrong_link"), "https://em-content.zobj.net/source/apple/419/cross-mark_274c.png");
    await ctx.answerInlineQuery([result], { cache_time: 0 });
  });

  bot.on("chosen_inline_result", async (ctx) => {
    const id = ctx.chosenInlineResult.inline_message_id;
    if (!id) return;
    const resultId = ctx.chosenInlineResult.result_id;
    if (resultId !== "tt_download" && resultId !== "ig_download") return;
    const user = await ctx.getUserRecord(ctx.from.id); if (!user) return;
    await processInline(ctx, id, ctx.chosenInlineResult.query, user.lang, resultId === "ig_download");
  });

  bot.callbackQuery(/^ir:(tt|ig):([0-9a-z]+):(.+)$/, async (ctx) => {
    const id = ctx.callbackQuery.inline_message_id;
    if (!id) return ctx.answerCallbackQuery();
    if (ctx.from.id.toString(36) !== ctx.match[2]) return ctx.answerCallbackQuery();
    const instagram = ctx.match[1] === "ig";
    const link = normalize(`https://${ctx.match[3]}`, instagram);
    if (!link) return ctx.answerCallbackQuery({ text: "Retry button expired.", show_alert: true });
    if (retrying.has(id)) return ctx.answerCallbackQuery({ text: "Retrying..." });
    retrying.add(id);
    try {
      const lang = await languageForInline(ctx, ctx.from.id);
      await ctx.answerCallbackQuery();
      await editText(ctx, id, text(lang, "inline_download_video_text"), { inline_keyboard: loadingKeyboard.inline_keyboard });
      await processInline(ctx, id, link, lang, instagram);
    } finally { retrying.delete(id); }
  });

  // Buttons created before ownership was encoded cannot be authorized safely.
  bot.callbackQuery(/^ir:(?:tt|ig):[^:]+$/, (ctx) => ctx.answerCallbackQuery({ text: "Retry button expired.", show_alert: true }));
}

async function processInline(ctx: BotContext, id: string, rawLink: string, lang: Language, instagram: boolean): Promise<void> {
  const link = normalize(rawLink, instagram);
  if (!link) {
    await editText(ctx, id, text(lang, "inline_wrong_link"), { inline_keyboard: [] });
    return;
  }
  try {
    const queued = await ctx.queue.withSlot(ctx.from!.id, async () => {
      const onRetry = async (attempt: number, max: number) => editText(ctx, id, `${text(lang, "inline_download_video_text")}\n${text(lang, "inline_retry_attempt").replace("{0}", String(attempt)).replace("{1}", String(max))}`, { inline_keyboard: loadingKeyboard.inline_keyboard });
      const identity = { userId: ctx.from!.id, fullName: [ctx.from!.first_name, ctx.from!.last_name].filter(Boolean).join(" "), ...(ctx.from!.username ? { username: ctx.from!.username } : {}) };
      const options = {
        db: ctx.db, scrap: ctx.scrap, link, userId: ctx.from!.id, botId: ctx.me.id,
        fileMode: false, deliverySurface: "inline" as const, retry: { attempts: 4, onRetry },
      };
      const execute = instagram ? executeInstagramMediaRequest : executeTikTokMediaRequest;
      return execute(options, async (prepared) => {
        let media: InlineMediaReference[];
        let telegramFiles;
        if (prepared.cachedFiles) {
          media = inlineMediaFromFiles(prepared.cachedFiles);
        } else {
          const service = new DeliveryService(ctx.scrap, ctx.config);
          const extraction = prepared.extraction;
          if (!extraction) throw new Error("Extraction is required for inline storage upload");
          const result = extraction.platform === "instagram"
            ? await service.stageInstagram(extraction, link, identity)
            : await service.stageTikTok(extraction, link, identity);
          telegramFiles = telegramFilesFromResult(result);
          media = allMessages(result).map(inlineMediaFromMessage).filter((value): value is InlineMediaReference => value !== null);
        }
        if (!media.length) throw new Error("Storage delivery returned no inline-compatible Telegram media");
        if (media.length === 1) {
          const markup = prepared.platform === "tiktok" ? statsKeyboard(prepared.likesDisplay, prepared.viewsDisplay) : undefined;
          await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(media[0]!, lang, link), ...(markup ? { reply_markup: markup } : {}) });
        } else {
          const keyboard = createInlineSlideshow(ctx.api, id, media, lang, link, identity,
            prepared.platform === "tiktok" ? prepared.likesDisplay : undefined,
            prepared.platform === "tiktok" ? prepared.viewsDisplay : undefined,
            prepared.detailsId !== null && prepared.cacheVersion !== null ? { detailsId: prepared.detailsId, cacheVersion: prepared.cacheVersion } : undefined);
          await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(media[0]!, lang, link), reply_markup: keyboard });
        }
        return { value: media, ...(telegramFiles ? { telegramFiles } : {}) };
      });
    });
    if (!queued.acquired) {
      if (queued.reason === "capacity") await editText(ctx, id, text(lang, "error_queue_full").replace("{0}", String(ctx.queue.count(ctx.from!.id))), retryKeyboard(lang, link, instagram, ctx.from!.id));
      return;
    }
    const completed = queued.value;
    logger.info(`Inline Download: ${ctx.from!.id} - ${completed.prepared.contentType === "video" ? "VIDEO" : "IMAGES"} ${link} - CACHE ${completed.cacheHit ? "HIT" : "MISS"}`);
  } catch (error) {
    logger.error(`Inline delivery failed for ${link}`, error);
    const markup = shouldOfferRetry(error) ? retryKeyboard(lang, link, instagram, ctx.from!.id) : { inline_keyboard: [] };
    await editText(ctx, id, errorText(error, lang, instagram), markup);
  }
}


async function languageForInline(ctx: BotContext, userId: number): Promise<Language> {
  const user = await ctx.getUserRecord(userId); return user?.lang ?? await resolveLanguage(ctx, true);
}
function article(id: string, title: string, description: string, body: string, thumbnail: string, keyboard?: InlineKeyboardMarkup["inline_keyboard"]): InlineQueryResultArticle {
  return { type: "article", id, title, description, input_message_content: { message_text: body, parse_mode: "HTML" }, thumbnail_url: thumbnail, ...(keyboard ? { reply_markup: { inline_keyboard: keyboard } } : {}) };
}
async function editText(ctx: BotContext, id: string, value: string, markup?: InlineKeyboardMarkup): Promise<void> {
  try { await ctx.api.raw.editMessageText({ inline_message_id: id, text: value, parse_mode: "HTML", ...(markup ? { reply_markup: markup } : {}) }); }
  catch (error) { logger.warn("Inline text edit failed", error); }
}
function retryKeyboard(lang: Language, link: string, instagram: boolean, ownerId: number): InlineKeyboardMarkup {
  const data = inlineRetryCallbackData(link, instagram, ownerId);
  return { inline_keyboard: data ? [[{ text: text(lang, "try_again_button"), callback_data: data }]] : [] };
}
function normalize(value: string, instagram: boolean): string | null {
  return instagram ? findInstagramUrl(value) : findTikTokUrl(value);
}
export function compressInlineRetryLink(link: string, instagram: boolean): string {
  const normalized = normalize(link, instagram);
  if (!normalized) return "";
  let value = normalized.split("?")[0]!.replace(/^https?:\/\//, "");
  if (!instagram) value = value.replace(/@[\w.]+/, "@user");
  return value;
}

export function inlineRetryCallbackData(link: string, instagram: boolean, ownerId: number): string | null {
  const compressed = compressInlineRetryLink(link, instagram);
  if (!compressed) return null;
  const data = `ir:${instagram ? "ig" : "tt"}:${ownerId.toString(36)}:${compressed}`;
  return data.length <= 64 ? data : null;
}
