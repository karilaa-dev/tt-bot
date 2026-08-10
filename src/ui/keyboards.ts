import { InlineKeyboard } from "grammy";
import type { Language } from "../locales.ts";
import { languages, locales, text } from "../locales.ts";
import { statsRow } from "./stats.ts";
import type { DisplayStat } from "./stats.ts";

export function languageKeyboard(): InlineKeyboard {
  const keyboard = new InlineKeyboard();
  languages.forEach((lang, index) => {
    keyboard.text(locales[lang].lang_name, `lang/${lang}`);
    if (index % 2 === 1 && index < languages.length - 1) keyboard.row();
  });
  return keyboard;
}

export function statsKeyboard(likes?: DisplayStat | null, views?: DisplayStat | null): InlineKeyboard | undefined {
  const row = statsRow(likes, views);
  if (!row.length) return undefined;
  const keyboard = new InlineKeyboard();
  for (const button of row) keyboard.text(button.text, button.callback_data);
  return keyboard;
}

export function musicKeyboard(videoId: string, lang: Language, likes?: DisplayStat | null, views?: DisplayStat | null): InlineKeyboard {
  const keyboard = new InlineKeyboard();
  const row = statsRow(likes, views);
  for (const button of row) keyboard.text(button.text, button.callback_data);
  if (row.length) keyboard.row();
  return keyboard.text(text(lang, "get_sound"), `id/${videoId}`);
}

export function retryKeyboard(lang: Language): InlineKeyboard {
  return new InlineKeyboard().text(text(lang, "try_again_button"), "retry_video");
}

export const loadingKeyboard = new InlineKeyboard().text("⏳", "loading");
