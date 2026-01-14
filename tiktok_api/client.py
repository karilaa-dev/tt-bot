"""TikTok API client for extracting video and music information."""

import asyncio
import http.cookiejar
import json
import logging
import os
import random
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

# curl_cffi for browser impersonation (TLS fingerprint bypass)
import curl_cffi
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from curl_cffi import CurlError

# Static imports from yt-dlp - only used for headers and browser targets
# These are static values, no yt-dlp runtime execution
from yt_dlp.utils import std_headers as YTDLP_STD_HEADERS

try:
    from yt_dlp.networking._curlcffi import BROWSER_TARGETS, _TARGETS_COMPAT_LOOKUP
except ImportError:
    BROWSER_TARGETS = {}
    _TARGETS_COMPAT_LOOKUP = {}

from .exceptions import (
    TikTokDeletedError,
    TikTokError,
    TikTokExtractionError,
    TikTokInvalidLinkError,
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

# Maximum retries for each operation step
MAX_RETRIES = 3


def _strip_proxy_auth(proxy_url: Optional[str]) -> str:
    """Strip authentication info from proxy URL for safe logging."""
    if proxy_url is None:
        return "direct connection"

    match = re.match(r"^((?:https?|socks5h?|socks4a?)://)(?:[^@]+@)?(.+)$", proxy_url)
    if match:
        scheme, host_port = match.groups()
        return f"{scheme}{host_port}"

    return proxy_url


class TikTokClient:
    """Client for extracting TikTok video and music information.

    Uses curl_cffi with browser impersonation for all TikTok operations.
    Proxies are sticky within a single video() or music() call - only rotated on retry.

    Args:
        proxy_manager: Optional ProxyManager for proxy rotation.
        data_only_proxy: If True, proxy is used only for API, not for media downloads.
        cookies: Optional path to Netscape-format cookies file.
        max_video_duration: Maximum video duration in seconds (default from config).
            Videos longer than this raise TikTokVideoTooLongError.
        long_video_threshold: Duration threshold in seconds (default: 60 = 1 min).
            Videos longer than this include metadata (thumbnail, dimensions) in VideoInfo.

    Example:
        >>> from tiktok_api import TikTokClient, ProxyManager
        >>> proxy_manager = ProxyManager.initialize("proxies.txt", include_host=True)
        >>> client = TikTokClient(proxy_manager=proxy_manager, data_only_proxy=True)
        >>> video_info = await client.video("https://www.tiktok.com/@user/video/123")
    """

    # Shared curl_cffi session (class-level singleton)
    _curl_session: Optional[CurlAsyncSession] = None
    _impersonate_target: Optional[str] = None
    _session_lock: Optional[asyncio.Lock] = None

    @classmethod
    def _get_session_lock(cls) -> asyncio.Lock:
        """Get or create session lock. Safe because Lock() creation is atomic."""
        if cls._session_lock is None:
            cls._session_lock = asyncio.Lock()
        return cls._session_lock

    @classmethod
    def _get_impersonate_target(cls) -> str:
        """Get the best impersonation target from yt-dlp's BROWSER_TARGETS."""
        try:
            curl_cffi_version = tuple(
                int(x) for x in curl_cffi.__version__.split(".")[:2]
            )
        except (ValueError, AttributeError):
            curl_cffi_version = (0, 9)

        available_targets: dict[str, Any] = {}
        for version, targets in BROWSER_TARGETS.items():
            if curl_cffi_version >= version:
                available_targets.update(targets)

        if not available_targets:
            logger.warning("No BROWSER_TARGETS available, using 'chrome' fallback")
            return "chrome"

        # Sort by yt-dlp's priority (desktop > mobile, Chrome > Safari > Firefox)
        sorted_targets = sorted(
            available_targets.items(),
            key=lambda x: (
                x[1].os not in ("ios", "android"),
                ("tor", "edge", "firefox", "safari", "chrome").index(x[1].client)
                if x[1].client in ("tor", "edge", "firefox", "safari", "chrome")
                else -1,
                float(x[1].version) if x[1].version else 0,
                x[1].os or "",
            ),
            reverse=True,
        )

        best_name = sorted_targets[0][0]

        if curl_cffi_version < (0, 11):
            best_name = _TARGETS_COMPAT_LOOKUP.get(best_name, best_name)

        logger.debug(f"Selected impersonation target: {best_name}")
        return best_name

    @classmethod
    async def _get_curl_session(cls) -> CurlAsyncSession:
        """Get or create shared curl_cffi AsyncSession (async-safe).

        Uses double-checked locking to ensure only one session is created
        even under concurrent first-use from multiple coroutines.
        """
        # Fast path - already initialized
        if cls._curl_session is not None:
            return cls._curl_session

        # Slow path - acquire lock and double-check
        async with cls._get_session_lock():
            if cls._curl_session is None:
                from data.config import config

                perf_config = config.get("performance", {})
                pool_size = perf_config.get("curl_pool_size", 200)

                cls._impersonate_target = cls._get_impersonate_target()
                cls._curl_session = CurlAsyncSession(
                    impersonate=cls._impersonate_target,  # type: ignore[arg-type]
                    max_clients=pool_size,
                )
                logger.info(
                    f"Created curl_cffi session: impersonate={cls._impersonate_target}, "
                    f"max_clients={pool_size}"
                )
        return cls._curl_session

    @classmethod
    async def initialize_session(cls) -> None:
        """Initialize the shared curl_cffi session.

        Call this at application startup to ensure the session is created
        before any concurrent requests. This avoids the lock overhead during
        normal operation.
        """
        await cls._get_curl_session()
        logger.info("TikTokClient session initialized")

    @classmethod
    async def close_curl_session(cls) -> None:
        """Close shared curl_cffi session. Call on application shutdown."""
        async with cls._get_session_lock():
            session = cls._curl_session
            cls._curl_session = None
            cls._impersonate_target = None
        if session is not None:
            try:
                await session.close()
            except Exception as e:
                logger.debug(f"Error closing curl_cffi session: {e}")

    def __init__(
        self,
        proxy_manager: Optional["ProxyManager"] = None,
        data_only_proxy: bool = False,
        cookies: Optional[str] = None,
        max_video_duration: Optional[int] = None,
        long_video_threshold: int = 60,
        # Legacy parameters - kept for compatibility but unused
        aiohttp_pool_size: int = 200,
        aiohttp_limit_per_host: int = 50,
    ):
        self.proxy_manager = proxy_manager
        self.data_only_proxy = data_only_proxy
        self.long_video_threshold = long_video_threshold

        # Get max_video_duration from config if not specified
        if max_video_duration is None:
            from data.config import config

            perf_config = config.get("performance", {})
            self.max_video_duration = perf_config.get("max_video_duration", 1800)
        else:
            self.max_video_duration = max_video_duration

        # Load cookies from Netscape file
        self._cookies: dict[str, str] = {}
        if cookies is None:
            from data.config import config

            cookies = config.get("tiktok", {}).get("cookies_file", "")
        if cookies:
            self._load_cookies(cookies)

        # URL patterns
        self.mobile_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+")
        self.web_regex = re.compile(r"https?://www\.tiktok\.com/@[^\s]+?/video/[0-9]+")
        self.photo_regex = re.compile(
            r"https?://www\.tiktok\.com/@[^\s]+?/photo/[0-9]+"
        )

        # Data extraction patterns (compiled for performance)
        # Use .*? with DOTALL to handle JSON containing '<' characters (e.g., "I <3 TikTok")
        self._universal_data_re = re.compile(
            r'<script[^>]+\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
            re.DOTALL,
        )
        self._sigi_state_re = re.compile(
            r'<script[^>]+\bid="(?:SIGI_STATE|sigi-persisted-data)"[^>]*>(.*?)</script>',
            re.DOTALL,
        )
        self._next_data_re = re.compile(
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            re.DOTALL,
        )

    def _load_cookies(self, cookies_path: str) -> None:
        """Load cookies from Netscape-format file."""
        if not os.path.isabs(cookies_path):
            cookies_path = os.path.abspath(cookies_path)

        if not os.path.isfile(cookies_path):
            logger.warning(f"Cookie file not found: {cookies_path}")
            return

        try:
            jar = http.cookiejar.MozillaCookieJar(cookies_path)
            jar.load(ignore_discard=True, ignore_expires=True)
            for cookie in jar:
                if "tiktok" in (cookie.domain or "").lower():
                    self._cookies[cookie.name] = cookie.value
            if self._cookies:
                logger.info(f"Loaded {len(self._cookies)} cookies from {cookies_path}")
        except Exception as e:
            logger.warning(f"Failed to load cookies from {cookies_path}: {e}")

    def _get_headers(
        self, referer_url: str = "https://www.tiktok.com/"
    ) -> dict[str, str]:
        """Get request headers with browser-like values."""
        headers = dict(YTDLP_STD_HEADERS)
        headers["Referer"] = referer_url
        headers["Origin"] = "https://www.tiktok.com"
        headers["Accept"] = "*/*"
        return headers

    def _get_initial_proxy(self) -> Optional[str]:
        """Get initial proxy for a request."""
        if self.proxy_manager:
            return self.proxy_manager.get_next_proxy()
        return None

    def _rotate_proxy(self, current_proxy: Optional[str]) -> Optional[str]:
        """Rotate to next proxy on failure."""
        if self.proxy_manager:
            new_proxy = self.proxy_manager.get_next_proxy()
            logger.debug(
                f"Rotating proxy: {_strip_proxy_auth(current_proxy)} -> "
                f"{_strip_proxy_auth(new_proxy)}"
            )
            return new_proxy
        return current_proxy

    # -------------------------------------------------------------------------
    # URL Resolution
    # -------------------------------------------------------------------------

    async def _resolve_short_url(self, url: str, proxy: Optional[str]) -> str:
        """Resolve short URLs (vm.tiktok.com, vt.tiktok.com, /t/) to full URLs."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""

        is_short_url = host in {"vm.tiktok.com", "vt.tiktok.com"} or (
            host in {"www.tiktok.com", "tiktok.com"} and path.startswith("/t/")
        )

        if not is_short_url:
            return url

        session = await self._get_curl_session()
        headers = self._get_headers()

        response = await session.get(
            url,
            headers=headers,
            cookies=self._cookies,
            proxy=proxy,
            timeout=15,
            allow_redirects=True,
        )

        final_url = str(response.url)
        logger.debug(f"Resolved short URL: {url} -> {final_url}")
        return final_url

    def _extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from TikTok URL."""
        match = re.search(r"/(?:video|photo)/(\d+)", url)
        if match:
            return match.group(1)
        return None

    async def _resolve_and_extract_id(
        self, video_link: str, proxy: Optional[str]
    ) -> tuple[str, str, Optional[str]]:
        """Resolve URL and extract video ID with retries.

        Returns:
            Tuple of (full_url, video_id, current_proxy)
        """
        current_proxy = proxy

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                full_url = await self._resolve_short_url(video_link, current_proxy)
                video_id = self._extract_video_id(full_url)

                if not video_id:
                    raise TikTokExtractionError(
                        f"Could not extract video ID from {video_link}"
                    )

                return full_url, video_id, current_proxy

            except (CurlError, TikTokExtractionError) as e:
                if attempt < MAX_RETRIES:
                    current_proxy = self._rotate_proxy(current_proxy)
                    delay = 1.0 * (2 ** (attempt - 1))
                    logger.warning(
                        f"URL resolution attempt {attempt}/{MAX_RETRIES} failed: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise TikTokNetworkError(f"Failed to resolve URL: {e}") from e

            except TikTokError:
                raise

            except Exception as e:
                raise TikTokExtractionError(f"URL resolution failed: {e}") from e

        raise TikTokNetworkError(f"URL resolution failed after {MAX_RETRIES} attempts")

    # -------------------------------------------------------------------------
    # Video Info Extraction
    # -------------------------------------------------------------------------

    def _parse_webpage_data(
        self, html: str, video_id: str
    ) -> tuple[dict[str, Any], int]:
        """Parse video data from TikTok webpage HTML.

        Returns:
            Tuple of (video_data dict, status_code)
        """
        # Try UNIVERSAL_DATA first (most common format)
        match = self._universal_data_re.search(html)
        if match:
            try:
                data = json.loads(match.group(1))
                scope = data.get("__DEFAULT_SCOPE__", {})
                video_detail = scope.get("webapp.video-detail", {})
                status = video_detail.get("statusCode", 0)
                item_info = video_detail.get("itemInfo", {})
                video_data = item_info.get("itemStruct", {})
                if video_data:
                    logger.debug("Parsed video data from UNIVERSAL_DATA")
                    return video_data, status
            except json.JSONDecodeError:
                pass

        # Try SIGI_STATE
        match = self._sigi_state_re.search(html)
        if match:
            try:
                data = json.loads(match.group(1))
                status = data.get("VideoPage", {}).get("statusCode", 0)
                video_data = data.get("ItemModule", {}).get(video_id, {})
                if video_data:
                    logger.debug("Parsed video data from SIGI_STATE")
                    return video_data, status
            except json.JSONDecodeError:
                pass

        # Try Next.js data
        match = self._next_data_re.search(html)
        if match:
            try:
                data = json.loads(match.group(1))
                page_props = data.get("props", {}).get("pageProps", {})
                status = page_props.get("statusCode", 0)
                video_data = page_props.get("itemInfo", {}).get("itemStruct", {})
                if video_data:
                    logger.debug("Parsed video data from NEXT_DATA")
                    return video_data, status
            except json.JSONDecodeError:
                pass

        return {}, -1

    def _check_status(self, status: int, video_link: str) -> None:
        """Check status code and raise appropriate error."""
        if status == 0:
            return  # Success

        if status in (10216, 10222):
            raise TikTokPrivateError(f"Video {video_link} is private")
        elif status == 10204:
            raise TikTokRegionError(f"Video {video_link} is blocked in your region")
        elif status == 10000:
            raise TikTokDeletedError(f"Video {video_link} was deleted")
        elif status != 0 and status != -1:
            logger.warning(f"Unknown TikTok status code: {status}")

    async def _fetch_video_info(
        self, url: str, video_id: str, proxy: Optional[str]
    ) -> dict[str, Any]:
        """Fetch and parse video info from TikTok webpage."""
        # Normalize photo URLs to video URLs (TikTok serves slideshow data on /video/ endpoint)
        normalized_url = url.replace("/photo/", "/video/")

        session = await self._get_curl_session()
        headers = self._get_headers(normalized_url)

        response = await session.get(
            normalized_url,
            headers=headers,
            cookies=self._cookies,
            proxy=proxy,
            timeout=30,
            allow_redirects=True,
        )

        if response.status_code != 200:
            if response.status_code == 429:
                raise TikTokRateLimitError("Rate limited by TikTok")
            raise TikTokNetworkError(f"HTTP {response.status_code}")

        # Check for login redirect
        final_url = str(response.url)
        if "/login" in urlparse(final_url).path:
            raise TikTokPrivateError("TikTok requires login to access this content")

        html = response.text

        # Debug logging - also serves as a timing buffer for curl_cffi response handling
        # (removing this logging has caused intermittent extraction failures)
        has_universal = "__UNIVERSAL_DATA_FOR_REHYDRATION__" in html
        has_sigi = "SIGI_STATE" in html or "sigi-persisted-data" in html
        has_next = "__NEXT_DATA__" in html
        logger.debug(
            f"Fetched {len(html)} bytes, patterns: UNIVERSAL={has_universal}, "
            f"SIGI={has_sigi}, NEXT={has_next}"
        )

        if not any([has_universal, has_sigi, has_next]):
            # Log preview at DEBUG level to avoid exposing sensitive data in production logs
            logger.debug(f"No data patterns found! HTML preview: {html[:2000]}")

        video_data, status = self._parse_webpage_data(html, video_id)

        self._check_status(status, url)

        if not video_data:
            raise TikTokExtractionError("Unable to extract video data from webpage")

        return video_data

    async def _fetch_video_info_with_retry(
        self, url: str, video_id: str, proxy: Optional[str]
    ) -> tuple[dict[str, Any], Optional[str]]:
        """Fetch video info with retries. Returns (video_data, final_proxy)."""
        current_proxy = proxy
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                video_data = await self._fetch_video_info(url, video_id, current_proxy)
                return video_data, current_proxy

            except (TikTokNetworkError, TikTokRateLimitError, CurlError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    current_proxy = self._rotate_proxy(current_proxy)
                    delay = 1.0 * (2 ** (attempt - 1))
                    logger.warning(
                        f"Video info fetch attempt {attempt}/{MAX_RETRIES} failed: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            except TikTokError:
                raise

            except Exception as e:
                raise TikTokExtractionError(f"Video info fetch failed: {e}") from e

        if last_error:
            raise last_error
        raise TikTokExtractionError("Video info fetch failed")

    # -------------------------------------------------------------------------
    # Media Download
    # -------------------------------------------------------------------------

    async def _download_media(
        self,
        media_url: str,
        proxy: Optional[str],
        referer_url: str = "https://www.tiktok.com/",
        timeout: int = 60,
    ) -> bytes:
        """Download media (video, audio, image) from TikTok CDN."""
        session = await self._get_curl_session()
        headers = self._get_headers(referer_url)

        response = await session.get(
            media_url,
            headers=headers,
            cookies=self._cookies,
            proxy=proxy,
            timeout=timeout,
            allow_redirects=True,
        )

        if response.status_code != 200:
            raise TikTokNetworkError(
                f"Media download failed: HTTP {response.status_code}"
            )

        return response.content

    async def _download_media_with_retry(
        self,
        media_url: str,
        proxy: Optional[str],
        referer_url: str = "https://www.tiktok.com/",
    ) -> tuple[bytes, Optional[str]]:
        """Download media with retries. Returns (data, final_proxy)."""
        current_proxy = proxy if not self.data_only_proxy else None
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                data = await self._download_media(media_url, current_proxy, referer_url)
                return data, current_proxy

            except (TikTokNetworkError, CurlError) as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    if not self.data_only_proxy:
                        current_proxy = self._rotate_proxy(current_proxy)
                    delay = 1.0 * (2 ** (attempt - 1))
                    logger.warning(
                        f"Media download attempt {attempt}/{MAX_RETRIES} failed: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise TikTokNetworkError(f"Media download failed: {e}") from e

            except Exception as e:
                raise TikTokNetworkError(f"Media download failed: {e}") from e

        raise TikTokNetworkError("Media download failed after all retries")

    # -------------------------------------------------------------------------
    # URL Pattern Matching
    # -------------------------------------------------------------------------

    async def regex_check(
        self, video_link: str
    ) -> tuple[Optional[str], Optional[bool]]:
        """Check if a link matches known TikTok URL patterns.

        Returns:
            Tuple of (matched_link, is_mobile).
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
        return None, None

    # -------------------------------------------------------------------------
    # Public API: Video
    # -------------------------------------------------------------------------

    async def video(
        self,
        video_link: str,
        _resolved: Optional[tuple[str, str, Optional[str]]] = None,
    ) -> VideoInfo:
        """Extract video/slideshow data from TikTok URL.

        Args:
            video_link: TikTok video or slideshow URL

        Returns:
            VideoInfo: Object containing video/slideshow information.
                - For videos: data contains bytes
                - For slideshows: data contains list of image URLs

        Raises:
            TikTokDeletedError: Video was deleted
            TikTokPrivateError: Video is private
            TikTokNetworkError: Network error
            TikTokRateLimitError: Rate limited
            TikTokRegionError: Video geo-blocked
            TikTokVideoTooLongError: Video exceeds max duration
            TikTokExtractionError: Generic extraction failure
        """
        # Pick a proxy for this entire operation
        current_proxy = self._get_initial_proxy()

        try:
            # Step 1: Resolve URL and extract video ID
            if _resolved:
                full_url, video_id, current_proxy = _resolved
            else:
                full_url, video_id, current_proxy = await self._resolve_and_extract_id(
                    video_link, current_proxy
                )

            # Step 2: Fetch video info
            video_data, current_proxy = await self._fetch_video_info_with_retry(
                full_url, video_id, current_proxy
            )

            # Check for slideshow (imagePost)
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
                        _proxy=current_proxy,
                    )

            # It's a video - extract info and download
            video_info = video_data.get("video", {})

            # Get duration
            duration = video_info.get("duration")
            if duration:
                duration = int(duration)

            # Check max duration
            if (
                self.max_video_duration > 0
                and duration
                and duration > self.max_video_duration
            ):
                raise TikTokVideoTooLongError(
                    f"Video is {duration // 60} minutes long, "
                    f"max allowed is {self.max_video_duration // 60} minutes"
                )

            # Get video URL
            video_url = (
                video_info.get("playAddr")
                or video_info.get("downloadAddr")
                or self._get_video_url_from_bitrate(video_info)
            )

            if not video_url:
                raise TikTokExtractionError("Could not find video URL")

            # Save extraction proxy before download (download may use different proxy
            # when data_only_proxy=True, but we want to preserve the extraction proxy
            # for VideoInfo._proxy which is used for slideshow image downloads)
            extraction_proxy = current_proxy

            # Step 3: Download video
            video_bytes, _ = await self._download_media_with_retry(
                video_url, current_proxy, full_url
            )

            # Extract metadata
            author = video_data.get("author", {}).get("uniqueId", "")

            # Include metadata for long videos (> threshold)
            if duration and duration > self.long_video_threshold:
                cover = video_info.get("cover") or video_info.get("originCover")
                width = (
                    int(video_info.get("width")) if video_info.get("width") else None
                )
                height = (
                    int(video_info.get("height")) if video_info.get("height") else None
                )
            else:
                cover = None
                width = None
                height = None

            logger.info(f"Successfully downloaded video {video_id}")

            return VideoInfo(
                type="video",
                data=video_bytes,
                id=int(video_id),
                cover=cover,
                width=width,
                height=height,
                duration=duration,
                author=author,
                link=video_link,
                url=video_url,
                _proxy=extraction_proxy,
            )

        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"Error extracting video {video_link}: {e}")
            raise TikTokExtractionError(f"Failed to extract video: {e}") from e

    def _get_video_url_from_bitrate(self, video_info: dict[str, Any]) -> Optional[str]:
        """Extract video URL from bitrateInfo."""
        for br in video_info.get("bitrateInfo", []):
            play_addr = br.get("PlayAddr", {})
            url_list = play_addr.get("UrlList", [])
            if url_list:
                return url_list[0]
        return None

    async def video_with_retry(
        self,
        video_link: str,
        max_attempts: int = 3,
        request_timeout: float = 30.0,
        base_delay: float = 1.0,
        on_retry: Optional[Callable[[int], Awaitable[None]]] = None,
    ) -> VideoInfo:
        """Extract video info with top-level retry logic and timeout.

        Args:
            video_link: TikTok video URL
            max_attempts: Maximum attempts
            request_timeout: Timeout per attempt in seconds
            base_delay: Base delay for exponential backoff
            on_retry: Optional async callback(attempt_number) before each attempt

        Returns:
            VideoInfo object

        Raises:
            TikTokDeletedError, TikTokPrivateError, TikTokRegionError: Not retried
            TikTokVideoTooLongError: Not retried
            Other errors: After all retries exhausted
        """
        last_error: Optional[Exception] = None

        # Resolve URL once before retry loop (has its own 3 retries)
        current_proxy = self._get_initial_proxy()
        try:
            resolved = await self._resolve_and_extract_id(video_link, current_proxy)
        except (TikTokNetworkError, TikTokExtractionError) as e:
            raise TikTokInvalidLinkError(f"Invalid video link: {video_link}") from e

        for attempt in range(1, max_attempts + 1):
            try:
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    return await self.video(video_link, _resolved=resolved)

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} timed out for {video_link}"
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

            except (
                TikTokDeletedError,
                TikTokPrivateError,
                TikTokRegionError,
                TikTokVideoTooLongError,
            ):
                raise

            except TikTokError:
                raise

            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                jitter = delay * 0.1 * random.random()
                await asyncio.sleep(delay + jitter)

        if isinstance(last_error, asyncio.TimeoutError):
            raise TikTokNetworkError(f"Request timed out after {max_attempts} attempts")

        if last_error:
            raise last_error

        raise TikTokExtractionError(f"Failed after {max_attempts} attempts")

    # -------------------------------------------------------------------------
    # Public API: Music
    # -------------------------------------------------------------------------

    async def music(self, video_id: int) -> MusicInfo:
        """Extract music info from a TikTok video.

        Args:
            video_id: TikTok video ID

        Returns:
            MusicInfo: Object containing music/audio information

        Raises:
            TikTokExtractionError: No music found or extraction failed
            TikTokNetworkError: Network error
        """
        current_proxy = self._get_initial_proxy()

        try:
            # Construct URL
            url = f"https://www.tiktok.com/@_/video/{video_id}"

            # Fetch video info
            video_data, current_proxy = await self._fetch_video_info_with_retry(
                url, str(video_id), current_proxy
            )

            # Extract music info
            music_info = video_data.get("music", {})
            if not music_info:
                raise TikTokExtractionError(f"No music info for video {video_id}")

            music_url = music_info.get("playUrl")
            if not music_url:
                raise TikTokExtractionError(f"No music URL for video {video_id}")

            # Download audio
            audio_bytes, _ = await self._download_media_with_retry(
                music_url, current_proxy, url
            )

            logger.info(f"Successfully downloaded music from video {video_id}")

            return MusicInfo(
                data=audio_bytes,
                id=video_id,
                title=music_info.get("title", ""),
                author=music_info.get("authorName", ""),
                duration=int(music_info.get("duration", 0)),
                cover=(
                    music_info.get("coverLarge")
                    or music_info.get("coverMedium")
                    or music_info.get("coverThumb")
                    or ""
                ),
            )

        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"Error extracting music for video {video_id}: {e}")
            raise TikTokExtractionError(f"Failed to extract music: {e}") from e

    async def music_with_retry(
        self,
        video_id: int,
        max_attempts: int = 3,
        request_timeout: float = 30.0,
        base_delay: float = 1.0,
        on_retry: Optional[Callable[[int], Awaitable[None]]] = None,
    ) -> MusicInfo:
        """Extract music info with top-level retry logic and timeout."""
        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                if on_retry:
                    await on_retry(attempt)

                async with asyncio.timeout(request_timeout):
                    return await self.music(video_id)

            except asyncio.TimeoutError as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} timed out for music {video_id}"
                )
                last_error = e

            except (
                TikTokNetworkError,
                TikTokRateLimitError,
                TikTokExtractionError,
            ) as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for music {video_id}: {e}"
                )
                last_error = e

            except (TikTokDeletedError, TikTokPrivateError, TikTokRegionError):
                raise

            except TikTokError:
                raise

            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                jitter = delay * 0.1 * random.random()
                await asyncio.sleep(delay + jitter)

        if isinstance(last_error, asyncio.TimeoutError):
            raise TikTokNetworkError(f"Request timed out after {max_attempts} attempts")

        if last_error:
            raise last_error

        raise TikTokExtractionError(f"Failed after {max_attempts} attempts")

    # -------------------------------------------------------------------------
    # Public API: Image Download (for slideshows)
    # -------------------------------------------------------------------------

    async def download_image(self, image_url: str, video_info: VideoInfo) -> bytes:
        """Download a slideshow image.

        Uses the proxy stored in VideoInfo from the original video() call.

        Args:
            image_url: Direct URL to the image
            video_info: VideoInfo from video() call (contains proxy info)

        Returns:
            Image bytes

        Raises:
            TikTokNetworkError: Download failed
        """
        # Use proxy from VideoInfo if available and not data_only_proxy
        proxy = None
        if not self.data_only_proxy and video_info._proxy:
            proxy = video_info._proxy

        try:
            data, _ = await self._download_media_with_retry(
                image_url, proxy, video_info.link
            )
            return data
        except Exception as e:
            raise TikTokNetworkError(f"Failed to download image: {e}") from e

    async def detect_image_format(self, image_url: str, video_info: VideoInfo) -> str:
        """Detect image format using HTTP Range request (first 20 bytes).

        Args:
            image_url: Direct URL to the image
            video_info: VideoInfo from video() call

        Returns:
            File extension: ".jpg", ".webp", ".heic", or ".jpg" (default)
        """
        proxy = None
        if not self.data_only_proxy and video_info._proxy:
            proxy = video_info._proxy

        session = await self._get_curl_session()
        headers = self._get_headers(video_info.link)
        headers["Range"] = "bytes=0-19"

        try:
            response = await session.get(
                image_url,
                headers=headers,
                cookies=self._cookies,
                proxy=proxy,
                timeout=10,
                allow_redirects=True,
            )

            if response.status_code in (200, 206):
                return self._detect_format_from_bytes(response.content)
            return ".heic"

        except Exception as e:
            logger.debug(f"Range request failed for {image_url}: {e}")
            return ".heic"

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
        return ".jpg"

    # -------------------------------------------------------------------------
    # Legacy Methods (for backwards compatibility)
    # -------------------------------------------------------------------------

    async def get_video_id_from_mobile(self, link: str) -> Optional[str]:
        """Extract video ID from mobile URL (legacy method)."""
        try:
            full_url = await self._resolve_short_url(link, self._get_initial_proxy())
            return self._extract_video_id(full_url)
        except Exception as e:
            logger.error(f"Failed to get video ID from mobile link: {e}")
            return None

    async def get_video_id(self, link: str, is_mobile: bool) -> Optional[str]:
        """Extract video ID from URL (legacy method)."""
        if not is_mobile:
            return self._extract_video_id(link)
        return await self.get_video_id_from_mobile(link)


# Backwards compatibility alias
ttapi = TikTokClient
