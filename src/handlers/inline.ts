import type { Bot } from "grammy";
import type { InlineKeyboardMarkup, InlineQueryResultArticle } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { getUser } from "../db/users.ts";
import { addVideo } from "../db/videos.ts";
import { type Language, text } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, fileIdFromMessage } from "../services/delivery.ts";
import { resolveLanguage } from "../services/registration.ts";
import { resultCaption } from "../ui/captions.ts";
import { loadingKeyboard, statsKeyboard } from "../ui/keyboards.ts";
import { createInlineSlideshow } from "./inline-slideshow.ts";
import { findInstagramUrl } from "./links.ts";
import { errorText, findTikTokUrl } from "./tiktok.ts";

const retrying = new Set<string>();

export function registerInlineHandlers(bot: Bot<BotContext>): void {
  bot.on("inline_query", async (ctx) => {
    const query = ctx.inlineQuery.query.trim();
    const lang = await languageForInline(ctx, ctx.from.id);
    if (!await getUser(ctx.db, ctx.from.id)) {
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
    const user = await getUser(ctx.db, ctx.from.id); if (!user) return;
    await processInline(ctx, id, ctx.chosenInlineResult.query, user.lang, ctx.chosenInlineResult.result_id === "ig_download");
  });

  bot.callbackQuery(/^ir:(tt|ig):(.+)$/, async (ctx) => {
    const id = ctx.callbackQuery.inline_message_id;
    if (!id) return ctx.answerCallbackQuery();
    if (retrying.has(id)) return ctx.answerCallbackQuery({ text: "Retrying..." });
    retrying.add(id);
    try {
      const lang = await languageForInline(ctx, ctx.from.id);
      await ctx.answerCallbackQuery();
      await editText(ctx, id, text(lang, "inline_download_video_text"), { inline_keyboard: loadingKeyboard.inline_keyboard });
      await processInline(ctx, id, `https://${ctx.match[2]}`, lang, ctx.match[1] === "ig");
    } finally { retrying.delete(id); }
  });
}

async function processInline(ctx: BotContext, id: string, rawLink: string, lang: Language, instagram: boolean): Promise<void> {
  const link = normalize(rawLink, instagram);
  try {
    const queued = await ctx.queue.withSlot(ctx.from!.id, async () => {
      const onRetry = async (attempt: number, max: number) => editText(ctx, id, `${text(lang, "inline_download_video_text")}\n${text(lang, "inline_retry_attempt").replace("{0}", String(attempt)).replace("{1}", String(max))}`, { inline_keyboard: loadingKeyboard.inline_keyboard });
      return instagram ? ctx.scrap.extractInstagram(link, { attempts: 4, onRetry }) : ctx.scrap.extractTikTok(link, { attempts: 4, onRetry });
    }, true);
    if (!queued.acquired) throw new Error("Inline queue rejected unexpectedly");
    const extraction = queued.value;
    const identity = { userId: ctx.from!.id, fullName: [ctx.from!.first_name, ctx.from!.last_name].filter(Boolean).join(" "), ...(ctx.from!.username ? { username: ctx.from!.username } : {}) };
    const service = new DeliveryService(ctx.scrap, ctx.api, ctx.config);
    const result = extraction.platform === "instagram" ? await service.stageInstagram(extraction, link, identity) : await service.stageTikTok(extraction, link, identity);
    const messages = allMessages(result);
    const files = messages.map(fileIdFromMessage).filter((value): value is string => !!value);
    if (!files.length) throw new Error("Storage delivery returned no Telegram file IDs");
    const isVideo = extraction.content_type === "video";
    if (isVideo) {
      const markup = extraction.platform === "tiktok" ? statsKeyboard(extraction.likes, extraction.views) : undefined;
      await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: { type: "video", media: files[0]!, caption: resultCaption(lang, link), parse_mode: "HTML", supports_streaming: true }, ...(markup ? { reply_markup: markup } : {}) });
    } else if (files.length === 1) {
      const markup = extraction.platform === "tiktok" ? statsKeyboard(extraction.likes, extraction.views) : undefined;
      await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: { type: "photo", media: files[0]!, caption: resultCaption(lang, link), parse_mode: "HTML" }, ...(markup ? { reply_markup: markup } : {}) });
    } else {
      const keyboard = createInlineSlideshow(ctx.api, id, files, lang, link, identity, extraction.platform === "tiktok" ? extraction.likes : undefined, extraction.platform === "tiktok" ? extraction.views : undefined);
      await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: { type: "photo", media: files[0]!, caption: resultCaption(lang, link), parse_mode: "HTML" }, reply_markup: keyboard });
    }
    try {
      await addVideo(ctx.db, ctx.from!.id, link, !isVideo, false, true);
      logger.info(`Inline Download: ${ctx.from!.id} - ${isVideo ? "VIDEO" : "IMAGES"} ${link}`);
    } catch (error) { logger.error("Can't write inline download into database", error); }
  } catch (error) {
    logger.error(`Inline delivery failed for ${link}`, error);
    await editText(ctx, id, errorText(error, lang, instagram), retryKeyboard(lang, link, instagram));
  }
}

async function languageForInline(ctx: BotContext, userId: number): Promise<Language> {
  const user = await getUser(ctx.db, userId); return user?.lang ?? await resolveLanguage(ctx, true);
}
function article(id: string, title: string, description: string, body: string, thumbnail: string, keyboard?: InlineKeyboardMarkup["inline_keyboard"]): InlineQueryResultArticle {
  return { type: "article", id, title, description, input_message_content: { message_text: body, parse_mode: "HTML" }, thumbnail_url: thumbnail, ...(keyboard ? { reply_markup: { inline_keyboard: keyboard } } : {}) };
}
async function editText(ctx: BotContext, id: string, value: string, markup?: InlineKeyboardMarkup): Promise<void> {
  try { await ctx.api.raw.editMessageText({ inline_message_id: id, text: value, parse_mode: "HTML", ...(markup ? { reply_markup: markup } : {}) }); } catch { /* message may already contain the same text */ }
}
function retryKeyboard(lang: Language, link: string, instagram: boolean): InlineKeyboardMarkup {
  const data = `ir:${instagram ? "ig" : "tt"}:${compress(link, instagram)}`;
  return { inline_keyboard: data.length <= 64 ? [[{ text: text(lang, "try_again_button"), callback_data: data }]] : [] };
}
function normalize(value: string, instagram: boolean): string {
  const link = (instagram ? findInstagramUrl(value) : findTikTokUrl(value)) ?? value.trim(); return link.replace(/[.,)]+$/, "");
}
function compress(link: string, instagram: boolean): string {
  let value = normalize(link, instagram).split("?")[0]!.replace(/^https?:\/\//, "");
  if (!instagram) value = value.replace(/@[\w.]+/, "@");
  return value;
}
