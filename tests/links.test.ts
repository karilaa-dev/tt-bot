import { expect, test } from "bun:test";
import type { MessageEntity } from "grammy/types";
import { findInstagramUrl } from "../src/handlers/links.ts";
import { findTikTokUrl } from "../src/handlers/tiktok.ts";

test("routes direct and embedded TikTok links", () => {
  expect(findTikTokUrl("watch https://www.tiktok.com/@creator/video/7669880788879543583)."))
    .toBe("https://www.tiktok.com/@creator/video/7669880788879543583");
  const entities: MessageEntity[] = [{ type: "text_link", offset: 0, length: 5, url: "https://vm.tiktok.com/ZTest/" }];
  expect(findTikTokUrl("watch", entities)).toBe("https://vm.tiktok.com/ZTest/");
  expect(findTikTokUrl("https://example.com/video/1")).toBeNull();
});

test("routes direct and embedded Instagram links", () => {
  expect(findInstagramUrl("https://www.instagram.com/reel/ABC_123/)."))
    .toBe("https://www.instagram.com/reel/ABC_123");
  const entities: MessageEntity[] = [{ type: "text_link", offset: 0, length: 4, url: "https://instagram.com/p/POST-ID/" }];
  expect(findInstagramUrl("open", entities)).toBe("https://instagram.com/p/POST-ID");
});
