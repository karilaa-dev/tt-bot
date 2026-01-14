"""TikTok API client for extracting video and music information."""

import asyncio
import logging
import os
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Tuple

# Type alias for download progress callback: (bytes_downloaded, total_bytes or None)
ProgressCallback = Callable[[int, Optional[int]], None]

import aiohttp
from aiohttp import TCPConnector, ClientTimeout
import yt_dlp

# Dynamic import of yt-dlp bypass mechanisms (updates automatically with yt-dlp)
from yt_dlp.utils import std_headers as YTDLP_STD_HEADERS

# curl_cffi for browser impersonation (TLS fingerprint bypass)
import curl_cffi
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from curl_cffi import CurlError

# Import yt-dlp's browser targets for dynamic impersonation
# This ensures impersonation targets update automatically with yt-dlp
try:
    from yt_dlp.networking._curlcffi import BROWSER_TARGETS, _TARGETS_COMPAT_LOOKUP
except ImportError:
    # Fallback if yt-dlp structure changes or curl_cffi not available during import
    BROWSER_TARGETS = {}
    _TARGETS_COMPAT_LOOKUP = {}

from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
    TikTokVideoTooLongError,
)
from .models import MusicInfo, VideoInfo

if TYPE_CHECKING:
    from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

# Regex for extracting video ID from redirected URLs (used by legacy get_id functions)
_redirect_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+?/([0-9]+)")


def _strip_proxy_auth(proxy_url: Optional[str]) -> str:
    """Strip authentication info from proxy URL for safe logging.

    Args:
        proxy_url: Proxy URL that may contain credentials (e.g., http://user:pass@host:port)

    Returns:
        Proxy URL without credentials (e.g., http://host:port) or "direct connection" if None
    """
    if proxy_url is None:
        return "direct connection"

    # Match proxy URL pattern: protocol://[user:pass@]host:port
    match = re.match(r"^(https?://)(?:[^@]+@)?(.+)$", proxy_url)
    if match:
        protocol, host_port = match.groups()
        return f"{protocol}{host_port}"

    # If pattern doesn't match, return as-is (shouldn't happen with valid proxy URLs)
    return proxy_url


class TikTokClient:
    """Client for extracting TikTok video and music information.

    This client uses yt-dlp internally to extract video/slideshow data and music
    from TikTok URLs. It supports both regular videos and slideshows (image posts).

    All media downloads (video, audio, images) use curl_cffi with browser
    impersonation (TLS fingerprint spoofing) derived from yt-dlp's BROWSER_TARGETS.
    This automatically updates when you update yt-dlp, ensuring compatibility
    with TikTok's anti-bot detection.

    Args:
        proxy_manager: Optional ProxyManager instance for round-robin proxy rotation.
            If provided, each request will use the next proxy in rotation.
        data_only_proxy: If True, proxy is used only for API extraction, not for
            media downloads. Defaults to False.
        cookies: Optional path to a Netscape-format cookies file (e.g., exported from browser).
            If not provided, uses YTDLP_COOKIES env var. If the file doesn't exist,
            a warning is logged and cookies are not used.
        aiohttp_pool_size: Total connection pool size for async downloads. Default: 200.
        aiohttp_limit_per_host: Per-host connection limit. Default: 50.

    Example:
        >>> from tiktok_api import TikTokClient, ProxyManager
        >>> proxy_manager = ProxyManager.initialize("proxies.txt", include_host=True)
        >>> client = TikTokClient(proxy_manager=proxy_manager, data_only_proxy=True)
        >>> video_info = await client.video("https://www.tiktok.com/@user/video/123")
        >>> print(video_info.author)
        >>> print(video_info.duration)

        # With cookies for authenticated requests:
        >>> client = TikTokClient(cookies="cookies.txt")
    """

    # Configurable executor - call set_executor_size() before first use
    _executor: Optional[ThreadPoolExecutor] = None
    _executor_lock = threading.Lock()
    _executor_size: int = 128  # Default, configurable via set_executor_size()

    _aiohttp_connector: Optional[TCPConnector] = None
    _connector_lock = threading.Lock()

    # curl_cffi session for browser-impersonated media downloads
    _curl_session: Optional[CurlAsyncSession] = None
    _curl_session_lock = threading.Lock()
    _impersonate_target: Optional[str] = None

    @classmethod
    def _get_impersonate_target(cls) -> str:
        """Get the best impersonation target from yt-dlp's BROWSER_TARGETS.

        Uses the same priority as yt-dlp:
        1. Prioritize desktop over mobile (non-ios, non-android)
        2. Prioritize Chrome > Safari > Firefox > Edge > Tor
        3. Prioritize newest version

        This ensures the impersonation target updates automatically when you
        update yt-dlp, without any hardcoded values.

        Returns:
            curl_cffi-compatible impersonate string (e.g., "chrome136")
        """
        import itertools

        # Get curl_cffi version as tuple for comparison
        try:
            curl_cffi_version = tuple(
                int(x) for x in curl_cffi.__version__.split(".")[:2]
            )
        except (ValueError, AttributeError):
            curl_cffi_version = (0, 9)  # Minimum supported version

        # Collect all available targets for our curl_cffi version
        available_targets: dict[str, Any] = {}
        for version, targets in BROWSER_TARGETS.items():
            if curl_cffi_version >= version:
                available_targets.update(targets)

        if not available_targets:
            # Fallback to a common target if BROWSER_TARGETS is empty
            logger.warning(
                "No BROWSER_TARGETS available from yt-dlp, using 'chrome' fallback"
            )
            return "chrome"

        # Sort by yt-dlp's priority (same logic as _curlcffi.py)
        # This ensures we pick the same target yt-dlp would use
        sorted_targets = sorted(
            available_targets.items(),
            key=lambda x: (
                # deprioritize mobile targets since they give very different behavior
                x[1].os not in ("ios", "android"),
                # prioritize tor < edge < firefox < safari < chrome
                ("tor", "edge", "firefox", "safari", "chrome").index(x[1].client)
                if x[1].client in ("tor", "edge", "firefox", "safari", "chrome")
                else -1,
                # prioritize newest version
                float(x[1].version) if x[1].version else 0,
                # group by os name
                x[1].os or "",
            ),
            reverse=True,
        )

        # Get the best target name
        best_name = sorted_targets[0][0]

        # Apply compatibility lookup for older curl_cffi versions
        if curl_cffi_version < (0, 11):
            best_name = _TARGETS_COMPAT_LOOKUP.get(best_name, best_name)

        logger.debug(
            f"Selected impersonation target: {best_name} "
            f"(curl_cffi {curl_cffi.__version__})"
        )
        return best_name

    @classmethod
    def _get_curl_session(cls) -> CurlAsyncSession:
        """Get or create shared curl_cffi AsyncSession with browser impersonation.

        The session uses yt-dlp's BROWSER_TARGETS to select the best impersonation
        target, ensuring TLS fingerprint matches a real browser.

        Pool size is configurable via CURL_POOL_SIZE environment variable.
        """
        with cls._curl_session_lock:
            # Check if session needs to be created
            # Note: CurlAsyncSession doesn't have is_closed, we track via _curl_session being None
            if cls._curl_session is None:
                from data.config import config

                perf_config = config.get("performance", {})
                pool_size = perf_config.get("curl_pool_size", 200)

                cls._impersonate_target = cls._get_impersonate_target()
                cls._curl_session = CurlAsyncSession(
                    impersonate=cls._impersonate_target,
                    max_clients=pool_size,
                )
                logger.info(
                    f"Created curl_cffi session with impersonate={cls._impersonate_target}, "
                    f"max_clients={pool_size}"
                )
            return cls._curl_session

    @classmethod
    async def close_curl_session(cls) -> None:
        """Close shared curl_cffi session. Call on application shutdown."""
        with cls._curl_session_lock:
            session = cls._curl_session
            cls._curl_session = None
            cls._impersonate_target = None
        if session is not None:
            try:
                await session.close()
            except Exception as e:
                logger.debug(f"Error closing curl_cffi session: {e}")

    @classmethod
    def set_executor_size(cls, size: int) -> None:
        """Set executor size before first use. Call at app startup.

        Args:
            size: Number of worker threads for sync yt-dlp extraction calls.
                  Higher values allow more concurrent extractions.
        """
        with cls._executor_lock:
            if cls._executor is not None:
                logger.warning(
                    f"Executor already created with {cls._executor._max_workers} workers. "
                    f"set_executor_size({size}) has no effect. Call before first TikTokClient use."
                )
                return
            cls._executor_size = size
            logger.info(f"TikTokClient executor size set to {size}")

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
    def _get_connector(cls, pool_size: int, limit_per_host: int = 50) -> TCPConnector:
        """Get or create shared aiohttp connector for URL resolution.

        Note: This is only used for resolving short URLs (vm.tiktok.com, vt.tiktok.com).
        Media downloads use curl_cffi for browser impersonation.

        Args:
            pool_size: Total connection pool size
            limit_per_host: Maximum connections per host
        """
        with cls._connector_lock:
            if cls._aiohttp_connector is None or cls._aiohttp_connector.closed:
                cls._aiohttp_connector = TCPConnector(
                    limit=pool_size,
                    limit_per_host=limit_per_host,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True,
                    force_close=False,  # Keep connections alive for reuse
                )
            return cls._aiohttp_connector

    @classmethod
    async def close_connector(cls) -> None:
        """Close shared aiohttp connector. Call on application shutdown."""
        # Grab and clear connector under lock
        with cls._connector_lock:
            connector = cls._aiohttp_connector
            cls._aiohttp_connector = None
        # Close outside lock to avoid blocking
        if connector and not connector.closed:
            await connector.close()

    @classmethod
    def shutdown_executor(cls) -> None:
        """Shutdown the shared executor. Call on application shutdown."""
        with cls._executor_lock:
            if cls._executor is not None:
                cls._executor.shutdown(wait=False)
                cls._executor = None

    def __init__(
        self,
        proxy_manager: Optional["ProxyManager"] = None,
        data_only_proxy: bool = False,
        cookies: Optional[str] = None,
        aiohttp_pool_size: int = 200,
        aiohttp_limit_per_host: int = 50,
    ):
        self.proxy_manager = proxy_manager
        self.data_only_proxy = data_only_proxy
        self.aiohttp_pool_size = aiohttp_pool_size
        self.aiohttp_limit_per_host = aiohttp_limit_per_host

        # Handle cookies with validation
        cookies_path = cookies or os.getenv("YTDLP_COOKIES")
        if cookies_path:
            # Convert relative path to absolute path
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

        self.mobile_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+")
        self.web_regex = re.compile(r"https?://www\.tiktok\.com/@[^\s]+?/video/[0-9]+")
        self.photo_regex = re.compile(
            r"https?://www\.tiktok\.com/@[^\s]+?/photo/[0-9]+"
        )
        self.mus_regex = re.compile(r"https?://www\.tiktok\.com/music/[^\s]+")

    def _get_proxy_info(self) -> str:
        """Get proxy configuration info for logging."""
        if self.proxy_manager:
            count = self.proxy_manager.get_proxy_count()
            return f"rotating ({count} proxies)"
        return "None"

    def _get_bypass_headers(self, referer_url: str) -> dict[str, str]:
        """Get bypass headers dynamically from yt-dlp.

        Uses yt-dlp's standard headers which are updated with each yt-dlp release.
        We add Origin and Referer for CORS compliance with TikTok CDN.

        Args:
            referer_url: The referer URL to set in headers

        Returns:
            Dict of headers for media download
        """
        headers = dict(YTDLP_STD_HEADERS)  # Copy to avoid mutation
        headers["Referer"] = referer_url
        headers["Origin"] = "https://www.tiktok.com"
        headers["Accept"] = "*/*"
        # Avoid hardcoding Sec-Fetch-* headers; incorrect values can break
        # audio/video downloads. Let the browser/client defaults apply.
        return headers

    async def _fetch_webpage_async(
        self,
        url: str,
        proxy: Optional[str] = None,
        max_retries: int = 2,
        base_delay: float = 1.0,
    ) -> Tuple[str, str]:
        """Fetch TikTok webpage using curl_cffi with browser impersonation.

        Uses the same bypass mechanism as media downloads for consistency.
        This replaces yt-dlp's internal _download_webpage_handle() for fetching.

        Args:
            url: TikTok URL to fetch
            proxy: Optional proxy URL to use
            max_retries: Maximum retry attempts for retryable errors (default: 2)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)

        Returns:
            Tuple of (html_content, final_url) where final_url is the URL after redirects

        Raises:
            TikTokNetworkError: On network/connection errors after retries
            TikTokRateLimitError: On rate limiting (429)
            TikTokExtractionError: On other HTTP errors
        """
        headers = self._get_bypass_headers(url)
        session = self._get_curl_session()

        for attempt in range(1, max_retries + 1):
            logger.debug(
                f"Webpage fetch attempt {attempt}/{max_retries} for {url} "
                f"(proxy: {_strip_proxy_auth(proxy)})"
            )
            response = None
            try:
                response = await session.get(
                    url,
                    headers=headers,
                    proxy=proxy,
                    timeout=30,
                    allow_redirects=True,
                )

                if response.status_code == 200:
                    # Get final URL after redirects
                    final_url = str(response.url) if response.url else url
                    content = response.text
                    logger.debug(
                        f"Successfully fetched webpage ({len(content)} bytes), "
                        f"final URL: {final_url}"
                    )
                    return content, final_url

                elif response.status_code == 429:
                    # Rate limited
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        jitter = delay * 0.1 * random.random()
                        logger.warning(
                            f"Rate limited (429) fetching {url}, "
                            f"retry {attempt}/{max_retries} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                    raise TikTokRateLimitError(
                        f"Rate limited after {max_retries} attempts"
                    )

                elif response.status_code in (500, 502, 503, 504):
                    # Server errors - retry
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        jitter = delay * 0.1 * random.random()
                        logger.warning(
                            f"Server error ({response.status_code}) fetching {url}, "
                            f"retry {attempt}/{max_retries} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                    raise TikTokNetworkError(
                        f"Server error {response.status_code} after {max_retries} attempts"
                    )

                elif response.status_code == 403:
                    # Forbidden - may be blocked, retry with different fingerprint
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            f"Forbidden (403) fetching {url}, "
                            f"retry {attempt}/{max_retries} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise TikTokExtractionError(
                        f"Access forbidden (403) after {max_retries} attempts"
                    )

                elif response.status_code == 404:
                    raise TikTokDeletedError("Video not found (404)")

                else:
                    raise TikTokExtractionError(
                        f"HTTP {response.status_code} fetching webpage"
                    )

            except CurlError as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"curl_cffi error fetching {url}, "
                        f"retry {attempt}/{max_retries} after {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise TikTokNetworkError(
                    f"Network error after {max_retries} attempts: {e}"
                ) from e

            except TikTokError:
                raise

            except Exception as e:
                logger.error(f"Unexpected error fetching {url}: {e}")
                raise TikTokExtractionError(f"Failed to fetch webpage: {e}") from e

            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        # Should not reach here, but satisfy type checker
        raise TikTokExtractionError(
            f"Failed to fetch webpage after {max_retries} attempts"
        )

    def _parse_webpage_data(
        self,
        webpage: str,
        video_id: str,
        final_url: str,
    ) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """Parse TikTok webpage HTML to extract video data using yt-dlp helpers.

        This method uses yt-dlp's parsing functions but does NOT make any network
        requests. All network operations should be done via _fetch_webpage_async().

        Args:
            webpage: HTML content of the TikTok page
            video_id: The video ID extracted from the URL
            final_url: The final URL after redirects (used for login detection)

        Returns:
            Tuple of (video_data, status):
            - video_data: Dict containing video/slideshow data, or None on error
            - status: Error status string ("deleted", "private", "region", etc.) or None

        Raises:
            TikTokExtractionError: If unable to parse the webpage data
        """
        import urllib.parse

        # Check for login redirect
        if urllib.parse.urlparse(final_url).path == "/login":
            raise TikTokExtractionError(
                "TikTok is requiring login for access to this content"
            )

        # Create minimal yt-dlp instance just for parsing (no network)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
        }
        if self.cookies:
            ydl_opts["cookiefile"] = self.cookies

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ie = ydl.get_info_extractor("TikTok")
                ie.set_downloader(ydl)

                video_data = None
                status: Optional[int | str] = None

                # Try universal data first (most common format)
                try:
                    universal_data = ie._get_universal_data(webpage, video_id)
                    logger.debug(f"Universal data found: {universal_data is not None}")
                    if universal_data:
                        from yt_dlp.utils import traverse_obj

                        status = (
                            traverse_obj(
                                universal_data,
                                ("webapp.video-detail", "statusCode", {int}),
                            )
                            or 0
                        )
                        video_data = traverse_obj(
                            universal_data,
                            ("webapp.video-detail", "itemInfo", "itemStruct", {dict}),
                        )
                        logger.debug(f"Universal data video_data found: {video_data is not None}")
                except Exception as e:
                    logger.debug(f"Failed to parse universal data: {e}")

                # Try sigi state data
                if not video_data:
                    try:
                        sigi_data = ie._get_sigi_state(webpage, video_id)
                        logger.debug(f"Sigi state data found: {sigi_data is not None}")
                        if sigi_data:
                            from yt_dlp.utils import traverse_obj

                            status = (
                                traverse_obj(
                                    sigi_data, ("VideoPage", "statusCode", {int})
                                )
                                or 0
                            )
                            video_data = traverse_obj(
                                sigi_data, ("ItemModule", video_id, {dict})
                            )
                            logger.debug(f"Sigi state video_data found: {video_data is not None}")
                    except Exception as e:
                        logger.debug(f"Failed to parse sigi state: {e}")

                # Try next.js data
                if not video_data:
                    try:
                        next_data = ie._search_nextjs_data(
                            webpage, video_id, default={}
                        )
                        logger.debug(f"Next.js data found: {bool(next_data)}")
                        if next_data:
                            from yt_dlp.utils import traverse_obj

                            status = (
                                traverse_obj(
                                    next_data,
                                    ("props", "pageProps", "statusCode", {int}),
                                )
                                or 0
                            )
                            video_data = traverse_obj(
                                next_data,
                                (
                                    "props",
                                    "pageProps",
                                    "itemInfo",
                                    "itemStruct",
                                    {dict},
                                ),
                            )
                            logger.debug(f"Next.js video_data found: {video_data is not None}")
                    except Exception as e:
                        logger.debug(f"Failed to parse next.js data: {e}")

                # Check status codes for errors
                if isinstance(status, int) and status != 0:
                    # Map TikTok status codes to error types
                    if status == 10204:
                        return None, "deleted"
                    elif status == 10222:
                        return None, "private"
                    elif status in (10101, 10102):
                        return None, "region"

                if not video_data:
                    raise TikTokExtractionError(
                        f"Unable to extract video data from webpage for {video_id}"
                    )

                return video_data, None

        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"Failed to parse webpage for video {video_id}: {e}")
            raise TikTokExtractionError(f"Failed to parse webpage: {e}") from e

    def _get_cookies_from_context(
        self, download_context: dict[str, Any], media_url: Optional[str] = None
    ) -> dict[str, str]:
        """Extract cookies from yt-dlp context for media download.

        Uses yt-dlp's InfoExtractor to get cookies for the specific media URL.
        This properly handles TikTok's cookie propagation to CDN domains.

        Args:
            download_context: Dict containing 'ydl', 'ie' with YoutubeDL instance
            media_url: Optional media URL to get cookies for (for CDN domain matching)

        Returns:
            Dict of cookie name -> value
        """
        cookies: dict[str, str] = {}
        try:
            ie = download_context.get("ie")
            if ie:
                # Get cookies from TikTok main domain first
                tiktok_cookies = ie._get_cookies("https://www.tiktok.com/")
                for cookie_name, cookie in tiktok_cookies.items():
                    cookies[cookie_name] = cookie.value

                # If media_url is provided, also get cookies for that specific domain
                if media_url:
                    media_cookies = ie._get_cookies(media_url)
                    for cookie_name, cookie in media_cookies.items():
                        cookies[cookie_name] = cookie.value
            else:
                # Fallback: extract all cookies from cookiejar
                ydl = download_context.get("ydl")
                if ydl and hasattr(ydl, "cookiejar"):
                    for cookie in ydl.cookiejar:
                        cookies[cookie.name] = cookie.value
        except Exception as e:
            logger.debug(f"Failed to extract cookies from context: {e}")
        return cookies

    async def _download_media_async(
        self,
        media_url: str,
        download_context: dict[str, Any],
        duration: Optional[int] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        chunk_size: int = 65536,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[bytes]:
        """Download media asynchronously using curl_cffi with browser impersonation.

        Features:
        - Uses yt-dlp's BROWSER_TARGETS for TLS fingerprint impersonation
        - Conditional streaming for long videos (> threshold) to reduce memory spikes
        - Automatic retry with exponential backoff for CDN failures
        - Optional progress callback for download monitoring

        Args:
            media_url: Direct URL to the media on TikTok CDN
            download_context: Dict containing 'ydl', 'ie', 'referer_url', and 'proxy'
            duration: Video duration in seconds. If > threshold, uses streaming download.
            max_retries: Maximum retry attempts for retryable errors (default: 3)
            base_delay: Base delay in seconds for exponential backoff (default: 1.0)
            chunk_size: Chunk size for streaming downloads in bytes (default: 64KB)
            progress_callback: Optional callback(downloaded_bytes, total_bytes) for progress

        Returns:
            Media bytes if successful, None otherwise
        """
        from data.config import config

        perf_config = config.get("performance", {})
        streaming_threshold = perf_config.get("streaming_duration_threshold", 300)

        # Use streaming for long videos (> 5 minutes by default)
        use_streaming = duration is not None and duration > streaming_threshold

        referer_url = download_context.get("referer_url", "https://www.tiktok.com/")
        headers = self._get_bypass_headers(referer_url)

        # Get cookies using yt-dlp's cookie handling for proper domain matching
        cookies = self._get_cookies_from_context(download_context, media_url)

        # Use proxy from context unless data_only_proxy is True
        proxy = None
        if not self.data_only_proxy:
            proxy = download_context.get("proxy")

        session = self._get_curl_session()

        for attempt in range(1, max_retries + 1):
            logger.debug(f"CDN download attempt {attempt}/{max_retries} for media URL")
            response = None
            try:
                response = await session.get(
                    media_url,
                    headers=headers,
                    cookies=cookies,
                    proxy=proxy,
                    timeout=60,
                    allow_redirects=True,
                    stream=use_streaming,
                )

                if response.status_code == 200:
                    if use_streaming:
                        # Stream in chunks for long videos to reduce memory spikes.
                        # Note: We still buffer all chunks in memory before returning.
                        # This is intentional for simplicity - the streaming reduces
                        # peak memory during download by not loading the entire response
                        # at once, but the final join still requires full size in memory.
                        # For truly large files, consider streaming to disk instead.
                        total_size = response.headers.get("content-length")
                        total_size = int(total_size) if total_size else None

                        chunks: list[bytes] = []
                        downloaded = 0
                        async for chunk in response.aiter_content(chunk_size):
                            chunks.append(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size)

                        if use_streaming and duration:
                            logger.debug(
                                f"Streamed {downloaded} bytes for {duration}s video"
                            )
                        return b"".join(chunks)
                    else:
                        # Direct content for short videos (faster, less overhead)
                        return response.content

                elif response.status_code in (403, 429, 500, 502, 503, 504):
                    # Retryable error - CDN issues, rate limiting, etc.
                    if attempt < max_retries:
                        delay = base_delay * (2 ** (attempt - 1))
                        jitter = delay * 0.1 * random.random()
                        logger.warning(
                            f"CDN returned {response.status_code} for {media_url}, "
                            f"retry {attempt}/{max_retries} after {delay:.1f}s"
                        )
                        await asyncio.sleep(delay + jitter)
                        continue
                    else:
                        logger.error(
                            f"Media download failed after {max_retries} attempts "
                            f"with status {response.status_code} for {media_url}"
                        )
                        return None
                else:
                    # Non-retryable error (e.g., 404)
                    logger.error(
                        f"Media download failed with status {response.status_code} "
                        f"for {media_url}"
                    )
                    return None

            except CurlError as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"curl_cffi error for {media_url}, "
                        f"retry {attempt}/{max_retries} after {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    f"curl_cffi download failed after {max_retries} attempts "
                    f"for {media_url}: {e}"
                )
                return None

            except Exception as e:
                # Unexpected errors - don't retry
                logger.error(f"Unexpected error downloading media {media_url}: {e}")
                return None

            finally:
                # Ensure response is properly closed to release connection back to pool.
                # curl_cffi responses should be closed to prevent connection leaks.
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass  # Ignore errors during cleanup

        return None  # Should not reach here, but satisfy type checker

    async def _download_video_with_rotation(
        self,
        media_url: str,
        referer_url: str,
        initial_proxy: Optional[str] = None,
        duration: Optional[int] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        chunk_size: int = 65536,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> Optional[bytes]:
        """Download video with proxy rotation on failure.

        Unlike _download_media_async which uses download_context, this method
        accepts explicit parameters and rotates proxies on retryable failures.

        Args:
            media_url: Direct URL to the media on TikTok CDN
            referer_url: Referer URL for headers
            initial_proxy: Initial proxy to use (None for direct connection)
            duration: Video duration in seconds. If > threshold, uses streaming.
            max_retries: Maximum retry attempts (default: 3)
            base_delay: Base delay for exponential backoff (default: 1.0)
            chunk_size: Chunk size for streaming (default: 64KB)
            progress_callback: Optional progress callback

        Returns:
            Media bytes if successful, None otherwise
        """
        from data.config import config

        perf_config = config.get("performance", {})
        streaming_threshold = perf_config.get("streaming_duration_threshold", 300)

        # Use streaming for long videos (> 5 minutes by default)
        use_streaming = duration is not None and duration > streaming_threshold

        headers = self._get_bypass_headers(referer_url)
        session = self._get_curl_session()

        # Current proxy - may be rotated on failure
        current_proxy = initial_proxy
        # Skip proxy for downloads if data_only_proxy is True
        if self.data_only_proxy:
            current_proxy = None

        for attempt in range(1, max_retries + 1):
            logger.debug(
                f"CDN download attempt {attempt}/{max_retries} "
                f"(proxy: {_strip_proxy_auth(current_proxy)})"
            )
            response = None
            try:
                response = await session.get(
                    media_url,
                    headers=headers,
                    proxy=current_proxy,
                    timeout=60,
                    allow_redirects=True,
                    stream=use_streaming,
                )

                if response.status_code == 200:
                    if use_streaming:
                        total_size = response.headers.get("content-length")
                        total_size = int(total_size) if total_size else None

                        chunks: list[bytes] = []
                        downloaded = 0
                        async for chunk in response.aiter_content(chunk_size):
                            chunks.append(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_size)

                        if duration:
                            logger.debug(
                                f"Streamed {downloaded} bytes for {duration}s video"
                            )
                        return b"".join(chunks)
                    else:
                        return response.content

                elif response.status_code in (403, 429, 500, 502, 503, 504):
                    # Retryable error - rotate proxy and retry
                    if attempt < max_retries:
                        # Rotate to next proxy if available
                        if self.proxy_manager and not self.data_only_proxy:
                            old_proxy = current_proxy
                            current_proxy = self.proxy_manager.get_next_proxy()
                            logger.warning(
                                f"CDN returned {response.status_code}, rotating proxy: "
                                f"{_strip_proxy_auth(old_proxy)} -> {_strip_proxy_auth(current_proxy)}"
                            )
                        else:
                            logger.warning(
                                f"CDN returned {response.status_code}, retrying..."
                            )

                        delay = base_delay * (2 ** (attempt - 1))
                        jitter = delay * 0.1 * random.random()
                        await asyncio.sleep(delay + jitter)
                        continue
                    else:
                        logger.error(
                            f"Media download failed after {max_retries} attempts "
                            f"with status {response.status_code}"
                        )
                        return None
                else:
                    # Non-retryable error (e.g., 404)
                    logger.error(
                        f"Media download failed with status {response.status_code}"
                    )
                    return None

            except CurlError as e:
                if attempt < max_retries:
                    # Rotate proxy on network error
                    if self.proxy_manager and not self.data_only_proxy:
                        old_proxy = current_proxy
                        current_proxy = self.proxy_manager.get_next_proxy()
                        logger.warning(
                            f"curl_cffi error, rotating proxy: "
                            f"{_strip_proxy_auth(old_proxy)} -> {_strip_proxy_auth(current_proxy)}: {e}"
                        )
                    else:
                        logger.warning(f"curl_cffi error, retrying: {e}")

                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    f"curl_cffi download failed after {max_retries} attempts: {e}"
                )
                return None

            except Exception as e:
                logger.error(f"Unexpected error downloading media: {e}")
                return None

            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

        return None

    async def regex_check(
        self, video_link: str
    ) -> Tuple[Optional[str], Optional[bool]]:
        """Check if a link matches known TikTok URL patterns.

        Args:
            video_link: URL to check

        Returns:
            Tuple of (matched_link, is_mobile) where is_mobile indicates if it's
            a short/mobile URL. Returns (None, None) if no pattern matches.
        """
        if self.web_regex.search(video_link) is not None:
            link = self.web_regex.findall(video_link)[0]
            return link, False
        elif self.photo_regex.search(video_link) is not None:
            link = self.photo_regex.findall(video_link)[0]
            return link, False
        elif self.mobile_regex.search(video_link) is not None:
            link = self.mobile_regex.findall(video_link)[0]
            return link, True
        else:
            return None, None

    async def get_video_id_from_mobile(self, link: str) -> Optional[str]:
        """Extract video ID from a mobile/short TikTok URL by following redirects.

        This resolves short URLs like vm.tiktok.com or vt.tiktok.com to get the
        actual video ID.

        Args:
            link: Mobile/short TikTok URL

        Returns:
            Video ID string if found, None otherwise.
        """
        async with aiohttp.ClientSession() as client:
            try:
                async with client.get(link, allow_redirects=True) as response:
                    return response.url.name
            except Exception as e:
                logger.error(f"Failed to get video ID from mobile link {link}: {e}")
                return None

    async def get_video_id(self, link: str, is_mobile: bool) -> Optional[str]:
        """Extract video ID from a TikTok URL.

        Args:
            link: TikTok URL (web or mobile)
            is_mobile: Whether the link is a mobile/short URL

        Returns:
            Video ID string if found, None otherwise.
        """
        video_id: Optional[str] = None
        if not is_mobile:
            matches = _redirect_regex.findall(link)
            if matches:
                video_id = matches[0]
        else:
            try:
                video_id = await self.get_video_id_from_mobile(link)
            except Exception:
                pass
        return video_id

    async def _resolve_url(self, url: str) -> str:
        """Resolve short URLs to full URLs.

        Handles:
        - vm.tiktok.com short links
        - vt.tiktok.com short links
        - www.tiktok.com/t/ short links

        Uses shared connector for connection pooling efficiency.
        """
        # Check for various short URL formats
        is_short_url = (
            "vm.tiktok.com" in url
            or "vt.tiktok.com" in url
            or "/t/" in url  # Handles www.tiktok.com/t/XXX format
        )
        if is_short_url:
            connector = self._get_connector(
                self.aiohttp_pool_size, self.aiohttp_limit_per_host
            )
            timeout = ClientTimeout(total=15, connect=5, sock_read=10)
            try:
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    connector_owner=False,  # Don't close shared connector
                ) as session:
                    async with session.get(url, allow_redirects=True) as response:
                        return str(response.url)
            except Exception as e:
                logger.error(f"Failed to resolve URL {url}: {e}")
                return url
        return url

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from TikTok URL."""
        match = re.search(r"/(?:video|photo)/(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _get_ydl_opts(
        self, use_proxy: bool = True, explicit_proxy: Any = ...
    ) -> dict[str, Any]:
        """Get base yt-dlp options.

        Args:
            use_proxy: If True and no explicit_proxy is given, use proxy from config.
                       If False, no proxy is used (for media downloads when data_only_proxy=True).
            explicit_proxy: If provided (including None), use this specific proxy decision
                           instead of getting one from rotation. Pass None to force direct
                           connection. Uses sentinel default (...) to distinguish "not provided"
                           from "provided as None".

        Returns:
            Dict of yt-dlp options.
        """
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
        }

        # Use explicit proxy decision if it was provided (even if None = direct connection)
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
            if proxy is not None:  # None means direct connection
                opts["proxy"] = proxy
                logger.debug(f"Using proxy: {_strip_proxy_auth(proxy)}")
            else:
                logger.debug("Using direct connection (no proxy)")

        if self.cookies:
            opts["cookiefile"] = self.cookies
            logger.debug(f"yt-dlp using cookie file: {self.cookies}")
        return opts

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run synchronous function in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._get_executor(), func, *args)

    def _raise_for_status(self, status: str, video_link: str) -> None:
        """Raise appropriate exception based on status string."""
        if status == "deleted":
            raise TikTokDeletedError(f"Video {video_link} was deleted")
        elif status == "private":
            raise TikTokPrivateError(f"Video {video_link} is private")
        elif status == "rate_limit":
            raise TikTokRateLimitError("Rate limited by TikTok")
        elif status == "network":
            raise TikTokNetworkError("Network error occurred")
        elif status == "region":
            raise TikTokRegionError(
                f"Video {video_link} is not available in your region"
            )
        else:
            # Handle "extraction" and any unknown status values
            raise TikTokExtractionError(f"Failed to extract video {video_link}")

    async def download_image(self, image_url: str, video_info: VideoInfo) -> bytes:
        """
        Download an image using curl_cffi with browser impersonation.

        Uses the same TLS fingerprint bypass as video downloads.

        Args:
            image_url: Direct URL to the image on TikTok CDN
            video_info: VideoInfo object that was returned by video() method
                        (must be a slideshow with _download_context set)

        Returns:
            Image bytes

        Raises:
            ValueError: If video_info has no download context
            TikTokNetworkError: If the download fails
        """
        if not video_info._download_context:
            raise ValueError(
                "VideoInfo has no download context - was it extracted as a slideshow?"
            )

        # Extract referer and proxy from context
        referer_url = video_info._download_context.get(
            "referer_url", "https://www.tiktok.com/"
        )
        proxy = video_info._download_context.get("proxy")

        # Skip proxy for downloads if data_only_proxy is True
        if self.data_only_proxy:
            proxy = None

        headers = self._get_bypass_headers(referer_url)
        session = self._get_curl_session()

        logger.debug(
            f"Downloading image: {image_url[:80]}... "
            f"(proxy: {_strip_proxy_auth(proxy)})"
        )

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            logger.debug(f"Image download attempt {attempt}/{max_retries}")
            response = None
            try:
                response = await session.get(
                    image_url,
                    headers=headers,
                    proxy=proxy,
                    timeout=60,
                    allow_redirects=True,
                )

                if response.status_code == 200:
                    logger.debug(
                        f"Image download successful: {len(response.content)} bytes"
                    )
                    return response.content

                logger.warning(
                    f"Image download attempt {attempt}/{max_retries} "
                    f"failed with status {response.status_code}"
                )

            except Exception as e:
                logger.warning(
                    f"Image download attempt {attempt}/{max_retries} "
                    f"failed with error: {e}"
                )
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

            if attempt < max_retries:
                await asyncio.sleep(1.0 * attempt)  # Exponential backoff

        raise TikTokNetworkError(f"Failed to download image after {max_retries} attempts: {image_url}")

    async def detect_image_format(self, image_url: str, video_info: VideoInfo) -> str:
        """
        Detect image format using HTTP Range request (only fetches first 20 bytes).

        Uses curl_cffi with browser impersonation for TLS fingerprint bypass.

        Args:
            image_url: Direct URL to the image on TikTok CDN
            video_info: VideoInfo object with download context

        Returns:
            File extension string: ".jpg", ".webp", ".heic", or ".jpg" (default)
        """
        if not video_info._download_context:
            # Fallback: assume needs processing if no context
            return ".heic"

        referer_url = video_info._download_context.get(
            "referer_url", "https://www.tiktok.com/"
        )
        headers = self._get_bypass_headers(referer_url)
        headers["Range"] = "bytes=0-19"  # Only fetch first 20 bytes
        cookies = self._get_cookies_from_context(
            video_info._download_context, image_url
        )

        # Use proxy from context unless data_only_proxy is True
        proxy = None
        if not self.data_only_proxy:
            proxy = video_info._download_context.get("proxy")

        session = self._get_curl_session()

        response = None
        try:
            response = await session.get(
                image_url,
                headers=headers,
                cookies=cookies,
                proxy=proxy,
                timeout=10,
                allow_redirects=True,
            )
            if response.status_code in (200, 206):  # 206 = Partial Content
                return self._detect_format_from_bytes(response.content)
            else:
                logger.warning(
                    f"Range request returned status {response.status_code} for {image_url}"
                )
                return ".heic"  # Assume needs processing on error
        except Exception as e:
            logger.debug(f"Range request failed for {image_url}: {e}")
            return ".heic"  # Assume needs processing on error
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _detect_format_from_bytes(data: bytes) -> str:
        """Detect image format from magic bytes."""
        if data.startswith(b"\xff\xd8\xff"):
            return ".jpg"
        elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
            return ".webp"
        elif len(data) >= 12 and (
            data[4:12] == b"ftypheic" or data[4:12] == b"ftypmif1"
        ):
            return ".heic"
        else:
            return ".jpg"  # Unknown format, default to jpg

    async def video(self, video_link: str) -> VideoInfo:
        """
        Extract video/slideshow data from TikTok URL.

        Uses curl_cffi for both webpage fetching and media download (same bypass method).
        Uses yt-dlp only for parsing the fetched HTML, not for network requests.

        For retry logic with proxy rotation, use video_with_retry() instead.

        Args:
            video_link: TikTok video or slideshow URL

        Returns:
            VideoInfo: Object containing video/slideshow information.
                - For videos: data contains bytes, url contains direct video URL
                - For slideshows: data contains list of image URLs

        Raises:
            TikTokDeletedError: Video was deleted by creator
            TikTokPrivateError: Video is private
            TikTokNetworkError: Network/connection error
            TikTokRateLimitError: Too many requests
            TikTokRegionError: Video not available in region
            TikTokExtractionError: Generic extraction failure
        """
        from data.config import config

        try:
            # Get proxy for this request
            request_proxy: Optional[str] = None
            if self.proxy_manager:
                request_proxy = self.proxy_manager.get_next_proxy()

            # Resolve short URLs
            full_url = await self._resolve_url(video_link)
            video_id = self._extract_video_id(full_url)
            logger.debug(f"Extracted video ID: {video_id} from URL: {full_url}")

            if not video_id:
                logger.error(f"Could not extract video ID from {video_link}")
                raise TikTokExtractionError(
                    f"Could not extract video ID from {video_link}"
                )

            # Normalize /photo/ to /video/ URL - yt-dlp's parsing expects /video/ structure
            normalized_url = full_url.replace("/photo/", "/video/")

            # Step 1: Fetch webpage using curl_cffi
            webpage, final_url = await self._fetch_webpage_async(
                normalized_url, proxy=request_proxy
            )

            # Step 2: Parse webpage using yt-dlp (no network)
            video_data, status = self._parse_webpage_data(webpage, video_id, final_url)

            # Check for error status
            if status:
                self._raise_for_status(status, video_link)

            if not video_data:
                raise TikTokExtractionError(
                    f"Failed to extract video info for {video_link}"
                )

            # Step 3: Check if it's a slideshow
            image_post = video_data.get("imagePost")
            if image_post:
                images = image_post.get("images", [])
                image_urls = []
                for img in images:
                    url_list = img.get("imageURL", {}).get("urlList", [])
                    if url_list:
                        image_urls.append(url_list[0])

                if image_urls:
                    author = video_data.get("author", {}).get("uniqueId", "")
                    # Create minimal download context for slideshow image downloads
                    download_context = {
                        "referer_url": full_url,
                        "proxy": request_proxy,
                    }
                    return VideoInfo(
                        type="images",
                        data=image_urls,
                        id=int(video_id),
                        cover=None,
                        width=None,
                        height=None,
                        duration=None,
                        author=author,
                        link=video_link,
                        url=None,
                        _download_context=download_context,
                    )

            # Step 4: It's a video - extract URL and download
            video_info = video_data.get("video", {})
            duration = video_info.get("duration")
            if duration:
                duration = int(duration)

            # Check max duration limit
            perf_config = config.get("performance", {})
            max_video_duration = perf_config.get("max_video_duration", 1800)
            if max_video_duration > 0 and duration and duration > max_video_duration:
                logger.warning(
                    f"Video {video_link} exceeds max duration: {duration}s > {max_video_duration}s"
                )
                raise TikTokVideoTooLongError(
                    f"Video is {duration // 60} minutes long, "
                    f"max allowed is {max_video_duration // 60} minutes"
                )

            # Get video URL
            video_url = None
            play_addr = video_info.get("playAddr")
            if play_addr:
                video_url = play_addr
            if not video_url:
                download_addr = video_info.get("downloadAddr")
                if download_addr:
                    video_url = download_addr
            if not video_url:
                bitrate_info = video_info.get("bitrateInfo", [])
                for br in bitrate_info:
                    play_addr_obj = br.get("PlayAddr", {})
                    url_list = play_addr_obj.get("UrlList", [])
                    if url_list:
                        video_url = url_list[0]
                        break

            if not video_url:
                logger.error(f"Could not find video URL in raw data for {video_link}")
                raise TikTokExtractionError(
                    f"Could not find video URL for {video_link}"
                )

            # Step 5: Download video using curl_cffi
            video_bytes = await self._download_video_with_rotation(
                video_url,
                referer_url=full_url,
                initial_proxy=request_proxy,
                duration=duration,
            )

            if video_bytes is None:
                raise TikTokExtractionError(f"Failed to download video {video_link}")

            logger.info(f"Successfully downloaded video {video_id}")

            # Extract metadata
            width = video_info.get("width")
            height = video_info.get("height")
            author = video_data.get("author", {}).get("uniqueId", "")
            cover = video_info.get("cover") or video_info.get("originCover")

            return VideoInfo(
                type="video",
                data=video_bytes,
                id=int(video_id),
                cover=cover,
                width=int(width) if width else None,
                height=int(height) if height else None,
                duration=duration,
                author=author,
                link=video_link,
                url=video_url,
            )

        except TikTokError:
            raise
        except asyncio.CancelledError:
            logger.debug(f"Video extraction cancelled for {video_link}")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting video {video_link}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting video {video_link}: {e}")
            raise TikTokExtractionError(f"Failed to extract video: {e}") from e

    async def video_with_retry(
        self,
        video_link: str,
        max_attempts: int = 3,
        request_timeout: float = 10.0,
        base_delay: float = 1.0,
        on_retry: Callable[[int], Awaitable[None]] | None = None,
    ) -> VideoInfo:
        """
        Extract video info with retry logic, proxy persistence, and unified curl_cffi flow.

        Uses curl_cffi for both webpage fetching and media download (same bypass method).
        Uses yt-dlp only for parsing the fetched HTML, not for network requests.

        Proxy behavior:
        - All attempts use proxies from the pool
        - When extraction succeeds with a proxy, the same proxy is used for download
        - On extraction failure, rotates to next proxy before retry
        - On download failure, rotates proxy during download retries

        Args:
            video_link: TikTok video URL
            max_attempts: Maximum number of attempts (default: 3)
            request_timeout: Timeout per request in seconds (default: 10)
            base_delay: Base delay for exponential backoff in seconds (default: 1.0)
            on_retry: Optional async callback called with attempt number (1, 2, 3...)
                     before each attempt. Use for updating status (e.g., emoji reactions).

        Returns:
            VideoInfo object containing video/slideshow data

        Raises:
            TikTokDeletedError: Video was deleted (not retried)
            TikTokPrivateError: Video is private (not retried)
            TikTokRegionError: Video geo-blocked (not retried)
            TikTokNetworkError: Network error after all retries exhausted
            TikTokRateLimitError: Rate limited after all retries exhausted
            TikTokExtractionError: Extraction error after all retries exhausted

        Example:
            async def update_status(attempt: int):
                emojis = ["👀", "🔄", "⏳"]
                await message.react([ReactionTypeEmoji(emoji=emojis[attempt - 1])])

            video_info = await client.video_with_retry(
                video_link,
                max_attempts=3,
                request_timeout=10.0,
                on_retry=update_status,
            )
        """
        from data.config import config

        last_error: Exception | None = None

        # Get first proxy from pool (all attempts use proxies)
        current_proxy: Optional[str] = None
        if self.proxy_manager:
            current_proxy = self.proxy_manager.get_next_proxy()

        # Resolve short URLs once (outside retry loop)
        full_url = await self._resolve_url(video_link)
        video_id = self._extract_video_id(full_url)
        if not video_id:
            raise TikTokExtractionError(f"Could not extract video ID from {video_link}")

        # Normalize /photo/ to /video/ URL - yt-dlp's parsing expects /video/ structure
        normalized_url = full_url.replace("/photo/", "/video/")
        logger.debug(f"Extracted video ID: {video_id} from URL: {full_url}")

        for attempt in range(1, max_attempts + 1):
            logger.debug(
                f"Attempt {attempt}/{max_attempts} for {video_link} "
                f"(proxy: {_strip_proxy_auth(current_proxy)})"
            )
            try:
                # Call status callback before each attempt
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    # Step 1: Fetch webpage using curl_cffi
                    webpage, final_url = await self._fetch_webpage_async(
                        normalized_url, proxy=current_proxy
                    )

                    # Step 2: Parse webpage using yt-dlp (no network)
                    video_data, status = self._parse_webpage_data(
                        webpage, video_id, final_url
                    )

                    # Check for error status
                    if status:
                        self._raise_for_status(status, video_link)

                    if not video_data:
                        raise TikTokExtractionError(
                            f"Failed to extract video info for {video_link}"
                        )

                    # Step 3: Check if it's a slideshow
                    image_post = video_data.get("imagePost")
                    if image_post:
                        images = image_post.get("images", [])
                        image_urls = []
                        for img in images:
                            url_list = img.get("imageURL", {}).get("urlList", [])
                            if url_list:
                                image_urls.append(url_list[0])

                        if image_urls:
                            author = video_data.get("author", {}).get("uniqueId", "")
                            # Create minimal download context for slideshow image downloads
                            download_context = {
                                "referer_url": full_url,
                                "proxy": current_proxy,
                            }
                            return VideoInfo(
                                type="images",
                                data=image_urls,
                                id=int(video_id),
                                cover=None,
                                width=None,
                                height=None,
                                duration=None,
                                author=author,
                                link=video_link,
                                url=None,
                                _download_context=download_context,
                            )

                    # Step 4: It's a video - extract URL and download
                    video_info = video_data.get("video", {})
                    duration = video_info.get("duration")
                    if duration:
                        duration = int(duration)

                    # Check max duration limit
                    perf_config = config.get("performance", {})
                    max_video_duration = perf_config.get("max_video_duration", 1800)
                    if (
                        max_video_duration > 0
                        and duration
                        and duration > max_video_duration
                    ):
                        raise TikTokVideoTooLongError(
                            f"Video is {duration // 60} minutes long, "
                            f"max allowed is {max_video_duration // 60} minutes"
                        )

                    # Get video URL
                    video_url = None
                    play_addr = video_info.get("playAddr")
                    if play_addr:
                        video_url = play_addr
                    if not video_url:
                        download_addr = video_info.get("downloadAddr")
                        if download_addr:
                            video_url = download_addr
                    if not video_url:
                        bitrate_info = video_info.get("bitrateInfo", [])
                        for br in bitrate_info:
                            play_addr_obj = br.get("PlayAddr", {})
                            url_list = play_addr_obj.get("UrlList", [])
                            if url_list:
                                video_url = url_list[0]
                                break

                    if not video_url:
                        raise TikTokExtractionError(
                            f"Could not find video URL for {video_link}"
                        )

                    # Step 5: Download video using same proxy that worked for extraction
                    video_bytes = await self._download_video_with_rotation(
                        video_url,
                        referer_url=full_url,
                        initial_proxy=current_proxy,
                        duration=duration,
                    )

                    if video_bytes is None:
                        raise TikTokExtractionError(
                            f"Failed to download video {video_link}"
                        )

                    logger.info(f"Successfully downloaded video {video_id}")

                    # Extract metadata
                    width = video_info.get("width")
                    height = video_info.get("height")
                    author = video_data.get("author", {}).get("uniqueId", "")
                    cover = video_info.get("cover") or video_info.get("originCover")

                    return VideoInfo(
                        type="video",
                        data=video_bytes,
                        id=int(video_id),
                        cover=cover,
                        width=int(width) if width else None,
                        height=int(height) if height else None,
                        duration=duration,
                        author=author,
                        link=video_link,
                        url=video_url,
                    )

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} timed out after "
                    f"{request_timeout}s for {video_link}"
                )
                last_error = e

            except (
                TikTokNetworkError,
                TikTokRateLimitError,
                TikTokExtractionError,
            ) as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for {video_link}: {e}"
                )
                last_error = e

            except (TikTokDeletedError, TikTokPrivateError, TikTokRegionError):
                # Permanent errors - don't retry, raise immediately
                raise

            except TikTokVideoTooLongError:
                # Video too long - don't retry
                raise

            except TikTokError:
                # Any other TikTok error - don't retry
                raise

            # On failure: rotate to next proxy before retry
            if attempt < max_attempts:
                if self.proxy_manager:
                    old_proxy = current_proxy
                    current_proxy = self.proxy_manager.get_next_proxy()
                    logger.debug(
                        f"Rotating proxy for retry: {_strip_proxy_auth(old_proxy)} -> "
                        f"{_strip_proxy_auth(current_proxy)}"
                    )

                # Exponential backoff with jitter
                delay = base_delay * (2 ** (attempt - 1))
                jitter = delay * 0.1 * (2 * random.random() - 1)
                delay = max(0.5, delay + jitter)
                logger.debug(
                    f"Retry backoff: sleeping {delay:.2f}s before attempt {attempt + 1}"
                )
                await asyncio.sleep(delay)

        # All attempts exhausted
        logger.error(
            f"All {max_attempts} attempts failed for {video_link}: {last_error}"
        )

        if isinstance(last_error, asyncio.TimeoutError):
            raise TikTokNetworkError(f"Request timed out after {max_attempts} attempts")

        if last_error:
            raise last_error

        raise TikTokExtractionError(
            f"Failed to extract video after {max_attempts} attempts"
        )

    async def music(self, video_id: int) -> MusicInfo:
        """
        Extract music info from a TikTok video.

        Uses curl_cffi for both webpage fetching and audio download (same bypass method).
        Uses yt-dlp only for parsing the fetched HTML, not for network requests.

        Args:
            video_id: TikTok video ID

        Returns:
            MusicInfo: Object containing music/audio information

        Raises:
            TikTokDeletedError: Video was deleted by creator
            TikTokPrivateError: Video is private
            TikTokNetworkError: Network/connection error
            TikTokRateLimitError: Too many requests
            TikTokRegionError: Video not available in region
            TikTokExtractionError: Generic extraction failure
        """
        try:
            # Get proxy for this request
            request_proxy: Optional[str] = None
            if self.proxy_manager:
                request_proxy = self.proxy_manager.get_next_proxy()

            # Construct a URL with the video ID
            url = f"https://www.tiktok.com/@_/video/{video_id}"
            logger.debug(f"Using video ID: {video_id} for music extraction")

            # Step 1: Fetch webpage using curl_cffi
            webpage, final_url = await self._fetch_webpage_async(
                url, proxy=request_proxy
            )

            # Step 2: Parse webpage using yt-dlp (no network)
            video_data, status = self._parse_webpage_data(
                webpage, str(video_id), final_url
            )

            # Check for error status
            if status:
                self._raise_for_status(status, str(video_id))

            if video_data is None:
                raise TikTokExtractionError(f"No data returned for video {video_id}")

            # Get music info
            music_info = video_data.get("music")
            if not music_info:
                raise TikTokExtractionError(f"No music info found for video {video_id}")

            music_url = music_info.get("playUrl")
            if not music_url:
                raise TikTokExtractionError(f"No music URL found for video {video_id}")

            # Step 3: Download audio using curl_cffi with same proxy
            audio_bytes = await self._download_video_with_rotation(
                music_url,
                referer_url=url,
                initial_proxy=request_proxy,
            )
            if audio_bytes is None:
                raise TikTokExtractionError(
                    f"Failed to download audio for video {video_id}"
                )

            logger.info(f"Successfully downloaded music from video {video_id}")

            # Get the music cover URL from music object
            cover_url = (
                music_info.get("coverLarge")
                or music_info.get("coverMedium")
                or music_info.get("coverThumb")
                or ""
            )

            return MusicInfo(
                data=audio_bytes,
                id=int(video_id),
                title=music_info.get("title", ""),
                author=music_info.get("authorName", ""),
                duration=int(music_info.get("duration", 0)),
                cover=cover_url,
            )

        except TikTokError:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting music for video {video_id}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting music for video {video_id}: {e}")
            raise TikTokExtractionError(f"Failed to extract music: {e}") from e

    async def music_with_retry(
        self,
        video_id: int,
        max_attempts: int = 3,
        request_timeout: float = 10.0,
        base_delay: float = 1.0,
        on_retry: Callable[[int], Awaitable[None]] | None = None,
    ) -> MusicInfo:
        """
        Extract music info with retry logic, proxy persistence, and unified curl_cffi flow.

        Uses curl_cffi for both webpage fetching and audio download (same bypass method).
        Uses yt-dlp only for parsing the fetched HTML, not for network requests.

        Proxy behavior:
        - All attempts use proxies from the pool
        - When extraction succeeds with a proxy, the same proxy is used for download
        - On extraction failure, rotates to next proxy before retry
        - On download failure, rotates proxy during download retries

        Args:
            video_id: TikTok video ID
            max_attempts: Maximum number of attempts (default: 3)
            request_timeout: Timeout per request in seconds (default: 10)
            base_delay: Base delay for exponential backoff in seconds (default: 1.0)
            on_retry: Optional async callback called with attempt number (1, 2, 3...)
                     before each attempt. Use for updating status (e.g., emoji reactions).

        Returns:
            MusicInfo object containing audio data

        Raises:
            TikTokDeletedError: Video was deleted (not retried)
            TikTokPrivateError: Video is private (not retried)
            TikTokRegionError: Video geo-blocked (not retried)
            TikTokNetworkError: Network error after all retries exhausted
            TikTokRateLimitError: Rate limited after all retries exhausted
            TikTokExtractionError: Extraction error after all retries exhausted

        Example:
            async def update_status(attempt: int):
                emojis = ["👀", "🔄", "⏳"]
                await message.react([ReactionTypeEmoji(emoji=emojis[attempt - 1])])

            music_info = await client.music_with_retry(
                video_id,
                max_attempts=3,
                request_timeout=10.0,
                on_retry=update_status,
            )
        """
        last_error: Exception | None = None

        # Get first proxy from pool (all attempts use proxies)
        current_proxy: Optional[str] = None
        if self.proxy_manager:
            current_proxy = self.proxy_manager.get_next_proxy()

        # Construct a URL with the video ID
        url = f"https://www.tiktok.com/@_/video/{video_id}"

        for attempt in range(1, max_attempts + 1):
            logger.debug(
                f"Attempt {attempt}/{max_attempts} for music from video {video_id} "
                f"(proxy: {_strip_proxy_auth(current_proxy)})"
            )
            try:
                # Call status callback before each attempt
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    # Step 1: Fetch webpage using curl_cffi
                    webpage, final_url = await self._fetch_webpage_async(
                        url, proxy=current_proxy
                    )

                    # Step 2: Parse webpage using yt-dlp (no network)
                    video_data, status = self._parse_webpage_data(
                        webpage, str(video_id), final_url
                    )

                    # Check for error status
                    if status:
                        self._raise_for_status(status, str(video_id))

                    if video_data is None:
                        raise TikTokExtractionError(
                            f"No data returned for video {video_id}"
                        )

                    # Get music info
                    music_info = video_data.get("music")
                    if not music_info:
                        raise TikTokExtractionError(
                            f"No music info found for video {video_id}"
                        )

                    music_url = music_info.get("playUrl")
                    if not music_url:
                        raise TikTokExtractionError(
                            f"No music URL found for video {video_id}"
                        )

                    # Step 3: Download audio using same proxy that worked for extraction
                    audio_bytes = await self._download_video_with_rotation(
                        music_url,
                        referer_url=url,
                        initial_proxy=current_proxy,
                    )
                    if audio_bytes is None:
                        raise TikTokExtractionError(
                            f"Failed to download audio for video {video_id}"
                        )

                    logger.info(f"Successfully downloaded music from video {video_id}")

                    # Get the music cover URL
                    cover_url = (
                        music_info.get("coverLarge")
                        or music_info.get("coverMedium")
                        or music_info.get("coverThumb")
                        or ""
                    )

                    return MusicInfo(
                        data=audio_bytes,
                        id=int(video_id),
                        title=music_info.get("title", ""),
                        author=music_info.get("authorName", ""),
                        duration=int(music_info.get("duration", 0)),
                        cover=cover_url,
                    )

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} timed out after "
                    f"{request_timeout}s for music from video {video_id}"
                )
                last_error = e

            except (
                TikTokNetworkError,
                TikTokRateLimitError,
                TikTokExtractionError,
            ) as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for music from video {video_id}: {e}"
                )
                last_error = e

            except (TikTokDeletedError, TikTokPrivateError, TikTokRegionError):
                # Permanent errors - don't retry, raise immediately
                raise

            except TikTokError:
                # Any other TikTok error - don't retry
                raise

            # On failure: rotate to next proxy before retry
            if attempt < max_attempts:
                if self.proxy_manager:
                    old_proxy = current_proxy
                    current_proxy = self.proxy_manager.get_next_proxy()
                    logger.debug(
                        f"Rotating proxy for retry: {_strip_proxy_auth(old_proxy)} -> "
                        f"{_strip_proxy_auth(current_proxy)}"
                    )

                # Exponential backoff with jitter
                delay = base_delay * (2 ** (attempt - 1))
                jitter = delay * 0.1 * (2 * random.random() - 1)
                delay = max(0.5, delay + jitter)
                logger.debug(
                    f"Retry backoff: sleeping {delay:.2f}s before attempt {attempt + 1}"
                )
                await asyncio.sleep(delay)

        # All attempts exhausted
        logger.error(
            f"All {max_attempts} attempts failed for music from video {video_id}: {last_error}"
        )

        if isinstance(last_error, asyncio.TimeoutError):
            raise TikTokNetworkError(f"Request timed out after {max_attempts} attempts")

        if last_error:
            raise last_error

        raise TikTokExtractionError(
            f"Failed to extract music after {max_attempts} attempts"
        )


# Backwards compatibility alias
ttapi = TikTokClient
