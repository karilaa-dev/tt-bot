"""TikTok API exception classes."""


class TikTokError(Exception):
    """Base exception for TikTok API errors."""

    pass


class TikTokDeletedError(TikTokError):
    """Video has been deleted by the creator."""

    pass


class TikTokPrivateError(TikTokError):
    """Video is private and cannot be accessed."""

    pass


class TikTokNetworkError(TikTokError):
    """Network error occurred during request."""

    pass


class TikTokRateLimitError(TikTokError):
    """Too many requests - rate limited."""

    pass


class TikTokRegionError(TikTokError):
    """Video is not available in the user's region (geo-blocked)."""

    pass


class TikTokExtractionError(TikTokError):
    """Generic extraction/parsing error (invalid ID, unknown failure, etc.)."""

    pass


class TikTokVideoTooLongError(TikTokError):
    """Video exceeds the maximum allowed duration."""

    pass


class TikTokInvalidLinkError(TikTokError):
    """Invalid or unrecognized TikTok video link."""

    pass
