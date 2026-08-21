import { run } from "@grammyjs/runner";
import { createBot } from "./bot/create-bot.ts";
import { loadConfig } from "./config.ts";
import { TtScrapClient } from "./clients/tt-scrap.ts";
import { Database } from "./db/client.ts";
import { cleanupInlineSlideshows } from "./handlers/inline-slideshow.ts";
import { configureLogging, logger } from "./logging.ts";
import { QueueManager } from "./services/queue.ts";

export interface RunBotOptions {
  allowLegacyMigration?: boolean;
  /** A rejection is fatal; successful background work leaves the bot running. */
  backgroundTasks?: Promise<unknown>[];
  /** Ask background work to stop before closing shared process resources. */
  onShutdown?: () => void;
}

export async function runBot(options: RunBotOptions = {}): Promise<void> {
  const config = loadConfig();
  configureLogging(config.logLevel);
  const db = new Database(config.databaseUrl, config.databasePoolSize);
  await db.initialize({ allowLegacyMigration: options.allowLegacyMigration });
  const scrap = new TtScrapClient(config);
  if (!await scrap.healthReady()) logger.warn(`tt-scrap is not ready at ${config.ttScrapBaseUrl}; media requests will fail until it recovers`);
  const queue = new QueueManager(config.maxUserQueueSize, config.maxGroupQueueSize, config.maxActiveJobs);
  const bot = createBot({ config, db, scrap, queue });
  await bot.init();
  await bot.api.deleteWebhook({ drop_pending_updates: true });
  logger.info(`${bot.botInfo.first_name} [@${bot.botInfo.username}, id:${bot.botInfo.id}]`);
  const runner = run(bot, {
    runner: {
      fetch: {
        allowed_updates: ["message", "callback_query", "inline_query", "chosen_inline_result"],
      },
    },
  });
  let shutdownPromise: Promise<void> | null = null;
  let shutdownNotified = false;
  function notifyShutdown(): void {
    if (shutdownNotified) return;
    shutdownNotified = true;
    options.onShutdown?.();
  }
  async function shutdown(reason: string): Promise<void> {
    logger.info(`Received ${reason}; stopping bot`);
    queue.shutdown();
    await Promise.all([runner.stop(), queue.waitForIdle()]);
    cleanupInlineSlideshows();
    await db.close();
  }
  function requestShutdown(reason: string): void {
    notifyShutdown();
    shutdownPromise ??= shutdown(reason);
  }
  process.once("SIGINT", () => requestShutdown("SIGINT"));
  process.once("SIGTERM", () => requestShutdown("SIGTERM"));
  const runnerTask = runner.task();
  const backgroundFailures = (options.backgroundTasks ?? []).map((task) => {
    const failure = task.then(
      () => new Promise<never>(() => undefined),
      (error) => Promise.reject(error),
    );
    // Promise.race observes these during normal serving. Keep an explicit
    // terminal handler for a late rejection after shutdown (or no runner task).
    void failure.catch(() => undefined);
    return failure;
  });
  try {
    if (runnerTask) await Promise.race([runnerTask, ...backgroundFailures]);
  } catch (error) {
    logger.error("Fatal background task failure", error);
    requestShutdown("background task failure");
    await shutdownPromise;
    throw error;
  }
  if (shutdownPromise) await shutdownPromise;
  else {
    notifyShutdown();
    queue.shutdown();
    cleanupInlineSlideshows();
    await db.close();
  }
}

if (import.meta.main) await runBot();
