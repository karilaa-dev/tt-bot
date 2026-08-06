import type { BotContext } from "../bot/context.ts";
import { createUser, getUser } from "../db/users.ts";
import { languageFromTelegram, type Language, text } from "../locales.ts";
import { escapeHtml } from "../ui/captions.ts";
import { logger } from "../logging.ts";

export async function resolveLanguage(ctx: BotContext, noDatabase = false): Promise<Language> {
  const chatId = ctx.chat?.id;
  if (!noDatabase && chatId !== undefined) {
    try {
      const user = await getUser(ctx.db, chatId);
      if (user) return user.lang;
    } catch { /* locale fallback intentionally survives DB lookup errors */ }
  }
  return languageFromTelegram(ctx.from?.language_code);
}

export async function registerAndWelcome(ctx: BotContext, lang: Language, referral: string | null = null): Promise<void> {
  if (!ctx.chat) return;
  await createUser(ctx.db, ctx.chat.id, lang, referral);
  const fullName = (ctx.from ? [ctx.from.first_name, ctx.from.last_name].filter(Boolean).join(" ") : ("title" in ctx.chat ? ctx.chat.title : "Chat")) || "Chat";
  const username = ctx.from?.username ? `@${ctx.from.username}\n` : "";
  if (ctx.config.joinLogs !== null) {
    const logText = `<b><a href="tg://user?id=${ctx.chat.id}">${escapeHtml(fullName)}</a></b>\n${username}<code>${ctx.chat.id}</code>\n<i>${escapeHtml(referral || "")}</i>`;
    try { await ctx.api.sendMessage(ctx.config.joinLogs, logText, { parse_mode: "HTML" }); }
    catch (error) { logger.warn("Failed to send join log", error); }
  }
  logger.info(`New User: ${fullName} ${ctx.chat.id} ${referral || ""}`);
  await ctx.reply(text(lang, "start") + (ctx.chat.type === "private" ? text(lang, "group_info") : ""), { parse_mode: "HTML", link_preview_options: { is_disabled: true } });
  await ctx.reply(text(lang, "lang_start"), { parse_mode: "HTML" });
}
