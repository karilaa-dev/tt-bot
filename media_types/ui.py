from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale

STATS_CALLBACK_PREFIX = "stats_noop"


def format_stat(value: int) -> str:
    if value >= 999_950:
        formatted = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}M"
    if value >= 1_000:
        formatted = f"{value / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{formatted}K"
    return str(value)


def stats_row(
    likes: int | None = None, views: int | None = None
) -> list[InlineKeyboardButton]:
    buttons: list[InlineKeyboardButton] = []
    if likes is not None:
        buttons.append(
            InlineKeyboardButton(
                text=f"❤️ {format_stat(likes)}", callback_data=STATS_CALLBACK_PREFIX
            )
        )
    if views is not None:
        buttons.append(
            InlineKeyboardButton(
                text=f"👁 {format_stat(views)}", callback_data=STATS_CALLBACK_PREFIX
            )
        )
    return buttons


def stats_keyboard(
    likes: int | None = None, views: int | None = None
) -> InlineKeyboardMarkup | None:
    row = stats_row(likes, views)
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


def music_button(
    video_id: int,
    lang: str,
    likes: int | None = None,
    views: int | None = None,
) -> InlineKeyboardMarkup:
    keyb = InlineKeyboardBuilder()
    row = stats_row(likes, views)
    for btn in row:
        keyb.add(btn)
    keyb.button(text=locale[lang]["get_sound"], callback_data=f"id/{video_id}")
    if row:
        keyb.adjust(len(row), 1)
    return keyb.as_markup()


def result_caption(lang: str, link: str, group_warning: bool | None = None) -> str:
    result = locale[lang]["result"].format(locale[lang]["bot_tag"], link)
    if group_warning:
        result += locale[lang]["group_warning"]
    return result
