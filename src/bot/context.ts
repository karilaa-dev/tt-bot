import { Context } from "grammy";
import type { AppConfig } from "../config.ts";
import type { TtScrapClient } from "../clients/tt-scrap.ts";
import type { Database } from "../db/client.ts";
import type { QueueManager } from "../services/queue.ts";

export interface BotDependencies {
  config: AppConfig;
  db: Database;
  scrap: TtScrapClient;
  queue: QueueManager;
}

export class BotContext extends Context {
  declare config: AppConfig;
  declare db: Database;
  declare scrap: TtScrapClient;
  declare queue: QueueManager;
}
