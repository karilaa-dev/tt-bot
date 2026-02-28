from media_types.errors import register_error_mapping

from .client import INSTAGRAM_URL_REGEX, InstagramClient
from .exceptions import (
    InstagramError,
    InstagramNetworkError,
    InstagramNotFoundError,
    InstagramRateLimitError,
)
from .models import InstagramMediaInfo, InstagramMediaItem

register_error_mapping(InstagramNotFoundError, "error_instagram_not_found")
register_error_mapping(InstagramNetworkError, "error_network")
register_error_mapping(InstagramRateLimitError, "error_rate_limit")

__all__ = [
    "InstagramClient",
    "INSTAGRAM_URL_REGEX",
    "InstagramMediaInfo",
    "InstagramMediaItem",
    "InstagramError",
    "InstagramNetworkError",
    "InstagramNotFoundError",
    "InstagramRateLimitError",
]
