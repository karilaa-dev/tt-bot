import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { updateUserLanguage } from "../db/users.ts";
import { isLanguage, text } from "../locales.ts";
import { resolveLanguage } from "../services/registration.ts";
import { languageKeyboard } from "../ui/keyboards.ts";

export function registerLanguageHandlers(bot: Bot<BotContext>): void {
  bot.command("lang", async (ctx) => {
    if (!ctx.from) return;
    if (ctx.chat.type !== "private") {
      const member = await ctx.api.getChatMember(ctx.chat.id, ctx.from.id);
      if (member.status !== "creator" && member.status !== "administrator") {
        const lang = await resolveLanguage(ctx);
        await ctx.reply(text(lang, "not_admin"), { parse_mode: "HTML" });
        return;
      }
    }
    await ctx.reply("Select language:", { reply_markup: languageKeyboard() });
  });

  bot.callbackQuery(/^lang\/(.+)$/, async (ctx) => {
    const value = ctx.match[1];
    if (!isLanguage(value) || !ctx.chat || !ctx.callbackQuery.message) return ctx.answerCallbackQuery();
    if (ctx.chat.type !== "private") {
      const member = await ctx.api.getChatMember(ctx.chat.id, ctx.from.id);
      if (member.status !== "creator" && member.status !== "administrator") {
        const lang = await resolveLanguage(ctx);
        return ctx.answerCallbackQuery({ text: text(lang, "not_admin") });
      }
    }
    await updateUserLanguage(ctx.db, ctx.chat.id, value);
    const user = await ctx.getUserRecord();
    if (user) ctx.cacheUserRecord({ ...user, lang: value });
    try { await ctx.editMessageText(text(value, "lang"), { parse_mode: "HTML" }); } catch { /* unchanged message */ }
    await ctx.answerCallbackQuery();
  });
}
