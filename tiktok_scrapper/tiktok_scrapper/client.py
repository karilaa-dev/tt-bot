"""TikTok API client for extracting video and music metadata (no downloads)."""

import asyncio
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
import yt_dlp

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
except ImportError:
    ImpersonateTarget = None

from .config import settings
from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
)

# TikTok WAF blocks newer Chrome versions (136+) when used with proxies due to
# TLS fingerprint / User-Agent mismatches. Use Chrome 120 which is known to work.
TIKTOK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

if TYPE_CHECKING:
    from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)


def _strip_proxy_auth(proxy_url: str | None) -> str:
    """Strip authentication info from proxy URL for safe logging."""
    if proxy_url is None:
        return "direct connection"
    match = re.match(r"^(https?://)(?:[^@]+@)?(.+)$", proxy_url)
    if match:
        protocol, host_port = match.groups()
        return f"{protocol}{host_port}"
    return proxy_url


@dataclass
class ProxySession:
    """Manages proxy state for a single request flow.

    Ensures the same proxy is used across URL resolution and info extraction
    unless a retry rotates it.
    """

    proxy_manager: "ProxyManager | None"
    _current_proxy: str | None = field(default=None, init=False)
    _initialized: bool = field(default=False, init=False)

    def get_proxy(self) -> str | None:
        """Get the current proxy (lazily initialized on first call)."""
        if not self._initialized:
            self._initialized = True
            if self.proxy_manager:
                self._current_proxy = self.proxy_manager.get_next_proxy()
                logger.debug(
                    f"ProxySession initialized with proxy: "
                    f"{_strip_proxy_auth(self._current_proxy)}"
                )
            else:
                logger.debug("ProxySession initialized with direct connection")
        return self._current_proxy

    def rotate_proxy(self) -> str | None:
        """Rotate to the next proxy in the rotation (for retries)."""
        if self.proxy_manager:
            old_proxy = self._current_proxy
            self._current_proxy = self.proxy_manager.get_next_proxy()
            logger.debug(
                f"ProxySession rotated: {_strip_proxy_auth(old_proxy)} -> "
                f"{_strip_proxy_auth(self._current_proxy)}"
            )
        self._initialized = True
        return self._current_proxy


class TikTokClient:
    """Client for extracting TikTok video and music metadata.

    This client uses yt-dlp internally to extract video/slideshow data and music
    from TikTok URLs. It only extracts metadata — no media downloads.

    Args:
        proxy_manager: Optional ProxyManager instance for round-robin proxy rotation.
        cookies: Optional path to a Netscape-format cookies file.
    """

    _executor: ThreadPoolExecutor | None = None
    _executor_lock = threading.Lock()
    _executor_size: int = 500

    _http_client: httpx.AsyncClient | None = None
    _http_client_lock = threading.Lock()
    _impersonate_available: bool | None = None

    @classmethod
    def _get_executor(cls) -> ThreadPoolExecutor:
        """Get or create the shared ThreadPoolExecutor."""
        with cls._executor_lock:
            if cls._executor is None:
                cls._executor = ThreadPoolExecutor(
                    max_workers=cls._executor_size,
                    thread_name_prefix="tiktok_sync_",
                )
                logger.info(
                    f"Created TikTokClient executor with {cls._executor_size} workers"
                )
            return cls._executor

    @classmethod
    def _get_http_client(cls) -> httpx.AsyncClient:
        """Get or create shared httpx client for URL resolution."""
        with cls._http_client_lock:
            if cls._http_client is None or cls._http_client.is_closed:
                cls._http_client = httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=httpx.Timeout(15.0, connect=5.0, read=10.0),
                    limits=httpx.Limits(
                        max_connections=None,
                        max_keepalive_connections=None,
                    ),
                )
            return cls._http_client

    @classmethod
    def _can_impersonate(cls) -> bool:
        """Check if browser impersonation is available (cached)."""
        if cls._impersonate_available is None:
            if ImpersonateTarget is None:
                cls._impersonate_available = False
            else:
                try:
                    ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
                    targets = list(ydl._get_available_impersonate_targets())
                    ydl.close()
                    cls._impersonate_available = len(targets) > 0
                    if not cls._impersonate_available:
                        logger.warning(
                            "No impersonate targets available (curl_cffi not installed?), "
                            "falling back to User-Agent header only"
                        )
                except Exception:
                    cls._impersonate_available = False
                    logger.warning("Failed to check impersonate targets, skipping impersonation")
        return cls._impersonate_available

    @classmethod
    async def close_http_client(cls) -> None:
        """Close shared httpx client. Call on application shutdown."""
        with cls._http_client_lock:
            client = cls._http_client
            cls._http_client = None
        if client and not client.is_closed:
            await client.aclose()

    @classmethod
    def shutdown_executor(cls) -> None:
        """Shutdown the shared executor. Call on application shutdown."""
        with cls._executor_lock:
            if cls._executor is not None:
                cls._executor.shutdown(wait=False)
                cls._executor = None

    def __init__(
        self,
        proxy_manager: "ProxyManager | None" = None,
        cookies: str | None = None,
    ):
        self.proxy_manager = proxy_manager

        cookies_path = cookies or os.getenv("YTDLP_COOKIES")
        if cookies_path:
            if not os.path.isabs(cookies_path):
                cookies_path = os.path.abspath(cookies_path)
            if os.path.isfile(cookies_path):
                self.cookies = cookies_path
            else:
                logger.warning(
                    f"Cookie file not found: {cookies_path} - cookies will not be used"
                )
                self.cookies = None
        else:
            self.cookies = None

    async def _resolve_url(
        self,
        url: str,
        proxy_session: ProxySession,
        max_retries: int | None = None,
    ) -> str:
        """Resolve short URLs to full URLs with retry and proxy rotation."""
        if max_retries is None:
            max_retries = settings.url_resolve_max_retries

        is_short_url = (
            "vm.tiktok.com" in url
            or "vt.tiktok.com" in url
            or "/t/" in url
        )

        if not is_short_url:
            return url

        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            proxy = proxy_session.get_proxy()
            logger.debug(
                f"URL resolve attempt {attempt}/{max_retries} for {url} "
                f"via {_strip_proxy_auth(proxy)}"
            )

            try:
                if proxy:
                    async with httpx.AsyncClient(
                        follow_redirects=True,
                        timeout=httpx.Timeout(15.0, connect=5.0, read=10.0),
                        proxy=proxy,
                    ) as client:
                        response = await client.get(url)
                else:
                    client = self._get_http_client()
                    response = await client.get(url)

                resolved_url = str(response.url)
                if "tiktok.com" in resolved_url:
                    logger.debug(f"URL resolved: {url} -> {resolved_url}")
                    return resolved_url

                logger.warning(
                    f"URL resolution returned unexpected URL: {resolved_url}"
                )
                last_error = ValueError(f"Unexpected redirect: {resolved_url}")
            except Exception as e:
                logger.warning(
                    f"URL resolve attempt {attempt}/{max_retries} failed for {url}: {e}"
                )
                last_error = e

            if attempt < max_retries:
                proxy_session.rotate_proxy()

        logger.error(
            f"URL resolution failed after {max_retries} attempts for {url}: {last_error}"
        )
        raise TikTokInvalidLinkError("Invalid or expired TikTok link")

    def _extract_video_id(self, url: str) -> str | None:
        """Extract video ID from TikTok URL."""
        match = re.search(r"/(?:video|photo)/(\d+)", url)
        return match.group(1) if match else None

    def _get_ydl_opts(
        self, use_proxy: bool = True, explicit_proxy: Any = ...
    ) -> dict[str, Any]:
        """Get base yt-dlp options."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
        }

        if self._can_impersonate():
            opts["impersonate"] = ImpersonateTarget("chrome", "120", "macos", None)
        opts["http_headers"] = {"User-Agent": TIKTOK_USER_AGENT}

        if explicit_proxy is not ...:
            if explicit_proxy is not None:
                opts["proxy"] = explicit_proxy
                logger.debug(
                    f"Using explicit proxy: {_strip_proxy_auth(explicit_proxy)}"
                )
            else:
                logger.debug("Using explicit direct connection (no proxy)")
        elif use_proxy and self.proxy_manager:
            proxy = self.proxy_manager.get_next_proxy()
            if proxy is not None:
                opts["proxy"] = proxy
                logger.debug(f"Using proxy: {_strip_proxy_auth(proxy)}")
            else:
                logger.debug("Using direct connection (no proxy)")

        if self.cookies:
            opts["cookiefile"] = self.cookies
            logger.debug(f"yt-dlp using cookie file: {self.cookies}")
        return opts

    def _extract_with_context_sync(
        self, url: str, video_id: str, request_proxy: Any = ...
    ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
        """Extract TikTok data synchronously via yt-dlp.

        Returns:
            Tuple of (video_data, status, download_context)
        """
        ydl_opts = self._get_ydl_opts(use_proxy=True, explicit_proxy=request_proxy)
        ydl = None

        try:
            ydl = yt_dlp.YoutubeDL(ydl_opts)
            ie = ydl.get_info_extractor("TikTok")
            ie.set_downloader(ydl)

            normalized_url = url.replace("/photo/", "/video/")

            if not hasattr(ie, "_extract_web_data_and_status"):
                logger.error(
                    "yt-dlp's TikTok extractor is missing '_extract_web_data_and_status' method. "
                    f"Current yt-dlp version: {yt_dlp.version.__version__}. "
                    "Please update yt-dlp: pip install -U yt-dlp"
                )
                raise TikTokExtractionError(
                    "Incompatible yt-dlp version: missing required internal method."
                )

            try:
                video_data, status = ie._extract_web_data_and_status(
                    normalized_url, video_id
                )

                if status in (10204, 10216):
                    return None, "deleted", None
                if status == 10222:
                    return None, "private", None

                if not video_data:
                    logger.error(f"No video data returned for {video_id} (status={status})")
                    return None, "extraction", None
            except AttributeError as e:
                logger.error(
                    f"Failed to call yt-dlp internal method: {e}. "
                    f"Current yt-dlp version: {yt_dlp.version.__version__}."
                )
                raise TikTokExtractionError(
                    "Incompatible yt-dlp version."
                ) from e

            download_context = {
                "ydl": ydl,
                "ie": ie,
                "referer_url": url,
                "proxy": request_proxy if request_proxy is not ... else None,
            }

            ydl = None  # Transfer ownership to caller
            return video_data, status, download_context

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if "unavailable" in error_msg or "removed" in error_msg or "deleted" in error_msg:
                return None, "deleted", None
            elif "private" in error_msg:
                return None, "private", None
            elif "rate" in error_msg or "too many" in error_msg or "429" in error_msg:
                return None, "rate_limit", None
            elif (
                "region" in error_msg
                or "geo" in error_msg
                or "country" in error_msg
                or "not available in your" in error_msg
            ):
                return None, "region", None
            logger.error(f"yt-dlp download error for video {video_id}: {e}")
            return None, "extraction", None
        except yt_dlp.utils.ExtractorError as e:
            logger.error(f"yt-dlp extractor error for video {video_id}: {e}")
            return None, "extraction", None
        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"yt-dlp extraction failed for video {video_id}: {e}", exc_info=True)
            return None, "extraction", None
        finally:
            if ydl is not None:
                try:
                    ydl.close()
                except Exception:
                    pass

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run synchronous function in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(), func, *args)

    def _close_download_context(
        self, download_context: dict[str, Any] | None
    ) -> None:
        """Close the YoutubeDL instance in a download context if present."""
        if download_context and "ydl" in download_context:
            try:
                download_context["ydl"].close()
            except Exception:
                pass

    _STATUS_EXCEPTIONS: dict[str, type[TikTokError]] = {
        "deleted": TikTokDeletedError,
        "private": TikTokPrivateError,
        "rate_limit": TikTokRateLimitError,
        "network": TikTokNetworkError,
        "region": TikTokRegionError,
    }

    _STATUS_MESSAGES: dict[str, str] = {
        "deleted": "Video {link} was deleted",
        "private": "Video {link} is private",
        "rate_limit": "Rate limited by TikTok",
        "network": "Network error occurred",
        "region": "Video {link} is not available in your region",
    }

    def _raise_for_status(self, status: str, video_link: str) -> None:
        """Raise appropriate exception based on status string."""
        exc_cls = self._STATUS_EXCEPTIONS.get(status)
        if exc_cls:
            message = self._STATUS_MESSAGES[status].format(link=video_link)
            raise exc_cls(message)
        raise TikTokExtractionError(f"Failed to extract video {video_link}")

    async def _extract_video_info_with_retry(
        self,
        url: str,
        video_id: str,
        proxy_session: ProxySession,
        max_retries: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Extract video info with retry and proxy rotation.

        Returns:
            Tuple of (video_data, download_context)
        """
        if max_retries is None:
            max_retries = settings.video_info_max_retries

        last_error: Exception | None = None
        download_context: dict[str, Any] | None = None

        for attempt in range(1, max_retries + 1):
            proxy = proxy_session.get_proxy()
            logger.debug(
                f"Video info extraction attempt {attempt}/{max_retries} for {video_id} "
                f"via {_strip_proxy_auth(proxy)}"
            )

            try:
                video_data, status, download_context = await self._run_sync(
                    self._extract_with_context_sync, url, video_id, proxy
                )

                if status in ("deleted", "private", "region"):
                    self._raise_for_status(status, url)

                if status and status not in ("ok", None):
                    raise TikTokExtractionError(f"Extraction failed with status: {status}")

                if video_data is None:
                    raise TikTokExtractionError("No video data returned")

                if download_context is None:
                    raise TikTokExtractionError("No download context returned")

                return video_data, download_context

            except (TikTokDeletedError, TikTokPrivateError, TikTokRegionError):
                self._close_download_context(download_context)
                raise

            except Exception as e:
                last_error = e
                self._close_download_context(download_context)
                download_context = None

            if attempt < max_retries:
                proxy_session.rotate_proxy()
                logger.warning(
                    f"Video info extraction attempt {attempt}/{max_retries} failed, "
                    f"rotating proxy: {last_error}"
                )

        logger.error(
            f"Video info extraction failed after {max_retries} attempts "
            f"for {video_id}: {last_error}"
        )
        raise TikTokExtractionError(
            f"Failed to extract video info after {max_retries} attempts"
        )

    async def extract_video_info(self, video_link: str) -> dict[str, Any]:
        """Extract video/slideshow metadata without downloading media.

        Returns:
            Dict with keys: video_data, video_id, resolved_url
        """
        proxy_session = ProxySession(self.proxy_manager)
        download_context: dict[str, Any] | None = None

        try:
            full_url = await self._resolve_url(video_link, proxy_session)
            video_id = self._extract_video_id(full_url)

            if not video_id:
                raise TikTokInvalidLinkError("Invalid or expired TikTok link")

            extraction_url = f"https://www.tiktok.com/@_/video/{video_id}"
            video_data, download_context = await self._extract_video_info_with_retry(
                extraction_url, video_id, proxy_session
            )

            return {
                "video_data": video_data,
                "video_id": video_id,
                "resolved_url": full_url,
            }

        except (TikTokError, asyncio.CancelledError):
            raise
        except httpx.HTTPError as e:
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            raise TikTokExtractionError(f"Failed to extract video info: {e}") from e
        finally:
            self._close_download_context(download_context)

    async def extract_music_info(self, video_id: int) -> dict[str, Any]:
        """Extract music metadata without downloading audio.

        Returns:
            Dict with keys: video_data, music_data, video_id
        """
        proxy_session = ProxySession(self.proxy_manager)
        download_context: dict[str, Any] | None = None

        try:
            url = f"https://www.tiktok.com/@_/video/{video_id}"
            video_data, download_context = await self._extract_video_info_with_retry(
                url, str(video_id), proxy_session
            )

            music_info = video_data.get("music")
            if not music_info:
                raise TikTokExtractionError(f"No music info found for video {video_id}")

            return {
                "video_data": video_data,
                "music_data": music_info,
                "video_id": video_id,
            }

        except (TikTokError, asyncio.CancelledError):
            raise
        except httpx.HTTPError as e:
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            raise TikTokExtractionError(f"Failed to extract music info: {e}") from e
        finally:
            self._close_download_context(download_context)
