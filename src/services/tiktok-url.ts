import { parsePublicUrl } from "../handlers/urls.ts";

/** Convert every locally ID-bearing TikTok route into a resolver-safe post URL. */
export function normalizeTikTokLookupUrl(link: string): string {
  const url = parsePublicUrl(link);
  if (!url || !isTikTokHost(url.hostname)) return link;
  const directPostMatch = url.pathname.match(/^\/@([^/]*)\/(video|photo)\/([0-9]+)\/?$/u);
  if (directPostMatch && !directPostMatch[1]) {
    return `https://www.tiktok.com/@_/${directPostMatch[2]}/${directPostMatch[3]}`;
  }
  const pathMatch = url.pathname.match(/^\/(?:v|embed(?:\/v2)?|player\/v1|share\/(?:video|item))\/([0-9]+)(?:\.html)?\/?$/u);
  const queryId = url.searchParams.get("item_id") ?? url.searchParams.get("share_item_id");
  const videoId = pathMatch?.[1] ?? (queryId && /^[0-9]+$/u.test(queryId) ? queryId : null);
  return videoId ? `https://www.tiktok.com/@_/video/${videoId}` : link;
}

export function isTikTokHost(hostname: string): boolean {
  const host = normalizedTikTokHost(hostname);
  return host === "tiktok.com" || host.endsWith(".tiktok.com");
}

export function normalizedTikTokHost(hostname: string): string {
  return hostname.replace(/\.$/u, "").toLowerCase();
}
