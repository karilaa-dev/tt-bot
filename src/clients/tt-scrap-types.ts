import type { Message } from "grammy/types";
import type { components } from "./tt-scrap.generated.ts";

type ApiSchemas = components["schemas"];
export type AssetDescriptor = ApiSchemas["AssetDescriptor"];
export type TikTokMusicMetadata = ApiSchemas["TikTokMusicMetadata"];
export type TikTokExtraction = ApiSchemas["TikTokExtractionResponse"];
export type TikTokMusicExtraction = ApiSchemas["TikTokMusicResponse"];
export type InstagramMediaItem = ApiSchemas["InstagramMediaItem"];
export type InstagramExtraction = ApiSchemas["InstagramExtractionResponse"];

export interface TelegramParameters {
  chat_id: number | string;
  caption?: string;
  parse_mode?: "HTML" | "MarkdownV2";
  disable_notification?: boolean;
  reply_parameters?: { message_id: number; chat_id?: number | string; allow_sending_without_reply?: boolean };
  reply_markup?: unknown;
  message_thread_id?: number;
  supports_streaming?: boolean;
  disable_content_type_detection?: boolean;
  [key: string]: unknown;
}

export interface TikTokDeliveryRequest {
  source: { url: string } | { extraction_id: string } | { video_id: bigint };
  delivery: "media" | "document" | "audio";
  refresh?: boolean;
  telegram: TelegramParameters;
}

export interface InstagramDeliveryRequest {
  source: { url: string } | { extraction_id: string };
  delivery: "media" | "document";
  refresh?: boolean;
  telegram: TelegramParameters;
}

export interface TelegramDeliveryCall<T extends Message | Message[] = Message | Message[]> {
  method: string;
  statusCode: number;
  result: T;
}

export interface TelegramDeliveryResult {
  calls: TelegramDeliveryCall[];
}
