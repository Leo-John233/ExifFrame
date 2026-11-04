"""按文件版本缓存小图，避免重复解码原尺寸图像"""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps


def _signature(path):
    """文件修改后自动失效缓存"""
    source = Path(path).resolve()
    info = source.stat()
    return str(source), info.st_mtime_ns, info.st_size


@lru_cache(maxsize=256)
def _thumbnail(source, modified, file_size, bounds):
    with Image.open(source) as opened:
        width, height = opened.size
        if opened.getexif().get(274, 1) in (5, 6, 7, 8):
            width, height = height, width
        opened.thumbnail(bounds, Image.Resampling.LANCZOS)
        image = ImageOps.exif_transpose(opened).convert('RGBA')
    return image, width, height


def photo_thumbnail(path: Path, bounds=(144, 112)):
    """返回独立缩略图和方向修正后的原始尺寸"""
    image, width, height = _thumbnail(*_signature(path), tuple(bounds))
    return image.copy(), width, height


@lru_cache(maxsize=24)
def _logo(source, modified, file_size, bounds, contain):
    with Image.open(source) as opened:
        image = opened.convert('RGBA')
    if contain:
        return ImageOps.contain(image, bounds, Image.Resampling.LANCZOS)
    return image.resize(bounds, Image.Resampling.LANCZOS)


def resized_logo(path, bounds, contain=False):
    """缓存标识的最终尺寸，调用方修改不会污染后续渲染"""
    return _logo(*_signature(path), tuple(bounds), contain).copy()
