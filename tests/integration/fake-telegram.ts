interface UploadedFileSummary {
  filename: string;
  contentType: string;
  size: number;
}

export interface TelegramTestMessage {
  message_id: number;
  date: number;
  chat: { id: number; type: "private"; first_name: string } | { id: number; type: "supergroup"; title: string };
  text?: string;
  caption?: string;
  photo?: Array<{ file_id: string; file_unique_id: string; width: number; height: number; file_size: number }>;
  video?: { file_id: string; file_unique_id: string; width: number; height: number; duration: number; file_size: number };
  document?: { file_id: string; file_unique_id: string; file_name: string; mime_type: string; file_size: number };
}

export interface TelegramTestCall {
  method: string;
  token: string;
  payload: Record<string, unknown>;
  multipart: boolean;
  messages: TelegramTestMessage[];
}

const JSON_FIELDS = new Set([
  "link_preview_options",
  "media",
  "reaction",
  "reply_markup",
  "reply_parameters",
]);

/**
 * A deterministic Telegram Bot API boundary shared by the bot and tt-scrap.
 * tt-scrap reaches it with multipart uploads, while grammY reaches it with JSON
 * when cached file IDs are reused. Recording both paths makes the integration
 * assertions independent of a real Telegram chat and real bot credentials.
 */
export class FakeTelegramApi {
  readonly calls: TelegramTestCall[] = [];
  readonly baseUrl: string;
  private readonly server: ReturnType<typeof Bun.serve>;
  private nextMessageId = 10_000;

  constructor(port: number, private readonly botId: number) {
    this.server = Bun.serve({
      hostname: "127.0.0.1",
      port,
      fetch: (request) => this.handle(request),
    });
    this.baseUrl = `http://127.0.0.1:${this.server.port}`;
  }

  stop(): void {
    this.server.stop(true);
  }

  mark(): number {
    return this.calls.length;
  }

  since(mark: number): TelegramTestCall[] {
    return this.calls.slice(mark);
  }

  private async handle(request: Request): Promise<Response> {
    const match = new URL(request.url).pathname.match(/^\/bot([^/]+)\/([^/]+)$/u);
    if (!match) return Response.json({ ok: false, error_code: 404, description: "Unknown test route" }, { status: 404 });
    const token = match[1]!;
    const method = match[2]!;
    const contentType = request.headers.get("content-type") ?? "";
    const multipart = contentType.startsWith("multipart/form-data");
    const payload = request.method === "POST" ? await requestPayload(request, contentType) : {};
    const messages = this.responseMessages(method, payload);
    this.calls.push({ method, token, payload, multipart, messages });

    if (method === "getMe") {
      return Response.json({ ok: true, result: { id: this.botId, is_bot: true, first_name: "Integration Bot", username: "integration_test_bot" } });
    }
    if ([
      "answerCallbackQuery",
      "answerInlineQuery",
      "deleteMessage",
      "editMessageMedia",
      "editMessageReplyMarkup",
      "editMessageText",
      "sendChatAction",
      "setMessageReaction",
    ].includes(method)) return Response.json({ ok: true, result: true });
    if (method === "sendMediaGroup") return Response.json({ ok: true, result: messages });
    if (messages[0]) return Response.json({ ok: true, result: messages[0] });
    return Response.json({ ok: false, error_code: 400, description: `Unsupported fake Telegram method: ${method}` }, { status: 400 });
  }

  private responseMessages(method: string, payload: Record<string, unknown>): TelegramTestMessage[] {
    if (method === "sendMediaGroup") {
      const media = Array.isArray(payload.media) ? payload.media : [];
      return media.map((item, index) => {
        const row = isRecord(item) ? item : {};
        return this.mediaMessage(String(row.type ?? "document"), payload, row, index);
      });
    }
    if (method === "sendPhoto") return [this.mediaMessage("photo", payload, payload, 0)];
    if (method === "sendVideo") return [this.mediaMessage("video", payload, payload, 0)];
    if (method === "sendDocument") return [this.mediaMessage("document", payload, payload, 0)];
    if (method === "sendMessage") {
      return [{
        message_id: this.nextMessageId++,
        date: 1,
        chat: chatFor(payload.chat_id),
        text: String(payload.text ?? ""),
      }];
    }
    return [];
  }

  private mediaMessage(type: string, outer: Record<string, unknown>, item: Record<string, unknown>, index: number): TelegramTestMessage {
    const id = this.nextMessageId++;
    const common: TelegramTestMessage = {
      message_id: id,
      date: 1,
      chat: chatFor(outer.chat_id),
      ...(typeof item.caption === "string" ? { caption: item.caption } : typeof outer.caption === "string" ? { caption: outer.caption } : {}),
    };
    if (type === "photo") {
      common.photo = [{ file_id: `integration-photo-${id}-${index}`, file_unique_id: `integration-photo-unique-${id}-${index}`, width: 1280, height: 720, file_size: 1234 }];
    } else if (type === "video") {
      common.video = { file_id: `integration-video-${id}-${index}`, file_unique_id: `integration-video-unique-${id}-${index}`, width: 1280, height: 720, duration: 5, file_size: 5678 };
    } else {
      common.document = { file_id: `integration-document-${id}-${index}`, file_unique_id: `integration-document-unique-${id}-${index}`, file_name: `media-${index}.bin`, mime_type: "application/octet-stream", file_size: 9012 };
    }
    return common;
  }
}

async function requestPayload(request: Request, contentType: string): Promise<Record<string, unknown>> {
  if (contentType.startsWith("application/json")) {
    const value: unknown = await request.json();
    return isRecord(value) ? value : {};
  }
  if (contentType.startsWith("multipart/form-data") || contentType.startsWith("application/x-www-form-urlencoded")) {
    const result: Record<string, unknown> = {};
    const form = await request.formData();
    for (const [name, value] of form.entries() as IterableIterator<[string, string | File]>) {
      if (typeof value !== "string") {
        result[name] = { filename: value.name, contentType: value.type, size: value.size } satisfies UploadedFileSummary;
      } else if (JSON_FIELDS.has(name)) {
        result[name] = parseJson(value);
      } else if (value === "true" || value === "false") {
        result[name] = value === "true";
      } else {
        result[name] = value;
      }
    }
    return result;
  }
  const text = await request.text();
  return text ? { body: text } : {};
}

function parseJson(value: string): unknown {
  try { return JSON.parse(value) as unknown; }
  catch { return value; }
}

function chatFor(value: unknown): TelegramTestMessage["chat"] {
  const id = Number(value ?? 0);
  return id < 0
    ? { id, type: "supergroup", title: "Integration Storage" }
    : { id, type: "private", first_name: "Integration User" };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
