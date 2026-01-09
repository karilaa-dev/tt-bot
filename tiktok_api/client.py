"""TikTok API client for extracting video and music information."""

import asyncio
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Optional, Tuple

import aiohttp
import yt_dlp

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

logger = logging.getLogger(__name__)

# Regex for extracting video ID from redirected URLs (used by legacy get_id functions)
_redirect_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+?/([0-9]+)")


class TikTokClient:
    """Client for extracting TikTok video and music information.

    This client uses yt-dlp internally to extract video/slideshow data and music
    from TikTok URLs. It supports both regular videos and slideshows (image posts).

    Args:
        proxy: Optional proxy URL for requests. If not provided, uses YTDLP_PROXY env var.
        cookies: Optional path to a Netscape-format cookies file (e.g., exported from browser).
            If not provided, uses YTDLP_COOKIES env var. If the file doesn't exist,
            a warning is logged and cookies are not used.

    Example:
        >>> client = TikTokClient(proxy="http://proxy:8080")
        >>> video_info = await client.video("https://www.tiktok.com/@user/video/123")
        >>> print(video_info.author)
        >>> print(video_info.duration)

        # With cookies for authenticated requests:
        >>> client = TikTokClient(cookies="cookies.txt")
    """

    _executor = ThreadPoolExecutor(max_workers=4)

    def __init__(self, proxy: Optional[str] = None, cookies: Optional[str] = None):
        self.proxy = proxy or os.getenv("YTDLP_PROXY")

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
        """Resolve short URLs (vm.tiktok.com, vt.tiktok.com) to full URLs."""
        if "vm.tiktok.com" in url or "vt.tiktok.com" in url:
            async with aiohttp.ClientSession() as client:
                try:
                    async with client.get(url, allow_redirects=True) as response:
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

    def _get_ydl_opts(self) -> dict[str, Any]:
        """Get base yt-dlp options."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        if self.cookies:
            opts["cookiefile"] = self.cookies
            logger.debug(f"yt-dlp using cookie file: {self.cookies}")
        return opts

    def _extract_raw_data_sync(
        self, url: str, video_id: str
    ) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        """
        Extract raw TikTok data using yt-dlp's internal API.
        This method supports both videos AND slideshows.

        NOTE: This code relies on yt-dlp's private API (_extract_web_data_and_status),
        which may change or be removed in future yt-dlp releases. Keep yt-dlp up-to-date
        and be prepared to update this code if the private API changes.
        """
        ydl_opts = self._get_ydl_opts()

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
            logger.error(f"yt-dlp download error: {e}")
            return None, "extraction"
        except yt_dlp.utils.ExtractorError as e:
            logger.error(f"yt-dlp extractor error: {e}")
            return None, "extraction"
        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"yt-dlp extraction failed: {e}")
            return None, "extraction"

    def _download_audio_sync(self, url: str) -> Optional[bytes]:
        """Download audio using yt-dlp's urlopen (for direct audio URLs)."""
        ydl_opts = self._get_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                response = ydl.urlopen(url)
                return response.read()
        except Exception as e:
            logger.error(f"yt-dlp audio download failed for {url}: {e}")
            return None

    def _download_image_sync(
        self, image_url: str, download_context: dict[str, Any]
    ) -> Optional[bytes]:
        """
        Download image using the same yt-dlp context that was used for extraction.

        This ensures all cookies/auth set by yt-dlp's TikTok extractor are used.
        We don't hardcode any bypass logic - we leverage yt-dlp's existing
        cookie and header handling.

        Args:
            image_url: Direct URL to the image on TikTok CDN
            download_context: Dict containing 'ydl', 'ie', and 'referer_url'
                from the extraction phase

        Returns:
            Image bytes if successful, None otherwise
        """
        return self._download_media_to_memory_sync(image_url, download_context)

    def _download_media_to_memory_sync(
        self, media_url: str, download_context: dict[str, Any]
    ) -> Optional[bytes]:
        """
        Download any media (video, image, etc.) directly to memory using yt-dlp.

        This uses the same yt-dlp context that was used for extraction, ensuring
        all cookies/auth set by yt-dlp's TikTok extractor are used. No files are
        written to disk - everything stays in RAM.

        Args:
            media_url: Direct URL to the media on TikTok CDN
            download_context: Dict containing 'ydl', 'ie', and 'referer_url'
                from the extraction phase

        Returns:
            Media bytes if successful, None otherwise
        """
        from yt_dlp.networking.common import Request
        import urllib.parse

        ydl = download_context["ydl"]
        ie = download_context["ie"]
        referer_url = download_context["referer_url"]

        try:
            # Propagate cookies from TikTok's main domain to the media CDN domain.
            # This replicates what yt-dlp does internally for video downloads.
            # We use yt-dlp's own _get_cookies and _set_cookie methods to avoid
            # hardcoding any specific cookie names - when yt-dlp updates their
            # bypass logic, we automatically get the changes.
            media_host = urllib.parse.urlparse(media_url).hostname
            tiktok_cookies = ie._get_cookies("https://www.tiktok.com/")
            for cookie_name, cookie in tiktok_cookies.items():
                ie._set_cookie(media_host, cookie_name, cookie.value)

            # Create request with Referer header (standard HTTP practice)
            request = Request(media_url, headers={"Referer": referer_url})

            response = ydl.urlopen(request)
            return response.read()
        except Exception as e:
            logger.error(f"yt-dlp media download failed for {media_url}: {e}")
            return None

    def _extract_with_context_sync(
        self, url: str, video_id: str
    ) -> Tuple[Optional[dict[str, Any]], Optional[str], Optional[dict[str, Any]]]:
        """
        Extract TikTok data and return the download context for later media downloads.

        This method keeps the YoutubeDL instance alive so it can be reused for
        downloading media (videos, images) with the same auth context.

        Returns:
            Tuple of (video_data, status, download_context)
            - video_data: Raw TikTok API response
            - status: Error status string or None
            - download_context: Dict with 'ydl', 'ie', 'referer_url' for media downloads

        Note:
            The caller is responsible for closing the YDL instance in download_context
            when done. On error paths, this method closes the YDL instance before returning.
        """
        ydl_opts = self._get_ydl_opts()
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
            logger.error(f"yt-dlp download error: {e}")
            return None, "extraction", None
        except yt_dlp.utils.ExtractorError as e:
            logger.error(f"yt-dlp extractor error: {e}")
            return None, "extraction", None
        except TikTokError:
            raise
        except Exception as e:
            logger.error(f"yt-dlp extraction failed: {e}")
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
        return await loop.run_in_executor(self._executor, func, *args)

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
        Download an image using the yt-dlp context from video extraction.

        This method uses the same YoutubeDL instance that was used to extract
        the video info, ensuring all cookies and authentication set by yt-dlp's
        TikTok extractor are used for the image download.

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

        result = await self._run_sync(
            self._download_image_sync, image_url, video_info._download_context
        )

        if result is None:
            raise TikTokNetworkError(f"Failed to download image: {image_url}")

        return result

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
            # Resolve short URLs
            full_url = await self._resolve_url(video_link)
            video_id = self._extract_video_id(full_url)

            if not video_id:
                logger.error(f"Could not extract video ID from {video_link}")
                raise TikTokExtractionError(
                    f"Could not extract video ID from {video_link}"
                )

            # First, extract raw data with download context for authenticated downloads
            # Use _extract_with_context_sync to keep YDL alive for both videos and slideshows
            video_data, status, download_context = await self._run_sync(
                self._extract_with_context_sync, full_url, video_id
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

            # Download video directly to memory using yt-dlp context
            video_bytes = await self._run_sync(
                self._download_media_to_memory_sync, video_url, download_context
            )

            # Close the download context - it's no longer needed for videos
            # (unlike slideshows where we keep it for image downloads)
            self._close_download_context(download_context)
            context_transferred = True  # Mark as handled

            if video_bytes is None:
                raise TikTokExtractionError(f"Failed to download video {video_link}")

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
        on_retry: Callable[[int], Awaitable[None]] | None = None,
    ) -> VideoInfo:
        """
        Extract video info with retry logic and per-request timeout.

        Each request times out after `request_timeout` seconds. On timeout or
        transient errors (network, rate limit, extraction), retries immediately.
        Does NOT retry on permanent errors (deleted, private, region).

        Args:
            video_link: TikTok video URL
            max_attempts: Maximum number of attempts (default: 3)
            request_timeout: Timeout per request in seconds (default: 10)
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
                # Brief delay to allow emoji update to register
                await asyncio.sleep(0.5)

            except (
                TikTokNetworkError,
                TikTokRateLimitError,
                TikTokExtractionError,
            ) as e:
                logger.warning(
                    f"Attempt {attempt}/{max_attempts} failed for {video_link}: {e}"
                )
                last_error = e
                # Brief delay to allow emoji update to register
                await asyncio.sleep(0.5)

            except (TikTokDeletedError, TikTokPrivateError, TikTokRegionError):
                # Permanent errors - don't retry, raise immediately
                raise

            except TikTokError:
                # Any other TikTok error - don't retry
                raise

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
            # Construct a URL with the video ID
            url = f"https://www.tiktok.com/@_/video/{video_id}"

            # Extract raw data to get music info
            video_data, status = await self._run_sync(
                self._extract_raw_data_sync, url, str(video_id)
            )

            # Check for error status and raise appropriate exception
            if status and status not in ("ok", None):
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

            # Download audio using yt-dlp
            audio_bytes = await self._run_sync(self._download_audio_sync, music_url)
            if audio_bytes is None:
                raise TikTokExtractionError(
                    f"Failed to download audio for video {video_id}"
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


# Backwards compatibility alias
ttapi = TikTokClient
