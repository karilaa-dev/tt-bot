export interface LegacyVideoIdentity {
  platform: "tiktok" | "instagram" | null;
  platformVideoId: string | null;
  urlContentType: "video" | "images" | null;
  canonicalCandidate: string | null;
  conflict: boolean;
}

const unresolved = (): LegacyVideoIdentity => ({ platform: null, platformVideoId: null, urlContentType: null, canonicalCandidate: null, conflict: false });

/** Pure counterpart of the server-side migration parser, useful for fixtures and audits. */
export function parseLegacyVideoIdentity(value: string): LegacyVideoIdentity {
  let url: URL;
  try { url = new URL(value); } catch { return unresolved(); }
  if (url.protocol !== "http:" && url.protocol !== "https:") return unresolved();
  const host = url.hostname.replace(/\.$/u, "").toLowerCase();
  if (host === "tiktok.com" || host.endsWith(".tiktok.com")) return parseTikTok(url);
  if (host === "instagram.com" || host.endsWith(".instagram.com")) return parseInstagram(url);
  return unresolved();
}

function parseTikTok(url: URL): LegacyVideoIdentity {
  let pathId: string | null = null;
  let type: "video" | "images" | null = null;
  let match = url.pathname.match(/^\/@[^/]*\/(video|photo)\/([0-9]+)(?:\/|$)/iu);
  if (match) {
    type = match[1]?.toLowerCase() === "photo" ? "images" : "video";
    pathId = match[2] ?? null;
  } else if ((match = url.pathname.match(/^\/v\/([0-9]+)(?:\.html)?(?:\/|$)/iu))) {
    pathId = match[1] ?? null; type = "video";
  } else if ((match = url.pathname.match(/^\/embed\/(?:v2\/)?([0-9]+)(?:\/|$)/iu))) {
    pathId = match[1] ?? null; type = "video";
  } else if ((match = url.pathname.match(/^\/player\/v1\/([0-9]+)(?:\/|$)/iu))) {
    pathId = match[1] ?? null; type = "video";
  } else if ((match = url.pathname.match(/^\/share\/(video|item)\/([0-9]+)(?:\/|$)/iu))) {
    pathId = match[2] ?? null; type = match[1]?.toLowerCase() === "video" ? "video" : null;
  }
  const queryIds = [url.searchParams.get("item_id"), url.searchParams.get("share_item_id")]
    .filter((item): item is string => item !== null && /^[0-9]+$/u.test(item));
  const ids = new Set([pathId, ...queryIds].filter((item): item is string => item !== null));
  if (ids.size > 1) return { ...unresolved(), conflict: true };
  const id = ids.values().next().value as string | undefined;
  if (!id) return unresolved();
  return {
    platform: "tiktok", platformVideoId: id, urlContentType: type,
    canonicalCandidate: type ? `https://www.tiktok.com/@_/${type === "images" ? "photo" : "video"}/${id}` : null,
    conflict: false,
  };
}

function parseInstagram(url: URL): LegacyVideoIdentity {
  const match = url.pathname.match(/^\/(p|reel|reels|tv)\/([A-Za-z0-9_-]+)(?:\/|$)/iu);
  if (!match?.[1] || !match[2]) return unresolved();
  const route = match[1].toLowerCase();
  const normalizedRoute = route === "reels" ? "reel" : route;
  return {
    platform: "instagram", platformVideoId: match[2],
    urlContentType: normalizedRoute === "reel" || normalizedRoute === "tv" ? "video" : null,
    canonicalCandidate: `https://www.instagram.com/${normalizedRoute}/${match[2]}/`, conflict: false,
  };
}
