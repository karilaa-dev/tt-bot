import { expect, test } from "bun:test";
import type { MessageEntity } from "grammy/types";
import { compressInlineRetryLink, inlineRetryCallbackData } from "../src/handlers/inline.ts";
import { findInstagramUrl } from "../src/handlers/links.ts";
import { findTikTokUrl, tikTokExtractionUrl } from "../src/handlers/tiktok.ts";

test("routes all TikTok-owned link formats", () => {
  const supported = [
    ["https://www.tiktok.com/@creator/video/7669880788879543583?is_from_webapp=1", "https://www.tiktok.com/@creator/video/7669880788879543583"],
    ["https://tiktok.com/@creator/photo/7669880788879543583/", "https://tiktok.com/@creator/photo/7669880788879543583"],
    ["https://m.tiktok.com/v/7669880788879543583.html", "https://m.tiktok.com/v/7669880788879543583.html"],
    ["https://www.tiktok.com/embed/7669880788879543583", "https://www.tiktok.com/embed/7669880788879543583"],
    ["https://www.tiktok.com/embed/v2/7669880788879543583", "https://www.tiktok.com/embed/v2/7669880788879543583"],
    ["https://www.tiktok.com/player/v1/7669880788879543583?controls=0", "https://www.tiktok.com/player/v1/7669880788879543583"],
    ["https://www.tiktok.com/share/video/7669880788879543583", "https://www.tiktok.com/share/video/7669880788879543583"],
    ["https://www.tiktok.com/t/ZTest/", "https://www.tiktok.com/t/ZTest"],
    ["https://www.tiktok.com/?item_id=7669880788879543583", "https://www.tiktok.com/@_/video/7669880788879543583"],
    ["https://vm.tiktok.com/ZTest/", "https://vm.tiktok.com/ZTest"],
    ["https://vt.tiktok.com/ZTest/", "https://vt.tiktok.com/ZTest"],
  ] as const;
  for (const [input, expected] of supported) expect(findTikTokUrl(`watch ${input}).`)).toBe(expected);

  const entities: MessageEntity[] = [{ type: "text_link", offset: 0, length: 5, url: "https://vm.tiktok.com/ZTest/" }];
  expect(findTikTokUrl("watch", entities)).toBe("https://vm.tiktok.com/ZTest");
  expect(findTikTokUrl("https://www.tiktok.com/")).toBeNull();
  expect(findTikTokUrl("https://example.com/video/1")).toBeNull();
  expect(findTikTokUrl("https://evil.example/path/tiktok.com/video/1")).toBeNull();
  expect(findTikTokUrl("https://evil-tiktok.com/video/1")).toBeNull();
  expect(findTikTokUrl("https://tiktok.com.evil.example/video/1")).toBeNull();
  expect(findTikTokUrl("https://user:password@www.tiktok.com/@creator/video/1")).toBeNull();
  for (const nonPost of [
    "https://www.tiktok.com/@creator",
    "https://www.tiktok.com/legal/privacy-policy",
    "https://www.tiktok.com/discover/example",
    "https://www.tiktok.com/music/example-123",
    "https://newsroom.tiktok.com/example",
  ]) expect(findTikTokUrl(nonPost)).toBeNull();
});

test("inline TikTok retries retain a valid placeholder username", () => {
  const compressed = compressInlineRetryLink("https://www.tiktok.com/@creator/video/7669880788879543583", false);
  expect(compressed).toBe("www.tiktok.com/@user/video/7669880788879543583");
  expect(findTikTokUrl(`https://${compressed}`)).toBe("https://www.tiktok.com/@user/video/7669880788879543583");
  const callback = inlineRetryCallbackData(`https://${compressed}`, false, 123456789);
  expect(callback).toBe(`ir:tt:${(123456789).toString(36)}:${compressed}`);
  expect(callback!.length).toBeLessThanOrEqual(64);
});

test("normalizes ID-bearing legacy and embed routes for extraction", () => {
  for (const link of [
    "https://m.tiktok.com/v/7669880788879543583.html",
    "https://www.tiktok.com/embed/7669880788879543583",
    "https://www.tiktok.com/embed/v2/7669880788879543583",
    "https://www.tiktok.com/player/v1/7669880788879543583",
    "https://www.tiktok.com/share/video/7669880788879543583",
    "https://www.tiktok.com/share/item/7669880788879543583",
  ]) expect(tikTokExtractionUrl(link)).toBe("https://www.tiktok.com/@_/video/7669880788879543583");
  expect(tikTokExtractionUrl("https://vm.tiktok.com/ZTest")).toBe("https://vm.tiktok.com/ZTest");
});

test("routes direct and embedded Instagram links", () => {
  expect(findInstagramUrl("https://www.instagram.com/reel/ABC_123/)."))
    .toBe("https://www.instagram.com/reel/ABC_123");
  const entities: MessageEntity[] = [{ type: "text_link", offset: 0, length: 4, url: "https://instagram.com/p/POST-ID/" }];
  expect(findInstagramUrl("open", entities)).toBe("https://instagram.com/p/POST-ID");
  expect(findInstagramUrl("https://instagram.com/stories/creator/123456789/")).toBeNull();
});
