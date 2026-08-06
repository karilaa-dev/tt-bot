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
const db = new Database(config.databaseUrl, config.databasePoolSize);
await db.initialize();
const scrap = new TtScrapClient(config);
if (!await scrap.healthReady()) logger.warn(`tt-scrap is not ready at ${config.ttScrapBaseUrl}; media requests will fail until it recovers`);
const queue = new QueueManager(config.maxUserQueueSize, config.maxGroupQueueSize, config.maxActiveJobs);
const bot = createBot({ config, db, scrap, queue });
await bot.init();
logger.info(`${bot.botInfo.first_name} [@${bot.botInfo.username}, id:${bot.botInfo.id}]`);
const runner = run(bot, {
  runner: {
    fetch: {
      allowed_updates: ["message", "callback_query", "inline_query", "chosen_inline_result"],
    },
  },
});
let shutdownPromise: Promise<void> | null = null;
async function shutdown(signal: string): Promise<void> {
  logger.info(`Received ${signal}; stopping bot`);
  queue.shutdown();
  const forceExit = setTimeout(() => {
    logger.error("Graceful shutdown exceeded 15 seconds; forcing exit");
    process.exit(0);
  }, 15_000);
  try {
    await runner.stop();
    cleanupInlineSlideshows();
    await db.close();
  } finally {
    clearTimeout(forceExit);
  }
}
function requestShutdown(signal: string): void {
  shutdownPromise ??= shutdown(signal);
}
process.once("SIGINT", () => requestShutdown("SIGINT"));
process.once("SIGTERM", () => requestShutdown("SIGTERM"));
const runnerTask = runner.task();
if (runnerTask) await runnerTask;
if (shutdownPromise) await shutdownPromise;
else {
  queue.shutdown();
  cleanupInlineSlideshows();
  await db.close();
}
