import { Context } from "grammy";
import type { AppConfig } from "../config.ts";
import type { TtScrapClient } from "../clients/tt-scrap.ts";
import type { Database } from "../db/client.ts";
import { getUser, type UserRecord } from "../db/users.ts";
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
  declare onboardingSent: boolean;

  declare userRecords: Map<number, Promise<UserRecord | null>>;

  getUserRecord(userId = this.chat?.id ?? this.from?.id): Promise<UserRecord | null> {
    if (userId === undefined) return Promise.resolve(null);
    const cached = this.userRecords.get(userId);
    if (cached) return cached;
    const loaded = getUser(this.db, userId);
    this.userRecords.set(userId, loaded);
    void loaded.catch(() => {
      if (this.userRecords.get(userId) === loaded) this.userRecords.delete(userId);
    });
    return loaded;
  }

  cacheUserRecord(user: UserRecord): void {
    this.userRecords.set(user.userId, Promise.resolve(user));
  }
}
