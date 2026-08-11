import { afterEach, describe, expect, test } from "bun:test";
import type { Api } from "grammy";
import type { Message } from "grammy/types";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { InstagramExtraction, TikTokExtraction } from "../src/clients/tt-scrap-types.ts";
import { DeliveryService, inlineMediaFromMessage, inlineMediaPayload, telegramFilesFromResult } from "../src/services/delivery.ts";
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
const documentMessage: Message = { message_id: 44, date: 1, chat: { id: 7, type: "private", first_name: "Test" }, document: { file_id: "d", file_unique_id: "du" } };

function instagramExtraction(contentType: InstagramExtraction["content_type"], mediaTypes: Array<"image" | "video">): InstagramExtraction {
  return {
    extraction_id: "instagram-1", platform: "instagram", source_id: "ABC123", source_url: "https://www.instagram.com/p/ABC123",
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

  test("attaches caption and controls for tt-scrap's one-image sendPhoto contract", async () => {
    let payload: Record<string, any> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, any>; return Response.json({ ok: true, result: message }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    const singleImage = { ...extraction, media: [{
      asset_id: "image-1", kind: "image" as const, position: 0, download_url: "/v1/assets/image-1",
      filename: "image.jpg", expires_at: new Date(Date.now() + 60_000).toISOString(),
    }] };
    await service.deliverTikTokToChat(singleImage, singleImage.source_url, 7, 9, "en", false);
    expect(payload).toMatchObject({
      source: { extraction_id: "extraction-1" }, delivery: "media",
      telegram: { chat_id: 7, parse_mode: "HTML", reply_parameters: { message_id: 9 }, reply_markup: { inline_keyboard: expect.any(Array) } },
    });
    expect(payload.telegram.caption).toContain(singleImage.source_url);
  });

  test("stages document mode in the configured storage channel", async () => {
    let payload: Record<string, unknown> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, unknown>; return Response.json({ ok: true, result: message }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    await service.stageTikTok(extraction, extraction.source_url, { userId: 7, fullName: "Test" }, { editMessageCaption: async () => true } as Pick<Api, "editMessageCaption">, true);
    expect(payload).toMatchObject({ source: { extraction_id: "extraction-1" }, delivery: "document", telegram: { chat_id: -100123, disable_notification: true } });
    expect(payload.telegram).not.toHaveProperty("disable_content_type_detection");
    expect(payload.telegram).not.toHaveProperty("supports_streaming");
  });

  test("captions the first image in the final staged slideshow gallery", async () => {
    const finalFirst = { ...message, message_id: 52 };
    const finalSecond = { ...message, message_id: 53 };
    server = Bun.serve({ port: 0, async fetch() {
      return Response.json({
        ok: true,
        partial: false,
        deliveries: [
          { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [{ ...message, message_id: 50 }, { ...message, message_id: 51 }] } },
          { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [finalFirst, finalSecond] } },
        ],
      });
    } });
    const edits: Array<{ chatId: number | string; messageId: number; options: Record<string, unknown> }> = [];
    const api = {
      async editMessageCaption(chatId: number | string, messageId: number, options: Record<string, unknown>) {
        edits.push({ chatId, messageId, options });
        return true as const;
      },
    } as Pick<Api, "editMessageCaption">;
    const gallery = {
      ...extraction,
      media: Array.from({ length: 12 }, (_, position) => ({
        asset_id: `image-${position}`, kind: "image" as const, position,
        download_url: `/v1/assets/image-${position}`, filename: `${position}.jpg`,
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      })),
    };
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    await service.stageTikTok(gallery, gallery.source_url, { userId: 7, username: "tester", fullName: "Test User" }, api);
    expect(edits).toHaveLength(1);
    expect(edits[0]).toMatchObject({
      chatId: -100123,
      messageId: finalFirst.message_id,
      options: { parse_mode: "HTML" },
    });
    expect(String(edits[0]?.options.caption)).toContain(gallery.source_url);
    expect(String(edits[0]?.options.caption)).toContain("Test User");
  });

  test("keeps a successful staged slideshow when its caption edit fails", async () => {
    const secondMessage = { ...message, message_id: 43 };
    server = Bun.serve({ port: 0, async fetch() { return Response.json({ ok: true, result: [message, secondMessage] }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), config);
    const gallery = {
      ...extraction,
      media: Array.from({ length: 2 }, (_, position) => ({
        asset_id: `image-${position}`, kind: "image" as const, position,
        download_url: `/v1/assets/image-${position}`, filename: `${position}.jpg`,
        expires_at: new Date(Date.now() + 60_000).toISOString(),
      })),
    };
    const api = { editMessageCaption: async () => { throw new Error("caption edit rejected"); } } as unknown as Pick<Api, "editMessageCaption">;
    const result = await service.stageTikTok(gallery, gallery.source_url, { userId: 7, fullName: "Test" }, api);
    expect(result.calls[0]?.result).toEqual([message, secondMessage]);
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
    expect(payloads[0]?.telegram).toMatchObject({ parse_mode: "HTML" });
    expect(payloads[0]?.telegram.caption).toContain("https://www.instagram.com/p/ABC123");
    expect(payloads[1]?.telegram).not.toHaveProperty("caption");
    expect(payloads[1]?.telegram).not.toHaveProperty("parse_mode");
    for (const payload of payloads) {
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

  test("collects complete ordered reusable file IDs", () => {
    expect(telegramFilesFromResult({ calls: [{ method: "sendMediaGroup", statusCode: 200, result: [message, videoMessage] }] })).toEqual([
      { position: 0, media_type: "photo", file_id: "p", file_unique_id: "pu" },
      { position: 1, media_type: "video", file_id: "v", file_unique_id: "vu" },
    ]);
  });

  test("skips file-ID caching when a successful delivery has no reusable standard-media ID", () => {
    expect(telegramFilesFromResult({ calls: [{ method: "sendVideo", statusCode: 200, result: documentMessage }] })).toBeUndefined();
    expect(telegramFilesFromResult({ calls: [] })).toBeUndefined();
  });
});
