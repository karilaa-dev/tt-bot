import type { AppConfig } from "../src/config.ts";

export function testConfig(baseUrl: string): AppConfig {
  return {
    botToken: "123456:test-token-value-that-is-long-enough",
    adminIds: new Set(), joinLogs: null, storageChannelId: -100123,
    telegramApiRoot: "https://api.telegram.org", databaseUrl: "postgresql://postgres:postgres@db/test",
    ttScrapBaseUrl: baseUrl, ttScrapApiKey: "test-api-key-that-is-long-enough",
    ttScrapRequestTimeoutMs: 2_000, ttScrapDeliveryTimeoutMs: 2_000,
    maxUserQueueSize: 3, maxGroupQueueSize: 10, maxActiveJobs: 25, databasePoolSize: 10, logLevel: "ERROR",
  };
}
