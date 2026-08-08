import { GrammyError } from "grammy";
import type { Message } from "grammy/types";
import type { AppConfig } from "../config.ts";
import { PartialDeliveryError, TtScrapError } from "../bot/errors.ts";
import { logger } from "../logging.ts";
import type {
  InstagramDeliveryRequest,
  InstagramExtraction,
  InstagramTelegramMethod,
  TelegramDeliveryCall,
  TelegramDeliveryResult,
  TikTokDeliveryRequest,
  TikTokExtraction,
  TikTokResolution,
} from "./tt-scrap-types.ts";

interface ErrorEnvelope { error: { code: string; message: string; request_id: string } }
interface TelegramEnvelope { ok: boolean; result?: unknown; error_code?: number; description?: string; parameters?: Record<string, unknown> | null }
interface MultiEnvelope { ok: boolean; partial: boolean; deliveries: Array<{ method: string; status_code: number; response: unknown }> }

export interface RetryOptions {
  attempts?: number;
  onRetry?: (attempt: number, maxRetries: number) => Promise<void>;
}

export class TtScrapClient {
  constructor(private readonly config: AppConfig) {}

  async healthReady(): Promise<boolean> {
    try {
      const response = await fetch(`${this.config.ttScrapBaseUrl}/health/ready`, { signal: AbortSignal.timeout(5_000) });
      return response.ok;
    } catch {
      return false;
    }
  }

  extractTikTok(url: string, options: RetryOptions = {}): Promise<TikTokExtraction> {
    return this.requestWithRetry("/v1/tiktok/extractions", { url, refresh: false }, isTikTokExtraction, options);
  }

  resolveTikTok(url: string, options: RetryOptions = {}): Promise<TikTokResolution> {
    return this.requestWithRetry("/v1/tiktok/resolutions", { url }, isTikTokResolution, options);
  }

  extractInstagram(url: string, options: RetryOptions = {}): Promise<InstagramExtraction> {
    return this.requestWithRetry("/v1/instagram/extractions", { url, refresh: false }, isInstagramExtraction, options);
  }

  deliverTikTok(request: TikTokDeliveryRequest): Promise<TelegramDeliveryResult> {
    return this.deliver("/v1/tiktok/telegram-deliveries", request, inferTikTokMethod(request));
  }

  deliverInstagram(request: InstagramDeliveryRequest, expectedMethod: InstagramTelegramMethod): Promise<TelegramDeliveryResult> {
    return this.deliver(this.config.ttScrapInstagramDeliveryPath, request, expectedMethod);
  }

  private async requestWithRetry<T>(path: string, body: unknown, validate: (value: unknown) => value is T, options: RetryOptions): Promise<T> {
    const attempts = Math.max(1, options.attempts ?? 1);
    let last: unknown;
    for (let attempt = 1; attempt <= attempts; attempt++) {
      try {
        return await this.post(path, body, this.config.ttScrapRequestTimeoutMs, validate);
      } catch (error) {
        last = error;
        if (attempt >= attempts || !isRetryableRequestError(error)) throw error;
        await options.onRetry?.(attempt, attempts - 1);
        await Bun.sleep(Math.min(4_000, 500 * 2 ** (attempt - 1)));
      }
    }
    throw last;
  }

  private async deliver(path: string, body: unknown, expectedMethod: string): Promise<TelegramDeliveryResult> {
    const response = await this.fetch(path, body, this.config.ttScrapDeliveryTimeoutMs, true);
    const requestId = response.headers.get("x-request-id") || "unknown";
    logger.debug("tt-scrap delivery response", { path, status: response.status, request_id: requestId });
    const value: unknown = await parseJson(response);
    if (isErrorEnvelope(value)) throw toTtScrapError(value, response.status);
    if (isMultiEnvelope(value)) {
      const calls: TelegramDeliveryCall[] = [];
      for (const delivery of value.deliveries) {
        const envelope = delivery.response;
        if (!isTelegramEnvelope(envelope) || !envelope.ok) {
          if (calls.length > 0 || value.partial) throw new PartialDeliveryError(calls.length, requestId);
          throw telegramError(envelope, delivery.method, body, requestId);
        }
        calls.push({ method: delivery.method, statusCode: delivery.status_code, result: telegramResult(envelope.result) });
      }
      if (!response.ok || response.status === 207 || value.partial || !value.ok) throw new PartialDeliveryError(calls.length, requestId);
      return { calls };
    }
    if (!response.ok) {
      if (isTelegramEnvelope(value) && !value.ok) throw telegramError(value, expectedMethod, body, requestId);
      throw new TtScrapError("http_error", `tt-scrap returned HTTP ${response.status}`, requestId, response.status);
    }
    if (!isTelegramEnvelope(value)) throw new TtScrapError("invalid_response", "tt-scrap returned an invalid Telegram response", "unknown", response.status);
    if (!value.ok) throw telegramError(value, expectedMethod, body, requestId);
    return { calls: [{ method: expectedMethod, statusCode: response.status, result: telegramResult(value.result) }] };
  }

  private async post<T>(path: string, body: unknown, timeoutMs: number, validate: (value: unknown) => value is T): Promise<T> {
    const response = await this.fetch(path, body, timeoutMs);
    logger.debug("tt-scrap extraction response", { path, status: response.status, request_id: response.headers.get("x-request-id") || "unknown" });
    const value: unknown = await parseJson(response);
    if (isErrorEnvelope(value)) throw toTtScrapError(value, response.status);
    if (!response.ok) throw new TtScrapError("http_error", `tt-scrap returned HTTP ${response.status}`, response.headers.get("x-request-id") || "unknown", response.status);
    if (!validate(value)) throw new TtScrapError("invalid_response", "tt-scrap returned an invalid extraction response", response.headers.get("x-request-id") || "unknown", response.status);
    return value;
  }

  private async fetch(path: string, body: unknown, timeoutMs: number, delivery = false): Promise<Response> {
    try {
      return await fetch(`${this.config.ttScrapBaseUrl}${path}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${this.config.ttScrapApiKey}`, "Content-Type": "application/json" },
        body: stringifyJson(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (error) {
      logger.warn("tt-scrap request failed", error);
      throw new TtScrapError(delivery ? "telegram_delivery_ambiguous" : "upstream_network_error", delivery ? "The tt-scrap delivery outcome is unknown" : "Could not reach tt-scrap", "unknown", 502);
    }
  }
}

function inferTikTokMethod(request: TikTokDeliveryRequest): string {
  if (request.delivery === "audio") return "sendAudio";
  if (request.delivery === "document") return "sendDocument";
  return "sendVideo";
}

function telegramResult(value: unknown): Message | Message[] {
  if (Array.isArray(value)) {
    if (!value.every(isMessage)) throw new TtScrapError("invalid_response", "Telegram album response contains an invalid message", "unknown", 502);
    return value as Message[];
  }
  if (!isMessage(value)) throw new TtScrapError("invalid_response", "Telegram response does not contain a message", "unknown", 502);
  return value as Message;
}

function isMessage(value: unknown): value is Message {
  return typeof value === "object" && value !== null && typeof (value as { message_id?: unknown }).message_id === "number" && typeof (value as { chat?: unknown }).chat === "object";
}
function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (!isRecord(value) || !("error" in value)) return false;
  const error = value.error;
  return isRecord(error) && typeof error.code === "string" && typeof error.message === "string" && typeof error.request_id === "string";
}
function isTelegramEnvelope(value: unknown): value is TelegramEnvelope {
  if (!isRecord(value) || typeof value.ok !== "boolean") return false;
  if (value.error_code !== undefined && value.error_code !== null && typeof value.error_code !== "number") return false;
  if (value.description !== undefined && value.description !== null && typeof value.description !== "string") return false;
  return value.parameters === undefined || value.parameters === null || isRecord(value.parameters);
}
function isMultiEnvelope(value: unknown): value is MultiEnvelope {
  return isRecord(value)
    && typeof value.ok === "boolean"
    && typeof value.partial === "boolean"
    && Array.isArray(value.deliveries)
    && value.deliveries.every((delivery) => isRecord(delivery)
      && typeof delivery.method === "string"
      && typeof delivery.status_code === "number"
      && "response" in delivery);
}
function toTtScrapError(value: ErrorEnvelope, status: number): TtScrapError {
  return new TtScrapError(value.error.code, value.error.message, value.error.request_id, status);
}
function telegramError(value: unknown, method: string, payload: unknown, requestId: string): GrammyError {
  const envelope = isTelegramEnvelope(value) ? value : { ok: false, error_code: 502, description: "Invalid Telegram error response" };
  const error = new GrammyError(`Call to '${method}' through tt-scrap failed!`, {
    ok: false,
    error_code: envelope.error_code ?? 502,
    description: envelope.description ?? "Telegram delivery failed",
    parameters: envelope.parameters as never,
  }, method, payload as Record<string, unknown>);
  Object.assign(error, { ttScrapRequestId: requestId });
  return error;
}
async function parseJson(response: Response): Promise<unknown> {
  try { return await response.json(); }
  catch { throw new TtScrapError("invalid_response", "tt-scrap returned invalid JSON", response.headers.get("x-request-id") || "unknown", response.status); }
}
function isRetryableRequestError(error: unknown): boolean {
  return error instanceof TtScrapError && (
    ["upstream_network_error", "upstream_extraction_error", "upstream_timeout", "upstream_rate_limited"].includes(error.code)
    || [429, 502, 503, 504].includes(error.status)
  );
}
function stringifyJson(value: unknown): string {
  const rawJson = (JSON as typeof JSON & { rawJSON(value: string): unknown }).rawJSON;
  // Emit bigint values as exact JSON integer tokens. Converting them to Number
  // would lose precision, while quoting them would violate the OpenAPI schema.
  return JSON.stringify(value, (_key, item: unknown) => typeof item === "bigint" ? rawJson(item.toString()) : item);
}

function isTikTokExtraction(value: unknown): value is TikTokExtraction {
  if (!isRecord(value)) return false;
  return value.platform === "tiktok"
    && typeof value.extraction_id === "string"
    && typeof value.source_id === "string"
    && typeof value.source_url === "string"
    && typeof value.resolved_url === "string"
    && (value.content_type === "video" || value.content_type === "slideshow")
    && Array.isArray(value.media)
    && value.media.every(isRecord)
    && typeof value.expires_at === "string";
}

function isTikTokResolution(value: unknown): value is TikTokResolution {
  return isRecord(value)
    && value.platform === "tiktok"
    && typeof value.source_id === "string"
    && /^[0-9]+$/u.test(value.source_id)
    && typeof value.source_url === "string"
    && typeof value.resolved_url === "string";
}

function isInstagramExtraction(value: unknown): value is InstagramExtraction {
  if (!isRecord(value)) return false;
  return value.platform === "instagram"
    && typeof value.extraction_id === "string"
    && typeof value.source_id === "string"
    && typeof value.source_url === "string"
    && ["video", "image", "carousel"].includes(String(value.content_type))
    && Array.isArray(value.media)
    && value.media.every((media) => isRecord(media)
      && typeof media.position === "number"
      && (media.media_type === "video" || media.media_type === "image")
      && isRecord(media.asset))
    && typeof value.expires_at === "string";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
