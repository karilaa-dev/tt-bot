import type { Api, InlineKeyboard } from "grammy";
import type { InputMediaPhoto, InputMediaVideo, Message } from "grammy/types";
import type { AppConfig } from "../config.ts";
import type { TelegramFileReference } from "../db/videos.ts";
import type { TtScrapClient } from "../clients/tt-scrap.ts";
import type { InstagramExtraction, InstagramTelegramMethod, TelegramDeliveryResult, TikTokExtraction } from "../clients/tt-scrap-types.ts";
import { text, type Language } from "../locales.ts";
import { logger } from "../logging.ts";
import { resultCaption, storageCaption } from "../ui/captions.ts";
import { musicKeyboard } from "../ui/keyboards.ts";

export interface DeliveryIdentity { userId?: number; username?: string; fullName?: string }
export interface InlineMediaReference { type: "photo" | "video"; fileId: string }

export class DeliveryService {
  constructor(private readonly scrap: TtScrapClient, private readonly config: AppConfig) {}

  deliverTikTokToChat(extraction: TikTokExtraction, sourceUrl: string, chatId: number, replyTo: number, lang: Language, fileMode: boolean, disableNotification = false): Promise<TelegramDeliveryResult> {
    // Matching tt-scrap contract: its slideshow handler selects sendPhoto for
    // one standard image (sendDocument in document mode), so these top-level
    // caption/control fields are valid and are not passed to sendMediaGroup.
    const captionSingle = extraction.content_type === "video" || extraction.media.length === 1;
    return this.scrap.deliverTikTok({
      source: { extraction_id: extraction.extraction_id },
      delivery: fileMode ? "document" : "media",
      telegram: {
        chat_id: chatId,
        ...(captionSingle ? { caption: resultCaption(lang, sourceUrl), parse_mode: "HTML" as const } : {}),
        reply_parameters: { message_id: replyTo },
        disable_notification: extraction.content_type === "slideshow" || disableNotification,
        reply_markup: captionSingle ? { inline_keyboard: musicKeyboard(extraction.source_id, lang, extraction.likes, extraction.views).inline_keyboard } : undefined,
        ...technicalParameters(extraction.content_type, fileMode),
      },
    });
  }

  async stageTikTok(extraction: TikTokExtraction, sourceUrl: string, identity: DeliveryIdentity, api: Pick<Api, "editMessageCaption">, fileMode = false): Promise<TelegramDeliveryResult> {
    const chatId = this.requireStorage();
    const captionSingle = extraction.content_type === "video" || extraction.media.length === 1;
    const result = await this.scrap.deliverTikTok({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: chatId,
      ...(captionSingle ? { caption: storageCaption(sourceUrl, identity.userId, identity.username, identity.fullName), parse_mode: "HTML" as const } : {}),
      disable_notification: true,
      ...technicalParameters(extraction.content_type, fileMode),
    } });
    if (!captionSingle) {
      // Product contract: add one storage caption to the first item of the
      // final gallery batch, rather than repeating it on every batch.
      const firstMessage = lastBatch(result)[0];
      if (!firstMessage) throw new Error("Staged TikTok slideshow returned no final gallery message");
      try {
        await api.editMessageCaption(chatId, firstMessage.message_id, {
          caption: storageCaption(sourceUrl, identity.userId, identity.username, identity.fullName),
          parse_mode: "HTML",
        });
      } catch (error) {
        // The media is already staged. Preserve its reusable file IDs instead
        // of turning a cosmetic caption failure into a duplicate re-upload.
        logger.warn("Staged slideshow caption edit failed", error);
      }
    }
    return result;
  }

  deliverAudio(videoId: bigint, chatId: number, replyTo: number, lang: Language, group: boolean): Promise<TelegramDeliveryResult> {
    return this.scrap.deliverTikTok({ source: { video_id: videoId }, delivery: "audio", telegram: {
      chat_id: chatId, caption: `<b>${text(lang, "bot_tag")}</b>`, parse_mode: "HTML", reply_parameters: { message_id: replyTo }, disable_notification: group,
    } });
  }

  deliverInstagram(extraction: InstagramExtraction, sourceUrl: string, chatId: number, replyTo: number, lang: Language, fileMode: boolean): Promise<TelegramDeliveryResult> {
    const captionSingle = extraction.media.length === 1;
    return this.scrap.deliverInstagram({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: chatId,
      ...(captionSingle ? { caption: resultCaption(lang, sourceUrl), parse_mode: "HTML" as const } : {}),
      reply_parameters: { message_id: replyTo },
      disable_notification: extraction.content_type !== "video",
      ...technicalParameters(extraction.content_type, fileMode),
    } }, instagramMethod(extraction, fileMode));
  }

  stageInstagram(extraction: InstagramExtraction, sourceUrl: string, identity: DeliveryIdentity, fileMode = false): Promise<TelegramDeliveryResult> {
    const captionSingle = extraction.media.length === 1;
    return this.scrap.deliverInstagram({ source: { extraction_id: extraction.extraction_id }, delivery: fileMode ? "document" : "media", telegram: {
      chat_id: this.requireStorage(),
      ...(captionSingle ? { caption: storageCaption(sourceUrl, identity.userId, identity.username, identity.fullName), parse_mode: "HTML" as const } : {}),
      disable_notification: true, ...technicalParameters(extraction.content_type, fileMode),
    } }, instagramMethod(extraction, fileMode));
  }

  private requireStorage(): number {
    if (this.config.storageChannelId === null) throw new Error("STORAGE_CHANNEL_ID is required for inline and staged delivery");
    return this.config.storageChannelId;
  }
}

function instagramMethod(extraction: InstagramExtraction, fileMode: boolean): InstagramTelegramMethod {
  if (extraction.media.length > 1) return "sendMediaGroup";
  if (fileMode) return "sendDocument";
  return extraction.media[0]?.media_type === "video" ? "sendVideo" : "sendPhoto";
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
export function inlineMediaFromMessage(message: Message): InlineMediaReference | null {
  if (message.video) return { type: "video", fileId: message.video.file_id };
  const photo = message.photo?.at(-1);
  return photo ? { type: "photo", fileId: photo.file_id } : null;
}
export function telegramFileFromMessage(message: Message, position: number): TelegramFileReference | null {
  if (message.video) return { position, media_type: "video", file_id: message.video.file_id, file_unique_id: message.video.file_unique_id };
  const photo = message.photo?.at(-1);
  return photo ? { position, media_type: "photo", file_id: photo.file_id, file_unique_id: photo.file_unique_id } : null;
}
export function telegramFilesFromResult(result: TelegramDeliveryResult): TelegramFileReference[] | undefined {
  const files = allMessages(result).map(telegramFileFromMessage);
  if (files.length === 0 || files.some((file) => file === null)) return undefined;
  return files as TelegramFileReference[];
}
export function inlineMediaFromFiles(files: TelegramFileReference[]): InlineMediaReference[] {
  return files.map((file) => ({ type: file.media_type, fileId: file.file_id }));
}
export function inlineMediaPayload(media: InlineMediaReference, lang: Language, link: string): InputMediaPhoto | InputMediaVideo {
  const common = { media: media.fileId, caption: resultCaption(lang, link), parse_mode: "HTML" as const };
  return media.type === "video" ? { type: "video", supports_streaming: true, ...common } : { type: "photo", ...common };
}
