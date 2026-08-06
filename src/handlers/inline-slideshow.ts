import type { Api, Bot } from "grammy";
import type { InlineKeyboardMarkup } from "grammy/types";
import type { BotContext } from "../bot/context.ts";
import type { Language } from "../locales.ts";
import { logger } from "../logging.ts";
import { DeliveryService, allMessages, inlineMediaFromMessage, inlineMediaPayload, type InlineMediaReference } from "../services/delivery.ts";
import { resolveLanguage } from "../services/registration.ts";
import { statsRow } from "../ui/stats.ts";
import { findInstagramUrl } from "./links.ts";

interface SlideshowSession {
  media: InlineMediaReference[];
  currentIndex: number;
  lang: Language;
  sourceLink: string;
  userId: number;
  username?: string;
  fullName: string;
  likes?: number | null;
  views?: number | null;
  timer: ReturnType<typeof setTimeout>;
  loading: Set<number>;
}

const sessions = new Map<string, SlideshowSession>();
const refreshing = new Set<string>();
const TTL_MS = 600_000;

export function createInlineSlideshow(api: Api, inlineMessageId: string, media: InlineMediaReference[], lang: Language, sourceLink: string, identity: { userId: number; username?: string; fullName: string }, likes?: number | null, views?: number | null): InlineKeyboardMarkup {
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
    const index = action === "next" ? Math.min(session.currentIndex + 1, session.media.length - 1) : Math.max(session.currentIndex - 1, 0);
    if (index === session.currentIndex) return ctx.answerCallbackQuery();
    if (session.loading.has(index)) return ctx.answerCallbackQuery({ text: "Loading…" });
    session.loading.add(index);
    try {
      await ctx.answerCallbackQuery();
      await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(session.media[index]!, session.lang, session.sourceLink), reply_markup: navigationKeyboard(index, session.media.length, session.likes, session.views) });
      session.currentIndex = index;
      resetTimer(ctx.api, id, session);
    } catch (error) { logger.warn("Inline slideshow edit failed", error); }
    finally { session.loading.delete(index); }
  });

  bot.callbackQuery(/^sr:(\d+):(\d+):(.+)$/, async (ctx) => {
    const id = ctx.callbackQuery.inline_message_id;
    if (!id) return ctx.answerCallbackQuery();
    const ownerId = Number(ctx.match[1]);
    if (ctx.from.id !== ownerId) return ctx.answerCallbackQuery({ text: "Only the original requester can refresh this slideshow.", show_alert: true });
    if (refreshing.has(id)) return ctx.answerCallbackQuery({ text: "Refreshing…" });
    if (!ctx.queue.hasCapacity(ctx.from.id)) return ctx.answerCallbackQuery({ text: "Your download queue is full.", show_alert: true });
    refreshing.add(id);
    try {
      await ctx.answerCallbackQuery({ text: "Refreshing…" });
      const saved = Number(ctx.match[2]);
      const link = `https://${ctx.match[3]}`;
      const user = await ctx.getUserRecord(ctx.from.id);
      const lang = user?.lang ?? await resolveLanguage(ctx, true);
      const identity = { userId: ctx.from.id, fullName: [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" "), ...(ctx.from.username ? { username: ctx.from.username } : {}) };
      const service = new DeliveryService(ctx.scrap, ctx.config);
      const queued = await ctx.queue.withSlot(ctx.from.id, async () => {
        let media: InlineMediaReference[];
        let likes: number | null | undefined;
        let views: number | null | undefined;
        if (findInstagramUrl(link)) {
          const extraction = await ctx.scrap.extractInstagram(link, { attempts: 4 });
          media = inlineMedia(await service.stageInstagram(extraction, link, identity));
        } else {
          const extraction = await ctx.scrap.extractTikTok(link, { attempts: 4 });
          media = inlineMedia(await service.stageTikTok(extraction, link, identity));
          likes = extraction.likes; views = extraction.views;
        }
        createInlineSlideshow(ctx.api, id, media, lang, link, identity, likes, views);
        const session = sessions.get(id)!;
        session.currentIndex = Math.max(0, Math.min(saved, media.length - 1));
        await ctx.api.raw.editMessageMedia({ inline_message_id: id, media: inlineMediaPayload(media[session.currentIndex]!, lang, link), reply_markup: navigationKeyboard(session.currentIndex, media.length, likes, views) });
      });
      if (!queued.acquired) {
        if (queued.reason === "capacity") logger.warn(`Inline refresh queue filled for user ${ctx.from.id}`);
        return;
      }
    } catch (error) { logger.error("Inline slideshow refresh failed", error); }
    finally { refreshing.delete(id); }
  });
}

export function cleanupInlineSlideshows(): void {
  for (const session of sessions.values()) clearTimeout(session.timer);
  sessions.clear();
}

function inlineMedia(result: Awaited<ReturnType<DeliveryService["stageTikTok"]>>): InlineMediaReference[] {
  return allMessages(result).map(inlineMediaFromMessage).filter((value): value is InlineMediaReference => value !== null);
}
function navigationKeyboard(index: number, total: number, likes?: number | null, views?: number | null): InlineKeyboardMarkup {
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
