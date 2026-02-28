import asyncio
import concurrent.futures
import io
import logging

logger = logging.getLogger(__name__)

# Persistent ProcessPoolExecutor for image conversion
# This prevents "cannot schedule new futures after shutdown" errors under high load
_image_executor: concurrent.futures.ProcessPoolExecutor | None = None


def get_image_executor() -> concurrent.futures.ProcessPoolExecutor:
    """Get or create a persistent ProcessPoolExecutor for image conversion."""
    global _image_executor
    if _image_executor is None:
        _image_executor = concurrent.futures.ProcessPoolExecutor(max_workers=4)
    return _image_executor


# PIL imports for image processing
try:
    from PIL import Image
    import pillow_heif

    # Register HEIF opener with pillow once at module load
    pillow_heif.register_heif_opener()
    IMAGE_CONVERSION_AVAILABLE = True
except ImportError:
    IMAGE_CONVERSION_AVAILABLE = False


def detect_image_format(image_data: bytes) -> str:
    """Detect image format from magic bytes and return appropriate extension."""
    if image_data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    elif image_data.startswith(b"RIFF") and image_data[8:12] == b"WEBP":
        return ".webp"
    elif image_data[4:12] == b"ftypheic" or image_data[4:12] == b"ftypmif1":
        return ".heic"
    else:
        return ".jpg"


def convert_image_to_jpeg_optimized(image_data: bytes) -> bytes:
    """Convert any image data to JPEG format with good size/quality ratio.

    Note: pillow_heif.register_heif_opener() is called once at module load,
    not per-image, for better performance.
    """
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
                subsampling=2,  # 4:2:0 chroma subsampling
                progressive=False,
            )
            return output.getvalue()
    except Exception as e:
        logger.error(f"Image to JPEG conversion failed: {e}")
        return image_data


async def check_and_convert_image(image_data, executor, loop):
    """Check image type and convert to JPEG if it's not WebP or JPEG.

    Returns:
        tuple: (converted_image_data, extension)
    """
    extension = detect_image_format(image_data)

    if IMAGE_CONVERSION_AVAILABLE and image_data and extension not in [".jpg", ".webp"]:
        try:
            converted_data = await loop.run_in_executor(
                executor, convert_image_to_jpeg_optimized, image_data
            )
            return converted_data, ".jpg"
        except Exception as e:
            logger.error(f"Failed to convert image: {e}")
            return image_data, extension

    return image_data, extension
