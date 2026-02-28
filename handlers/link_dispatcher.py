import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.types import Message, ReactionTypeEmoji

from data.config import config, locale
from data.db_service import get_user_settings
from media_types import get_error_message
from misc.queue_manager import QueueManager
from misc.utils import start_manager, lang_func

from instagram_api import INSTAGRAM_URL_REGEX, InstagramError

logger = logging.getLogger(__name__)

link_router = Router(name=__name__)


class IsInstagramLink(Filter):
    async def __call__(self, message: Message) -> dict | bool:
        if not message.text:
            return False
        match = INSTAGRAM_URL_REGEX.search(message.text)
        if match:
            return {"instagram_url": match.group(0)}
        return False


@link_router.message(IsInstagramLink())
async def handle_instagram_message(
    message: Message, instagram_url: str
) -> None:
    from handlers.instagram import handle_instagram_link

    status_message = None
    group_chat = message.chat.type != "private"

    settings = await get_user_settings(message.chat.id)
    if not settings:
        lang = await lang_func(
            message.chat.id, message.from_user.language_code, True
        )
        file_mode = False
        await start_manager(message.chat.id, message, lang)
    else:
        lang, file_mode = settings

    queue = QueueManager.get_instance()
    queue_config = config["queue"]

    try:
        # Check per-user queue limit
        max_queue = queue_config["max_user_queue_size"]
        if max_queue > 0:
            user_queue_count = queue.get_user_queue_count(message.chat.id)
            if user_queue_count >= max_queue:
                if not group_chat:
                    await message.reply(
                        locale[lang]["error_queue_full"].format(
                            user_queue_count
                        )
                    )
                return

        # Send initial reaction
        try:
            await message.react(
                [ReactionTypeEmoji(emoji="👀")], disable_notification=True
            )
        except TelegramBadRequest:
            status_message = await message.reply(
                "⏳", disable_notification=True
            )

        # Acquire queue slot
        async with queue.info_queue(message.chat.id) as acquired:
            if not acquired:
                if status_message:
                    await status_message.delete()
                if not group_chat:
                    await message.reply(
                        locale[lang]["error_queue_full"].format(
                            queue.get_user_queue_count(message.chat.id)
                        )
                    )
                return

            try:
                await handle_instagram_link(
                    message, instagram_url, lang, file_mode, group_chat
                )
            except InstagramError as e:
                if status_message:
                    await status_message.delete()
                else:
                    try:
                        await message.react([ReactionTypeEmoji(emoji="😢")])
                    except TelegramBadRequest:
                        pass
                if not group_chat:
                    await message.reply(get_error_message(e, lang))
                return

        # Success - clear reaction
        if status_message:
            await status_message.delete()
        else:
            await message.react([])

    except Exception as e:
        logger.error(f"Instagram handler error: {e}", exc_info=True)
        try:
            if status_message:
                await status_message.delete()
            if not group_chat:
                await message.reply(locale[lang]["error"])
                if not status_message:
                    await message.react([ReactionTypeEmoji(emoji="😢")])
            else:
                if not status_message:
                    await message.react([ReactionTypeEmoji(emoji="😢")])
        except TelegramBadRequest:
            logger.debug("Failed to update UI during error cleanup")
        except Exception as cleanup_err:
            logger.warning(
                f"Unexpected error during cleanup: {cleanup_err}"
            )
