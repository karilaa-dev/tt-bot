import { Keyboard, type Bot } from "grammy";
import type { BotContext } from "../bot/context.ts";
import { getUserIds } from "../db/users.ts";
import { logger } from "../logging.ts";

interface StoredMessage { chatId: number; messageId: number }
let advertMessage: StoredMessage | null = null;
const awaitingMessage = new Set<number>();
const adminKeyboard = new Keyboard().text("👁‍🗨Check message").text("✏Edit message").row().text("📢Send message").row().text("🔽Hide keyboard").resized();
const backKeyboard = new Keyboard().text("↩Return").resized();

export function registerAdvertHandlers(bot: Bot<BotContext>): void {
  bot.command(["stop", "cancel", "back"], cancel);
  bot.hears("↩Return", cancel);

  bot.command("hide", hide);
  bot.hears("🔽Hide keyboard", hide);

  bot.command("admin", async (ctx, next) => {
    if (!ctx.from) return next();
    if (ctx.chat.type !== "private" || !ctx.config.adminIds.has(ctx.from.id)) return next();
    await ctx.reply("🤖You opened admin menu", { reply_markup: adminKeyboard });
  });

  bot.hears("👁‍🗨Check message", async (ctx, next) => {
    if (!ctx.from) return next();
    if (!ctx.config.adminIds.has(ctx.from.id)) return next();
    if (!advertMessage) return void await ctx.reply("⚠️You have not created a message yet");
    await ctx.api.copyMessage(ctx.from.id, advertMessage.chatId, advertMessage.messageId);
  });

  bot.hears("✏Edit message", async (ctx, next) => {
    if (!ctx.from) return next();
    if (!ctx.config.adminIds.has(ctx.from.id)) return next();
    awaitingMessage.add(ctx.from.id);
    await ctx.reply("📝Write new message", { reply_markup: backKeyboard });
  });

  bot.hears("📢Send message", async (ctx, next) => {
    if (!ctx.from) return next();
    if (!ctx.config.adminIds.has(ctx.from.id)) return next();
    if (!advertMessage) return void await ctx.reply("⚠️You have not created a message yet");
    const status = await ctx.reply("<code>Announcement started</code>", { parse_mode: "HTML" });
    let delivered = 0, blocked = 0, errors = 0;
    for (const userId of await getUserIds(ctx.db, true)) {
      try { await ctx.api.copyMessage(userId, advertMessage.chatId, advertMessage.messageId); delivered++; }
      catch (error) {
        const description = error instanceof Error ? error.message.toLowerCase() : "";
        if (description.includes("blocked") || description.includes("forbidden")) blocked++; else errors++;
        logger.debug(`Broadcast failed for ${userId}`, error);
      }
      await Bun.sleep(40);
    }
    try { await ctx.api.deleteMessage(ctx.chat.id, status.message_id); } catch { /* best effort */ }
    await ctx.reply(`✅Message received by <b>${delivered}</b> users\n🚫Blocked: <b>${blocked}</b>\n❌Errors: <b>${errors}</b>`, { parse_mode: "HTML" });
  });

  bot.on("message", async (ctx, next) => {
    if (!ctx.from) return next();
    if (!awaitingMessage.has(ctx.from.id)) return next();
    advertMessage = { chatId: ctx.chat.id, messageId: ctx.message.message_id };
    awaitingMessage.delete(ctx.from.id);
    await ctx.reply("✅Message added", { reply_markup: adminKeyboard });
  });
}

async function cancel(ctx: BotContext): Promise<void> {
  awaitingMessage.delete(ctx.from?.id ?? 0);
  await ctx.reply("↩You have returned", { reply_markup: adminKeyboard });
}
async function hide(ctx: BotContext): Promise<void> {
  await ctx.reply("🔽You successfully hide the keyboard", { reply_markup: { remove_keyboard: true } });
}
