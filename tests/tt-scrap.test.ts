import { afterEach, describe, expect, test } from "bun:test";
import { GrammyError } from "grammy";
import type { Message } from "grammy/types";
import { PartialDeliveryError, TtScrapError } from "../src/bot/errors.ts";
import { TtScrapClient } from "../src/clients/tt-scrap.ts";
import { testConfig } from "./helpers.ts";

let server: ReturnType<typeof Bun.serve> | undefined;
afterEach(() => { server?.stop(true); server = undefined; });

function start(handler: (request: Request) => Response | Promise<Response>): TtScrapClient {
  server = Bun.serve({ port: 0, fetch: handler });
  return new TtScrapClient(testConfig(`http://127.0.0.1:${server.port}`));
}
const message: Message = { message_id: 42, date: 1, chat: { id: 7, type: "private", first_name: "Test" }, video: { file_id: "video-file", file_unique_id: "u", width: 1, height: 1, duration: 1 } };

describe("TtScrapClient", () => {
  test("hydrates a raw Telegram result without wrapping or copying it", async () => {
    const client = start(async (request) => {
      expect(request.headers.get("authorization")).toBe("Bearer test-api-key-that-is-long-enough");
      return Response.json({ ok: true, result: message });
    });
    const result = await client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/video/1" }, delivery: "media", telegram: { chat_id: 7 } });
    expect(result.calls[0]?.result).toEqual(message);
  });

  test("retains ordered album batches from a multi response", async () => {
    const client = start(() => Response.json({ ok: true, partial: false, deliveries: [
      { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [{ ...message, message_id: 1 }] } },
      { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [{ ...message, message_id: 2 }] } },
    ] }));
    const result = await client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/photo/1" }, delivery: "media", telegram: { chat_id: 7 } });
    expect(result.calls).toHaveLength(2); expect((result.calls[1]?.result as Array<typeof message>)[0]?.message_id).toBe(2);
  });

  test("turns Telegram failures into GrammyError", async () => {
    const client = start(() => Response.json({ ok: false, error_code: 429, description: "retry later" }, { status: 429 }));
    await expect(client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/video/1" }, delivery: "media", telegram: { chat_id: 7 } })).rejects.toBeInstanceOf(GrammyError);
  });

  test("does not hide partial delivery", async () => {
    const client = start(() => Response.json({ ok: false, partial: true, deliveries: [
      { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [message] } },
      { method: "sendMediaGroup", status_code: 429, response: { ok: false, error_code: 429, description: "retry" } },
    ] }, { status: 207 }));
    await expect(client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/photo/1" }, delivery: "media", telegram: { chat_id: 7 } })).rejects.toBeInstanceOf(PartialDeliveryError);
  });

  test("preserves stable API errors and request IDs", async () => {
    const client = start(() => Response.json({ error: { code: "content_private", message: "private", request_id: "request-1" } }, { status: 403 }));
    try { await client.extractTikTok("https://www.tiktok.com/@a/video/1"); throw new Error("expected failure"); }
    catch (error) { expect(error).toBeInstanceOf(TtScrapError); expect((error as TtScrapError).requestId).toBe("request-1"); }
  });

  test("uses the future Instagram delivery endpoint", async () => {
    let path = "";
    const client = start((request) => { path = new URL(request.url).pathname; return Response.json({ ok: true, result: message }); });
    await client.deliverInstagram({ source: { extraction_id: "ig-1" }, delivery: "media", telegram: { chat_id: 7 } });
    expect(path).toBe("/v1/instagram/telegram-deliveries");
  });

  test("sends 19-digit IDs as exact decimal strings", async () => {
    let payload: unknown;
    const client = start(async (request) => { payload = await request.json(); return Response.json({ ok: true, result: message }); });
    await client.deliverTikTok({ source: { video_id: 7669880788879543583n }, delivery: "audio", telegram: { chat_id: 7 } });
    expect(payload).toMatchObject({ source: { video_id: "7669880788879543583" } });
  });

  test("treats a transport failure during delivery as ambiguous and never retries it", async () => {
    let requests = 0;
    server = Bun.serve({ port: 0, fetch: () => { requests++; return new Promise<Response>(() => {}); } });
    const config = testConfig(`http://127.0.0.1:${server.port}`);
    config.ttScrapDeliveryTimeoutMs = 25;
    const client = new TtScrapClient(config);
    try {
      await client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/video/1" }, delivery: "media", telegram: { chat_id: 7 } });
      throw new Error("expected failure");
    } catch (error) {
      expect(error).toBeInstanceOf(TtScrapError);
      expect((error as TtScrapError).code).toBe("telegram_delivery_ambiguous");
      expect(requests).toBe(1);
    }
  });
});
