import { afterEach, describe, expect, test } from "bun:test";
import type { Message } from "grammy/types";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { InstagramExtraction, TikTokExtraction } from "../src/clients/tt-scrap-types.ts";
import { DeliveryService, inlineMediaFromMessage, inlineMediaPayload } from "../src/services/delivery.ts";
import { testConfig } from "./helpers.ts";

let server: ReturnType<typeof Bun.serve> | undefined;
afterEach(() => { server?.stop(true); server = undefined; });

const extraction: TikTokExtraction = {
  extraction_id: "extraction-1", platform: "tiktok", source_id: "7669880788879543583",
  source_url: "https://www.tiktok.com/@creator/photo/7669880788879543583",
  resolved_url: "https://www.tiktok.com/@creator/photo/7669880788879543583",
  content_type: "slideshow", media: [], expires_at: new Date(Date.now() + 60_000).toISOString(), likes: 1, views: 2,
};
const message: Message = { message_id: 42, date: 1, chat: { id: 7, type: "private", first_name: "Test" }, photo: [{ file_id: "p", file_unique_id: "pu", width: 1, height: 1, file_size: 1 }] };
const videoMessage: Message = { message_id: 43, date: 1, chat: { id: 7, type: "private", first_name: "Test" }, video: { file_id: "v", file_unique_id: "vu", width: 1, height: 1, duration: 1 } };

function instagramExtraction(contentType: InstagramExtraction["content_type"], mediaTypes: Array<"image" | "video">): InstagramExtraction {
  return {
    extraction_id: "instagram-1", platform: "instagram", source_url: "https://www.instagram.com/p/ABC123",
    content_type: contentType,
    media: mediaTypes.map((mediaType, position) => ({
      position, media_type: mediaType,
      asset: { asset_id: `asset-${position}`, kind: mediaType, position, download_url: `/v1/assets/${position}`, filename: `${position}.bin`, expires_at: new Date(Date.now() + 60_000).toISOString() },
    })),
    expires_at: new Date(Date.now() + 60_000).toISOString(),
  };
}

describe("DeliveryService", () => {
  test("uses an extraction reference for ordered slideshow delivery", async () => {
    let payload: Record<string, unknown> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, unknown>; return Response.json({ ok: true, result: [message] }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    const result = await service.deliverTikTokToChat(extraction, extraction.source_url, 7, 9, "en", false);
    expect(result.calls[0]?.result).toEqual([message]);
    expect(payload).toMatchObject({ source: { extraction_id: "extraction-1" }, delivery: "media", telegram: { chat_id: 7, disable_notification: true, reply_parameters: { message_id: 9 } } });
    expect(payload.telegram).not.toHaveProperty("caption");
    expect(payload.telegram).not.toHaveProperty("parse_mode");
  });

  test("stages document mode in the configured storage channel", async () => {
    let payload: Record<string, unknown> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, unknown>; return Response.json({ ok: true, result: message }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    await service.stageTikTok(extraction, extraction.source_url, { userId: 7, fullName: "Test" }, true);
    expect(payload).toMatchObject({ source: { extraction_id: "extraction-1" }, delivery: "document", telegram: { chat_id: -100123, disable_notification: true } });
    expect(payload.telegram).not.toHaveProperty("disable_content_type_detection");
    expect(payload.telegram).not.toHaveProperty("supports_streaming");
  });

  test("delivers a single Instagram video with the exact video request shape", async () => {
    let payload: Record<string, any> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, any>; return Response.json({ ok: true, result: videoMessage }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    const result = await service.deliverInstagram(instagramExtraction("video", ["video"]), "https://www.instagram.com/reel/ABC123", 7, 9, "en", false);
    expect(result.calls[0]?.method).toBe("sendVideo");
    expect(payload).toMatchObject({ source: { extraction_id: "instagram-1" }, delivery: "media", telegram: { chat_id: 7, parse_mode: "HTML", supports_streaming: true, reply_parameters: { message_id: 9 } } });
    expect(payload.telegram).not.toHaveProperty("disable_content_type_detection");
  });

  test("delivers Instagram images and mixed carousels without video-only parameters", async () => {
    const payloads: Array<Record<string, any>> = [];
    server = Bun.serve({ port: 0, async fetch(request) {
      payloads.push(await request.json() as Record<string, any>);
      return payloads.length === 1
        ? Response.json({ ok: true, result: message })
        : Response.json({ ok: true, result: [message, videoMessage] });
    } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    const image = await service.deliverInstagram(instagramExtraction("image", ["image"]), "https://www.instagram.com/p/ABC123", 7, 9, "en", false);
    const carousel = await service.deliverInstagram(instagramExtraction("carousel", ["image", "video"]), "https://www.instagram.com/p/ABC123", 7, 9, "en", false);
    expect(image.calls[0]?.method).toBe("sendPhoto");
    expect(carousel.calls[0]?.method).toBe("sendMediaGroup");
    for (const payload of payloads) {
      expect(payload.telegram).not.toHaveProperty("caption");
      expect(payload.telegram).not.toHaveProperty("parse_mode");
      expect(payload.telegram).not.toHaveProperty("supports_streaming");
      expect(payload.telegram).not.toHaveProperty("disable_content_type_detection");
    }
  });

  test("keeps photo and video identities for mixed inline carousels", () => {
    const photo = inlineMediaFromMessage(message);
    const video = inlineMediaFromMessage(videoMessage);
    expect(photo).toEqual({ type: "photo", fileId: "p" });
    expect(video).toEqual({ type: "video", fileId: "v" });
    expect(inlineMediaPayload(photo!, "en", "https://www.instagram.com/p/ABC123").type).toBe("photo");
    expect(inlineMediaPayload(video!, "en", "https://www.instagram.com/p/ABC123")).toMatchObject({ type: "video", supports_streaming: true });
  });
});
