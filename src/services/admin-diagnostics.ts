import type { BotContext } from "../bot/context.ts";
import { TtScrapError } from "../bot/errors.ts";
import { logger } from "../logging.ts";
import { escapeHtml } from "../ui/captions.ts";

const MAX_DIAGNOSTIC_LENGTH = 3_900;

export async function sendAdminDiagnostic(ctx: BotContext, error: unknown): Promise<void> {
  const adminId = ctx.from?.id;
  if (adminId === undefined || !ctx.config.adminIds.has(adminId) || !(error instanceof Error)) return;

  const diagnostic = truncateDiagnostic(formatDiagnostic(error));
  try {
    await ctx.api.sendMessage(adminId, `<code>${escapeHtml(diagnostic)}</code>`, { parse_mode: "HTML" });
  } catch (sendError) {
    logger.warn(`Failed to send diagnostic privately to admin ${adminId}`, sendError);
  }
}

function formatDiagnostic(error: Error): string {
  const summary = `${error.name}: ${error.message}`;
  const request = error instanceof TtScrapError ? `\ncode=${error.code}\nrequest_id=${error.requestId}` : "";
  const stack = error.stack && !error.stack.startsWith(summary) ? `\n${error.stack}` : "";
  return `${summary}${request}${stack}`;
}

function truncateDiagnostic(value: string): string {
  if (value.length <= MAX_DIAGNOSTIC_LENGTH) return value;
  return `${value.slice(0, MAX_DIAGNOSTIC_LENGTH - 12)}\n…truncated`;
}
