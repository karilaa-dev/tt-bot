import { describe, expect, test } from "bun:test";
import { languages, locales } from "../src/locales.ts";

describe("locales", () => {
  test("all translations have the English key set", () => {
    const english = Object.keys(locales.en).sort();
    for (const lang of languages) expect(Object.keys(locales[lang]).sort()).toEqual(english);
  });
});
