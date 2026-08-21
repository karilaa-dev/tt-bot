import { afterEach, beforeEach, describe, expect, jest, test } from "bun:test";
import { createSpamProtection } from "../src/bot/spam-protection.ts";

interface TestContext {
  message?: {
    message_id: number;
    text?: string;
    entities?: Array<{ type: string; offset: number; length: number }>;
  };
  chat?: { id: number; type: "private" | "group" | "supergroup" };
  from?: { id: number; is_bot: boolean; first_name: string; language_code?: string };
  callbackQuery?: object;
  inlineQuery?: object;
  chosenInlineResult?: object;
  reply: (text: string, options: Record<string, unknown>) => Promise<unknown>;
}

interface DispatchOptions {
  chatId?: number;
  chatType?: "private" | "group" | "supergroup";
  senderId?: number;
  text?: string;
  command?: boolean;
  bot?: boolean;
  message?: boolean;
}

type TestMiddleware = (ctx: TestContext, next: () => Promise<void>) => Promise<void>;

let now = 0;

beforeEach(() => {
  now = 0;
  jest.spyOn(performance, "now").mockImplementation(() => now);
  jest.spyOn(console, "log").mockImplementation(() => undefined);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("spam protection", () => {
  test("allows five private messages, warns on the sixth, and silently ignores the timeout", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 5; index++) await harness.dispatch();

    expect(harness.passed).toBe(5);
    expect(harness.replies).toHaveLength(0);
    await harness.dispatch();
    expect(harness.passed).toBe(5);
    expect(harness.replies).toHaveLength(1);
    expect(harness.replies[0]?.text).toContain("1 minute");

    await harness.dispatch();
    expect(harness.passed).toBe(5);
    expect(harness.replies).toHaveLength(1);

    now = 60_000;
    await harness.dispatch();
    expect(harness.passed).toBe(6);
  });

  test("uses a rolling sender window", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 3; index++) await harness.dispatch();
    now = 4_999;
    for (let index = 0; index < 2; index++) await harness.dispatch();
    now = 5_000;
    await harness.dispatch();

    expect(harness.passed).toBe(6);
    expect(harness.replies).toHaveLength(0);
  });

  test("escalates a repeat violation to five minutes", async () => {
    const harness = spamHarness();
    await triggerSenderTimeout(harness);
    now = 60_000;
    await triggerSenderTimeout(harness);

    expect(harness.replies.map((reply) => reply.text)).toEqual([
      expect.stringContaining("1 minute"),
      expect.stringContaining("5 minutes"),
    ]);
    now = 359_999;
    await harness.dispatch();
    expect(harness.passed).toBe(10);
    now = 360_000;
    await harness.dispatch();
    expect(harness.passed).toBe(11);
  });

  test("resets escalation after one hour without a violation", async () => {
    const harness = spamHarness();
    await triggerSenderTimeout(harness);
    now = 60_000;
    await triggerSenderTimeout(harness);
    now = 3_660_000;
    await triggerSenderTimeout(harness);

    expect(harness.replies.at(-1)?.text).toContain("1 minute");
  });

  test("times out only the offending member of a group", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 6; index++) await harness.dispatch(groupCommand(1));
    await harness.dispatch(groupCommand(2));
    await harness.dispatch(groupCommand(1));

    expect(harness.passed).toBe(6);
    expect(harness.replies).toHaveLength(1);
    expect(harness.replies[0]?.text).toContain("your messages");
  });

  test("pauses a group on its twenty-first actionable message", async () => {
    const harness = spamHarness();
    for (let senderId = 1; senderId <= 20; senderId++) await harness.dispatch(groupCommand(senderId));
    await harness.dispatch(groupCommand(21));
    await harness.dispatch(groupCommand(22));

    expect(harness.passed).toBe(20);
    expect(harness.replies).toHaveLength(1);
    expect(harness.replies[0]?.text).toContain("this group");
    now = 60_000;
    await harness.dispatch(groupCommand(22));
    expect(harness.passed).toBe(21);
  });

  test("does not charge muted sender traffic to the group budget", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 6; index++) await harness.dispatch(groupCommand(1));
    for (let index = 0; index < 20; index++) await harness.dispatch(groupCommand(1));
    for (let senderId = 2; senderId <= 15; senderId++) await harness.dispatch(groupCommand(senderId));

    expect(harness.passed).toBe(19);
    expect(harness.replies).toHaveLength(1);
    await harness.dispatch(groupCommand(16));
    expect(harness.passed).toBe(19);
    expect(harness.replies).toHaveLength(2);
    expect(harness.replies.at(-1)?.text).toContain("this group");
  });

  test("advances both penalties but sends one group warning when both limits trip", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 5; index++) await harness.dispatch(groupCommand(1));
    for (let senderId = 2; senderId <= 16; senderId++) await harness.dispatch(groupCommand(senderId));
    await harness.dispatch(groupCommand(1));

    expect(harness.passed).toBe(20);
    expect(harness.replies).toHaveLength(1);
    expect(harness.replies[0]?.text).toContain("this group");
    const logs = (console.log as unknown as ReturnType<typeof jest.fn>).mock.calls.flat().join("\n");
    expect(logs).toContain('"scope":"sender"');
    expect(logs).toContain('"scope":"group"');
  });

  test("counts commands and supported links but bypasses ordinary group conversation", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 30; index++) {
      await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "ordinary conversation" });
      await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "https://example.com/video/1" });
    }
    expect(harness.passed).toBe(60);

    await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "https://vm.tiktok.com/ZTest" });
    await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "https://www.instagram.com/reel/ABC123" });
    await harness.dispatch(groupCommand(1));
    await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "https://www.tiktok.com/@user/video/123" });
    await harness.dispatch({ chatId: -1, chatType: "group", senderId: 1, text: "https://instagram.com/p/POST" });
    await harness.dispatch(groupCommand(1));

    expect(harness.passed).toBe(65);
    expect(harness.replies).toHaveLength(1);
  });

  test("bypasses non-message updates and bot-authored messages", async () => {
    const harness = spamHarness();
    for (let index = 0; index < 10; index++) await harness.dispatch({ message: false });
    for (let index = 0; index < 10; index++) await harness.dispatch({ bot: true });

    expect(harness.passed).toBe(20);
    expect(harness.replies).toHaveLength(0);
  });

  test("keeps a timeout when its warning fails and never logs message text", async () => {
    const secret = "private incoming payload";
    const failure = new Error("Telegram warning failed");
    const harness = spamHarness(failure);
    for (let index = 0; index < 6; index++) await harness.dispatch({ text: secret });
    await harness.dispatch({ text: secret });

    expect(harness.passed).toBe(5);
    expect(harness.replyAttempts).toBe(1);
    const logs = (console.log as unknown as ReturnType<typeof jest.fn>).mock.calls.flat().join("\n");
    expect(logs).toContain("Spam timeout started");
    expect(logs).toContain("Failed to send spam timeout warning");
    expect(logs).not.toContain(secret);
  });
});

function spamHarness(replyFailure?: Error): {
  readonly passed: number;
  readonly replyAttempts: number;
  replies: Array<{ text: string; options: Record<string, unknown> }>;
  dispatch: (options?: DispatchOptions) => Promise<void>;
} {
  const middleware = createSpamProtection() as unknown as TestMiddleware;
  const replies: Array<{ text: string; options: Record<string, unknown> }> = [];
  let passed = 0;
  let replyAttempts = 0;
  let messageId = 0;

  return {
    get passed() { return passed; },
    get replyAttempts() { return replyAttempts; },
    replies,
    async dispatch(options = {}) {
      messageId++;
      const chatId = options.chatId ?? 1;
      const chatType = options.chatType ?? "private";
      const senderId = options.senderId ?? 1;
      const hasMessage = options.message ?? true;
      const text = options.text ?? (options.command ? "/mode" : "hello");
      const ctx: TestContext = {
        chat: { id: chatId, type: chatType },
        from: { id: senderId, is_bot: options.bot ?? false, first_name: "Tester", language_code: "en" },
        ...(hasMessage ? { message: {
          message_id: messageId,
          text,
          ...(options.command ? { entities: [{ type: "bot_command", offset: 0, length: text.length }] } : {}),
        } } : { callbackQuery: {} }),
        reply: async (value, replyOptions) => {
          replyAttempts++;
          if (replyFailure) throw replyFailure;
          replies.push({ text: value, options: replyOptions });
          return {};
        },
      };
      await middleware(ctx, async () => { passed++; });
    },
  };
}

function groupCommand(senderId: number): DispatchOptions {
  return { chatId: -1, chatType: "group", senderId, command: true };
}

async function triggerSenderTimeout(harness: ReturnType<typeof spamHarness>): Promise<void> {
  for (let index = 0; index < 6; index++) await harness.dispatch();
}
