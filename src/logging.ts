import type { LogLevel } from "./config.ts";

const weights: Record<LogLevel, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
let threshold = weights.INFO;

export function configureLogging(level: LogLevel): void {
  threshold = weights[level];
}

function write(level: LogLevel, message: string, details?: unknown): void {
  if (weights[level] < threshold) return;
  const prefix = `${new Date().toISOString()} [${level.padEnd(8)}] ${message}`;
  const output = details === undefined ? prefix : `${prefix} ${safeDetails(details)}`;
  if (weights[level] >= weights.ERROR) console.error(output);
  else console.log(output);
}

function safeDetails(details: unknown): string {
  let raw: string;
  if (details instanceof Error) {
    const diagnostic = details as Error & { requestId?: unknown; ttScrapRequestId?: unknown };
    const requestId = typeof diagnostic.requestId === "string" ? diagnostic.requestId : typeof diagnostic.ttScrapRequestId === "string" ? diagnostic.ttScrapRequestId : null;
    raw = `${details.name}: ${details.message}${requestId ? ` request_id=${requestId}` : ""}`;
  } else raw = JSON.stringify(details);
  return (raw || String(details))
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [REDACTED]")
    .replace(/\b\d{6,12}:[A-Za-z0-9_-]{20,}\b/g, "[BOT_TOKEN_REDACTED]");
}

export const logger = {
  debug: (message: string, details?: unknown) => write("DEBUG", message, details),
  info: (message: string, details?: unknown) => write("INFO", message, details),
  warn: (message: string, details?: unknown) => write("WARNING", message, details),
  error: (message: string, details?: unknown) => write("ERROR", message, details),
};
