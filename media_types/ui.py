from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from data.config import locale


def music_button(video_id: int, lang: str) -> InlineKeyboardMarkup:
    keyb = InlineKeyboardBuilder()
    keyb.button(text=locale[lang]["get_sound"], callback_data=f"id/{video_id}")
    return keyb.as_markup()


def result_caption(lang: str, link: str, group_warning: bool | None = None) -> str:
    result = locale[lang]["result"].format(locale[lang]["bot_tag"], link)
    if group_warning:
        result += locale[lang]["group_warning"]
    return result
