import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { loadConfig } from "../src/config.ts";

const names = ["BOT_TOKEN", "DB_URL", "TT_SCRAP_API_KEY", "ADMIN_IDS", "TG_SERVER", "TT_SCRAP_BASE_URL", "TT_SCRAP_REQUEST_TIMEOUT_SECONDS", "TT_SCRAP_INSTAGRAM_DELIVERY_PATH", "MAX_USER_QUEUE_SIZE", "MAX_GROUP_QUEUE_SIZE", "MAX_ACTIVE_JOBS", "DB_POOL_SIZE"];
const saved = new Map<string, string | undefined>();
beforeEach(() => { for (const name of names) saved.set(name, Bun.env[name]); Bun.env.BOT_TOKEN = "123:test"; Bun.env.DB_URL = "postgresql://u:p@db/x"; Bun.env.TT_SCRAP_API_KEY = "1234567890abcdef"; Bun.env.ADMIN_IDS = "[1]"; Bun.env.TG_SERVER = "https://api.telegram.org"; Bun.env.TT_SCRAP_BASE_URL = "http://127.0.0.1:8000"; Bun.env.MAX_USER_QUEUE_SIZE = "3"; Bun.env.MAX_GROUP_QUEUE_SIZE = "10"; Bun.env.DB_POOL_SIZE = "10"; });
afterEach(() => { for (const [name, value] of saved) { if (value === undefined) delete Bun.env[name]; else Bun.env[name] = value; } });

describe("loadConfig", () => {
  test("validates the PostgreSQL URL and administrator IDs", () => {
    const config = loadConfig();
    expect(config.databaseUrl).toBe("postgresql://u:p@db/x");
    expect(config.adminIds).toEqual(new Set([1]));
    expect(config.ttScrapBaseUrl).toBe("http://127.0.0.1:8000");
    expect([config.maxUserQueueSize, config.maxGroupQueueSize, config.maxActiveJobs, config.databasePoolSize]).toEqual([3, 10, 25, 10]);
  });
  test("requires secrets", () => { delete Bun.env.TT_SCRAP_API_KEY; expect(() => loadConfig()).toThrow("TT_SCRAP_API_KEY is required"); });
  test("rejects disabled queue limits", () => {
    Bun.env.MAX_USER_QUEUE_SIZE = "0";
    expect(() => loadConfig()).toThrow("greater than zero");
    Bun.env.MAX_USER_QUEUE_SIZE = "3";
    Bun.env.MAX_GROUP_QUEUE_SIZE = "0";
    expect(() => loadConfig()).toThrow("greater than zero");
    Bun.env.MAX_GROUP_QUEUE_SIZE = "10";
    Bun.env.MAX_ACTIVE_JOBS = "0";
    expect(() => loadConfig()).toThrow("greater than zero");
  });
  test("rejects removed database driver URL schemes", () => {
    Bun.env.DB_URL = "postgresql+asyncpg://u:p@db/x";
    expect(() => loadConfig()).toThrow("DB_URL must use PostgreSQL");
  });
  test("rejects invalid timeout and endpoint values", () => {
    Bun.env.TT_SCRAP_REQUEST_TIMEOUT_SECONDS = "0";
    expect(() => loadConfig()).toThrow("greater than zero");
    Bun.env.TT_SCRAP_REQUEST_TIMEOUT_SECONDS = "90";
    Bun.env.TT_SCRAP_INSTAGRAM_DELIVERY_PATH = "https://unexpected.example/delivery";
    expect(() => loadConfig()).toThrow("absolute API path");
  });
});
