"""按文件版本缓存预览图和渲染中间图"""

from collections import OrderedDict
from concurrent.futures import CancelledError
from functools import lru_cache
from pathlib import Path
import stat
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
_palette_cache = OrderedDict()
_palette_lock = RLock()
_PALETTE_LIMIT = 128


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


def _palette_sample(image):
    """只在最长边不超过160像素的样本上计算主色"""
    scale = min(1.0, 160 / max(image.size))
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    sample = image.resize(size, Image.Resampling.LANCZOS) if size != image.size else image.copy()
    if 'A' in sample.getbands():
        background = Image.new('RGBA', sample.size, 'white')
        background.alpha_composite(sample.convert('RGBA'))
        sample = background.convert('RGB')
    else:
        sample = sample.convert('RGB')
    quantized = sample.quantize(colors=5, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors() or [], key=lambda item: (-item[0], item[1]))
    colors = [tuple(palette[index * 3:index * 3 + 3]) for _, index in counts]
    if not colors:
        colors = [(0, 0, 0)]
    return tuple((colors + [colors[-1]] * 5)[:5])


def dominant_palette(image, image_id=None):
    """按原片版本复用五个主色，来源不明时只采样当前图"""
    if not valid_file_image_id(image_id):
        return _palette_sample(image)
    with _palette_lock:
        if image_id in _palette_cache:
            _palette_cache.move_to_end(image_id)
            return _palette_cache[image_id]
    try:
        with Image.open(image_id[1]) as opened:
            opened.draft('RGB', (160, 160))
            opened.thumbnail((160, 160), Image.Resampling.LANCZOS)
            result = _palette_sample(opened)
        if not valid_file_image_id(image_id):
            return _palette_sample(image)
    except (OSError, ValueError):
        return _palette_sample(image)
    with _palette_lock:
        _palette_cache[image_id] = result
        _palette_cache.move_to_end(image_id)
        while len(_palette_cache) > _PALETTE_LIMIT:
            _palette_cache.popitem(last=False)
    return result


def _signature(path):
    """文件修改后自动失效缓存"""
    source = Path(path).resolve()
    info = source.stat()
    return str(source), info.st_mtime_ns, info.st_size


def file_image_id(path):
    """为完整文件和各级代理生成相同的版本身份"""
    try:
        return ('file', *_signature(path))
    except (OSError, ValueError):
        return None


def valid_file_image_id(image_id):
    """仅接受仍与磁盘文件版本一致的可信身份"""
    if not (isinstance(image_id, tuple) and len(image_id) == 4 and image_id[0] == 'file'
            and isinstance(image_id[1], str) and Path(image_id[1]).is_absolute()
            and isinstance(image_id[2], int) and isinstance(image_id[3], int)):
        return False
    try:
        info = Path(image_id[1]).stat()
        return stat.S_ISREG(info.st_mode) and (info.st_mtime_ns, info.st_size) == image_id[2:]
    except (OSError, ValueError):
        return False


def _check_source_version(source, modified, file_size):
    """照片在解码期间变化时不复用旧身份"""
    if _signature(source) != (source, modified, file_size):
        raise OSError('照片在预览期间发生变化，请重试')


@lru_cache(maxsize=512)
def _dimensions(source, modified, file_size):
    with Image.open(source) as opened:
        encoded_size = opened.size
        full_size = encoded_size[::-1] if opened.getexif().get(274, 1) in (5, 6, 7, 8) else encoded_size
    _check_source_version(source, modified, file_size)
    return full_size, encoded_size


def photo_dimensions(path: Path, cancelled=None):
    """读取照片方向修正后的尺寸和编码尺寸"""
    check_cancelled(cancelled)
    signature = _signature(path)
    dimensions = _dimensions(*signature)
    _check_source_version(*signature)
    check_cancelled(cancelled)
    return dimensions


def _thumbnail(source, modified, file_size, bounds, cancelled=None):
    key = ('thumbnail', source, modified, file_size, bounds)
    cached = _preview_cache.get(key)
    if cached is not None:
        _check_source_version(source, modified, file_size)
        check_cancelled(cancelled)
        image, (width, height) = cached
        return image, width, height
    with Image.open(source) as opened:
        width, height = opened.size
        rotated = opened.getexif().get(274, 1) in (5, 6, 7, 8)
        if rotated:
            width, height = height, width
        check_cancelled(cancelled)
        opened.thumbnail(bounds[::-1] if rotated else bounds, Image.Resampling.LANCZOS)
        check_cancelled(cancelled)
        image = ImageOps.exif_transpose(opened).convert('RGBA')
    check_cancelled(cancelled)
    _check_source_version(source, modified, file_size)
    _preview_cache.put(key, image, (width, height))
    return image, width, height


def photo_thumbnail(path: Path, bounds=(144, 112), cancelled=None):
    """返回独立缩略图和方向修正后的原始尺寸"""
    check_cancelled(cancelled)
    signature = _signature(path)
    image, width, height = _thumbnail(*signature, tuple(bounds), cancelled)
    _check_source_version(*signature)
    check_cancelled(cancelled)
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
        _check_source_version(source, modified, file_size)
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
    _check_source_version(source, modified, file_size)
    _preview_cache.put(key, image, (full_size, encoded_size))
    return image, full_size, encoded_size


def contain_logo(image, bounds):
    """将标识等比放入指定范围，极细的笔画至少占一像素"""
    scale = min(bounds[0] / image.width, bounds[1] / image.height)
    size = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    return image.resize(size, Image.Resampling.LANCZOS)


def _logo(source, modified, file_size, bounds, contain):
    key = ('logo', source, modified, file_size, bounds, contain)
    cached = _preview_cache.get(key)
    if cached is not None:
        return cached[0]
    with Image.open(source) as opened:
        image = opened.convert('RGBA')
    if contain:
        result = contain_logo(image, bounds)
    else:
        result = image.resize(bounds, Image.Resampling.LANCZOS)
    _preview_cache.put(key, result)
    return result


def resized_logo(path, bounds, contain=False):
    """缓存标识的最终尺寸，调用方修改不会污染后续渲染"""
    return _logo(*_signature(path), tuple(bounds), contain)
