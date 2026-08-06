import { describe, expect, test } from "bun:test";
import { formatStat, statsRow } from "../src/ui/stats.ts";
import { resultCaption } from "../src/ui/captions.ts";
import { PartialDeliveryError, TtScrapError } from "../src/bot/errors.ts";
import { errorText, shouldOfferRetry } from "../src/handlers/tiktok.ts";

describe("UI compatibility", () => {
  test("formats engagement counts at the existing thresholds", () => {
    expect(formatStat(999)).toBe("999"); expect(formatStat(1_000)).toBe("1K"); expect(formatStat(999_950)).toBe("1M");
    expect(statsRow(1234, 2)[0]?.callback_data).toBe("stats_noop");
  });
  test("retains source and group warning captions", () => {
    const caption = resultCaption("en", "https://www.tiktok.com/@a/video/1", true);
    expect(caption).toContain("Source"); expect(caption).toContain("first ten images");
  });
  test("escapes source links and distinguishes unsafe delivery retries", () => {
    expect(resultCaption("en", "https://example.test/a'b")).toContain("a&#39;b");
    const partial = new PartialDeliveryError(1, "request-1");
    const unknown = new TtScrapError("telegram_delivery_ambiguous", "unknown", "request-2", 502);
    expect(errorText(partial, "en")).toContain("Some media was delivered");
    expect(errorText(unknown, "en")).toContain("status is unknown");
    expect(shouldOfferRetry(partial)).toBe(false);
    expect(shouldOfferRetry(unknown)).toBe(false);
  });
});
