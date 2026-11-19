"""按原始名称或便携素材映射查找标识深浅版本，不初始化渲染依赖"""

import json
import re
from functools import lru_cache
from pathlib import Path


VARIANT_MAP_NAME = '.exifframe-logo-variants.json'
_ARCHIVED_IMAGE = re.compile(r'[0-9a-f]{64}\.(?:png|jpg)\Z')
_VARIANTS = {'sony': ('sony.png', 'sony_dark.png'),
             'sony_dark': ('sony.png', 'sony_dark.png'),
             'olympus_blue_gold': ('olympus_blue_gold.png', 'olympus_white_gold.png'),
             'olympus_white_gold': ('olympus_blue_gold.png', 'olympus_white_gold.png')}


@lru_cache(maxsize=32)
def _read_variant_pairs(path, modified, size):
    try:
        if size > 1024 * 1024:
            return ()
        with Path(path).open('r', encoding='utf-8') as stream:
            document = json.load(stream)
        if not isinstance(document, dict) or document.get('version') != 1:
            return ()
        pairs = document.get('pairs')
        if not isinstance(pairs, list):
            return ()
        return tuple(tuple(pair) for pair in pairs if isinstance(pair, list) and len(pair) == 2
                     and all(isinstance(name, str) and _ARCHIVED_IMAGE.fullmatch(name) for name in pair))
    except (OSError, ValueError, TypeError):
        return ()


def logo_variant_pair(path):
    """返回普通深色标、浅色标路径，仅允许同目录实体文件"""
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        return None
    candidate = candidate.resolve()
    names = _VARIANTS.get(candidate.stem.casefold())
    if names:
        pair = tuple(candidate.with_name(name) for name in names)
        if all(item.is_file() and not item.is_symlink() for item in pair):
            return pair
    manifest = candidate.parent / VARIANT_MAP_NAME
    if manifest.is_symlink():
        return None
    try:
        stat = manifest.stat()
        pairs = _read_variant_pairs(str(manifest), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    for names in pairs:
        if candidate.name not in names:
            continue
        pair = tuple(candidate.parent / name for name in names)
        if all(item.is_file() and not item.is_symlink() and item.resolve().parent == candidate.parent for item in pair):
            return pair
    return None
