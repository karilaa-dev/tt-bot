import type { Api, Bot } from "grammy";
import type { InlineKeyboardMarkup } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import { invalidateTelegramFiles } from "../db/videos.ts";
import type { Language } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, inlineMediaFromFiles, inlineMediaFromMessage, inlineMediaPayload, telegramFilesFromResult, type InlineMediaReference } from "../services/delivery.ts";
import { executeInstagramMediaRequest, executeTikTokMediaRequest, type CacheIdentity } from "../services/media-cache.ts";
import { isConfirmedInvalidFileId } from "../services/media-cache.ts";
import { resolveLanguage } from "../services/registration.ts";
import { statsRow } from "../ui/stats.ts";
import type { DisplayStat } from "../ui/stats.ts";
import { findInstagramUrl } from "./links.ts";
import { findTikTokUrl } from "./tiktok.ts";

interface SlideshowSession {
  media: InlineMediaReference[];
  currentIndex: number;
  lang: Language;
  sourceLink: string;
  userId: number;
  username?: string;
  fullName: string;
  likes?: DisplayStat | null;
  views?: DisplayStat | null;
  timer: ReturnType<typeof setTimeout>;
  loading: Set<number>;
  cacheIdentity?: CacheIdentity;
}

const sessions = new Map<string, SlideshowSession>();
const refreshing = new Set<string>();
const TTL_MS = 600_000;

export function createInlineSlideshow(api: Api, inlineMessageId: string, media: InlineMediaReference[], lang: Language, sourceLink: string, identity: { userId: number; username?: string; fullName: string }, likes?: DisplayStat | null, views?: DisplayStat | null, cacheIdentity?: CacheIdentity): InlineKeyboardMarkup {
  if (!media.length) throw new Error("Slideshow delivery returned no inline-compatible Telegram media");
  const old = sessions.get(inlineMessageId);
  if (old) clearTimeout(old.timer);
  const session: SlideshowSession = {
    media, currentIndex: 0, lang, sourceLink, userId: identity.userId, fullName: identity.fullName,
    timer: setTimeout(() => expire(api, inlineMessageId), TTL_MS), loading: new Set(),
  };
  if (identity.username) session.username = identity.username;
  if (likes !== undefined) session.likes = likes;
  if (views !== undefined) session.views = views;
  if (cacheIdentity) session.cacheIdentity = cacheIdentity;
  sessions.set(inlineMessageId, session);
  return navigationKeyboard(0, media.length, likes, views);
}

export function registerInlineSlideshowHandlers(bot: Bot<BotContext>): void {
  bot.callbackQuery(/^slide:(prev|next|noop)$/, async (ctx) => {
    const id = ctx.callbackQuery.inline_message_id;
    if (!id) return ctx.answerCallbackQuery();
    const session = sessions.get(id);
    if (!session) return ctx.answerCallbackQuery({ text: "Slideshow expired.", show_alert: true });
    const action = ctx.match[1];
    if (action === "noop") return ctx.answerCallbackQuery();
    if (refreshing.has(id)) return ctx.answerCallbackQuery({ text: "Refreshing…" });
    const index = action === "next" ? Math.min(session.currentIndex + 1, session.media.length - 1) : Math.max(session.currentIndex - 1, 0);
    if (index === session.currentIndex) return ctx.answerCallbackQuery();
    if (session.loading.has(index)) return ctx.answerCallbackQuery({ text: "Loading…" });
    session.loading.add(index);
    try {
      await ctx.answerCallbackQuery();
      await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(session.media[index]!, session.lang, session.sourceLink), reply_markup: navigationKeyboard(index, session.media.length, session.likes, session.views) });
      session.currentIndex = index;
      resetTimer(ctx.api, id, session);
    } catch (error) {
      logger.warn("Inline slideshow edit failed", error);
      const cacheIdentity = session.cacheIdentity;
      if (isConfirmedInvalidFileId(error) && cacheIdentity?.detailsId !== null && cacheIdentity?.detailsId !== undefined
        && cacheIdentity.cacheVersion !== null && cacheIdentity.cacheVersion !== undefined) {
        await queueInvalidSessionRecovery(ctx, id, session, index, {
          detailsId: cacheIdentity.detailsId,
          cacheVersion: cacheIdentity.cacheVersion,
        });
      }
    }
    finally { session.loading.delete(index); }
  });

  bot.callbackQuery(/^sr:(\d+):(\d+):(.+)$/, async (ctx) => {
    const id = ctx.callbackQuery.inline_message_id;
    if (!id) return ctx.answerCallbackQuery();
    const ownerId = Number(ctx.match[1]);
    if (ctx.from.id !== ownerId) return ctx.answerCallbackQuery({ text: "Only the original requester can refresh this slideshow.", show_alert: true });
    const callbackLink = `https://${ctx.match[3]}`;
    const instagramLink = findInstagramUrl(callbackLink);
    const tikTokLink = instagramLink ? null : findTikTokUrl(callbackLink);
    const link = instagramLink ?? tikTokLink;
    if (!link) return ctx.answerCallbackQuery({ text: "Refresh button expired.", show_alert: true });
    if (refreshing.has(id)) return ctx.answerCallbackQuery({ text: "Refreshing…" });
    if (!ctx.queue.hasCapacity(ctx.from.id)) return ctx.answerCallbackQuery({ text: "Your download queue is full.", show_alert: true });
    refreshing.add(id);
    try {
      await ctx.answerCallbackQuery({ text: "Refreshing…" });
      const saved = Number(ctx.match[2]);
      const user = await ctx.getUserRecord(ctx.from.id);
      const lang = user?.lang ?? await resolveLanguage(ctx, true);
      const identity = { userId: ctx.from.id, fullName: [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" "), ...(ctx.from.username ? { username: ctx.from.username } : {}) };
      const service = new DeliveryService(ctx.scrap, ctx.config);
      const queued = await ctx.queue.withSlot(ctx.from.id, async () => {
        const options = {
          db: ctx.db, scrap: ctx.scrap, link, userId: ctx.from.id, botId: ctx.me.id,
          fileMode: false, deliverySurface: "inline" as const, retry: { attempts: 4 },
        };
        const execute = instagramLink ? executeInstagramMediaRequest : executeTikTokMediaRequest;
        await execute(options, async (prepared) => {
          let media: InlineMediaReference[];
          let telegramFiles;
          if (prepared.cachedFiles) media = inlineMediaFromFiles(prepared.cachedFiles);
          else {
            const extraction = prepared.extraction;
            if (!extraction) throw new Error("Extraction is required to refresh inline media");
            const result = extraction.platform === "instagram"
              ? await service.stageInstagram(extraction, link, identity)
              : await service.stageTikTok(extraction, link, identity);
            telegramFiles = telegramFilesFromResult(result);
            media = inlineMedia(result);
          }
          const likes = prepared.platform === "tiktok" ? prepared.likesDisplay : undefined;
          const views = prepared.platform === "tiktok" ? prepared.viewsDisplay : undefined;
          createInlineSlideshow(ctx.api, id, media, lang, link, identity, likes, views,
            prepared.cacheIdentity);
          const session = sessions.get(id)!;
          session.currentIndex = Math.max(0, Math.min(saved, media.length - 1));
          await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(media[session.currentIndex]!, lang, link), reply_markup: navigationKeyboard(session.currentIndex, media.length, likes, views) });
          return { value: media, ...(telegramFiles ? { telegramFiles } : {}) };
        });
      });
      if (!queued.acquired) {
        if (queued.reason === "capacity") logger.warn(`Inline refresh queue filled for user ${ctx.from.id}`);
        return;
      }
    } catch (error) { logger.error("Inline slideshow refresh failed", error); }
    finally { refreshing.delete(id); }
  });
}

async function queueInvalidSessionRecovery(ctx: BotContext, id: string, session: SlideshowSession, requestedIndex: number, cacheIdentity: { detailsId: bigint; cacheVersion: bigint }): Promise<void> {
  if (refreshing.has(id)) return;
  refreshing.add(id);
  try {
    const queued = await ctx.queue.withSlot(ctx.from!.id, async () => {
      await invalidateTelegramFiles(ctx.db, cacheIdentity.detailsId, cacheIdentity.cacheVersion);
      await recoverInvalidSession(ctx, id, session, requestedIndex);
    });
    if (!queued.acquired) logger.warn(`Inline slideshow recovery queue rejected user ${ctx.from!.id}: ${queued.reason}`);
  } catch (error) {
    logger.error("Inline slideshow invalid-file recovery failed", error);
  } finally {
    refreshing.delete(id);
  }
}

async function recoverInvalidSession(ctx: BotContext, id: string, old: SlideshowSession, requestedIndex: number): Promise<void> {
  const instagram = findInstagramUrl(old.sourceLink) !== null;
  const identity = { userId: old.userId, fullName: old.fullName, ...(old.username ? { username: old.username } : {}) };
  const options = {
    db: ctx.db, scrap: ctx.scrap, link: old.sourceLink, userId: old.userId, botId: ctx.me.id,
    fileMode: false, deliverySurface: "inline" as const, retry: { attempts: 4 }, recordHistory: false,
  };
  const execute = instagram ? executeInstagramMediaRequest : executeTikTokMediaRequest;
  await execute(options, async (prepared) => {
    let media: InlineMediaReference[];
    let telegramFiles;
    if (prepared.cachedFiles) media = inlineMediaFromFiles(prepared.cachedFiles);
    else {
      const extraction = prepared.extraction;
      if (!extraction) throw new Error("Extraction is required after an invalid inline file ID");
      const service = new DeliveryService(ctx.scrap, ctx.config);
      const delivered = extraction.platform === "instagram"
        ? await service.stageInstagram(extraction, old.sourceLink, identity)
        : await service.stageTikTok(extraction, old.sourceLink, identity);
      telegramFiles = telegramFilesFromResult(delivered);
      media = inlineMedia(delivered);
    }
    const likes = prepared.platform === "tiktok" ? prepared.likesDisplay : undefined;
    const views = prepared.platform === "tiktok" ? prepared.viewsDisplay : undefined;
    createInlineSlideshow(ctx.api, id, media, old.lang, old.sourceLink, identity, likes, views,
      prepared.cacheIdentity);
    const current = sessions.get(id)!;
    current.currentIndex = Math.max(0, Math.min(requestedIndex, media.length - 1));
    await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(media[current.currentIndex]!, old.lang, old.sourceLink), reply_markup: navigationKeyboard(current.currentIndex, media.length, likes, views) });
    return { value: media, ...(telegramFiles ? { telegramFiles } : {}) };
  });
}

export function cleanupInlineSlideshows(): void {
  for (const session of sessions.values()) clearTimeout(session.timer);
  sessions.clear();
}

function inlineMedia(result: Awaited<ReturnType<DeliveryService["stageTikTok"]>>): InlineMediaReference[] {
  return allMessages(result).map(inlineMediaFromMessage).filter((value): value is InlineMediaReference => value !== null);
}
function navigationKeyboard(index: number, total: number, likes?: DisplayStat | null, views?: DisplayStat | null): InlineKeyboardMarkup {
  const rows: InlineKeyboardMarkup["inline_keyboard"] = [];
  const stats = statsRow(likes, views);
  if (stats.length) rows.push(stats);
  const nav = [];
  if (index > 0) nav.push({ text: "◀️", callback_data: "slide:prev" });
  nav.push({ text: `📸 ${index + 1}/${total}`, callback_data: "slide:noop" });
  if (index < total - 1) nav.push({ text: "▶️", callback_data: "slide:next" });
  rows.push(nav);
  return { inline_keyboard: rows };
}
async function expire(api: Api, id: string): Promise<void> {
  const session = sessions.get(id); if (!session) return; sessions.delete(id);
  try { await api.raw.editMessageReplyMarkup({ inline_message_id: id, reply_markup: expiredKeyboardForSession(session) }); } catch { /* inline message gone */ }
}
function resetTimer(api: Api, id: string, session: SlideshowSession): void { clearTimeout(session.timer); session.timer = setTimeout(() => expire(api, id), TTL_MS); }
function compress(source: string): string {
  const clean = source.split("?")[0]!.replace(/^https?:\/\//, "");
  return clean.includes("tiktok.com") ? clean.replace(/@[\w.]+(?=\/(?:video|photo)\/)/, "@user") : clean;
}
function expiredKeyboardForSession(session: SlideshowSession): InlineKeyboardMarkup {
  const rows: InlineKeyboardMarkup["inline_keyboard"] = [];
  const stats = statsRow(session.likes, session.views); if (stats.length) rows.push(stats);
  const callbackData = `sr:${session.userId}:${session.currentIndex}:${compress(session.sourceLink)}`;
  const row = [{ text: `📸 ${session.currentIndex + 1}/${session.media.length}`, callback_data: "slide:noop" }];
  if (callbackData.length <= 64) row.push({ text: "🔄", callback_data: callbackData });
  rows.push(row);
  return { inline_keyboard: rows };
}
