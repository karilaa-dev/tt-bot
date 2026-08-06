import type { Api, InlineKeyboard } from "grammy";
import type { Message } from "grammy/types";
import type { AppConfig } from "../config.ts";
import type { TtScrapClient } from "../clients/tt-scrap.ts";
import type { InstagramExtraction, TelegramDeliveryResult, TikTokExtraction } from "../clients/tt-scrap-types.ts";
import { text, type Language } from "../locales.ts";
import { resultCaption, storageCaption } from "../ui/captions.ts";
import { musicKeyboard } from "../ui/keyboards.ts";

export interface DeliveryIdentity { userId?: number; username?: string; fullName?: string }

export class DeliveryService {
  constructor(private readonly scrap: TtScrapClient, private readonly api: Api, private readonly config: AppConfig) {}

  deliverTikTokToChat(extraction: TikTokExtraction, sourceUrl: string, chatId: number, replyTo: number, lang: Language, fileMode: boolean, disableNotification = false): Promise<TelegramDeliveryResult> {
    return this.scrap.deliverTikTok({
      source: { extraction_id: extraction.extraction_id },
      delivery: fileMode ? "document" : "media",
      telegram: {
        chat_id: chatId,
        ...(extraction.content_type === "video" ? { caption: resultCaption(lang, sourceUrl), parse_mode: "HTML" as const } : {}),
        reply_parameters: { message_id: replyTo },
        disable_notification: extraction.content_type === "slideshow" || disableNotification,
        reply_markup: extraction.content_type === "video" ? musicKeyboard(extraction.source_id, lang, extraction.likes, extraction.views) : undefined,
        ...technicalParameters(extraction.content_type, fileMode),
      },
    });
  }

  async stageTikTok(extraction: TikTokExtraction, sourceUrl: string, identity: DeliveryIdentity, fileMode = false): Promise<TelegramDeliveryResult> {
    const chatId = this.requireStorage();
    return this.scrap.deliverTikTok({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: chatId,
      ...(extraction.content_type === "video" ? { caption: storageCaption(sourceUrl, identity.userId, identity.username, identity.fullName), parse_mode: "HTML" as const } : {}),
      disable_notification: true,
      ...technicalParameters(extraction.content_type, fileMode),
    } });
  }

  deliverAudio(videoId: bigint, chatId: number, replyTo: number, lang: Language, group: boolean): Promise<TelegramDeliveryResult> {
    return this.scrap.deliverTikTok({ source: { video_id: videoId }, delivery: "audio", telegram: {
      chat_id: chatId, caption: `<b>${text(lang, "bot_tag")}</b>`, parse_mode: "HTML", reply_parameters: { message_id: replyTo }, disable_notification: group,
    } });
  }

  deliverInstagram(extraction: InstagramExtraction, sourceUrl: string, chatId: number, replyTo: number, lang: Language, fileMode: boolean): Promise<TelegramDeliveryResult> {
    return this.scrap.deliverInstagram({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: chatId,
      ...(extraction.content_type === "video" ? { caption: resultCaption(lang, sourceUrl), parse_mode: "HTML" as const } : {}),
      reply_parameters: { message_id: replyTo },
      disable_notification: extraction.content_type !== "video",
      ...technicalParameters(extraction.content_type, fileMode),
    } });
  }

  stageInstagram(extraction: InstagramExtraction, sourceUrl: string, identity: DeliveryIdentity, fileMode = false): Promise<TelegramDeliveryResult> {
    return this.scrap.deliverInstagram({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: this.requireStorage(),
      ...(extraction.content_type === "video" ? { caption: storageCaption(sourceUrl, identity.userId, identity.username, identity.fullName), parse_mode: "HTML" as const } : {}),
      disable_notification: true, ...technicalParameters(extraction.content_type, fileMode),
    } });
  }

  private requireStorage(): number {
    if (this.config.storageChannelId === null) throw new Error("STORAGE_CHANNEL_ID is required for inline and staged delivery");
    return this.config.storageChannelId;
  }
}

function technicalParameters(contentType: TikTokExtraction["content_type"] | InstagramExtraction["content_type"], fileMode: boolean): { supports_streaming?: true; disable_content_type_detection?: true } {
  if (contentType !== "video") return {};
  return fileMode ? { disable_content_type_detection: true } : { supports_streaming: true };
}

export function allMessages(result: TelegramDeliveryResult): Message[] {
  return result.calls.flatMap((call) => Array.isArray(call.result) ? call.result : [call.result]);
}
export function lastBatch(result: TelegramDeliveryResult): Message[] {
  const call = result.calls.at(-1);
  return call ? (Array.isArray(call.result) ? call.result : [call.result]) : [];
}
export function fileIdFromMessage(message: Message): string | null {
  if (message.video) return message.video.file_id;
  if (message.document) return message.document.file_id;
  if (message.audio) return message.audio.file_id;
  if (message.photo?.length) return message.photo.at(-1)?.file_id ?? null;
  return null;
}
