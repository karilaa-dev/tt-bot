import type { MessageEntity } from "grammy/types";

const urlPattern = /https?:\/\/[^\s<>"']+/giu;

export function urlCandidates(value: string, entities: readonly MessageEntity[] | undefined): string[] {
  const candidates: string[] = [];
  for (const match of value.matchAll(urlPattern)) candidates.push(trimTrailingPunctuation(match[0]));
  for (const entity of entities ?? []) {
    const candidate = entity.type === "text_link"
      ? entity.url
      : entity.type === "url"
        ? value.slice(entity.offset, entity.offset + entity.length)
        : null;
    if (candidate) candidates.push(trimTrailingPunctuation(candidate));
  }
  return [...new Set(candidates)];
}

export function parsePublicUrl(value: string): URL | null {
  if (value.length > 2_048) return null;
  let url: URL;
  try { url = new URL(value); }
  catch { return null; }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
  return url;
}

export function canonicalHttpsUrl(url: URL): string {
  const path = url.pathname.replace(/\/+$/, "");
  const host = url.hostname.replace(/\.$/u, "").toLowerCase();
  return `https://${host}${path}`;
}

function trimTrailingPunctuation(value: string): string {
  return value.replace(/[.,)\]}]+$/u, "");
}
