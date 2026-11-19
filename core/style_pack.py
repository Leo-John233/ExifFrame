"""便携样式包和用户选用的图像素材"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageColor

from core.runtime_paths import config_path


_MAX_ASSET_BYTES = 64 * 1024 * 1024
_MAX_ASSET_PIXELS = 100_000_000
_MAX_PACK_BYTES = 256 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_ASSET_NAME = re.compile(r'assets/([0-9a-f]{64})\.(png|jpg)\Z')
_ASSET_FIELD = re.compile(
    r'("(?:left_logo|right_logo|center_logo|path)"\s*:\s*)("(?:\\.|[^"\\])*")', re.S)
_STYLE_FIELDS = (
    'title', 'subtitle', 'show_logo', 'font_scale', 'border_percent', 'border_override',
    'background', 'text_color', 'background_override', 'text_color_override',
    'use_template_styles', 'logo_choice', 'font_path', 'text_alignment',
    'text_spacing', 'line_spacing', 'brand_glyph_policy',
)


def _image_bytes(data):
    """拒绝损坏和过大的图像素材"""
    if not data or len(data) > _MAX_ASSET_BYTES:
        raise ValueError('素材图片大小无效')
    try:
        with Image.open(BytesIO(data)) as image:
            extension = {'PNG': 'png', 'JPEG': 'jpg'}.get(image.format)
            if not extension or image.width * image.height > _MAX_ASSET_PIXELS:
                raise ValueError('素材需要 PNG 或 JPEG 图片')
            image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('素材图片无效或已损坏') from exc
    return extension


def _read_asset(path):
    with Path(path).expanduser().open('rb') as stream:
        data = stream.read(_MAX_ASSET_BYTES + 1)
    return data, _image_bytes(data)


def _publish_asset(target, data):
    """同目录暂存后独占发布，不覆盖用户已有文件"""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.is_file() and target.read_bytes() == data:
            return
        raise FileExistsError('素材文件已存在且内容不同')
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.asset-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            if os.name == 'nt':
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            if not target.is_file() or target.read_bytes() != data:
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def copy_asset(path, *, png_only=False) -> str:
    """把用户选择的图片放进便携目录并返回相对路径"""
    data, extension = _read_asset(path)
    if png_only and extension != 'png':
        raise ValueError('相框贴图须为 PNG 图片')
    name = f'{hashlib.sha256(data).hexdigest()}.{extension}'
    _publish_asset(config_path('style_assets') / name, data)
    return f'config/style_assets/{name}'


def _image_reference(value):
    return (isinstance(value, str) and value.lower().endswith(('.png', '.jpg', '.jpeg'))
            and not any(token in value for token in ('{{', '{%', '{#')))


def _rewrite_references(source, convert):
    """只替换图片字段的静态字符串，保留原始 Jinja 和源码排版"""
    def replace(match):
        try:
            value = json.loads(match.group(2))
        except ValueError:
            return match.group(0)
        if not _image_reference(value):
            return match.group(0)
        updated = convert(value)
        return match.group(1) + json.dumps(updated, ensure_ascii=False) if updated != value else match.group(0)

    return _ASSET_FIELD.sub(replace, source)


def asset_signature(source, logo_choice=''):
    """外部图片变化后使桌面预览重新渲染"""
    paths = []

    def collect(value):
        paths.append(value)
        return value

    _rewrite_references(source, collect)
    if _image_reference(logo_choice):
        collect(logo_choice)
    result = []
    for value in dict.fromkeys(paths):
        try:
            info = Path(value).expanduser().stat()
            result.append((value, info.st_mtime_ns, info.st_size))
        except OSError:
            result.append((value, None, None))
    return tuple(result)


def _checked_style(values):
    """只接受可保存为模板的显示设置"""
    from core.brand_glyphs import validate_policy
    from core.desktop_service import WatermarkSettings

    if not isinstance(values, dict) or values.keys() - set(_STYLE_FIELDS):
        raise ValueError('样式包格式无效')
    defaults = WatermarkSettings()
    result = {key: values.get(key, getattr(defaults, key)) for key in _STYLE_FIELDS}
    for key in ('title', 'subtitle', 'logo_choice', 'font_path', 'text_alignment',
                'brand_glyph_policy', 'background', 'text_color'):
        if not isinstance(result[key], str):
            raise ValueError('样式包格式无效')
    for key in ('show_logo', 'border_override', 'background_override', 'text_color_override',
                'use_template_styles'):
        if not isinstance(result[key], bool):
            raise ValueError('样式包格式无效')
    scale = result['font_scale']
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not .5 <= scale <= 2:
        raise ValueError('样式包格式无效')
    border = result['border_percent']
    if isinstance(border, bool) or not isinstance(border, int) or not 6 <= border <= 30:
        raise ValueError('样式包格式无效')
    for key in ('text_spacing', 'line_spacing'):
        value = result[key]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5000):
            raise ValueError('样式包格式无效')
    if result['text_alignment'] not in ('', 'left', 'right'):
        raise ValueError('样式包格式无效')
    if result['brand_glyph_policy']:
        validate_policy(result['brand_glyph_policy'])
    for key in ('background', 'text_color'):
        ImageColor.getrgb(result[key])
    return result


def _prepare(source, settings):
    """收集实际引用的图像并替换为包内名称"""
    from core.desktop_service import validate_template

    validate_template(source)
    style = _checked_style({key: getattr(settings, key) for key in _STYLE_FIELDS})
    assets = {}

    def collect(value):
        try:
            data, extension = _read_asset(value)
        except OSError as exc:
            raise ValueError(f'所选样式引用的素材不存在：{value}') from exc
        name = f'assets/{hashlib.sha256(data).hexdigest()}.{extension}'
        assets[name] = data
        return name

    source = _rewrite_references(source, collect)
    if _image_reference(style['logo_choice']):
        style['logo_choice'] = collect(style['logo_choice'])
    if sum(map(len, assets.values())) > _MAX_PACK_BYTES:
        raise ValueError('样式包素材过大')
    return source, style, assets


def _write_unique(target, data):
    """先完整写入临时文件，再以不覆盖的方式发布"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.style-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        if os.name == 'nt':
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _style_path(name):
    from core.desktop_service import _template_path

    _template_path(name)
    return config_path('style_presets') / f'{name}.json'


def read_preset_style(name):
    """读取另存模板的快捷样式，普通模板没有附加设置"""
    path = _style_path(name)
    if not path.is_file():
        return {}
    return _checked_style(json.loads(path.read_text(encoding='utf-8')))


def _install(name, source, style, assets):
    """先准备素材和样式，最后独占发布模板"""
    from core.desktop_service import _template_path, validate_template

    target = _template_path(name)
    style_target = _style_path(name)
    if target.exists() or style_target.exists():
        raise FileExistsError('模板已存在，请换一个名称')
    validate_template(source)
    style = _checked_style(style)
    folder = config_path('style_assets') / uuid.uuid4().hex if assets else None
    sidecar_created = folder_created = False
    try:
        mapping = {}
        if folder is not None:
            folder.mkdir(parents=True, exist_ok=False)
            folder_created = True
            for entry, data in assets.items():
                match = _ASSET_NAME.fullmatch(entry)
                if match is None:
                    raise ValueError('样式包素材无效或已损坏')
                filename = Path(entry).name
                (folder / filename).write_bytes(data)
                mapping[entry] = f'config/style_assets/{folder.name}/{filename}'

        def replace(value):
            if value not in mapping:
                raise ValueError('样式包素材无效或已损坏')
            return mapping[value]

        source = _rewrite_references(source, replace)
        if _image_reference(style['logo_choice']):
            style['logo_choice'] = replace(style['logo_choice'])
        _write_unique(style_target, json.dumps(style, ensure_ascii=False, indent=2).encode('utf-8'))
        sidecar_created = True
        _write_unique(target, source.encode('utf-8'))
    except Exception:
        if sidecar_created:
            style_target.unlink(missing_ok=True)
        if folder_created:
            shutil.rmtree(folder)
        raise
    return name


def save_custom_template(name, source, settings):
    """保存当前照片的模板与有效样式，不覆盖已有模板"""
    source, style, assets = _prepare(source, settings)
    return _install(name, source, style, assets)


def export_style_pack(path, name, source, settings, *, overwrite=False):
    """导出 JSON 模板、样式快照及引用的图片"""
    from core.desktop_service import _template_path

    _template_path(name)
    source, style, assets = _prepare(source, settings)
    manifest = {'format': 'exifframe-style', 'version': 1, 'name': name,
                'template': source, 'style': style, 'assets': sorted(assets)}
    content = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError('样式包格式无效')
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.efstyle-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', content)
            for entry, data in assets.items():
                archive.writestr(entry, data)
        if overwrite:
            os.replace(temporary, target)
        elif os.name == 'nt':
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_pack(path):
    """只读取限定名称和大小的包内文件，不解压任意路径"""
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (not entries or len(entries) > 257 or len(names) != len(set(names))
                    or names.count('manifest.json') != 1):
                raise ValueError('样式包格式无效')
            for entry in entries:
                mode = entry.external_attr >> 16
                if (entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits & 1
                        or (entry.filename != 'manifest.json' and not _ASSET_NAME.fullmatch(entry.filename))
                        or entry.file_size > (_MAX_MANIFEST_BYTES if entry.filename == 'manifest.json' else _MAX_ASSET_BYTES)):
                    raise ValueError('样式包格式无效')
            if sum(item.file_size for item in entries) > _MAX_PACK_BYTES + _MAX_MANIFEST_BYTES:
                raise ValueError('样式包素材过大')
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'))
            if not isinstance(manifest, dict) or manifest.get('format') != 'exifframe-style':
                raise ValueError('样式包格式无效')
            if manifest.get('version') != 1:
                raise ValueError('样式包版本不受支持')
            listed = manifest.get('assets')
            if (not isinstance(listed, list) or any(not isinstance(item, str) for item in listed)
                    or len(listed) != len(set(listed)) or set(listed) != set(names) - {'manifest.json'}):
                raise ValueError('样式包格式无效')
            assets = {}
            for entry in listed:
                data = archive.read(entry)
                match = _ASSET_NAME.fullmatch(entry)
                if (match is None or hashlib.sha256(data).hexdigest() != match.group(1)
                        or _image_bytes(data) != match.group(2)):
                    raise ValueError('样式包素材无效或已损坏')
                assets[entry] = data
            name, source = manifest.get('name'), manifest.get('template')
            if not isinstance(name, str) or not isinstance(source, str):
                raise ValueError('样式包格式无效')
            style = _checked_style(manifest.get('style'))
            return name, source, style, assets
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, RuntimeError) as exc:
        raise ValueError('样式包格式无效') from exc


def import_style_pack(path):
    """同名时自动编号，失败不覆盖已有模板"""
    from core.desktop_service import _template_path, validate_template

    name, source, style, assets = _read_pack(path)
    _template_path(name)
    validate_template(source)
    for index in range(1, 10000):
        suffix = '' if index == 1 else f' ({index})'
        candidate = name[:80 - len(suffix)].rstrip(' .') + suffix
        try:
            return _install(candidate, source, style, assets)
        except FileExistsError:
            continue
    raise FileExistsError('模板已存在，请换一个名称')
