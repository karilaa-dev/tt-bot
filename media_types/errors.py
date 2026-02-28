from data.config import locale
from tiktok_api import (
    TikTokDeletedError,
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
)

_ERROR_MAP: dict[type, str] = {
    TikTokDeletedError: "error_deleted",
    TikTokPrivateError: "error_private",
    TikTokInvalidLinkError: "link_error",
    TikTokNetworkError: "error_network",
    TikTokRateLimitError: "error_rate_limit",
    TikTokRegionError: "error_region",
    TikTokVideoTooLongError: "error_too_long",
}

_DEFAULT_ERROR_KEY = "error"


def register_error_mapping(exception_type: type, locale_key: str) -> None:
    _ERROR_MAP[exception_type] = locale_key


def get_error_message(error: Exception, lang: str) -> str:
    lang_dict = locale.get(lang) or locale.get("en") or {}

    for exc_type, locale_key in _ERROR_MAP.items():
        if isinstance(error, exc_type):
            return lang_dict.get(locale_key, str(error))

    return lang_dict.get(_DEFAULT_ERROR_KEY, "An error occurred.")
