"""按文件版本缓存预览图和渲染中间图"""

from collections import OrderedDict
from concurrent.futures import CancelledError
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps


class PreviewImageCache:
    """按估算字节数限制图像缓存并返回独立副本"""

    def __init__(self, max_bytes=512 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._items = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    @staticmethod
    def _cost(image):
        # Pillow 的 RGB 图像可能按四字节对齐，统一保守估算
        return image.width * image.height * max(4, len(image.getbands()))

    def get(self, key):
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            self._items.move_to_end(key)
            image, metadata, _ = entry
            return image.copy(), metadata

    def put(self, key, image, metadata=None):
        cost = self._cost(image)
        if cost > self.max_bytes:
            return
        owned = image.copy()
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old[2]
            while self._items and self._bytes + cost > self.max_bytes:
                _, entry = self._items.popitem(last=False)
                self._bytes -= entry[2]
            self._items[key] = (owned, metadata, cost)
            self._bytes += cost

    def clear(self):
        with self._lock:
            self._items.clear()
            self._bytes = 0


_preview_cache = PreviewImageCache()


def check_cancelled(cancelled):
    """在可中断的步骤之间停止过期任务"""
    if cancelled is not None and cancelled():
        raise CancelledError()


def cached_preview_image(key):
    """读取缓存中间图，不让调用方修改缓存副本"""
    entry = _preview_cache.get(key)
    return entry[0] if entry else None


def cache_preview_image(key, image):
    """按同一内存预算缓存预览中间图"""
    _preview_cache.put(key, image)


def _signature(path):
    """文件修改后自动失效缓存"""
    source = Path(path).resolve()
    info = source.stat()
    return str(source), info.st_mtime_ns, info.st_size


def _thumbnail(source, modified, file_size, bounds):
    key = ('thumbnail', source, modified, file_size, bounds)
    cached = _preview_cache.get(key)
    if cached is not None:
        image, (width, height) = cached
        return image, width, height
    with Image.open(source) as opened:
        width, height = opened.size
        if opened.getexif().get(274, 1) in (5, 6, 7, 8):
            width, height = height, width
        opened.thumbnail(bounds, Image.Resampling.LANCZOS)
        image = ImageOps.exif_transpose(opened).convert('RGBA')
    _preview_cache.put(key, image, (width, height))
    return image, width, height


def photo_thumbnail(path: Path, bounds=(144, 112)):
    """返回独立缩略图和方向修正后的原始尺寸"""
    image, width, height = _thumbnail(*_signature(path), tuple(bounds))
    return image, width, height


def photo_proxy(path: Path, max_side=1800, cancelled=None):
    """返回代理图、方向修正后的尺寸和文件编码尺寸"""
    if max_side <= 0:
        raise ValueError('代理图尺寸必须大于零')
    check_cancelled(cancelled)
    source, modified, file_size = _signature(path)
    key = ('photo', source, modified, file_size, max_side)
    cached = _preview_cache.get(key)
    if cached is not None:
        image, (full_size, encoded_size) = cached
        check_cancelled(cancelled)
        return image, full_size, encoded_size
    with Image.open(source) as opened:
        encoded_size = opened.size
        full_size = encoded_size[::-1] if opened.getexif().get(274, 1) in (5, 6, 7, 8) else encoded_size
        check_cancelled(cancelled)
        opened.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        check_cancelled(cancelled)
        image = ImageOps.exif_transpose(opened).copy()
    check_cancelled(cancelled)
    _preview_cache.put(key, image, (full_size, encoded_size))
    return image, full_size, encoded_size


def _logo(source, modified, file_size, bounds, contain):
    key = ('logo', source, modified, file_size, bounds, contain)
    cached = _preview_cache.get(key)
    if cached is not None:
        return cached[0]
    with Image.open(source) as opened:
        image = opened.convert('RGBA')
    if contain:
        result = ImageOps.contain(image, bounds, Image.Resampling.LANCZOS)
    else:
        result = image.resize(bounds, Image.Resampling.LANCZOS)
    _preview_cache.put(key, result)
    return result


def resized_logo(path, bounds, contain=False):
    """缓存标识的最终尺寸，调用方修改不会污染后续渲染"""
    return _logo(*_signature(path), tuple(bounds), contain)
