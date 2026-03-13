"""Scraper exception classes (service-agnostic)."""


class ScraperError(Exception):
    """Base exception for all scraper errors."""


class ContentDeletedError(ScraperError):
    """Content has been deleted by the creator."""


class ContentPrivateError(ScraperError):
    """Content is private and cannot be accessed."""


class NetworkError(ScraperError):
    """Network error occurred during request."""


class RateLimitError(ScraperError):
    """Too many requests - rate limited."""


class RegionBlockedError(ScraperError):
    """Content is not available in the user's region (geo-blocked)."""


class ExtractionError(ScraperError):
    """Generic extraction/parsing error (invalid ID, unknown failure, etc.)."""


class ContentTooLongError(ScraperError):
    """Content exceeds the maximum allowed duration."""


class InvalidLinkError(ScraperError):
    """Link is invalid or expired (failed URL resolution)."""


class UnsupportedServiceError(ScraperError):
    """URL does not match any registered service."""
