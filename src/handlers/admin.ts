import { GrammyError, InputFile, type Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { getUserIds } from "../db/users.ts";
import { logger } from "../logging.ts";

export function registerAdminHandlers(bot: Bot<BotContext>): void {
  bot.command(["msg", "tell", "say", "send"], async (ctx, next) => {
    if (!ctx.from || !ctx.message) return next();
    if (ctx.chat.type !== "private" || !ctx.config.secondAdminIds.has(ctx.from.id)) return next();
    const parts = ctx.message.text.split(" ");
    const target = parts[1];
    const message = parts.slice(2).join(" ");
    if (!target || !message) return void await ctx.reply("ops");
    try { await ctx.api.sendMessage(target, message); await ctx.reply("Message sent"); }
    catch (error) {
      logger.error("Failed to send admin message", error);
      if (error instanceof GrammyError) {
        const description = error.description.toLowerCase();
        if (description.includes("blocked") || description.includes("forbidden")) await ctx.reply("User has blocked the bot");
        else await ctx.reply(`Bad request: ${error.description}`);
      } else await ctx.reply("ops");
    }
  });

  bot.command("export", async (ctx, next) => {
    if (!ctx.from) return next();
    if (ctx.chat.type !== "private" || !ctx.config.secondAdminIds.has(ctx.from.id)) return next();
    const users = await getUserIds(ctx.db, true);
    await ctx.replyWithDocument(new InputFile(Buffer.from(users.join("\n")), "users.txt"), { caption: "User list" });
  });
}
