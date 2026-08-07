import { InputFile, type Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { getUserIds } from "../db/users.ts";

export function registerAdminHandlers(bot: Bot<BotContext>): void {
  bot.command("export", async (ctx, next) => {
    if (!ctx.from) return next();
    if (ctx.chat.type !== "private" || !ctx.config.adminIds.has(ctx.from.id)) return next();
    const users = await getUserIds(ctx.db);
    await ctx.replyWithDocument(new InputFile(Buffer.from(users.join("\n")), "users.txt"), { caption: "User list" });
  });
}
