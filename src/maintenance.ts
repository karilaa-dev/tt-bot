import { Bot } from "grammy";
import { loadConfig } from "./config.ts";
import { configureLogging, logger } from "./logging.ts";
import { languageFromTelegram, text } from "./locales.ts";

const config = loadConfig({ requireDatabase: false, requireTtScrap: false });
configureLogging(config.logLevel);
const bot = new Bot(config.botToken, { client: { apiRoot: config.telegramApiRoot } });
bot.on("message", async (ctx) => {
  if (ctx.chat.type !== "private") return;
  const lang = languageFromTelegram(ctx.from?.language_code);
  await ctx.reply(text(lang, "maintenance"), { parse_mode: "HTML" });
});
bot.catch((error) => logger.error("Maintenance bot error", error.error));
bot.start({ onStart: (info) => logger.info(`MAINTENANCE MODE: ${info.first_name} [@${info.username}, id:${info.id}]`) });
