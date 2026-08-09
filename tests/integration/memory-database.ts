import type { Database } from "../../src/db/client.ts";
import type { DeliveryMode, DeliverySurface, MediaKind, TelegramFileReference, VideoPlatform } from "../../src/db/videos.ts";

export interface IntegrationHistoryRow {
  userId: number;
  detailsId: bigint;
  downloadedAt: number;
  sharedLink: string;
  mediaKind: MediaKind;
  deliverySurface: DeliverySurface;
  deliveryMode: DeliveryMode;
  cacheHit: boolean;
}

export interface IntegrationDetailsRow {
  pk_id: bigint;
  platform: VideoPlatform;
  platform_video_id: string;
  creator_username: string | null;
  content_type: string | null;
  canonical_link: string | null;
  telegram_bot_id: bigint | null;
  telegram_files: TelegramFileReference[] | null;
  likes_display: string | null;
  views_display: string | null;
  first_downloaded_at: number | null;
  last_used_at: number | null;
  metadata_refreshed_at: number | null;
  file_ids_updated_at: number | null;
  cache_version: bigint;
}

interface IntegrationUserRow {
  user_id: number;
  registered_at: number;
  lang: string;
  link: string | null;
  file_mode: boolean;
}

export class IntegrationMemoryDatabase {
  readonly db: Database;
  readonly history: IntegrationHistoryRow[] = [];
  readonly users = new Map<number, IntegrationUserRow>();
  readonly details = new Map<string, IntegrationDetailsRow>();
  invalidations = 0;
  private nextDetailsId = 1n;

  constructor() {
    const sql = async (strings: TemplateStringsArray, ...values: unknown[]): Promise<unknown[]> => {
      const query = strings.join("?").replace(/\s+/gu, " ").trim();
      if (query.startsWith("SELECT user_id, registered_at, lang, link, file_mode FROM users")) {
        const user = this.users.get(Number(values[0]));
        return user ? [user] : [];
      }
      if (query.startsWith("INSERT INTO users")) {
        const userId = Number(values[0]);
        if (this.users.has(userId)) return [];
        const row: IntegrationUserRow = {
          user_id: userId,
          registered_at: Number(values[1]),
          lang: String(values[2]),
          link: values[3] === null ? null : String(values[3]),
          file_mode: false,
        };
        this.users.set(userId, row);
        return [row];
      }
      if (query.startsWith("SELECT * FROM video_details")) {
        const row = this.details.get(key(String(values[0]), String(values[1])));
        return row ? [row] : [];
      }
      if (query.startsWith("UPDATE video_details SET telegram_bot_id = NULL")) {
        const expectedId = BigInt(String(values[0]));
        const expectedVersion = BigInt(String(values[1]));
        const row = [...this.details.values()].find((candidate) => candidate.pk_id === expectedId);
        if (!row || row.cache_version !== expectedVersion) return [];
        row.telegram_bot_id = null;
        row.telegram_files = null;
        row.file_ids_updated_at = null;
        row.cache_version++;
        this.invalidations++;
        return [{ pk_id: row.pk_id }];
      }
      if (query.startsWith("INSERT INTO video_details")) {
        const platform = String(values[0]) as VideoPlatform;
        const platformVideoId = String(values[1]);
        const rowKey = key(platform, platformVideoId);
        const existing = this.details.get(rowKey);
        const hasFiles = values[6] !== null;
        const updatesLikes = Boolean(values[16]);
        const updatesViews = Boolean(values[17]);
        const updatesMetadata = Boolean(values[18]);
        const files = hasFiles ? decodeFiles(values[6]) : existing?.telegram_files ?? null;
        const row: IntegrationDetailsRow = {
          pk_id: existing?.pk_id ?? this.nextDetailsId++,
          platform,
          platform_video_id: platformVideoId,
          creator_username: nullableString(values[2]) ?? existing?.creator_username ?? null,
          content_type: nullableString(values[3]) ?? existing?.content_type ?? null,
          canonical_link: nullableString(values[4]) ?? existing?.canonical_link ?? null,
          telegram_bot_id: hasFiles ? nullableBigInt(values[5]) : existing?.telegram_bot_id ?? null,
          telegram_files: files,
          likes_display: updatesLikes ? nullableString(values[7]) : existing?.likes_display ?? nullableString(values[7]),
          views_display: updatesViews ? nullableString(values[8]) : existing?.views_display ?? nullableString(values[8]),
          first_downloaded_at: existing?.first_downloaded_at ?? Number(values[9]),
          last_used_at: Number(values[10]),
          metadata_refreshed_at: updatesMetadata ? nullableNumber(values[11]) : existing?.metadata_refreshed_at ?? nullableNumber(values[11]),
          file_ids_updated_at: hasFiles ? nullableNumber(values[12]) : existing?.file_ids_updated_at ?? null,
          cache_version: (existing?.cache_version ?? 0n) + (hasFiles ? 1n : 0n),
        };
        this.details.set(rowKey, row);
        return [row];
      }
      if (query.startsWith("INSERT INTO videos")) {
        this.history.push({
          userId: Number(values[0]),
          detailsId: BigInt(String(values[1])),
          downloadedAt: Number(values[2]),
          sharedLink: String(values[3]),
          mediaKind: String(values[4]) as MediaKind,
          deliverySurface: String(values[5]) as DeliverySurface,
          deliveryMode: String(values[6]) as DeliveryMode,
          cacheHit: Boolean(values[7]),
        });
        return [];
      }
      throw new Error(`Unexpected integration-memory SQL query: ${query}`);
    };
    Object.assign(sql, { begin: async (operation: (transaction: typeof sql) => Promise<unknown>) => operation(sql) });
    this.db = { sql } as unknown as Database;
  }

  seedUser(userId: number, fileMode = false): void {
    this.users.set(userId, { user_id: userId, registered_at: 1, lang: "en", link: null, file_mode: fileMode });
  }

  setFileMode(userId: number, fileMode: boolean): void {
    const user = this.users.get(userId);
    if (!user) throw new Error(`Integration user ${userId} is not registered`);
    user.file_mode = fileMode;
  }

  detailsFor(platform: VideoPlatform, platformVideoId: string): IntegrationDetailsRow | null {
    return this.details.get(key(platform, platformVideoId)) ?? null;
  }
}

function key(platform: string, platformVideoId: string): string {
  return `${platform}:${platformVideoId}`;
}

function decodeFiles(value: unknown): TelegramFileReference[] | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Uint8Array) return JSON.parse(new TextDecoder().decode(value)) as TelegramFileReference[];
  if (typeof value === "string") return JSON.parse(value) as TelegramFileReference[];
  return value as TelegramFileReference[];
}

function nullableString(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}

function nullableNumber(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}

function nullableBigInt(value: unknown): bigint | null {
  return value === null || value === undefined ? null : BigInt(String(value));
}
