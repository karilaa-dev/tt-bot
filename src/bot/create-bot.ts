import { Bot, GrammyError, HttpError } from "grammy";
import { BotContext, type BotDependencies } from "./context.ts";
import { logger } from "../logging.ts";
import { registerUserHandlers } from "../handlers/user.ts";
import { registerLanguageHandlers } from "../handlers/language.ts";
import { registerAdminHandlers } from "../handlers/admin.ts";
import { registerLinkHandlers } from "../handlers/links.ts";
import { registerTikTokHandlers } from "../handlers/tiktok.ts";
import { registerMusicHandlers } from "../handlers/music.ts";
import { registerInlineHandlers } from "../handlers/inline.ts";
import { registerInlineSlideshowHandlers } from "../handlers/inline-slideshow.ts";
import { registerUnsupportedHandlers } from "../handlers/unsupported.ts";
import { ensurePrivateRegistration } from "../services/registration.ts";

export function createBot(deps: BotDependencies): Bot<BotContext> {
  const bot = new Bot<BotContext>(deps.config.botToken, {
    ContextConstructor: BotContext,
    client: { apiRoot: deps.config.telegramApiRoot, timeoutSeconds: 500 },
  });
  bot.use(async (ctx, next) => {
    ctx.config = deps.config; ctx.db = deps.db; ctx.scrap = deps.scrap; ctx.queue = deps.queue;
    ctx.userRecords = new Map();
    await ensurePrivateRegistration(ctx);
    await next();
  });
  registerUserHandlers(bot);
  registerLanguageHandlers(bot);
  registerAdminHandlers(bot);
  registerLinkHandlers(bot);
  registerTikTokHandlers(bot);
  registerMusicHandlers(bot);
  registerInlineHandlers(bot);
  registerInlineSlideshowHandlers(bot);
  registerUnsupportedHandlers(bot);
  bot.catch((error) => {
    if (error.error instanceof GrammyError) logger.error(`Telegram API error in update ${error.ctx.update.update_id}`, error.error);
    else if (error.error instanceof HttpError) logger.error(`Telegram transport error in update ${error.ctx.update.update_id}`, error.error);
    else logger.error(`Unhandled bot error in update ${error.ctx.update.update_id}`, error.error);
  });
  return bot;
}
