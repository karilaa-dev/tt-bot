import re
import os
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import yt_dlp

logger = logging.getLogger(__name__)


# Custom exception classes for specific TikTok errors
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


class TikTokExtractionError(TikTokError):
    """Generic extraction/parsing error (includes region-locked, invalid ID, etc.)."""

    pass


class ttapi:
    _executor = ThreadPoolExecutor(max_workers=4)

    def __init__(self, proxy: str = None):
        self.proxy = proxy or os.getenv("YTDLP_PROXY")
        self.mobile_regex = re.compile(r"https?://[^\s]+tiktok\.com/[^\s]+")
        self.web_regex = re.compile(r"https?://www\.tiktok\.com/@[^\s]+?/video/[0-9]+")
        self.photo_regex = re.compile(
            r"https?://www\.tiktok\.com/@[^\s]+?/photo/[0-9]+"
        )
        self.mus_regex = re.compile(r"https?://www\.tiktok\.com/music/[^\s]+")

    async def regex_check(self, video_link: str):
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

    def _extract_video_id(self, url: str) -> str:
        """Extract video ID from TikTok URL."""
        match = re.search(r"/(?:video|photo)/(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _get_ydl_opts(self):
        """Get base yt-dlp options."""
        opts = {
            "quiet": True,
            "no_warnings": True,
        }
        if self.proxy:
            opts["proxy"] = self.proxy
        return opts

    def _extract_raw_data_sync(self, url: str, video_id: str):
        """
        Extract raw TikTok data using yt-dlp's internal API.
        This method supports both videos AND slideshows.
        """
        ydl_opts = self._get_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get the TikTok extractor
                ie = ydl.get_info_extractor("TikTok")
                ie.set_downloader(ydl)

                # Convert /photo/ to /video/ URL (yt-dlp requirement)
                normalized_url = url.replace("/photo/", "/video/")

                # Use yt-dlp's internal method to get raw webpage data
                video_data, status = ie._extract_web_data_and_status(
                    normalized_url, video_id
                )

                return video_data, status
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if (
                "unavailable" in error_msg
                or "removed" in error_msg
                or "deleted" in error_msg
            ):
                return None, "deleted"
            elif "private" in error_msg:
                return None, "private"
            elif "rate" in error_msg or "too many" in error_msg or "429" in error_msg:
                return None, "rate_limit"
            # Region-locked, IP blocked, and other errors -> generic extraction error
            logger.error(f"yt-dlp download error: {e}")
            return None, "extraction"
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            return None, "network"
        except Exception as e:
            logger.error(f"yt-dlp extraction failed: {e}")
            return None, "extraction"

    def _extract_video_info_sync(self, url: str):
        """
        Extract video info using standard yt-dlp extract_info.
        This works reliably for videos but not for slideshow images.
        """
        ydl_opts = self._get_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if (
                "unavailable" in error_msg
                or "removed" in error_msg
                or "deleted" in error_msg
            ):
                return {"_error": "deleted"}
            elif "private" in error_msg:
                return {"_error": "private"}
            elif "rate" in error_msg or "too many" in error_msg or "429" in error_msg:
                return {"_error": "rate_limit"}
            # Region-locked, IP blocked, and other errors -> generic extraction error
            logger.error(f"yt-dlp download error: {e}")
            return {"_error": "extraction"}
        except aiohttp.ClientError as e:
            logger.error(f"Network error: {e}")
            return {"_error": "network"}
        except Exception as e:
            logger.error(f"yt-dlp extraction failed: {e}")
            return {"_error": "extraction"}

    def _download_video_sync(self, url: str) -> bytes:
        """Download video using yt-dlp to a temp file, read it, then delete."""
        import uuid
        import glob

        ydl_opts = self._get_ydl_opts()

        # Use current directory with a unique filename
        temp_id = uuid.uuid4().hex[:8]
        temp_filename = f".tiktok_temp_{temp_id}"

        ydl_opts.update(
            {
                "outtmpl": f"{temp_filename}.%(ext)s",
                "format": "best",
            }
        )

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                # Find the actual downloaded file
                actual_path = None
                if info:
                    ext = info.get("ext", "mp4")
                    actual_path = f"{temp_filename}.{ext}"

                # Fallback: find any file matching the pattern
                if not actual_path or not os.path.exists(actual_path):
                    matches = glob.glob(f"{temp_filename}.*")
                    if matches:
                        actual_path = matches[0]

                if actual_path and os.path.exists(actual_path):
                    with open(actual_path, "rb") as f:
                        return f.read()

            return None
        except Exception as e:
            logger.error(f"yt-dlp download failed: {e}")
            return None
        finally:
            # Clean up temp files
            for f in glob.glob(f"{temp_filename}.*"):
                try:
                    os.remove(f)
                except:
                    pass

    def _download_audio_sync(self, url: str) -> bytes:
        """Download audio using yt-dlp's urlopen (for direct audio URLs)."""
        ydl_opts = self._get_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                response = ydl.urlopen(url)
                return response.read()
        except Exception as e:
            logger.error(f"yt-dlp audio download failed for {url}: {e}")
            return None

    async def _run_sync(self, func, *args):
        """Run synchronous function in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    async def video(self, video_link: str) -> dict:
        """
        Extract video/slideshow data from TikTok URL.

        Returns:
            dict: Video/slideshow info on success

        Raises:
            TikTokDeletedError: Video was deleted by creator
            TikTokPrivateError: Video is private
            TikTokNetworkError: Network/connection error
            TikTokRateLimitError: Too many requests
            TikTokExtractionError: Generic extraction failure
        """
        try:
            # Resolve short URLs
            full_url = await self._resolve_url(video_link)
            video_id = self._extract_video_id(full_url)

            if not video_id:
                logger.error(f"Could not extract video ID from {video_link}")
                raise TikTokExtractionError(
                    f"Could not extract video ID from {video_link}"
                )

            # First, try to extract raw data for slideshow detection
            video_data, status = await self._run_sync(
                self._extract_raw_data_sync, full_url, video_id
            )

            # Check for error status and raise appropriate exception
            if status == "deleted":
                raise TikTokDeletedError(f"Video {video_link} was deleted")
            elif status == "private":
                raise TikTokPrivateError(f"Video {video_link} is private")
            elif status == "rate_limit":
                raise TikTokRateLimitError("Rate limited by TikTok")
            elif status == "network":
                raise TikTokNetworkError("Network error occurred")
            elif status == "extraction":
                raise TikTokExtractionError(f"Failed to extract video {video_link}")

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

                        return {
                            "type": "images",
                            "data": image_urls,
                            "id": int(video_id),
                            "cover": None,
                            "width": None,
                            "height": None,
                            "duration": None,
                            "author": author,
                            "link": video_link,
                        }

            # It's a video - use standard extract_info which works reliably for videos
            info = await self._run_sync(self._extract_video_info_sync, full_url)

            # Check for errors from _extract_video_info_sync
            if isinstance(info, dict) and info.get("_error"):
                error_type = info.get("_error")
                if error_type == "deleted":
                    raise TikTokDeletedError(f"Video {video_link} was deleted")
                elif error_type == "private":
                    raise TikTokPrivateError(f"Video {video_link} is private")
                elif error_type == "rate_limit":
                    raise TikTokRateLimitError("Rate limited by TikTok")
                elif error_type == "network":
                    raise TikTokNetworkError("Network error occurred")
                else:
                    raise TikTokExtractionError(f"Failed to extract video {video_link}")

            if info is None:
                raise TikTokExtractionError(
                    f"Failed to extract video info for {video_link}"
                )

            # Get video URL from extract_info result
            video_url = info.get("url")
            if not video_url:
                # Try to get from formats
                formats = info.get("formats", [])
                if formats:
                    # Get best quality video format
                    for fmt in reversed(formats):
                        if fmt.get("vcodec") != "none":
                            video_url = fmt.get("url")
                            break
                    # Fallback to last format
                    if not video_url:
                        video_url = formats[-1].get("url")

            if not video_url:
                logger.error(f"Could not find video URL for {video_link}")
                raise TikTokExtractionError(
                    f"Could not find video URL for {video_link}"
                )

            # Download video using yt-dlp (downloads to temp file, reads, deletes)
            video_bytes = await self._run_sync(self._download_video_sync, full_url)
            if video_bytes is None:
                raise TikTokExtractionError(f"Failed to download video {video_link}")

            # Extract metadata
            duration = info.get("duration")
            if duration:
                duration = int(duration)

            width = info.get("width")
            height = info.get("height")
            author = info.get("uploader") or info.get("creator") or ""
            cover = info.get("thumbnail")

            return {
                "type": "video",
                "data": video_bytes,
                "url": video_url,
                "id": int(video_id),
                "cover": cover,
                "width": int(width) if width else None,
                "height": int(height) if height else None,
                "duration": duration,
                "author": author,
                "link": video_link,
            }

        except TikTokError:
            # Re-raise TikTok errors as-is
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting video {video_link}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting video {video_link}: {e}")
            raise TikTokExtractionError(f"Failed to extract video: {e}") from e

    async def music(self, video_id: int) -> dict:
        """
        Extract music info from a TikTok video.

        Returns:
            dict: Music info on success

        Raises:
            TikTokDeletedError: Video was deleted by creator
            TikTokPrivateError: Video is private
            TikTokNetworkError: Network/connection error
            TikTokRateLimitError: Too many requests
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
            if status == "deleted":
                raise TikTokDeletedError(f"Video {video_id} was deleted")
            elif status == "private":
                raise TikTokPrivateError(f"Video {video_id} is private")
            elif status == "rate_limit":
                raise TikTokRateLimitError("Rate limited by TikTok")
            elif status == "network":
                raise TikTokNetworkError("Network error occurred")
            elif status == "extraction":
                raise TikTokExtractionError(
                    f"Failed to extract music for video {video_id}"
                )

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

            return {
                "data": audio_bytes,
                "id": int(video_id),
                "title": music_info.get("title", ""),
                "author": music_info.get("authorName", ""),
                "duration": int(music_info.get("duration", 0)),
                "cover": cover_url,
            }

        except TikTokError:
            # Re-raise TikTok errors as-is
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Network error extracting music for video {video_id}: {e}")
            raise TikTokNetworkError(f"Network error: {e}") from e
        except Exception as e:
            logger.error(f"Error extracting music for video {video_id}: {e}")
            raise TikTokExtractionError(f"Failed to extract music: {e}") from e
