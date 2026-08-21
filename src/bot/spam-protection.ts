import type { Context, MiddlewareFn } from "grammy";
import { findInstagramUrl } from "../handlers/links.ts";
import { findTikTokUrl } from "../handlers/tiktok.ts";
import { languageFromTelegram, type LocaleKey, text } from "../locales.ts";
import { logger } from "../logging.ts";

const SENDER_CAPACITY = 5;
const SENDER_WINDOW_MS = 5_000;
const GROUP_CAPACITY = 20;
const GROUP_WINDOW_MS = 60_000;
const FIRST_TIMEOUT_MS = 60_000;
const REPEAT_TIMEOUT_MS = 300_000;
const ESCALATION_RESET_MS = 3_600_000;
const STATE_SWEEP_INTERVAL_MS = 60_000;

interface SpamState {
  receivedAt: number[];
  blockedUntil: number;
  lastViolationAt: number | null;
}

interface TimeoutEvent {
  scope: "sender" | "group";
  chatId: number;
  senderId?: number;
  durationMs: number;
}

export function createSpamProtection<C extends Context = Context>(): MiddlewareFn<C> {
  const senders = new Map<string, SpamState>();
  const groups = new Map<number, SpamState>();
  let nextSweepAt = 0;

  return async (ctx, next) => {
    if (!isActionableMessage(ctx)) return next();
    const message = ctx.message!;
    const chat = ctx.chat!;
    const now = performance.now();

    if (now >= nextSweepAt) {
      sweepStates(senders, SENDER_WINDOW_MS, now);
      sweepStates(groups, GROUP_WINDOW_MS, now);
      nextSweepAt = now + STATE_SWEEP_INTERVAL_MS;
    }

    const group = chat.type === "group" || chat.type === "supergroup";
    const groupState = group ? stateFor(groups, chat.id) : null;
    prepareState(groupState, GROUP_WINDOW_MS, now);
    if (groupState && groupState.blockedUntil > now) return;

    const senderId = ctx.from?.id;
    const senderKey = senderId === undefined ? null : `${chat.id}:${senderId}`;
    const senderState = senderKey === null ? null : stateFor(senders, senderKey);
    prepareState(senderState, SENDER_WINDOW_MS, now);
    if (senderState && senderState.blockedUntil > now) return;

    let senderTimeout: TimeoutEvent | null = null;
    if (senderState && exceeds(senderState, SENDER_CAPACITY, now)) {
      senderTimeout = {
        scope: "sender",
        chatId: chat.id,
        senderId,
        durationMs: startTimeout(senderState, now),
      };
    }

    let groupTimeout: TimeoutEvent | null = null;
    if (groupState && exceeds(groupState, GROUP_CAPACITY, now)) {
      groupTimeout = {
        scope: "group",
        chatId: chat.id,
        ...(senderId === undefined ? {} : { senderId }),
        durationMs: startTimeout(groupState, now),
      };
    }

    if (!senderTimeout && !groupTimeout) return next();
    if (senderTimeout) logTimeout(senderTimeout);
    if (groupTimeout) logTimeout(groupTimeout);
    await sendTimeoutWarning(ctx, groupTimeout ?? senderTimeout!, message.message_id);
  };
}

function isActionableMessage(ctx: Context): boolean {
  if (!ctx.message || !ctx.chat || ctx.from?.is_bot) return false;
  if (ctx.chat.type === "private") return true;
  if (ctx.chat.type !== "group" && ctx.chat.type !== "supergroup") return false;
  const value = ctx.message.text;
  if (!value) return false;
  if (ctx.message.entities?.some((entity) => entity.type === "bot_command")) return true;
  return findTikTokUrl(value, ctx.message.entities) !== null
    || findInstagramUrl(value, ctx.message.entities) !== null;
}

function stateFor<K>(states: Map<K, SpamState>, key: K): SpamState {
  let state = states.get(key);
  if (!state) {
    state = { receivedAt: [], blockedUntil: 0, lastViolationAt: null };
    states.set(key, state);
  }
  return state;
}

function prepareState(state: SpamState | null, windowMs: number, now: number): void {
  if (!state) return;
  prune(state.receivedAt, windowMs, now);
  if (state.lastViolationAt !== null && now - state.lastViolationAt >= ESCALATION_RESET_MS) {
    state.lastViolationAt = null;
  }
}

function exceeds(state: SpamState, capacity: number, now: number): boolean {
  state.receivedAt.push(now);
  return state.receivedAt.length > capacity;
}

function startTimeout(state: SpamState, now: number): number {
  const repeated = state.lastViolationAt !== null && now - state.lastViolationAt < ESCALATION_RESET_MS;
  const durationMs = repeated ? REPEAT_TIMEOUT_MS : FIRST_TIMEOUT_MS;
  state.receivedAt.length = 0;
  state.lastViolationAt = now;
  state.blockedUntil = now + durationMs;
  return durationMs;
}

function logTimeout(event: TimeoutEvent): void {
  logger.warn("Spam timeout started", {
    scope: event.scope,
    chat_id: event.chatId,
    ...(event.senderId === undefined ? {} : { sender_id: event.senderId }),
    duration_seconds: event.durationMs / 1_000,
  });
}

async function sendTimeoutWarning(ctx: Context, event: TimeoutEvent, messageId: number): Promise<void> {
  const key = timeoutKey(event.scope, event.durationMs);
  try {
    await ctx.reply(text(languageFromTelegram(ctx.from?.language_code), key), {
      parse_mode: "HTML",
      reply_parameters: { message_id: messageId },
    });
  } catch (error) {
    logger.warn(`Failed to send spam timeout warning for chat ${event.chatId}`, error);
  }
}

function timeoutKey(scope: TimeoutEvent["scope"], durationMs: number): LocaleKey {
  if (scope === "group") return durationMs === FIRST_TIMEOUT_MS ? "spam_group_timeout_1m" : "spam_group_timeout_5m";
  return durationMs === FIRST_TIMEOUT_MS ? "spam_sender_timeout_1m" : "spam_sender_timeout_5m";
}

function sweepStates<K>(states: Map<K, SpamState>, windowMs: number, now: number): void {
  for (const [key, state] of states) {
    prepareState(state, windowMs, now);
    if (state.receivedAt.length === 0 && state.blockedUntil <= now && state.lastViolationAt === null) states.delete(key);
  }
}

function prune(history: number[], windowMs: number, now: number): void {
  let expired = 0;
  while (history[expired] !== undefined && history[expired]! <= now - windowMs) expired++;
  if (expired > 0) history.splice(0, expired);
}
