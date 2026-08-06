import type { Language } from "../locales.ts";
import { text } from "../locales.ts";

export function resultCaption(lang: Language, link: string, groupWarning = false): string {
  let result = text(lang, "result").replace("{0}", text(lang, "bot_tag")).replace("{1}", link);
  if (groupWarning) result += text(lang, "group_warning");
  return result;
}

export function storageCaption(link: string, userId?: number, username?: string, fullName?: string): string {
  const parts = [`<a href='${escapeAttribute(link)}'>Source</a>`];
  if (userId) {
    parts.push("", `<b><a href="tg://user?id=${userId}">${escapeHtml(fullName || "User")}</a></b>`);
    if (username) parts.push(`@${escapeHtml(username)}`);
    parts.push(`<code>${userId}</code>`);
  }
  return parts.join("\n");
}

export function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
function escapeAttribute(value: string): string { return escapeHtml(value).replaceAll("'", "&#39;").replaceAll('"', "&quot;"); }
