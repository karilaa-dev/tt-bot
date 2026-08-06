export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";

export interface AppConfig {
  botToken: string;
  adminIds: Set<number>;
  secondAdminIds: Set<number>;
  joinLogs: number | string | null;
  storageChannelId: number | null;
  telegramApiRoot: string;
  databaseUrl: string;
  ttScrapBaseUrl: string;
  ttScrapApiKey: string;
  ttScrapRequestTimeoutMs: number;
  ttScrapDeliveryTimeoutMs: number;
  ttScrapInstagramDeliveryPath: string;
  maxUserQueueSize: number;
  maxGroupQueueSize: number;
  databasePoolSize: number;
  logLevel: LogLevel;
}

export interface LoadConfigOptions {
  requireDatabase?: boolean;
  requireTtScrap?: boolean;
}

function required(name: string): string {
  const value = Bun.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
}

function parseIds(name: string): Set<number> {
  const raw = Bun.env[name]?.trim();
  if (!raw) return new Set();
  let values: unknown;
  try {
    values = JSON.parse(raw);
  } catch {
    throw new Error(`${name} must be a JSON array of Telegram user IDs`);
  }
  if (!Array.isArray(values)) throw new Error(`${name} must be a JSON array`);
  const ids = values.map((value) => Number(value));
  if (ids.some((value) => !Number.isSafeInteger(value))) {
    throw new Error(`${name} contains an invalid Telegram user ID`);
  }
  return new Set(ids);
}

function parseInteger(name: string, fallback: number): number {
  const raw = Bun.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) throw new Error(`${name} must be an integer`);
  return value;
}

function parsePositiveInteger(name: string, fallback: number): number {
  const value = parseInteger(name, fallback);
  if (value <= 0) throw new Error(`${name} must be greater than zero`);
  return value;
}

function parseChat(name: string): number | string | null {
  const raw = Bun.env[name]?.trim();
  if (!raw || raw === "0") return null;
  if (raw.startsWith("@")) return raw;
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) throw new Error(`${name} must be a chat ID or @username`);
  return value;
}

function normalizeDatabaseUrl(url: string): string {
  const normalized = url.replace(/^postgresql\+asyncpg:\/\//, "postgresql://");
  let parsed: URL;
  try { parsed = new URL(normalized); }
  catch { throw new Error("DB_URL must be a valid PostgreSQL URL"); }
  if (!["postgresql:", "postgres:"].includes(parsed.protocol)) throw new Error("DB_URL must use PostgreSQL");
  return normalized;
}

function normalizeUrl(name: string, value: string): string {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error(`${name} must be a valid URL`);
  }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error(`${name} must use HTTP or HTTPS`);
  return value.replace(/\/+$/, "");
}

export function loadConfig(options: LoadConfigOptions = {}): AppConfig {
  const requireDatabase = options.requireDatabase ?? true;
  const requireTtScrap = options.requireTtScrap ?? true;
  const admins = parseIds("ADMIN_IDS");
  const secondAdmins = new Set([...admins, ...parseIds("SECOND_IDS")]);
  const storage = parseChat("STORAGE_CHANNEL_ID");
  if (typeof storage === "string") throw new Error("STORAGE_CHANNEL_ID must be numeric");
  const level = (Bun.env.LOG_LEVEL?.trim().toUpperCase() || "INFO") as LogLevel;
  if (!["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"].includes(level)) {
    throw new Error("LOG_LEVEL is invalid");
  }
  const instagramPath = Bun.env.TT_SCRAP_INSTAGRAM_DELIVERY_PATH?.trim() || "/v1/instagram/telegram-deliveries";
  if (!instagramPath.startsWith("/") || instagramPath.includes("://")) throw new Error("TT_SCRAP_INSTAGRAM_DELIVERY_PATH must be an absolute API path");
  const databaseUrl = requireDatabase ? normalizeDatabaseUrl(required("DB_URL")) : Bun.env.DB_URL?.trim() ? normalizeDatabaseUrl(Bun.env.DB_URL.trim()) : "";

  return {
    botToken: required("BOT_TOKEN"),
    adminIds: admins,
    secondAdminIds: secondAdmins,
    joinLogs: parseChat("JOIN_LOGS"),
    storageChannelId: storage,
    telegramApiRoot: normalizeUrl("TG_SERVER", Bun.env.TG_SERVER?.trim() || "https://api.telegram.org"),
    databaseUrl,
    ttScrapBaseUrl: normalizeUrl("TT_SCRAP_BASE_URL", Bun.env.TT_SCRAP_BASE_URL?.trim() || "http://127.0.0.1:8000"),
    ttScrapApiKey: requireTtScrap ? required("TT_SCRAP_API_KEY") : (Bun.env.TT_SCRAP_API_KEY?.trim() || ""),
    ttScrapRequestTimeoutMs: parsePositiveInteger("TT_SCRAP_REQUEST_TIMEOUT_SECONDS", 90) * 1000,
    ttScrapDeliveryTimeoutMs: parsePositiveInteger("TT_SCRAP_DELIVERY_TIMEOUT_SECONDS", 620) * 1000,
    ttScrapInstagramDeliveryPath: instagramPath,
    maxUserQueueSize: parsePositiveInteger("MAX_USER_QUEUE_SIZE", 3),
    maxGroupQueueSize: parsePositiveInteger("MAX_GROUP_QUEUE_SIZE", 10),
    databasePoolSize: parsePositiveInteger("DB_POOL_SIZE", 10),
    logLevel: level,
  };
}
