"""轻量读取启动画面偏好及安全保存自定义图片"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, replace
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import warnings

from core.runtime_paths import config_path, resource_path


_MAX_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000
_MAX_SAVED_IMAGES = 3
_IMAGE_REFERENCE = re.compile(r'config/splash/([0-9a-f]{64}\.(?:png|jpg|webp))\Z')
_IMAGE_REFERENCE = re.compile(r'config/splash/([^/\\\x00]+\.(?:png|jpe?g|webp))\Z', re.I)


@dataclass(frozen=True)
class SplashSettings:
    enabled: bool = True
    background_mode: str = 'follow'
    image_path: str = ''
    overlay_opacity: int = 40
    show_version: bool = True
    show_status: bool = True
    minimum_ms: int = 800


def _bool_value(value, default):
    value = str(value).strip().casefold()
    return True if value in ('1', 'yes', 'true', 'on') else False if value in ('0', 'no', 'false', 'off') else default


def load_splash_settings() -> SplashSettings:
    """在用户配置尚未初始化时读取打包默认值"""
    defaults = SplashSettings()
    target = config_path('config.ini')
    source = target if target.is_file() else resource_path('config/config.ini')
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(source, encoding='utf-8-sig')
        if not parser.has_section('splash'):
            return defaults
        section = parser['splash']
        mode = section.get('background_mode', defaults.background_mode).strip().casefold()
        if mode not in ('follow', 'photo', 'custom'):
            mode = defaults.background_mode
        image_path = section.get('image_path', '').strip().replace('\\', '/')
        if image_path and not _IMAGE_REFERENCE.fullmatch(image_path):
            image_path = ''
        if mode == 'custom' and not image_path:
            mode = defaults.background_mode
        try:
            opacity = max(0, min(100, int(section.get('overlay_opacity', defaults.overlay_opacity))))
        except (TypeError, ValueError):
            opacity = defaults.overlay_opacity
        try:
            minimum = int(section.get('minimum_ms', defaults.minimum_ms))
            if minimum not in (0, 800, 1500):
                minimum = defaults.minimum_ms
        except (TypeError, ValueError):
            minimum = defaults.minimum_ms
        return SplashSettings(
            enabled=_bool_value(section.get('enabled', defaults.enabled), defaults.enabled),
            background_mode=mode,
            image_path=image_path,
            overlay_opacity=opacity,
            show_version=_bool_value(section.get('show_version', defaults.show_version), defaults.show_version),
            show_status=_bool_value(section.get('show_status', defaults.show_status), defaults.show_status),
            minimum_ms=minimum,
        )
    except (OSError, UnicodeError, configparser.Error, ValueError):
        return defaults


def resolve_splash_image(value) -> Path | None:
    """将可迁移的配置路径或尚未保存的预览原图解析为实际路径"""
    if not value:
        return None
    text = str(value).replace('\\', '/')
    match = _IMAGE_REFERENCE.fullmatch(text)
    if match:
        filename = match.group(1)
        if filename in ('.', '..'):
            return None
        folder = config_path('splash')
        candidate = folder / filename
        if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)() or candidate.is_symlink():
            return None
        if candidate.parent.resolve() != folder.resolve():
            return None
        return candidate
    path = Path(value).expanduser()
    return path if path.is_absolute() else None


def _image_data(path):
    """限制文件和解码尺寸，拒绝伪装或损坏的背景"""
    from PIL import Image, UnidentifiedImageError

    with Path(path).expanduser().open('rb') as stream:
        data = stream.read(_MAX_IMAGE_BYTES + 1)
    if not data or len(data) > _MAX_IMAGE_BYTES:
        raise ValueError('启动图片过大或为空')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                extension = {'PNG': 'png', 'JPEG': 'jpg', 'WEBP': 'webp'}.get(image.format)
                if extension is None:
                    raise ValueError('启动图片须为 PNG、JPG 或 WebP')
                if image.width <= 0 or image.height <= 0 or image.width * image.height > _MAX_IMAGE_PIXELS:
                    raise ValueError('启动图片尺寸过大')
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()
    except (OSError, SyntaxError, EOFError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('启动图片无效或已损坏') from exc
    except ValueError as exc:
        if str(exc) in ('启动图片须为 PNG、JPG 或 WebP', '启动图片尺寸过大'):
            raise
        raise ValueError('启动图片无效或已损坏') from exc
    return data, extension


def validate_splash_image(path) -> None:
    """预览前验证用户选择的图片"""
    _image_data(path)


def _publish_image(data, extension) -> str:
    name = f'{hashlib.sha256(data).hexdigest()}.{extension}'
    folder = config_path('splash')
    if folder.is_symlink() or getattr(folder, 'is_junction', lambda: False)():
        raise ValueError('启动图片目录不能是链接')
    target = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError('启动图片副本不能是链接')
    if target.exists():
        if not target.is_file() or target.stat().st_size != len(data) or target.read_bytes() != data:
            raise FileExistsError('启动图片副本已存在且内容不同')
        return f'config/splash/{name}'
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.splash-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            if os.name == 'nt':
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.stat().st_size != len(data) or target.read_bytes() != data:
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return f'config/splash/{name}'


def _image_lock():
    from core.runtime_paths import _seed_lock
    lock = config_path('.splash-assets.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    return _seed_lock(lock)


def import_splash_image(path) -> str:
    """将图片无损复制到用户配置目录，返回可迁移的逻辑路径"""
    data, extension = _image_data(path)
    with _image_lock():
        return _publish_image(data, extension)


def _cleanup_images(active):
    """只回收经过摘要校验的托管副本，保留当前及最近两张"""
    folder = config_path('splash')
    if (not folder.is_dir() or folder.is_symlink()
            or getattr(folder, 'is_junction', lambda: False)()):
        return
    try:
        folder_root = folder.resolve(strict=True)
        candidates = []
        for path in folder.iterdir():
            match = _IMAGE_NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            if info.st_size > _MAX_IMAGE_BYTES or path.resolve(strict=True).parent != folder_root:
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != match.group(1):
                continue
            candidates.append((info.st_mtime_ns, path.name, path, info))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        keep = {Path(active).name} if active else set()
        for _, name, _, _ in candidates:
            if len(keep) >= _MAX_SAVED_IMAGES:
                break
            keep.add(name)
        for _, name, path, old in candidates:
            if name in keep:
                continue
            current = load_splash_settings().image_path
            if current and Path(current).name == name:
                continue
            if path.is_symlink() or path.resolve(strict=True).parent != folder_root:
                continue
            new = path.stat()
            if (new.st_dev, new.st_ino, new.st_mtime_ns, new.st_size) != (old.st_dev, old.st_ino, old.st_mtime_ns, old.st_size):
                continue
            path.unlink()
    except OSError:
        # 清理失败不影响已成功保存的设置
        pass


def save_splash_settings(settings: SplashSettings, *, image_source=None) -> SplashSettings:
    """仅更新启动画面配置，不保存照片或其他工作区设置"""
    if not isinstance(settings, SplashSettings):
        raise TypeError('启动画面设置无效')
    image_data = _image_data(image_source) if image_source else None
    if image_data:
        data, extension = image_data
        name = f'{hashlib.sha256(data).hexdigest()}.{extension}'
        settings = replace(settings, image_path=f'config/splash/{name}')
    if (not all(isinstance(getattr(settings, key), bool) for key in ('enabled', 'show_version', 'show_status'))
            or settings.background_mode not in ('follow', 'photo', 'custom')
            or isinstance(settings.overlay_opacity, bool) or not isinstance(settings.overlay_opacity, int)
            or not 0 <= settings.overlay_opacity <= 100 or isinstance(settings.minimum_ms, bool)
            or not isinstance(settings.minimum_ms, int) or settings.minimum_ms not in (0, 800, 1500)
            or not isinstance(settings.image_path, str)
            or (settings.image_path and not _IMAGE_REFERENCE.fullmatch(settings.image_path))):
        raise ValueError('启动画面设置无效')
    from core.ini_preferences import update_ini_values
    from core.runtime_paths import _copy_seed_file
    with _image_lock():
        if image_data:
            _publish_image(*image_data)
        if settings.background_mode == 'custom':
            image = resolve_splash_image(settings.image_path)
            if image is None or not image.is_file():
                raise ValueError('请选择自定义启动图片')
        target = config_path('config.ini')
        if not target.exists():
            bundled = resource_path('config/config.ini')
            if not bundled.is_file():
                raise FileNotFoundError('config.ini')
            _copy_seed_file(bundled, target)
        update_ini_values(target, 'splash', {
            'enabled': str(settings.enabled).lower(),
            'background_mode': settings.background_mode,
            'image_path': settings.image_path,
            'overlay_opacity': str(settings.overlay_opacity),
            'show_version': str(settings.show_version).lower(),
            'show_status': str(settings.show_status).lower(),
            'minimum_ms': str(settings.minimum_ms),
        })
        _cleanup_images(settings.image_path)
    return settings
