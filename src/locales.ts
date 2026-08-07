import ar from "../locales/ar.json";
import en from "../locales/en.json";
import hi from "../locales/hi.json";
import id from "../locales/id.json";
import ru from "../locales/ru.json";
import so from "../locales/so.json";
import uk from "../locales/uk.json";
import vi from "../locales/vi.json";

export const locales = { ar, en, hi, id, ru, so, uk, vi } as const;
export type Language = keyof typeof locales;
export type LocaleKey = keyof typeof en;
export const languages = Object.keys(locales).sort() as Language[];

export function isLanguage(value: string | undefined | null): value is Language {
  return !!value && value in locales;
}

export function languageFromTelegram(value: string | undefined): Language {
  return isLanguage(value) ? value : "en";
}

export function text(lang: Language, key: LocaleKey): string {
  return locales[lang][key] ?? locales.en[key];
}
