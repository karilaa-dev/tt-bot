import { afterEach, beforeEach, describe, expect, jest, test } from "bun:test";
import { createTelegramResponseLimiter } from "../src/bot/telegram-response-limiter.ts";

interface TestResponse {
  ok: boolean;
  result?: unknown;
  error_code?: number;
  parameters?: { retry_after?: unknown };
}

interface RecordedCall {
  method: string;
  payload: Record<string, unknown>;
  at: number;
}

type TestPrev = (method: string, payload: Record<string, unknown>, signal?: AbortSignal) => Promise<TestResponse>;
type TestTransformer = (prev: TestPrev, method: string, payload: Record<string, unknown>, signal?: AbortSignal) => Promise<TestResponse>;

let now = 0;

beforeEach(() => {
  now = 0;
  jest.useFakeTimers({ now: 0 });
  jest.spyOn(performance, "now").mockImplementation(() => now);
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

describe("Telegram response limiter", () => {
  test("shares thirty immediate slots across chats and queues the rest in FIFO order", async () => {
    const { calls, invoke } = recorder();
    const first = Array.from({ length: 30 }, (_, index) => invoke("sendMessage", { chat_id: index + 1, text: String(index + 1) }));
    const queued = [31, 32, 33].map((id) => invoke("sendMessage", { chat_id: id, text: String(id) }));
    await flushPromises();

    expect(calls.map((call) => call.payload.chat_id)).toEqual(Array.from({ length: 30 }, (_, index) => index + 1));
    await advance(999);
    expect(calls).toHaveLength(30);
    await advance(1);
    expect(calls.slice(30).map((call) => call.payload.chat_id)).toEqual([31, 32, 33]);
    await Promise.all([...first, ...queued]);
  });

  test("paces one chat at one call per second and preserves its FIFO order", async () => {
    const { calls, invoke } = recorder();
    const pending = ["first", "second", "third"].map((text) => invoke("sendMessage", { chat_id: 1, text }));
    await flushPromises();

    expect(calls.map((call) => call.payload.text)).toEqual(["first"]);
    await advance(999);
    expect(calls).toHaveLength(1);
    await advance(1);
    expect(calls.map((call) => call.payload.text)).toEqual(["first", "second"]);
    await advance(1_000);
    expect(calls.map((call) => call.payload.text)).toEqual(["first", "second", "third"]);
    await Promise.all(pending);
  });

  test("does not let a delayed chat block another chat", async () => {
    const { calls, invoke } = recorder();
    const first = invoke("sendMessage", { chat_id: 1, text: "chat-one-first" });
    const delayed = invoke("sendMessage", { chat_id: 1, text: "chat-one-second" });
    const other = invoke("sendMessage", { chat_id: 2, text: "chat-two" });
    await flushPromises();

    expect(calls.map((call) => call.payload.text)).toEqual(["chat-one-first", "chat-two"]);
    await advance(1_000);
    expect(calls.at(-1)?.payload.text).toBe("chat-one-second");
    await Promise.all([first, delayed, other]);
  });

  test("uses a rolling window instead of resetting at a fixed clock boundary", async () => {
    const { calls, invoke } = recorder();
    const pending = Array.from({ length: 20 }, (_, index) => invoke("sendMessage", { chat_id: index }));
    await flushPromises();
    await advance(500);
    pending.push(...Array.from({ length: 10 }, (_, index) => invoke("sendMessage", { chat_id: 20 + index })));
    const thirtyFirst = invoke("sendMessage", { chat_id: 31 });
    await flushPromises();

    expect(calls).toHaveLength(30);
    await advance(499);
    expect(calls).toHaveLength(30);
    await advance(1);
    expect(calls.at(-1)).toMatchObject({ payload: { chat_id: 31 }, at: 1_000 });
    await Promise.all([...pending, thirtyFirst]);
  });

  test("paces later windows from the actual dispatch time when a timer wakes late", async () => {
    const { calls, invoke } = recorder();
    const pending = Array.from({ length: 90 }, (_, index) => invoke("sendMessage", { chat_id: index }));
    await flushPromises();

    now = 1_900;
    jest.advanceTimersByTime(1_000);
    await flushPromises();
    expect(calls).toHaveLength(60);
    expect(calls.at(-1)?.at).toBe(1_900);

    now = 2_000;
    jest.advanceTimersByTime(1_000);
    await flushPromises();
    expect(calls).toHaveLength(60);

    now = 2_900;
    jest.advanceTimersByTime(900);
    await flushPromises();
    expect(calls).toHaveLength(90);
    expect(calls.at(-1)?.at).toBe(2_900);
    await Promise.all(pending);
  });

  test("counts every media-group item and waits until the complete weight fits", async () => {
    const { calls, invoke } = recorder();
    const textCalls = Array.from({ length: 25 }, (_, index) => invoke("sendMessage", { chat_id: index }));
    const album = invoke("sendMediaGroup", { chat_id: 100, media: Array.from({ length: 10 }, () => ({ type: "photo", media: "file" })) });
    const afterAlbum = invoke("sendMessage", { chat_id: 101 });
    await flushPromises();

    expect(calls).toHaveLength(25);
    expect(calls.some((call) => call.method === "sendMediaGroup")).toBe(false);
    await advance(1_000);
    expect(calls.slice(25).map((call) => call.method)).toEqual(["sendMediaGroup", "sendMessage"]);
    await Promise.all([...textCalls, album, afterAlbum]);
  });

  test("enforces one chat turn per second and twenty message-equivalents per group minute", async () => {
    const { calls, invoke } = recorder();
    const pending = Array.from({ length: 21 }, (_, index) => invoke("sendMessage", { chat_id: -1001, text: String(index) }));
    await flushPromises();
    expect(calls).toHaveLength(1);

    for (let index = 0; index < 19; index++) await advance(1_000);
    expect(calls).toHaveLength(20);
    await advance(40_999);
    expect(calls).toHaveLength(20);
    await advance(1);
    expect(calls).toHaveLength(21);
    await Promise.all(pending);
  });

  test("does not apply the group-minute budget to private chats", async () => {
    const { calls, invoke } = recorder();
    const pending = Array.from({ length: 21 }, (_, index) => invoke("sendMessage", { chat_id: 1, text: String(index) }));
    await flushPromises();
    for (let index = 0; index < 20; index++) await advance(1_000);

    expect(calls).toHaveLength(21);
    expect(calls.at(-1)?.at).toBe(20_000);
    await Promise.all(pending);
  });

  test("counts album items globally and per group but uses one chat turn", async () => {
    const { calls, invoke } = recorder();
    const media = Array.from({ length: 10 }, () => ({ type: "photo", media: "file" }));
    const first = invoke("sendMediaGroup", { chat_id: -1001, media });
    const second = invoke("sendMediaGroup", { chat_id: -1001, media });
    const blocked = invoke("sendMessage", { chat_id: -1001, text: "after albums" });
    await flushPromises();

    expect(calls).toHaveLength(1);
    await advance(1_000);
    expect(calls).toHaveLength(2);
    await advance(58_999);
    expect(calls).toHaveLength(2);
    await advance(1);
    expect(calls.map((call) => call.method)).toEqual(["sendMediaGroup", "sendMediaGroup", "sendMessage"]);
    await Promise.all([first, second, blocked]);
  });

  test("weights copyMessages and forwardMessages by their message ID counts", async () => {
    const { calls, invoke } = recorder();
    const copy = invoke("copyMessages", { message_ids: Array.from({ length: 15 }, (_, index) => index) });
    const forward = invoke("forwardMessages", { message_ids: Array.from({ length: 15 }, (_, index) => index) });
    const queued = invoke("sendMessage", { chat_id: 1 });
    await flushPromises();

    expect(calls.map((call) => call.method)).toEqual(["copyMessages", "forwardMessages"]);
    await advance(1_000);
    expect(calls.at(-1)?.method).toBe("sendMessage");
    await Promise.all([copy, forward, queued]);
  });

  test("rejects a bulk call above the limit before calling Telegram", async () => {
    const { calls, invoke } = recorder();
    await expect(invoke("copyMessages", { message_ids: Array.from({ length: 31 }, (_, index) => index) }))
      .rejects.toThrow("cannot create more than 30 messages");
    expect(calls).toHaveLength(0);
  });

  test("rejects a group bulk call above the group-minute capacity", async () => {
    const { calls, invoke } = recorder();
    await expect(invoke("copyMessages", { chat_id: -1001, message_ids: Array.from({ length: 21 }, (_, index) => index) }))
      .rejects.toThrow("group response cannot create more than 20 messages");
    expect(calls).toHaveLength(0);
  });

  test("treats negative IDs and usernames as groups while malformed targets stay global-only", async () => {
    for (const chatId of [-1001, "@example_group"]) {
      const { calls, invoke } = recorder();
      const bulk = invoke("copyMessages", { chat_id: chatId, message_ids: Array.from({ length: 20 }, (_, index) => index) });
      const blocked = invoke("sendMessage", { chat_id: chatId });
      await flushPromises();
      expect(calls, String(chatId)).toHaveLength(1);
      await advance(59_999);
      expect(calls, String(chatId)).toHaveLength(1);
      await advance(1);
      expect(calls, String(chatId)).toHaveLength(2);
      await Promise.all([bulk, blocked]);
    }

    const malformed = recorder();
    await Promise.all([
      malformed.invoke("sendMessage", { chat_id: "not-a-username" }),
      malformed.invoke("sendMessage", { chat_id: "not-a-username" }),
    ]);
    expect(malformed.calls).toHaveLength(2);
  });

  test("does not starve a weighted request behind newer single-message calls", async () => {
    const { calls, invoke } = recorder();
    const fillers = Array.from({ length: 29 }, (_, index) => invoke("sendMessage", { chat_id: index + 1 }));
    const album = invoke("sendMediaGroup", { chat_id: 100, media: Array.from({ length: 10 }, () => ({ type: "photo", media: "file" })) });
    const newer = Array.from({ length: 5 }, (_, index) => invoke("sendMessage", { chat_id: 200 + index }));
    await flushPromises();

    expect(calls).toHaveLength(29);
    await advance(1_000);
    expect(calls.slice(29).map((call) => call.method)).toEqual(["sendMediaGroup", ...Array.from({ length: 5 }, () => "sendMessage")]);
    await Promise.all([...fillers, album, ...newer]);
  });

  test("counts every supported single-message method", async () => {
    const methods = [
      "sendMessage", "sendRichMessage", "forwardMessage", "copyMessage", "sendPhoto", "sendLivePhoto",
      "sendAudio", "sendDocument", "sendVideo", "sendAnimation", "sendVoice", "sendVideoNote",
      "sendPaidMedia", "sendLocation", "sendVenue", "sendContact", "sendPoll", "sendChecklist",
      "sendDice", "sendSticker", "sendInvoice", "sendGame",
    ];

    for (const method of methods) {
      const { calls, invoke } = recorder();
      const fillers = Array.from({ length: 30 }, (_, index) => invoke("sendMessage", { chat_id: index }));
      const limited = invoke(method, { chat_id: 100 });
      await flushPromises();
      expect(calls, method).toHaveLength(30);
      await advance(1_000);
      expect(calls.at(-1)?.method, method).toBe(method);
      await Promise.all([...fillers, limited]);
    }
  });

  test("bypasses methods that do not create messages", async () => {
    const { calls, invoke } = recorder();
    const limited = Array.from({ length: 30 }, (_, index) => invoke("sendMessage", { chat_id: index }));
    const bypassedMethods = [
      "editMessageText", "setMessageReaction", "sendChatAction", "getMe", "deleteMessage", "getUpdates",
      "answerInlineQuery", "answerCallbackQuery", "setWebhook", "sendMessageDraft",
    ];
    const bypassed = bypassedMethods.map((method) => invoke(method));
    await flushPromises();

    expect(calls.slice(0, bypassedMethods.length).map((call) => call.method)).toEqual(bypassedMethods);
    expect(calls).toHaveLength(30 + bypassedMethods.length);
    await Promise.all([...limited, ...bypassed]);
  });

  test("waits for retry_after, reserves a new slot, and retries a 429 once", async () => {
    const responses: TestResponse[] = [
      { ok: false, error_code: 429, parameters: { retry_after: 2 } },
      { ok: true, result: "sent" },
    ];
    const { calls, invoke } = recorder(async () => responses.shift()!);
    const log = jest.spyOn(console, "log").mockImplementation(() => undefined);
    const result = invoke("sendMessage", { chat_id: 1, text: "private limiter payload" });
    await flushPromises();

    expect(calls).toHaveLength(1);
    expect(log).toHaveBeenCalledTimes(1);
    expect(log.mock.calls[0]?.[0]).toContain('"method":"sendMessage","retry_after":2');
    expect(log.mock.calls[0]?.[0]).not.toContain("private limiter payload");
    await advance(1_999);
    expect(calls).toHaveLength(1);
    await advance(1);
    expect(calls).toHaveLength(2);
    expect(await result).toEqual({ ok: true, result: "sent" });
  });

  test("reacquires the chat and group budgets before retrying", async () => {
    const responses: TestResponse[] = [
      { ok: false, error_code: 429, parameters: { retry_after: 0 } },
      { ok: true, result: "sent" },
    ];
    const { calls, invoke } = recorder(async () => responses.shift()!);
    jest.spyOn(console, "log").mockImplementation(() => undefined);
    const result = invoke("copyMessages", { chat_id: -1001, message_ids: Array.from({ length: 20 }, (_, index) => index) });
    await flushPromises();

    expect(calls).toHaveLength(1);
    await advance(59_999);
    expect(calls).toHaveLength(1);
    await advance(1);
    expect(calls).toHaveLength(2);
    expect(await result).toEqual({ ok: true, result: "sent" });
  });

  test("returns a second 429 without making a third attempt", async () => {
    const second = { ok: false, error_code: 429, parameters: { retry_after: 3 } } satisfies TestResponse;
    const responses: TestResponse[] = [
      { ok: false, error_code: 429, parameters: { retry_after: 1 } },
      second,
    ];
    const { calls, invoke } = recorder(async () => responses.shift()!);
    jest.spyOn(console, "log").mockImplementation(() => undefined);
    const result = invoke("sendMessage");
    await flushPromises();
    await advance(1_000);

    expect(await result).toBe(second);
    expect(calls).toHaveLength(2);
    await advance(3_000);
    expect(calls).toHaveLength(2);
  });

  test("does not retry malformed 429 responses, server errors, or non-message calls", async () => {
    const responses: TestResponse[] = [
      { ok: false, error_code: 429 },
      { ok: false, error_code: 429, parameters: { retry_after: -1 } },
      { ok: false, error_code: 429, parameters: { retry_after: 1.5 } },
      { ok: false, error_code: 429, parameters: { retry_after: "1" } },
      { ok: false, error_code: 500 },
      { ok: false, error_code: 429, parameters: { retry_after: 1 } },
    ];
    const { calls, invoke } = recorder(async () => responses.shift()!);
    const results = [];
    for (let index = 0; index < 5; index++) results.push(await invoke("sendMessage"));
    results.push(await invoke("editMessageText"));

    expect(results.map((response) => response.error_code)).toEqual([429, 429, 429, 429, 500, 429]);
    expect(calls).toHaveLength(6);
    expect(jest.getTimerCount()).toBe(0);
  });

  test("does not call Telegram for an aborted reservation and keeps its capacity consumed", async () => {
    const { calls, invoke } = recorder();
    const fillers = Array.from({ length: 30 }, (_, index) => invoke("sendMessage", { chat_id: index }));
    const controller = new AbortController();
    const queued = invoke("sendMessage", { chat_id: 31 }, controller.signal);
    const afterAbort = Array.from({ length: 30 }, (_, index) => invoke("sendMessage", { chat_id: 32 + index }));
    await flushPromises();
    const reason = new Error("cancelled by test");
    controller.abort(reason);

    await expect(queued).rejects.toBe(reason);
    await advance(1_000);
    expect(calls).toHaveLength(59);
    expect(calls.some((call) => call.payload.chat_id === 31)).toBe(false);
    await advance(1_000);
    expect(calls).toHaveLength(60);
    await Promise.all([...fillers, ...afterAbort]);
  });

  test("keeps an aborted reservation's chat turn", async () => {
    const { calls, invoke } = recorder();
    const first = invoke("sendMessage", { chat_id: 1, text: "first" });
    const controller = new AbortController();
    const aborted = invoke("sendMessage", { chat_id: 1, text: "aborted" }, controller.signal);
    const third = invoke("sendMessage", { chat_id: 1, text: "third" });
    await flushPromises();
    const reason = new Error("cancelled");
    controller.abort(reason);
    await expect(aborted).rejects.toBe(reason);

    await advance(1_000);
    expect(calls.map((call) => call.payload.text)).toEqual(["first"]);
    await advance(1_000);
    expect(calls.map((call) => call.payload.text)).toEqual(["first", "third"]);
    await Promise.all([first, third]);
  });

  test("does not call Telegram when an immediately granted reservation is aborted", async () => {
    const { calls, invoke } = recorder();
    const controller = new AbortController();
    const aborted = invoke("sendMessage", { chat_id: 1 }, controller.signal);
    const reason = new Error("cancelled before dispatch");
    controller.abort(reason);

    await expect(aborted).rejects.toBe(reason);
    expect(calls).toHaveLength(0);
    const next = invoke("sendMessage", { chat_id: 1 });
    await flushPromises();
    expect(calls).toHaveLength(0);
    await advance(1_000);
    expect(calls).toHaveLength(1);
    await next;
  });

  test("passes successful responses and thrown errors through unchanged", async () => {
    const success = { ok: true, result: { message_id: 1 } } satisfies TestResponse;
    const successful = recorder(async () => success);
    expect(await successful.invoke("sendMessage")).toBe(success);

    const failure = new Error("transport failed");
    const failing = recorder(async () => { throw failure; });
    await expect(failing.invoke("sendMessage")).rejects.toBe(failure);
    expect(failing.calls).toHaveLength(1);
  });
});

function recorder(respond: (call: RecordedCall) => Promise<TestResponse> = async () => ({ ok: true, result: true })): {
  calls: RecordedCall[];
  invoke: (method: string, payload?: Record<string, unknown>, signal?: AbortSignal) => Promise<TestResponse>;
} {
  const calls: RecordedCall[] = [];
  const transformer = createTelegramResponseLimiter() as unknown as TestTransformer;
  const prev: TestPrev = async (method, payload) => {
    const call = { method, payload, at: now };
    calls.push(call);
    return respond(call);
  };
  return {
    calls,
    invoke: (method, payload = {}, signal) => transformer(prev, method, payload, signal),
  };
}

async function advance(milliseconds: number): Promise<void> {
  now += milliseconds;
  jest.advanceTimersByTime(milliseconds);
  await flushPromises();
}

async function flushPromises(): Promise<void> {
  for (let index = 0; index < 8; index++) await Promise.resolve();
}
