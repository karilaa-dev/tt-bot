import type { Message } from "grammy/types";
import type { components } from "./tt-scrap.generated.ts";

type ApiSchemas = components["schemas"];
export type AssetDescriptor = ApiSchemas["AssetDescriptor"];
export type TikTokMusicMetadata = ApiSchemas["TikTokMusicMetadata"];
export type TikTokExtraction = ApiSchemas["TikTokExtractionResponse"];
export type TikTokMusicExtraction = ApiSchemas["TikTokMusicResponse"];
export type InstagramMediaItem = ApiSchemas["InstagramMediaItem"];
export type InstagramExtraction = ApiSchemas["InstagramExtractionResponse"];
export type TelegramParameters = ApiSchemas["TelegramParameters"];

type InstagramDeliverySchema = ApiSchemas["InstagramTelegramDeliveryRequest"];

export interface TikTokDeliveryRequest {
  source: { url: string } | { extraction_id: string } | { video_id: bigint };
  delivery: "media" | "document" | "audio";
  refresh?: boolean;
  telegram: TelegramParameters;
}

export interface InstagramDeliveryRequest extends Pick<InstagramDeliverySchema, "telegram"> {
  source: { url: string; extraction_id?: never } | { extraction_id: string; url?: never };
  delivery: InstagramDeliverySchema["delivery"];
  refresh?: boolean;
}

export type InstagramTelegramMethod = "sendPhoto" | "sendVideo" | "sendDocument" | "sendMediaGroup";

export interface TelegramDeliveryCall<T extends Message | Message[] = Message | Message[]> {
  method: string;
  statusCode: number;
  result: T;
}

export interface TelegramDeliveryResult {
  calls: TelegramDeliveryCall[];
}
