import type { Api } from "grammy";
import type { InputMediaPhoto, InputMediaVideo, Message } from "grammy/types";
import { PartialDeliveryError } from "../bot/errors.ts";
import type { TelegramFileReference } from "../db/videos.ts";
import type { Language } from "../locales.ts";
import { resultCaption } from "../ui/captions.ts";
import { musicKeyboard } from "../ui/keyboards.ts";
import type { TelegramDeliveryCall, TelegramDeliveryResult } from "../clients/tt-scrap-types.ts";

interface CachedChatOptions {
  api: Api;
  files: TelegramFileReference[];
  chatId: number;
  replyTo: number;
  lang: Language;
  sourceLink: string;
  group: boolean;
}

export async function deliverCachedTikTokToChat(options: CachedChatOptions & {
  sourceId: string;
  contentType: string;
  likesDisplay: string | null;
  viewsDisplay: string | null;
}): Promise<TelegramDeliveryResult> {
  if (options.contentType === "video") {
    const file = options.files[0];
    if (!file || file.media_type !== "video") throw new Error("TikTok video cache has an invalid media shape");
    const result = await options.api.sendVideo(options.chatId, file.file_id, {
      caption: resultCaption(options.lang, options.sourceLink), parse_mode: "HTML", supports_streaming: true,
      reply_parameters: { message_id: options.replyTo },
      reply_markup: musicKeyboard(options.sourceId, options.lang, options.likesDisplay, options.viewsDisplay),
    });
    return singleCall("sendVideo", result);
  }
  const files = options.group ? options.files.slice(0, 10) : options.files;
  return sendAlbum(options.api, options.chatId, files, options.replyTo, true);
}

export async function deliverCachedInstagramToChat(options: CachedChatOptions & { contentType: string }): Promise<TelegramDeliveryResult> {
  if (options.contentType === "video") {
    const file = options.files[0];
    if (!file || file.media_type !== "video") throw new Error("Instagram video cache has an invalid media shape");
    const result = await options.api.sendVideo(options.chatId, file.file_id, {
      caption: resultCaption(options.lang, options.sourceLink), parse_mode: "HTML", supports_streaming: true,
      reply_parameters: { message_id: options.replyTo },
    });
    return singleCall("sendVideo", result);
  }
  if (options.contentType === "image") {
    const file = options.files[0];
    if (!file || file.media_type !== "photo") throw new Error("Instagram image cache has an invalid media shape");
    const result = await options.api.sendPhoto(options.chatId, file.file_id, { disable_notification: true, reply_parameters: { message_id: options.replyTo } });
    return singleCall("sendPhoto", result);
  }
  const files = options.group ? options.files.slice(0, 10) : options.files;
  return sendAlbum(options.api, options.chatId, files, options.replyTo, true);
}

async function sendAlbum(api: Api, chatId: number, files: TelegramFileReference[], replyTo: number, disableNotification: boolean): Promise<TelegramDeliveryResult> {
  if (files.length === 1) {
    const file = files[0]!;
    const result = file.media_type === "video"
      ? await api.sendVideo(chatId, file.file_id, { supports_streaming: true, disable_notification: disableNotification, reply_parameters: { message_id: replyTo } })
      : await api.sendPhoto(chatId, file.file_id, { disable_notification: disableNotification, reply_parameters: { message_id: replyTo } });
    return singleCall(file.media_type === "video" ? "sendVideo" : "sendPhoto", result);
  }
  const calls: TelegramDeliveryCall[] = [];
  for (const batch of albumBatches(files)) {
    try {
      const media = batch.map((file): InputMediaPhoto | InputMediaVideo => file.media_type === "video"
        ? { type: "video", media: file.file_id, supports_streaming: true }
        : { type: "photo", media: file.file_id });
      const result = await api.sendMediaGroup(chatId, media as [InputMediaPhoto | InputMediaVideo, InputMediaPhoto | InputMediaVideo, ...(InputMediaPhoto | InputMediaVideo)[]], {
        disable_notification: disableNotification,
        reply_parameters: { message_id: replyTo },
      });
      calls.push({ method: "sendMediaGroup", statusCode: 200, result });
    } catch (error) {
      if (calls.length) throw new PartialDeliveryError(calls.length, "telegram-file-cache");
      throw error;
    }
  }
  return { calls };
}

/** Split albums into Telegram's 2-10 range without leaving a final singleton. */
export function albumBatches<T>(items: T[]): T[][] {
  if (items.length < 2) return items.length ? [items] : [];
  const result: T[][] = [];
  let offset = 0;
  while (items.length - offset > 10) {
    const remaining = items.length - offset;
    const size = remaining === 11 ? 9 : 10;
    result.push(items.slice(offset, offset + size));
    offset += size;
  }
  result.push(items.slice(offset));
  return result;
}

function singleCall(method: string, result: Message): TelegramDeliveryResult {
  return { calls: [{ method, statusCode: 200, result }] };
}
