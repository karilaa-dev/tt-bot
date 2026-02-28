class InstagramError(Exception):
    """Base exception for Instagram API errors."""


class InstagramNetworkError(InstagramError):
    """Network or connection error when calling the API."""


class InstagramNotFoundError(InstagramError):
    """Post not found, deleted, or private."""


class InstagramRateLimitError(InstagramError):
    """API rate limit exceeded."""
