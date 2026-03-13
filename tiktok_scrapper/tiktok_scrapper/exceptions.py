"""TikTok API exception classes."""


class TikTokError(Exception):
    """Base exception for TikTok API errors."""


class TikTokDeletedError(TikTokError):
    """Video has been deleted by the creator."""


class TikTokPrivateError(TikTokError):
    """Video is private and cannot be accessed."""


class TikTokNetworkError(TikTokError):
    """Network error occurred during request."""


class TikTokRateLimitError(TikTokError):
    """Too many requests - rate limited."""


class TikTokRegionError(TikTokError):
    """Video is not available in the user's region (geo-blocked)."""


class TikTokExtractionError(TikTokError):
    """Generic extraction/parsing error (invalid ID, unknown failure, etc.)."""


class TikTokVideoTooLongError(TikTokError):
    """Video exceeds the maximum allowed duration."""


class TikTokInvalidLinkError(TikTokError):
    """TikTok link is invalid or expired (failed URL resolution)."""
