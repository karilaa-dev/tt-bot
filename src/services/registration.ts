import type { BotContext } from "../bot/context.ts";
import { registerUser, type UserRegistration } from "../db/users.ts";
import { languageFromTelegram, type Language, text } from "../locales.ts";
import { escapeHtml } from "../ui/captions.ts";
import { logger } from "../logging.ts";

export async function resolveLanguage(ctx: BotContext, noDatabase = false): Promise<Language> {
  const chatId = ctx.chat?.id;
  if (!noDatabase && chatId !== undefined) {
    try {
      const user = await ctx.getUserRecord(chatId);
      if (user) return user.lang;
    } catch { /* locale fallback intentionally survives DB lookup errors */ }
  }
  return languageFromTelegram(ctx.from?.language_code);
}

export async function registerChat(ctx: BotContext, lang: Language, referral: string | null = null): Promise<UserRegistration | null> {
  if (!ctx.chat) return null;
  const registration = await registerUser(ctx.db, ctx.chat.id, lang, referral);
  const { user, created } = registration;
  ctx.cacheUserRecord(user);
  if (!created) return registration;
  const fullName = (ctx.from ? [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" ") : ("title" in ctx.chat ? ctx.chat.title : "Chat")) || "Chat";
  const username = ctx.from?.username ? `@${ctx.from.username}\n` : "";
  if (ctx.config.joinLogs !== null) {
    const logText = `<b><a href="tg://user?id=${ctx.chat.id}">${escapeHtml(fullName)}</a></b>\n${username}<code>${ctx.chat.id}</code>\n<i>${escapeHtml(referral || "")}</i>`;
    try { await ctx.api.sendMessage(ctx.config.joinLogs, logText, { parse_mode: "HTML" }); }
    catch (error) { logger.warn("Failed to send join log", error); }
  }
  logger.info(`New User: ${fullName} ${ctx.chat.id} ${referral || ""}`);
  return registration;
}

export async function ensurePrivateRegistration(ctx: BotContext): Promise<void> {
  if (!ctx.message || ctx.chat?.type !== "private") return;
  try {
    if (await ctx.getUserRecord(ctx.chat.id)) return;
    const lang = languageFromTelegram(ctx.from?.language_code);
    const registration = await registerChat(ctx, lang, startReferral(ctx.message.text));
    if (registration?.created) {
      await sendWelcome(ctx, lang);
      ctx.onboardingSent = true;
    }
  } catch (error) {
    logger.error(`Failed to register private chat ${ctx.chat.id}; continuing without database preferences`, error);
  }
}

export async function resolveDownloadPreferences(ctx: BotContext): Promise<{ lang: Language; fileMode: boolean }> {
  const fallback = { lang: languageFromTelegram(ctx.from?.language_code), fileMode: false };
  try {
    const user = await ctx.getUserRecord();
    if (user) return { lang: user.lang, fileMode: user.fileMode };
    await registerAndWelcome(ctx, fallback.lang);
  } catch (error) {
    logger.error(`Failed to load download preferences for chat ${ctx.chat?.id ?? "unknown"}; using defaults`, error);
  }
  return fallback;
}

async function registerAndWelcome(ctx: BotContext, lang: Language, referral: string | null = null): Promise<void> {
  const registration = await registerChat(ctx, lang, referral);
  if (!registration?.created || !ctx.chat) return;
  await sendWelcome(ctx, lang);
}

async function sendWelcome(ctx: BotContext, lang: Language): Promise<void> {
  if (!ctx.chat) return;
  await ctx.reply(text(lang, "start") + (ctx.chat.type === "private" ? text(lang, "group_info") : ""), { parse_mode: "HTML", link_preview_options: { is_disabled: true } });
  await ctx.reply(text(lang, "lang_start"), { parse_mode: "HTML" });
}

function startReferral(messageText: string | undefined): string | null {
  if (!messageText) return null;
  const match = messageText.match(/^\/start(?:@[A-Za-z0-9_]+)?(?:\s+(.+))?$/i);
  return match?.[1]?.trim().toLowerCase() || null;
}
