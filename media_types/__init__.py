"""Media type handling for video, image, and music content."""

from .errors import get_error_message, register_error_mapping
from .http_session import close_http_session
from .send_images import send_image_result
from .send_music import send_music_result
from .send_video import send_video_result
from .ui import music_button, result_caption

__all__ = [
    "close_http_session",
    "get_error_message",
    "register_error_mapping",
    "music_button",
    "result_caption",
    "send_video_result",
    "send_music_result",
    "send_image_result",
]
