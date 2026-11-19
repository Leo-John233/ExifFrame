"""便携样式包和用户选用的图像素材"""

from __future__ import annotations

import base64
import binascii
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

from PIL import Image, ImageColor, PngImagePlugin

from core.logo_variants import VARIANT_MAP_NAME, logo_variant_pair
from core.runtime_paths import config_path


_MAX_ASSET_BYTES = 64 * 1024 * 1024
_MAX_ASSET_PIXELS = 100_000_000
_MAX_PACK_BYTES = 256 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_MAX_CARD_PACK_BYTES = 40 * 1024 * 1024
_CARD_KEY = 'ExifFramePreset'
_ASSET_NAME = re.compile(r'assets/([0-9a-f]{64})\.(png|jpg)\Z')
_ASSET_FIELD = re.compile(
    r'("(?:left_logo|right_logo|center_logo|path)"\s*:\s*)("(?:\\.|[^"\\])*")', re.S)
_STYLE_FIELDS = (
    'title', 'subtitle', 'show_logo', 'font_scale', 'border_percent', 'border_override',
    'background', 'text_color', 'background_override', 'text_color_override',
    'use_template_styles', 'logo_choice', 'font_path', 'text_alignment',
    'text_spacing', 'line_spacing', 'brand_glyph_policy',
)


class _StyleAssets(dict):
    """与图片字节一起携带可选的深浅标识配对"""

    def __init__(self, *args, variants=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.variants = list(variants)


def _checked_variants(variants, names):
    """只接受归档内完整且没有冲突的哈希图片配对"""
    if not isinstance(variants, (list, tuple)) or len(variants) > len(names) // 2:
        raise ValueError('样式包素材无效或已损坏')
    result, membership = [], {}
    for pair in variants:
        if (not isinstance(pair, (list, tuple)) or len(pair) != 2
                or any(not isinstance(item, str) or not _ASSET_NAME.fullmatch(item) or item not in names
                       for item in pair) or pair[0] == pair[1]):
            raise ValueError('样式包素材无效或已损坏')
        pair = tuple(pair)
        if any(item in membership and membership[item] != pair for item in pair):
            raise ValueError('样式包素材无效或已损坏')
        if pair not in result:
            result.append(pair)
        for item in pair:
            membership[item] = pair
    return result


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
    path = Path(path).expanduser()
    if not path.is_file():
        # 旧模板中的内置 DJI.jpg 映射到透明 PNG，外部同名文件不受影响
        from processor.logo_layer import resolve_logo_path
        path = resolve_logo_path(path)
    with path.open('rb') as stream:
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
    for value in tuple(paths):
        path = Path(value).expanduser()
        if re.fullmatch(r'[0-9a-f]{64}\.(?:png|jpg)', path.name):
            paths.append(str(path.parent / VARIANT_MAP_NAME))
        try:
            pair = logo_variant_pair(path)
        except (OSError, ValueError):
            pair = None
        if pair:
            paths.extend(str(path) for path in pair)
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


def _prepare(source, settings, *, asset_root=None):
    """收集实际引用的图像并替换为包内名称"""
    from core.desktop_service import validate_template

    validate_template(source)
    style = _checked_style({key: getattr(settings, key) for key in _STYLE_FIELDS})
    assets = _StyleAssets()

    def add_asset(path):
        data, extension = _read_asset(path)
        name = f'assets/{hashlib.sha256(data).hexdigest()}.{extension}'
        assets[name] = data
        return name

    def collect(value):
        try:
            path = Path(value).expanduser()
            if asset_root is not None and not path.is_absolute():
                candidate = Path(asset_root) / path
                if candidate.is_file():
                    path = candidate
            name = add_asset(path)
        except OSError as exc:
            raise ValueError(f'所选样式引用的素材不存在：{value}') from exc
        pair = logo_variant_pair(path)
        if pair:
            variants = tuple(add_asset(item) for item in pair)
            if len(set(variants)) == 2 and name in variants and variants not in assets.variants:
                assets.variants.append(variants)
        return name

    source = _rewrite_references(source, collect)
    if _image_reference(style['logo_choice']):
        style['logo_choice'] = collect(style['logo_choice'])
    if sum(map(len, assets.values())) > _MAX_PACK_BYTES:
        raise ValueError('样式包素材过大')
    _checked_variants(assets.variants, assets)
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
            variants = _checked_variants(getattr(assets, 'variants', ()), assets)
            if variants:
                pairs = [[Path(item).name for item in pair] for pair in variants]
                (folder / VARIANT_MAP_NAME).write_text(
                    json.dumps({'version': 1, 'pairs': pairs}, ensure_ascii=True), encoding='utf-8')

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
    variants = _checked_variants(getattr(assets, 'variants', ()), assets)
    if variants:
        manifest['logo_variants'] = variants
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


def _write_export(path, writer, *, overwrite=False):
    """完整写入同目录临时文件后发布"""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.preset-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            writer(stream)
        if overwrite:
            os.replace(temporary, target)
        elif os.name == 'nt':
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _archive_bytes(name, source, style, assets):
    manifest = {'format': 'exifframe-style', 'version': 1, 'name': name,
                'template': source, 'style': style, 'assets': sorted(assets)}
    variants = _checked_variants(getattr(assets, 'variants', ()), assets)
    if variants:
        manifest['logo_variants'] = variants
    content = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError('样式包格式无效')
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', content)
        for entry, data in assets.items():
            archive.writestr(entry, data)
    return stream.getvalue()


def export_style_png(path, name, source, settings, preview, *, overwrite=False):
    """以 PNG 预览图保存校验过的完整样式和内嵌素材"""
    from core.desktop_service import _template_path

    _template_path(name)
    if not isinstance(preview, Image.Image) or preview.width <= 0 or preview.height <= 0:
        raise ValueError('模板卡片预览无效')
    source, style, assets = _prepare(source, settings)
    archive = _archive_bytes(name, source, style, assets)
    if len(archive) > _MAX_CARD_PACK_BYTES:
        raise ValueError('模板卡片素材过大，请使用 ZIP 样式包')
    data = {'format': 'exifframe-preset', 'version': 1, 'encoding': 'base64-zip',
            'sha256': hashlib.sha256(archive).hexdigest(),
            'payload': base64.b64encode(archive).decode('ascii')}
    metadata = PngImagePlugin.PngInfo()
    payload = json.dumps(data, ensure_ascii=True, separators=(',', ':'))
    # 大素材已在归档中压缩；避免再次压缩导致常见图片库的文本解压上限报错
    metadata.add_itxt(_CARD_KEY, payload, zip=len(payload) <= PngImagePlugin.MAX_TEXT_CHUNK)
    image = preview.copy()
    image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
    if image.mode not in ('RGB', 'RGBA', 'L', 'LA'):
        image = image.convert('RGBA')
    _write_export(path, lambda stream: image.save(stream, format='PNG', pnginfo=metadata), overwrite=overwrite)


def export_style_json(path, name, source, settings, *, overwrite=False):
    """保存可读配置，图片引用仍指向原有素材"""
    from core.desktop_service import _template_path, validate_template

    _template_path(name)
    validate_template(source)
    style = _checked_style({key: getattr(settings, key) for key in _STYLE_FIELDS})
    content = json.dumps({'format': 'exifframe-preset-json', 'version': 1, 'name': name,
                          'template': source, 'style': style}, ensure_ascii=False, indent=2).encode('utf-8')
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError('样式包格式无效')
    _write_export(path, lambda stream: stream.write(content), overwrite=overwrite)


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
            variants = _checked_variants(manifest.get('logo_variants', ()), listed)
            assets = _StyleAssets(variants=variants)
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


def _read_png_card(path):
    """校验 PNG 元数据、归档摘要和内部素材"""
    try:
        with Image.open(path) as image:
            if image.format != 'PNG':
                raise ValueError('模板卡片图片无效或已损坏')
            payload = image.info.get(_CARD_KEY)
            if payload is not None:
                if Path(path).stat().st_size > _MAX_CARD_PACK_BYTES * 2:
                    raise ValueError('模板卡片素材过大，请使用 ZIP 样式包')
                if image.width * image.height > _MAX_ASSET_PIXELS:
                    raise ValueError('模板卡片图片无效或已损坏')
                image.verify()
    except (OSError, SyntaxError, EOFError, Image.DecompressionBombError) as exc:
        raise ValueError('模板卡片图片无效或已损坏') from exc
    except ValueError as exc:
        if str(exc) in ('模板卡片素材过大，请使用 ZIP 样式包', '模板卡片图片无效或已损坏'):
            raise
        raise ValueError('模板卡片图片无效或已损坏') from exc
    if payload is None:
        raise ValueError('该 PNG 不含 ExifFrame 模板配置，如需作为自定义相框贴图请在「画框定制」中导入')
    try:
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get('format') != 'exifframe-preset':
            raise ValueError
        if data.get('version') != 1:
            raise ValueError('样式包版本不受支持')
        encoded, digest = data.get('payload'), data.get('sha256')
        if (data.get('encoding') != 'base64-zip' or not isinstance(encoded, str)
                or len(encoded) > ((_MAX_CARD_PACK_BYTES + 2) // 3) * 4
                or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
            raise ValueError
        archive = base64.b64decode(encoded, validate=True)
        if len(archive) > _MAX_CARD_PACK_BYTES or hashlib.sha256(archive).hexdigest() != digest:
            raise ValueError('模板卡片数据校验失败')
        return _read_pack(BytesIO(archive))
    except (binascii.Error, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError('模板卡片数据无效或已损坏') from exc
    except ValueError as exc:
        if str(exc) in ('样式包版本不受支持', '模板卡片数据校验失败'):
            raise
        raise ValueError('模板卡片数据无效或已损坏') from exc


def _read_json_config(path):
    """接受完整 JSON 配置或原有的 Jinja 模板源码"""
    from core.desktop_service import WatermarkSettings

    path = Path(path)
    with path.open('rb') as stream:
        data = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(data) > _MAX_MANIFEST_BYTES:
        raise ValueError('样式包格式无效')
    try:
        source = data.decode('utf-8-sig')
    except UnicodeError as exc:
        raise ValueError('样式包格式无效') from exc
    try:
        document = json.loads(source)
    except json.JSONDecodeError:
        # Jinja 控制语句可以出现在 JSON 结构之外
        document = None
    if isinstance(document, dict):
        if document.get('format') != 'exifframe-preset-json':
            raise ValueError('样式包格式无效')
        if document.get('version') != 1:
            raise ValueError('样式包版本不受支持')
        name, source = document.get('name'), document.get('template')
        style = _checked_style(document.get('style'))
        if not isinstance(name, str) or not isinstance(source, str):
            raise ValueError('样式包格式无效')
    elif document is None or isinstance(document, list):
        name = path.stem
        defaults = WatermarkSettings()
        style = _checked_style({key: getattr(defaults, key) for key in _STYLE_FIELDS})
    else:
        raise ValueError('样式包格式无效')
    settings = WatermarkSettings(template_name=name, **style)
    source, style, assets = _prepare(source, settings, asset_root=path.parent)
    return name, source, style, assets


def import_style_pack(path):
    """自动识别 PNG、JSON 和旧样式包，同名时不覆盖已有模板"""
    from core.desktop_service import _template_path, validate_template

    path = Path(path).expanduser()
    with path.open('rb') as stream:
        signature = stream.read(8)
    if signature == b'\x89PNG\r\n\x1a\n' or path.suffix.casefold() == '.png':
        name, source, style, assets = _read_png_card(path)
    elif zipfile.is_zipfile(path) or path.suffix.casefold() in ('.zip', '.efstyle'):
        name, source, style, assets = _read_pack(path)
    else:
        name, source, style, assets = _read_json_config(path)
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
