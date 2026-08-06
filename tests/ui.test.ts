import { describe, expect, test } from "bun:test";
import { formatStat, statsRow } from "../src/ui/stats.ts";
import { resultCaption } from "../src/ui/captions.ts";

describe("UI compatibility", () => {
  test("formats engagement counts at the existing thresholds", () => {
    expect(formatStat(999)).toBe("999"); expect(formatStat(1_000)).toBe("1K"); expect(formatStat(999_950)).toBe("1M");
    expect(statsRow(1234, 2)[0]?.callback_data).toBe("stats_noop");
  });
  test("retains source and group warning captions", () => {
    const caption = resultCaption("en", "https://www.tiktok.com/@a/video/1", true);
    expect(caption).toContain("Source"); expect(caption).toContain("first ten images");
  });
});
