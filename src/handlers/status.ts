import type { BotContext } from "../bot/context.ts";
import type { Message } from "grammy/types";

export async function setReaction(ctx: BotContext, message: Message, emoji: string | null): Promise<void> {
  try {
    await ctx.api.raw.setMessageReaction({
      chat_id: message.chat.id,
      message_id: message.message_id,
      reaction: emoji ? [{ type: "emoji", emoji: emoji as "👀" }] : [],
      is_big: false,
    });
  } catch { /* reactions are unavailable in some chats */ }
}

export async function beginStatus(ctx: BotContext, message: Message): Promise<Message | null> {
  try {
    await ctx.api.raw.setMessageReaction({ chat_id: message.chat.id, message_id: message.message_id, reaction: [{ type: "emoji", emoji: "👀" }], is_big: false });
    return null;
  } catch {
    return ctx.api.sendMessage(message.chat.id, "⏳", { reply_parameters: { message_id: message.message_id }, disable_notification: true });
  }
}

export async function clearStatus(ctx: BotContext, original: Message, status: Message | null): Promise<void> {
  if (status) { try { await ctx.api.deleteMessage(status.chat.id, status.message_id); } catch { /* best effort */ } }
  else await setReaction(ctx, original, null);
}
