import type { Transformer } from "grammy";
import { logger } from "../logging.ts";

const GLOBAL_CAPACITY = 30;
const GLOBAL_WINDOW_MS = 1_000;
const CHAT_WINDOW_MS = 1_000;
const GROUP_CAPACITY = 20;
const GROUP_WINDOW_MS = 60_000;
const STATE_SWEEP_INTERVAL_MS = 60_000;
type TransformerSignal = Parameters<Transformer>[3];

const SINGLE_MESSAGE_METHODS = new Set([
  "sendMessage",
  "sendRichMessage",
  "forwardMessage",
  "copyMessage",
  "sendPhoto",
  "sendLivePhoto",
  "sendAudio",
  "sendDocument",
  "sendVideo",
  "sendAnimation",
  "sendVoice",
  "sendVideoNote",
  "sendPaidMedia",
  "sendLocation",
  "sendVenue",
  "sendContact",
  "sendPoll",
  "sendChecklist",
  "sendDice",
  "sendSticker",
  "sendInvoice",
  "sendGame",
]);

interface ChatTarget {
  key: string;
  group: boolean;
}

interface Reservation {
  weight: number;
  target: ChatTarget | null;
  signal?: TransformerSignal;
  aborted: boolean;
  resolve: () => void;
  reject: (reason: unknown) => void;
  onAbort?: () => void;
}

interface DrainDecision {
  grantIndex: number | null;
  wakeAt: number;
}

class TelegramResponseScheduler {
  private readonly globalUsedAt: number[] = [];
  private readonly chatUsedAt = new Map<string, number[]>();
  private readonly groupUsedAt = new Map<string, number[]>();
  private readonly queue: Reservation[] = [];
  private wakeup: ReturnType<typeof setTimeout> | undefined;
  private nextSweepAt = 0;

  acquire(weight: number, target: ChatTarget | null, signal?: TransformerSignal): Promise<void> {
    validateWeight(weight, target);
    try {
      throwIfAborted(signal);
    } catch (error) {
      return Promise.reject(error);
    }

    return new Promise((resolve, reject) => {
      const reservation: Reservation = { weight, target, signal, aborted: false, resolve, reject };
      if (signal) {
        reservation.onAbort = () => {
          if (reservation.aborted) return;
          reservation.aborted = true;
          reject(abortReason(signal));
          this.drain();
        };
        signal.addEventListener("abort", reservation.onAbort, { once: true });
      }
      this.queue.push(reservation);
      this.drain();
    });
  }

  private drain(): void {
    this.clearWakeup();
    let now = performance.now();
    this.pruneGlobal(now);
    this.sweep(now);

    while (this.queue.length > 0) {
      const decision = this.nextDecision(now);
      if (decision.grantIndex === null) {
        this.scheduleWakeup(decision.wakeAt, now);
        return;
      }

      const reservation = this.queue.splice(decision.grantIndex, 1)[0]!;
      this.consume(this.globalUsedAt, reservation.weight, now);
      if (reservation.target) {
        this.consume(this.history(this.chatUsedAt, reservation.target.key), 1, now);
        if (reservation.target.group) this.consume(this.history(this.groupUsedAt, reservation.target.key), reservation.weight, now);
      }
      if (reservation.onAbort) reservation.signal?.removeEventListener("abort", reservation.onAbort);
      if (!reservation.aborted) reservation.resolve();

      now = performance.now();
      this.pruneGlobal(now);
    }
  }

  private nextDecision(now: number): DrainDecision {
    const chatHeads = new Set<string>();
    let wakeAt = Number.POSITIVE_INFINITY;

    for (let index = 0; index < this.queue.length; index++) {
      const reservation = this.queue[index]!;
      if (reservation.target) {
        if (chatHeads.has(reservation.target.key)) continue;
        chatHeads.add(reservation.target.key);
      }

      const localAvailableAt = this.localAvailableAt(reservation, now);
      if (localAvailableAt > now) {
        wakeAt = Math.min(wakeAt, localAvailableAt);
        continue;
      }

      const globalAvailableAt = availableAt(this.globalUsedAt, reservation.weight, GLOBAL_CAPACITY, GLOBAL_WINDOW_MS, now);
      if (globalAvailableAt <= now) return { grantIndex: index, wakeAt: now };

      return { grantIndex: null, wakeAt: Math.min(wakeAt, globalAvailableAt) };
    }

    return { grantIndex: null, wakeAt };
  }

  private localAvailableAt(reservation: Reservation, now: number): number {
    if (!reservation.target) return now;
    const chatAvailableAt = availableAt(
      this.history(this.chatUsedAt, reservation.target.key), 1, 1, CHAT_WINDOW_MS, now,
    );
    if (!reservation.target.group) return chatAvailableAt;
    const groupAvailableAt = availableAt(
      this.history(this.groupUsedAt, reservation.target.key), reservation.weight, GROUP_CAPACITY, GROUP_WINDOW_MS, now,
    );
    return Math.max(chatAvailableAt, groupAvailableAt);
  }

  private consume(history: number[], weight: number, now: number): void {
    for (let index = 0; index < weight; index++) history.push(now);
  }

  private history(store: Map<string, number[]>, key: string): number[] {
    let history = store.get(key);
    if (!history) {
      history = [];
      store.set(key, history);
    }
    return history;
  }

  private pruneGlobal(now: number): void {
    prune(this.globalUsedAt, GLOBAL_WINDOW_MS, now);
  }

  private sweep(now: number): void {
    if (now < this.nextSweepAt) return;
    sweepStore(this.chatUsedAt, CHAT_WINDOW_MS, now);
    sweepStore(this.groupUsedAt, GROUP_WINDOW_MS, now);
    this.nextSweepAt = now + STATE_SWEEP_INTERVAL_MS;
  }

  private scheduleWakeup(wakeAt: number, now: number): void {
    if (!Number.isFinite(wakeAt)) return;
    this.wakeup = setTimeout(() => {
      this.wakeup = undefined;
      this.drain();
    }, Math.max(0, wakeAt - now));
  }

  private clearWakeup(): void {
    if (this.wakeup === undefined) return;
    clearTimeout(this.wakeup);
    this.wakeup = undefined;
  }
}

export function createTelegramResponseLimiter(): Transformer {
  const scheduler = new TelegramResponseScheduler();

  return async (prev, method, payload, signal) => {
    const request = payload as Record<string, unknown>;
    const weight = messageWeight(method, request);
    if (weight === null) return prev(method, payload, signal);
    const target = chatTarget(request.chat_id);

    await scheduler.acquire(weight, target, signal);
    throwIfAborted(signal);
    const response = await prev(method, payload, signal);
    const retryAfter = telegramRetryAfter(response);
    if (retryAfter === null) return response;

    logger.warn("Telegram response rate-limited; retrying once", {
      method,
      retry_after: retryAfter,
    });
    await abortableDelay(retryAfter * 1_000, signal);
    await scheduler.acquire(weight, target, signal);
    throwIfAborted(signal);
    return prev(method, payload, signal);
  };
}

function messageWeight(method: string, payload: Record<string, unknown>): number | null {
  if (SINGLE_MESSAGE_METHODS.has(method)) return 1;
  if (method === "sendMediaGroup") return arrayWeight(payload.media, method);
  if (method === "forwardMessages" || method === "copyMessages") return arrayWeight(payload.message_ids, method);
  return null;
}

function arrayWeight(value: unknown, method: string): number {
  if (!Array.isArray(value) || value.length === 0) throw new RangeError(`${method} must contain at least one message`);
  return value.length;
}

function chatTarget(value: unknown): ChatTarget | null {
  if (typeof value === "number" && Number.isSafeInteger(value) && value !== 0) {
    return { key: `id:${value}`, group: value < 0 };
  }
  if (typeof value === "string" && /^@[A-Za-z0-9_]+$/u.test(value)) {
    return { key: `username:${value.toLowerCase()}`, group: true };
  }
  return null;
}

function validateWeight(weight: number, target: ChatTarget | null): void {
  if (!Number.isSafeInteger(weight) || weight < 1) throw new RangeError("Telegram response weight must be a positive integer");
  if (weight > GLOBAL_CAPACITY) throw new RangeError(`A Telegram response cannot create more than ${GLOBAL_CAPACITY} messages in one call`);
  if (target?.group && weight > GROUP_CAPACITY) {
    throw new RangeError(`A Telegram group response cannot create more than ${GROUP_CAPACITY} messages in one call`);
  }
}

function availableAt(history: number[], weight: number, capacity: number, windowMs: number, now: number): number {
  prune(history, windowMs, now);
  const slotsNeeded = history.length + weight - capacity;
  return slotsNeeded <= 0 ? now : history[slotsNeeded - 1]! + windowMs;
}

function prune(history: number[], windowMs: number, now: number): void {
  let expired = 0;
  while (history[expired] !== undefined && history[expired]! <= now - windowMs) expired++;
  if (expired > 0) history.splice(0, expired);
}

function sweepStore(store: Map<string, number[]>, windowMs: number, now: number): void {
  for (const [key, history] of store) {
    prune(history, windowMs, now);
    if (history.length === 0) store.delete(key);
  }
}

function telegramRetryAfter(response: { ok: boolean; error_code?: number; parameters?: { retry_after?: number } }): number | null {
  if (response.ok || response.error_code !== 429) return null;
  const retryAfter = response.parameters?.retry_after;
  return typeof retryAfter === "number" && Number.isSafeInteger(retryAfter) && retryAfter >= 0 ? retryAfter : null;
}

function abortableDelay(milliseconds: number, signal?: TransformerSignal): Promise<void> {
  try {
    throwIfAborted(signal);
  } catch (error) {
    return Promise.reject(error);
  }
  if (milliseconds <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, milliseconds);
    function onAbort(): void {
      clearTimeout(timeout);
      reject(abortReason(signal));
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function throwIfAborted(signal?: TransformerSignal): void {
  if (signal?.aborted) throw abortReason(signal);
}

function abortReason(signal?: TransformerSignal): unknown {
  if (signal && "reason" in signal && signal.reason !== undefined) return signal.reason;
  return new DOMException("The operation was aborted", "AbortError");
}
