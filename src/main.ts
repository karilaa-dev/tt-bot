import { run } from "@grammyjs/runner";
import { createBot } from "./bot/create-bot.ts";
import { loadConfig } from "./config.ts";
import { TtScrapClient } from "./clients/tt-scrap.ts";
import { Database } from "./db/client.ts";
import { cleanupInlineSlideshows } from "./handlers/inline-slideshow.ts";
import { configureLogging, logger } from "./logging.ts";
import { QueueManager } from "./services/queue.ts";

const config = loadConfig();
configureLogging(config.logLevel);
const db = new Database(config.databaseUrl);
await db.initialize();
const scrap = new TtScrapClient(config);
if (!await scrap.healthReady()) logger.warn(`tt-scrap is not ready at ${config.ttScrapBaseUrl}; media requests will fail until it recovers`);
const bot = createBot({ config, db, scrap, queue: new QueueManager(config.maxUserQueueSize) });
await bot.init();
logger.info(`${bot.botInfo.first_name} [@${bot.botInfo.username}, id:${bot.botInfo.id}]`);
const runner = run(bot, {
  runner: {
    fetch: {
      allowed_updates: ["message", "callback_query", "inline_query", "chosen_inline_result"],
    },
  },
});
let stopping = false;
async function shutdown(signal: string): Promise<void> {
  if (stopping) return; stopping = true;
  logger.info(`Received ${signal}; stopping bot`);
  await runner.stop();
  cleanupInlineSlideshows();
  await db.close();
}
process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));
await runner.task();
