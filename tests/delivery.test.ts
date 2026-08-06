import { afterEach, describe, expect, test } from "bun:test";
import type { Api } from "grammy";
import type { Message } from "grammy/types";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import type { TikTokExtraction } from "../src/clients/tt-scrap-types.ts";
import { DeliveryService } from "../src/services/delivery.ts";
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

describe("DeliveryService", () => {
  test("uses an extraction reference for ordered slideshow delivery", async () => {
    let payload: Record<string, unknown> = {};
    server = Bun.serve({ port: 0, async fetch(request) { payload = await request.json() as Record<string, unknown>; return Response.json({ ok: true, result: [message] }); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    const service = new DeliveryService(new TtScrapClient(config), {} as Api, config);
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
    const service = new DeliveryService(new TtScrapClient(config), {} as Api, config);
    await service.stageTikTok(extraction, extraction.source_url, { userId: 7, fullName: "Test" }, true);
    expect(payload).toMatchObject({ source: { extraction_id: "extraction-1" }, delivery: "document", telegram: { chat_id: -100123, disable_notification: true } });
    expect(payload.telegram).not.toHaveProperty("disable_content_type_detection");
    expect(payload.telegram).not.toHaveProperty("supports_streaming");
  });
});
