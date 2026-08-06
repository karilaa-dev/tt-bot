import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { toggleUserMode } from "../db/users.ts";
import { resolveLanguage, registerChat } from "../services/registration.ts";
import { text } from "../locales.ts";

export function registerUserHandlers(bot: Bot<BotContext>): void {
  bot.command("start", async (ctx, next) => {
    if (ctx.chat.type !== "private") return next();
    if (ctx.onboardingSent) return;
    const lang = await resolveLanguage(ctx);
    await ctx.reply(text(lang, "start") + text(lang, "group_info"), { parse_mode: "HTML", link_preview_options: { is_disabled: true } });
    await ctx.reply(text(lang, "lang_start"), { parse_mode: "HTML" });
  });

  bot.command("mode", async (ctx) => {
    if (!ctx.from) return;
    const lang = await resolveLanguage(ctx);
    if (ctx.chat.type !== "private") {
      const member = await ctx.api.getChatMember(ctx.chat.id, ctx.from.id);
      if (member.status !== "creator" && member.status !== "administrator") {
        await ctx.reply(text(lang, "not_admin"), { parse_mode: "HTML" });
        return;
      }
    }
    if (!await ctx.getUserRecord()) await registerChat(ctx, lang);
    const user = await toggleUserMode(ctx.db, ctx.chat.id);
    ctx.cacheUserRecord(user);
    await ctx.reply(text(lang, user.fileMode ? "file_mode_on" : "file_mode_off"), { parse_mode: "HTML" });
  });
}
