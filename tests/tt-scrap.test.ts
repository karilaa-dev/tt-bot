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
  test("resolves TikTok links before extraction with the stable source ID", async () => {
    let path = "";
    const client = start((request) => {
      path = new URL(request.url).pathname;
      return Response.json({ platform: "tiktok", source_id: "7669880788879543583", source_url: "https://vm.tiktok.com/token", resolved_url: "https://www.tiktok.com/@creator/video/7669880788879543583" });
    });
    const resolved = await client.resolveTikTok("https://vm.tiktok.com/token");
    expect(path).toBe("/v1/tiktok/resolutions");
    expect(resolved.source_id).toBe("7669880788879543583");
  });

  test("retries retryable TikTok resolution failures with the configured callback", async () => {
    let requests = 0;
    const retries: Array<[number, number]> = [];
    const client = start(() => {
      requests++;
      if (requests === 1) return Response.json({ error: { code: "upstream_timeout", message: "timed out", request_id: "request-1" } }, { status: 504 });
      return Response.json({ platform: "tiktok", source_id: "7669880788879543583", source_url: "https://vm.tiktok.com/token", resolved_url: "https://www.tiktok.com/@creator/video/7669880788879543583" });
    });
    const resolved = await client.resolveTikTok("https://vm.tiktok.com/token", {
      attempts: 2,
      onRetry: async (attempt, maxRetries) => { retries.push([attempt, maxRetries]); },
    });
    expect(resolved.source_id).toBe("7669880788879543583");
    expect(requests).toBe(2);
    expect(retries).toEqual([[1, 1]]);
  });

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

  test("preserves partial delivery details on an HTTP error status", async () => {
    const client = start(() => Response.json({ ok: false, partial: true, deliveries: [
      { method: "sendMediaGroup", status_code: 200, response: { ok: true, result: [message] } },
      { method: "sendMediaGroup", status_code: 500, response: { ok: false, error_code: 500, description: "failed" } },
    ] }, { status: 500 }));
    await expect(client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/photo/1" }, delivery: "media", telegram: { chat_id: 7 } }))
      .rejects.toMatchObject({ name: "PartialDeliveryError", successfulCalls: 1 });
  });

  test("preserves stable API errors and request IDs", async () => {
    const client = start(() => Response.json({ error: { code: "content_private", message: "private", request_id: "request-1" } }, { status: 403 }));
    try { await client.extractTikTok("https://www.tiktok.com/@a/video/1"); throw new Error("expected failure"); }
    catch (error) { expect(error).toBeInstanceOf(TtScrapError); expect((error as TtScrapError).requestId).toBe("request-1"); }
  });

  test("rejects a successful Telegram envelope carried by HTTP 500", async () => {
    const client = start(() => Response.json({ ok: true, result: message }, { status: 500 }));
    await expect(client.deliverTikTok({ source: { url: "https://www.tiktok.com/@a/video/1" }, delivery: "media", telegram: { chat_id: 7 } }))
      .rejects.toMatchObject({ code: "http_error", status: 500 });
  });

  test("rejects malformed successful extraction responses", async () => {
    const client = start(() => Response.json({ platform: "tiktok", extraction_id: "missing-fields" }));
    await expect(client.extractTikTok("https://www.tiktok.com/@a/video/1"))
      .rejects.toMatchObject({ code: "invalid_response" });
  });

  test("uses the Instagram delivery endpoint and retains its Telegram method", async () => {
    let path = "";
    const client = start((request) => { path = new URL(request.url).pathname; return Response.json({ ok: true, result: message }); });
    const result = await client.deliverInstagram({ source: { extraction_id: "ig-1" }, delivery: "media", telegram: { chat_id: 7 } }, "sendVideo");
    expect(path).toBe("/v1/instagram/telegram-deliveries");
    expect(result.calls[0]?.method).toBe("sendVideo");
  });

  test("sends 19-digit IDs as exact JSON integer tokens", async () => {
    let payload = "";
    const client = start(async (request) => { payload = await request.text(); return Response.json({ ok: true, result: message }); });
    await client.deliverTikTok({ source: { video_id: 7669880788879543583n }, delivery: "audio", telegram: { chat_id: 7 } });
    expect(payload).toContain('"video_id":7669880788879543583');
    expect(payload).not.toContain('"video_id":"7669880788879543583"');
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
