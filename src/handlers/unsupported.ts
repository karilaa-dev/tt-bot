import type { Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { text } from "../locales.ts";
import { resolveLanguage } from "../services/registration.ts";

export function registerUnsupportedHandlers(bot: Bot<BotContext>): void {
  bot.on(["message:video", "message:video_note"], async (ctx) => {
    if (ctx.chat.type !== "private") return;
    const lang = await resolveLanguage(ctx);
    await ctx.reply(text(lang, "video_upload_hint"), { parse_mode: "HTML", reply_parameters: { message_id: ctx.message.message_id } });
  });
  bot.on(["message:photo", "message:voice", "message:audio"], async (ctx) => {
    if (ctx.chat.type !== "private") return;
    const lang = await resolveLanguage(ctx);
    await ctx.reply(text(lang, "tiktok_links_only"), { parse_mode: "HTML", reply_parameters: { message_id: ctx.message.message_id } });
  });
  bot.on("message", async (ctx) => {
    if (ctx.chat.type !== "private") return;
    const lang = await resolveLanguage(ctx);
    await ctx.reply(text(lang, "tiktok_links_only"), { parse_mode: "HTML", reply_parameters: { message_id: ctx.message.message_id } });
  });
}
