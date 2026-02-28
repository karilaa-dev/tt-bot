import concurrent.futures
import io
import logging

logger = logging.getLogger(__name__)

# Persistent to prevent "cannot schedule new futures after shutdown" under high load
_image_executor: concurrent.futures.ProcessPoolExecutor | None = None


def get_image_executor() -> concurrent.futures.ProcessPoolExecutor:
    global _image_executor
    if _image_executor is None:
        _image_executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)
    return _image_executor


try:
    from PIL import Image
    import pillow_heif

    pillow_heif.register_heif_opener()
    IMAGE_CONVERSION_AVAILABLE = True
except ImportError:
    IMAGE_CONVERSION_AVAILABLE = False

_NATIVE_EXTENSIONS = {".jpg", ".webp"}


def detect_image_format(image_data: bytes) -> str:
    if image_data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        return ".webp"
    if image_data[4:12] in (b"ftypheic", b"ftypmif1"):
        return ".heic"
    return ".jpg"


def convert_image_to_jpeg_optimized(image_data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_data)) as img:
            if img.mode == "RGBA":
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[3])
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            output = io.BytesIO()
            img.save(
                output,
                format="JPEG",
                quality=75,
                optimize=False,
                subsampling=2,
                progressive=False,
            )
            return output.getvalue()
    except Exception as e:
        logger.error(f"Image to JPEG conversion failed: {e}")
        return image_data
