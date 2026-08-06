import { SQL } from "bun";
import { runMigrations } from "./migrations.ts";

export class Database {
  readonly sql: SQL;

  constructor(url: string) {
    this.sql = new SQL({ url, max: 20, idleTimeout: 30, connectionTimeout: 30 });
  }

  async initialize(): Promise<void> {
    await runMigrations(this.sql);
  }

  async close(): Promise<void> {
    await this.sql.close();
  }
}
