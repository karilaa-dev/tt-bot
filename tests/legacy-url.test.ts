import { describe, expect, test } from "bun:test";
import { parseLegacyVideoIdentity } from "../src/db/legacy-url.ts";

describe("legacy URL identity parsing", () => {
  test.each([
    ["https://www.tiktok.com/@creator/video/123", "tiktok", "123", "video"],
    ["https://www.tiktok.com/@/video/130", "tiktok", "130", "video"],
    ["https://www.tiktok.com/@creator/photo/124", "tiktok", "124", "images"],
    ["https://m.tiktok.com/v/125.html?tracking=1", "tiktok", "125", "video"],
    ["https://www.tiktok.com/embed/v2/126", "tiktok", "126", "video"],
    ["https://www.tiktok.com/player/v1/127", "tiktok", "127", "video"],
    ["https://www.tiktok.com/share/video/128", "tiktok", "128", "video"],
    ["https://www.tiktok.com/?item_id=129", "tiktok", "129", null],
    ["https://www.instagram.com/p/ABC_1/", "instagram", "ABC_1", null],
    ["https://www.instagram.com/reels/XYZ-2/", "instagram", "XYZ-2", "video"],
  ])("parses %s", (url, platform, id, type) => {
    expect(parseLegacyVideoIdentity(url)).toMatchObject({ platform, platformVideoId: id, urlContentType: type, conflict: false });
  });

  test.each([
    "https://vm.tiktok.com/TOKEN/",
    "https://vt.tiktok.com/TOKEN/",
    "https://www.tiktok.com/t/TOKEN/",
  ])("never resolves redirect token %s", (url) => {
    expect(parseLegacyVideoIdentity(url).platformVideoId).toBeNull();
  });

  test("marks conflicting path and query IDs unresolved", () => {
    expect(parseLegacyVideoIdentity("https://www.tiktok.com/@creator/video/123?item_id=999"))
      .toMatchObject({ platform: null, platformVideoId: null, conflict: true });
  });
});
