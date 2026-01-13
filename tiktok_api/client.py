"""TikTok API client for extracting video and music information."""

import asyncio
import logging
import os
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Tuple

import aiohttp
from aiohttp import TCPConnector, ClientTimeout
import yt_dlp

# Dynamic import of yt-dlp bypass mechanisms (updates automatically with yt-dlp)
from yt_dlp.utils import std_headers as YTDLP_STD_HEADERS

from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokNetworkError,
    TikTokPrivateError,
    TikTokRateLimitError,
    TikTokRegionError,
)
from .models import MusicInfo, VideoInfo

if TYPE_CHECKING:
    from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

# Regex for extracting video ID from redirected URLs (used by legacy get_id functions)
_redirect_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+?/([0-9]+)")


class TikTokClient:
    """Client for extracting TikTok video and music information.

    This client uses yt-dlp internally to extract video/slideshow data and music
    from TikTok URLs. It supports both regular videos and slideshows (image posts).

    All media downloads (video, audio, images) use async aiohttp with yt-dlp's
    bypass headers and cookies for high-throughput performance.

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
        """Get or create shared aiohttp connector with connection pooling.

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
        self, media_url: str, download_context: dict[str, Any]
    ) -> Optional[bytes]:
        """Download media asynchronously using aiohttp with yt-dlp bypass.

        This is the primary download method - uses async aiohttp for non-blocking
        downloads with headers and cookies dynamically imported from yt-dlp.

        Args:
            media_url: Direct URL to the media on TikTok CDN
            download_context: Dict containing 'ydl', 'ie', 'referer_url', and 'proxy'

        Returns:
            Media bytes if successful, None otherwise
        """
        referer_url = download_context.get("referer_url", "https://www.tiktok.com/")
        headers = self._get_bypass_headers(referer_url)

        # Get cookies using yt-dlp's cookie handling for proper domain matching
        cookies = self._get_cookies_from_context(download_context, media_url)

        # Use proxy from context unless data_only_proxy is True
        proxy = None
        if not self.data_only_proxy:
            proxy = download_context.get("proxy")

        connector = self._get_connector(
            self.aiohttp_pool_size, self.aiohttp_limit_per_host
        )
        # Add sock_read timeout to prevent slow-drip attacks holding connections
        timeout = ClientTimeout(total=60, connect=10, sock_read=30)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                connector_owner=False,  # Don't close shared connector
            ) as session:
                async with session.get(
                    media_url,
                    headers=headers,
                    cookies=cookies,
                    proxy=proxy,
                ) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(
                            f"Media download failed with status {response.status} "
                            f"for {media_url}"
                        )
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"aiohttp media download failed for {media_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading media {media_url}: {e}")
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
        """Resolve short URLs (vm.tiktok.com, vt.tiktok.com) to full URLs.

        Uses shared connector for connection pooling efficiency.
        """
        if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
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
        self, use_proxy: bool = True, explicit_proxy: Optional[str] = None
    ) -> dict[str, Any]:
        """Get base yt-dlp options.

        Args:
            use_proxy: If True and no explicit_proxy is given, use proxy from config.
                       If False, no proxy is used (for media downloads when data_only_proxy=True).
            explicit_proxy: If provided, use this specific proxy instead of getting one
                           from rotation. Used for per-request proxy assignment.

        Returns:
            Dict of yt-dlp options.
        """
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
        }

        # Use explicit proxy if provided, otherwise get from rotation if enabled
        if explicit_proxy is not None:
            opts["proxy"] = explicit_proxy
            logger.debug(f"Using explicit proxy: {explicit_proxy}")
        elif use_proxy and self.proxy_manager:
            proxy = self.proxy_manager.get_next_proxy()
            if proxy is not None:  # None means direct connection
                opts["proxy"] = proxy
                logger.debug(f"Using proxy: {proxy}")
            else:
                logger.debug("Using direct connection (no proxy)")

        if self.cookies:
            opts["cookiefile"] = self.cookies
            logger.debug(f"yt-dlp using cookie file: {self.cookies}")
        return opts

    def _extract_raw_data_sync(
        self, url: str, video_id: str, explicit_proxy: Optional[str] = None
    ) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """
        Extract raw TikTok data using yt-dlp's internal API.
        This method supports both videos AND slideshows.

        Args:
            url: The TikTok URL to extract
            video_id: The video ID extracted from the URL
            explicit_proxy: Optional explicit proxy to use for this request.
                           If provided, this proxy is used instead of rotation.

        NOTE: This code relies on yt-dlp's private API (_extract_web_data_and_status),
        which may change or be removed in future yt-dlp releases. Keep yt-dlp up-to-date
        and be prepared to update this code if the private API changes.
        """
        ydl_opts = self._get_ydl_opts(use_proxy=True, explicit_proxy=explicit_proxy)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get the TikTok extractor
                ie = ydl.get_info_extractor("TikTok")
                ie.set_downloader(ydl)

                # Convert /photo/ to /video/ URL (yt-dlp requirement)
                normalized_url = url.replace("/photo/", "/video/")

                # Guard: Check if the private method exists before calling it.
                # This method is part of yt-dlp's internal API and may be absent
                # in future releases.
                if not hasattr(ie, "_extract_web_data_and_status"):
                    logger.error(
                        "yt-dlp's TikTok extractor is missing '_extract_web_data_and_status' method. "
                        f"Current yt-dlp version: {yt_dlp.version.__version__}. "
                        "Please update yt-dlp to a compatible version: pip install -U yt-dlp"
                    )
                    raise TikTokExtractionError(
                        "Incompatible yt-dlp version: missing required internal method. "
                        "Please update yt-dlp: pip install -U yt-dlp"
                    )

                try:
                    # Use yt-dlp's internal method to get raw webpage data
                    video_data, status = ie._extract_web_data_and_status(
                        normalized_url, video_id
                    )
                except AttributeError as e:
                    logger.error(
                        f"Failed to call yt-dlp internal method: {e}. "
                        f"Current yt-dlp version: {yt_dlp.version.__version__}. "
                        "Please update yt-dlp: pip install -U yt-dlp"
                    )
                    raise TikTokExtractionError(
                        "Incompatible yt-dlp version. Please update yt-dlp: pip install -U yt-dlp"
                    ) from e

                return video_data, status
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if (
                "unavailable" in error_msg
                or "removed" in error_msg
                or "deleted" in error_msg
            ):
                logger.warning(f"Video appears deleted: {e}")
                return None, "deleted"
            elif "private" in error_msg:
                logger.warning(f"Video is private: {e}")
                return None, "private"
            elif "rate" in error_msg or "too many" in error_msg or "429" in error_msg:
                logger.warning(f"Rate limited: {e}")
                return None, "rate_limit"
            elif (
                "region" in error_msg
                or "geo" in error_msg
                or "country" in error_msg
                or "not available in your" in error_msg
            ):
                logger.warning(f"Region blocked: {e}")
                return None, "region"
            # IP blocked and other errors -> generic extraction error
            logger.error(
                f"yt-dlp download error for video {video_id} ({url}): {e}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Proxy: {self._get_proxy_info()}\n"
                f"  Cookies: {self.cookies or 'None'}"
            )
            return None, "extraction"
        except yt_dlp.utils.ExtractorError as e:
            error_msg = str(e)
            logger.error(
                f"yt-dlp extractor error for video {video_id} ({url}): {error_msg}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Proxy: {self._get_proxy_info()}\n"
                f"  Cookies: {self.cookies or 'None'}"
            )
            # Log additional guidance for common issues
            if "unable to extract" in error_msg.lower():
                logger.error(
                    "This may indicate TikTok changed their page structure. "
                    "Try updating yt-dlp: pip install -U yt-dlp\n"
                    "If the issue persists, check https://github.com/yt-dlp/yt-dlp/issues"
                )
            return None, "extraction"
        except TikTokError:
            raise
        except Exception as e:
            logger.error(
                f"yt-dlp extraction failed for video {video_id} ({url}): {e}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Error type: {type(e).__name__}",
                exc_info=True,
            )
            return None, "extraction"

    def _extract_with_context_sync(
        self, url: str, video_id: str, request_proxy: Optional[str] = None
    ) -> Tuple[Optional[dict[str, Any]], Optional[str], Optional[dict[str, Any]]]:
        """
        Extract TikTok data and return the download context for later media downloads.

        This method keeps the YoutubeDL instance alive so it can be reused for
        downloading media (videos, images) with the same auth context.

        Args:
            url: The TikTok URL to extract
            video_id: The video ID extracted from the URL
            request_proxy: Optional explicit proxy to use for this request.
                          If provided, this proxy will be stored in download_context
                          for use in media downloads (per-request proxy assignment).

        Returns:
            Tuple of (video_data, status, download_context)
            - video_data: Raw TikTok API response
            - status: Error status string or None
            - download_context: Dict with 'ydl', 'ie', 'referer_url', 'proxy' for media downloads

        Note:
            The caller is responsible for closing the YDL instance in download_context
            when done. On error paths, this method closes the YDL instance before returning.
        """
        ydl_opts = self._get_ydl_opts(use_proxy=True, explicit_proxy=request_proxy)
        ydl = None

        try:
            # Create YDL instance WITHOUT context manager so it stays alive
            ydl = yt_dlp.YoutubeDL(ydl_opts)

            # Get the TikTok extractor
            ie = ydl.get_info_extractor("TikTok")
            ie.set_downloader(ydl)

            # Convert /photo/ to /video/ URL (yt-dlp requirement)
            normalized_url = url.replace("/photo/", "/video/")

            # Guard: Check if the private method exists
            if not hasattr(ie, "_extract_web_data_and_status"):
                logger.error(
                    "yt-dlp's TikTok extractor is missing '_extract_web_data_and_status' method. "
                    f"Current yt-dlp version: {yt_dlp.version.__version__}. "
                    "Please update yt-dlp: pip install -U yt-dlp"
                )
                raise TikTokExtractionError(
                    "Incompatible yt-dlp version: missing required internal method. "
                    "Please update yt-dlp: pip install -U yt-dlp"
                )

            try:
                # Use yt-dlp's internal method to get raw webpage data
                # This also sets up all necessary cookies
                video_data, status = ie._extract_web_data_and_status(
                    normalized_url, video_id
                )
            except AttributeError as e:
                logger.error(
                    f"Failed to call yt-dlp internal method: {e}. "
                    f"Current yt-dlp version: {yt_dlp.version.__version__}. "
                    "Please update yt-dlp: pip install -U yt-dlp"
                )
                raise TikTokExtractionError(
                    "Incompatible yt-dlp version. Please update: pip install -U yt-dlp"
                ) from e

            # Create download context with the live instances
            download_context = {
                "ydl": ydl,
                "ie": ie,
                "referer_url": url,
                "proxy": request_proxy,  # Store proxy for per-request assignment
            }

            # Success - transfer ownership of ydl to caller via download_context
            # Set ydl to None so finally block doesn't close it
            ydl = None
            return video_data, status, download_context

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if (
                "unavailable" in error_msg
                or "removed" in error_msg
                or "deleted" in error_msg
            ):
                logger.warning(f"Video appears deleted: {e}")
                return None, "deleted", None
            elif "private" in error_msg:
                logger.warning(f"Video is private: {e}")
                return None, "private", None
            elif "rate" in error_msg or "too many" in error_msg or "429" in error_msg:
                logger.warning(f"Rate limited: {e}")
                return None, "rate_limit", None
            elif (
                "region" in error_msg
                or "geo" in error_msg
                or "country" in error_msg
                or "not available in your" in error_msg
            ):
                logger.warning(f"Region blocked: {e}")
                return None, "region", None
            logger.error(
                f"yt-dlp download error for video {video_id} ({url}): {e}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Proxy: {self._get_proxy_info()}\n"
                f"  Cookies: {self.cookies or 'None'}"
            )
            return None, "extraction", None
        except yt_dlp.utils.ExtractorError as e:
            error_msg = str(e)
            logger.error(
                f"yt-dlp extractor error for video {video_id} ({url}): {error_msg}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Proxy: {self._get_proxy_info()}\n"
                f"  Cookies: {self.cookies or 'None'}"
            )
            # Log additional guidance for common issues
            if "unable to extract" in error_msg.lower():
                logger.error(
                    "This may indicate TikTok changed their page structure. "
                    "Try updating yt-dlp: pip install -U yt-dlp\n"
                    "If the issue persists, check https://github.com/yt-dlp/yt-dlp/issues"
                )
            return None, "extraction", None
        except TikTokError:
            raise
        except Exception as e:
            logger.error(
                f"yt-dlp extraction failed for video {video_id} ({url}): {e}\n"
                f"  yt-dlp version: {yt_dlp.version.__version__}\n"
                f"  Error type: {type(e).__name__}",
                exc_info=True,
            )
            return None, "extraction", None
        finally:
            # Close ydl if we still own it (i.e., we didn't successfully transfer
            # ownership to the caller via download_context)
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
        self, download_context: Optional[dict[str, Any]]
    ) -> None:
        """Close the YoutubeDL instance in a download context if present.

        Args:
            download_context: Dict containing 'ydl' key with YoutubeDL instance, or None
        """
        if download_context and "ydl" in download_context:
            try:
                download_context["ydl"].close()
            except Exception:
                pass  # Ignore errors during cleanup

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
        Download an image using async aiohttp with yt-dlp bypass headers/cookies.

        This method uses the download context that was saved during video extraction,
        applying the same cookies and headers for authentication.

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

        result = await self._download_media_async(
            image_url, video_info._download_context
        )

        if result is None:
            raise TikTokNetworkError(f"Failed to download image: {image_url}")

        return result

    async def detect_image_format(self, image_url: str, video_info: VideoInfo) -> str:
        """
        Detect image format using HTTP Range request (only fetches first 20 bytes).

        This is much more efficient than downloading the entire image just to
        check its format.

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

        connector = self._get_connector(
            self.aiohttp_pool_size, self.aiohttp_limit_per_host
        )
        timeout = ClientTimeout(total=10, connect=5, sock_read=5)

        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                connector_owner=False,
            ) as session:
                async with session.get(
                    image_url,
                    headers=headers,
                    cookies=cookies,
                    proxy=proxy,
                ) as response:
                    if response.status in (200, 206):  # 206 = Partial Content
                        data = await response.read()
                        return self._detect_format_from_bytes(data)
                    else:
                        logger.warning(
                            f"Range request returned status {response.status} for {image_url}"
                        )
                        return ".heic"  # Assume needs processing on error
        except Exception as e:
            logger.debug(f"Range request failed for {image_url}: {e}")
            return ".heic"  # Assume needs processing on error

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
        download_context = None
        context_transferred = False  # Track if context ownership was transferred

        try:
            # Get proxy once for the entire request (per-request proxy assignment)
            request_proxy: Optional[str] = None
            if self.proxy_manager:
                request_proxy = self.proxy_manager.get_next_proxy()
                if request_proxy:
                    logger.info(f"Video attempt using proxy: {request_proxy}")
                else:
                    logger.info("Video attempt using direct connection (no proxy)")

            # Resolve short URLs
            full_url = await self._resolve_url(video_link)
            video_id = self._extract_video_id(full_url)

            if not video_id:
                logger.error(f"Could not extract video ID from {video_link}")
                raise TikTokExtractionError(
                    f"Could not extract video ID from {video_link}"
                )

            # Extract raw data with download context for authenticated downloads
            # Pass request_proxy for per-request proxy assignment
            video_data, status, download_context = await self._run_sync(
                self._extract_with_context_sync, full_url, video_id, request_proxy
            )

            # Check for error status and raise appropriate exception
            if status and status not in ("ok", None):
                self._raise_for_status(status, video_link)

            # Check if it's a slideshow (imagePost present in raw data)
            if video_data:
                image_post = video_data.get("imagePost")
                if image_post:
                    images = image_post.get("images", [])
                    image_urls = []

                    for img in images:
                        url_list = img.get("imageURL", {}).get("urlList", [])
                        if url_list:
                            # Use first URL (primary CDN)
                            image_urls.append(url_list[0])

                    if image_urls:
                        author = video_data.get("author", {}).get("uniqueId", "")

                        # Transfer context ownership to VideoInfo
                        context_transferred = True
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

            # It's a video - extract video URL from raw data and download to memory
            # No need to call _extract_video_info_sync again - we already have the data

            if not video_data:
                raise TikTokExtractionError(
                    f"Failed to extract video info for {video_link}"
                )

            if not download_context:
                raise TikTokExtractionError(
                    f"No download context available for {video_link}"
                )

            # Get video URL from raw TikTok data
            # Try multiple paths as TikTok API structure can vary
            video_url = None
            video_info = video_data.get("video", {})

            # Try playAddr first (primary playback URL)
            play_addr = video_info.get("playAddr")
            if play_addr:
                video_url = play_addr

            # Try downloadAddr (sometimes has better quality)
            if not video_url:
                download_addr = video_info.get("downloadAddr")
                if download_addr:
                    video_url = download_addr

            # Try bitrateInfo for specific quality URLs
            if not video_url:
                bitrate_info = video_info.get("bitrateInfo", [])
                if bitrate_info:
                    # Get the best quality (usually first or last)
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

            # Download video using async aiohttp with yt-dlp bypass headers/cookies
            video_bytes = await self._download_media_async(video_url, download_context)

            # Close the download context - it's no longer needed for videos
            # (unlike slideshows where we keep it for image downloads)
            self._close_download_context(download_context)
            context_transferred = True  # Mark as handled

            if video_bytes is None:
                raise TikTokExtractionError(f"Failed to download video {video_link}")

            # Log successful download with proxy info
            proxy_info = request_proxy or "direct connection"
            logger.info(
                f"Successfully downloaded video {video_id} using proxy: {proxy_info}"
            )

            # Extract metadata from raw data
            duration = video_info.get("duration")
            if duration:
                duration = int(duration)

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
            # Re-raise TikTok errors as-is
            raise
        except asyncio.CancelledError:
            # Handle cancellation (e.g., from timeout) - ensure cleanup happens
            logger.debug(f"Video extraction cancelled for {video_link}")
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting video {video_link}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting video {video_link}: {e}")
            raise TikTokExtractionError(f"Failed to extract video: {e}") from e
        finally:
            # Clean up download context if ownership wasn't transferred
            if not context_transferred:
                self._close_download_context(download_context)

    async def video_with_retry(
        self,
        video_link: str,
        max_attempts: int = 3,
        request_timeout: float = 10.0,
        base_delay: float = 1.0,
        on_retry: Callable[[int], Awaitable[None]] | None = None,
    ) -> VideoInfo:
        """
        Extract video info with retry logic and per-request timeout.

        Each request times out after `request_timeout` seconds. On timeout or
        transient errors (network, rate limit, extraction), retries with exponential
        backoff. Does NOT retry on permanent errors (deleted, private, region).

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
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                # Call status callback before each attempt
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    return await self.video(video_link)

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

            except TikTokError:
                # Any other TikTok error - don't retry
                raise

            # Exponential backoff with jitter (only if not last attempt)
            if attempt < max_attempts:
                # Calculate delay: base_delay * 2^(attempt-1) = 1s, 2s, 4s...
                delay = base_delay * (2 ** (attempt - 1))
                # Add jitter (±10%) to prevent thundering herd
                jitter = delay * 0.1 * (2 * random.random() - 1)
                delay = max(0.5, delay + jitter)  # Minimum 0.5s delay
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

        All network operations are fully async - uses yt-dlp only for metadata
        extraction, then downloads audio via async aiohttp.

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
        download_context = None
        try:
            # Get proxy once for the entire request (per-request proxy assignment)
            request_proxy: Optional[str] = None
            if self.proxy_manager:
                request_proxy = self.proxy_manager.get_next_proxy()
                if request_proxy:
                    logger.info(f"Music attempt using proxy: {request_proxy}")
                else:
                    logger.info("Music attempt using direct connection (no proxy)")

            # Construct a URL with the video ID
            url = f"https://www.tiktok.com/@_/video/{video_id}"

            # Extract with context (keeps YDL alive for authenticated downloads)
            video_data, status, download_context = await self._run_sync(
                self._extract_with_context_sync, url, str(video_id), request_proxy
            )

            # Check for error status and raise appropriate exception
            if status and status not in ("ok", None):
                self._raise_for_status(status, str(video_id))

            if video_data is None:
                raise TikTokExtractionError(f"No data returned for video {video_id}")

            if not download_context:
                raise TikTokExtractionError(
                    f"No download context available for video {video_id}"
                )

            # Get music info
            music_info = video_data.get("music")
            if not music_info:
                raise TikTokExtractionError(f"No music info found for video {video_id}")

            music_url = music_info.get("playUrl")
            if not music_url:
                raise TikTokExtractionError(f"No music URL found for video {video_id}")

            # Download audio using async aiohttp with yt-dlp context (headers, cookies)
            audio_bytes = await self._download_media_async(music_url, download_context)
            if audio_bytes is None:
                raise TikTokExtractionError(
                    f"Failed to download audio for video {video_id}"
                )

            # Log successful download with proxy info
            proxy_info = request_proxy or "direct connection"
            logger.info(
                f"Successfully downloaded music from video {video_id} using proxy: {proxy_info}"
            )

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
            # Re-raise TikTok errors as-is
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting music for video {video_id}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting music for video {video_id}: {e}")
            raise TikTokExtractionError(f"Failed to extract music: {e}") from e
        finally:
            # Always clean up download context
            self._close_download_context(download_context)

    async def music_with_retry(
        self,
        video_id: int,
        max_attempts: int = 3,
        request_timeout: float = 10.0,
        base_delay: float = 1.0,
        on_retry: Callable[[int], Awaitable[None]] | None = None,
    ) -> MusicInfo:
        """
        Extract music info with retry logic and per-request timeout.

        Each request times out after `request_timeout` seconds. On timeout or
        transient errors (network, rate limit, extraction), retries with exponential
        backoff. Does NOT retry on permanent errors (deleted, private, region).

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

        for attempt in range(1, max_attempts + 1):
            try:
                # Call status callback before each attempt
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    return await self.music(video_id)

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

            # Exponential backoff with jitter (only if not last attempt)
            if attempt < max_attempts:
                # Calculate delay: base_delay * 2^(attempt-1) = 1s, 2s, 4s...
                delay = base_delay * (2 ** (attempt - 1))
                # Add jitter (±10%) to prevent thundering herd
                jitter = delay * 0.1 * (2 * random.random() - 1)
                delay = max(0.5, delay + jitter)  # Minimum 0.5s delay
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
