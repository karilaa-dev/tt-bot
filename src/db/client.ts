import { SQL } from "bun";
import { runMigrations, type RunMigrationsOptions } from "./migrations.ts";

export class Database {
  readonly sql: SQL;

  constructor(url: string, poolSize = 10) {
    this.sql = new SQL({ url, max: poolSize, idleTimeout: 30, connectionTimeout: 10, maxLifetime: 3_600 });
  }

  async initialize(options: RunMigrationsOptions = {}): Promise<void> {
    await runMigrations(this.sql, options);
  }

  async close(): Promise<void> {
    await this.sql.close();
  }
}
