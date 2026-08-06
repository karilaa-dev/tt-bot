import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { updateUserMode } from "../db/users.ts";
import { resolveLanguage, registerAndWelcome } from "../services/registration.ts";
import { text } from "../locales.ts";

export function registerUserHandlers(bot: Bot<BotContext>): void {
  bot.command("start", async (ctx, next) => {
    if (ctx.chat.type !== "private") return next();
    const lang = await resolveLanguage(ctx);
    const user = await ctx.getUserRecord();
    if (!user) {
      const referral = typeof ctx.match === "string" && ctx.match.trim() ? ctx.match.trim().toLowerCase() : null;
      await registerAndWelcome(ctx, lang, referral);
      return;
    }
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
    const user = await ctx.getUserRecord();
    const oldMode = user?.fileMode ?? false;
    await updateUserMode(ctx.db, ctx.chat.id, !oldMode);
    if (user) ctx.cacheUserRecord({ ...user, fileMode: !oldMode });
    await ctx.reply(text(lang, oldMode ? "file_mode_off" : "file_mode_on"), { parse_mode: "HTML" });
  });
}
