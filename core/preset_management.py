"""自定义预设的安全文件操作与可回收素材识别"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from core.desktop_service import _PRESET_INFO, _template_path
from core.runtime_paths import config_path
from core.style_pack import _ASSET_FIELD, _install, _prepare, _style_path, _write_unique, asset_signature


_OWNED_NAME = re.compile(r'([0-9a-f]{64})\.(?:png|jpe?g|webp)$', re.I)
_OWNED_FOLDER = re.compile(r'[0-9a-f]{32}$', re.I)


def is_builtin_preset(name):
    return str(name).casefold() in {item.casefold() for item in _PRESET_INFO}


def _check_custom(name):
    if is_builtin_preset(name):
        raise ValueError('内置模板不可修改，请先复制为我的模板')
    path, style = _template_path(name), _style_path(name)
    if path.is_symlink() or style.is_symlink():
        raise ValueError('不能修改链接形式的模板文件')
    if not path.is_file():
        raise FileNotFoundError('模板文件不存在')
    return path, style


def _check_destination(name, old=None):
    target, style = _template_path(name), _style_path(name)
    if is_builtin_preset(name):
        raise ValueError('内置模板不可修改，请先复制为我的模板')
    for folder in (target.parent, style.parent):
        if folder.is_dir():
            for item in folder.glob('*.json'):
                if item.stem.casefold() == name.casefold() and (old is None or item.stem != old):
                    raise FileExistsError('模板名称已存在')
    return target, style


def _snapshot(path):
    return path.read_bytes() if path.is_file() else None


def _restore(path, data):
    if data is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_replace(path, data)


def _atomic_replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.preset-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update_saved_default(old, new):
    """只更新 INI 中已经保存的模板名，保留其他设置和排版"""
    from core import desktop_service
    path = desktop_service.WORKSPACE_CONFIG_PATH
    if not path.is_file():
        return None
    if path.is_symlink():
        raise ValueError('不能修改链接形式的设置文件')
    original = path.read_bytes()
    try:
        text = original.decode('utf-8-sig')
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
    except (UnicodeError, configparser.Error) as error:
        raise ValueError('无法读取已保存的默认模板') from error
    section = parser._sections.get('render', {})
    if section.get('template_name', '').strip() != old:
        return None
    in_render, changed, lines = False, False, []
    for line in text.splitlines(keepends=True):
        heading = re.match(r'^\s*\[([^]]+)\]', line)
        if heading:
            in_render = heading.group(1).strip().casefold() == 'render'
        match = re.match(r'^(\s*template_name\s*[=:]\s*)(.*?)([ \t]*)(\r?\n|$)', line, re.I) if in_render else None
        if match and match.group(2).strip() == old:
            line = match.group(1) + new + match.group(3) + match.group(4)
            changed = True
        lines.append(line)
    if not changed:
        raise ValueError('无法读取已保存的默认模板')
    updated = ''.join(lines).encode('utf-8')
    if original.startswith(b'\xef\xbb\xbf'):
        updated = b'\xef\xbb\xbf' + updated
    if path.read_bytes() != original:
        raise OSError('设置在更新期间发生变化，请重试')
    _atomic_replace(path, updated)
    return path, original, updated


def rollback_saved_default(change):
    if change:
        path, original, updated = change
        if _snapshot(path) == updated:
            _atomic_replace(path, original)


def _style_value(data):
    try:
        style = json.loads(data.decode('utf-8')) if data is not None else {}
        return style.get('logo_choice', '') if isinstance(style, dict) else ''
    except (UnicodeError, ValueError):
        return ''


def _managed_root():
    path = config_path('style_assets')
    for item in (path, path.parent):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            return None
    return path.resolve()


def referenced_assets(source, style_data=None):
    """只返回位于应用素材目录且内容与名称匹配的托管图片"""
    root = _managed_root()
    if root is None or not root.is_dir():
        return set()
    result = set()
    for value, *_ in asset_signature(source, _style_value(style_data)):
        raw = str(value).replace('\\', '/')
        parts = raw.split('/')
        if len(parts) >= 3 and [p.casefold() for p in parts[:2]] == ['config', 'style_assets']:
            path = root.joinpath(*parts[2:])
        else:
            path = Path(value).expanduser()
        try:
            if path.is_symlink() or path.parent.is_symlink() or getattr(path.parent, 'is_junction', lambda: False)():
                continue
            resolved = path.resolve(strict=True)
            rel = resolved.relative_to(root)
            if len(rel.parts) not in (1, 2) or (len(rel.parts) == 2 and not _OWNED_FOLDER.fullmatch(rel.parts[0])):
                continue
            match = _OWNED_NAME.fullmatch(rel.name)
            if not match or not resolved.is_file():
                continue
            if hashlib.sha256(resolved.read_bytes()).hexdigest().casefold() == match.group(1).casefold():
                result.add(resolved)
        except (OSError, ValueError):
            continue
    return result


def _owned_file(path, root):
    try:
        path = Path(path)
        if path.is_symlink() or path.parent.is_symlink() or getattr(path.parent, 'is_junction', lambda: False)():
            return None
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(root)
        if (len(relative.parts) not in (1, 2) or
                (len(relative.parts) == 2 and not _OWNED_FOLDER.fullmatch(relative.parts[0]))):
            return None
        match = _OWNED_NAME.fullmatch(relative.name)
        if not match or not resolved.is_file():
            return None
        if hashlib.sha256(resolved.read_bytes()).hexdigest().casefold() != match.group(1).casefold():
            return None
        return resolved, relative
    except (OSError, ValueError):
        return None


def _variant_manifest(path):
    """无法证明侧车完整时不碰同目录素材"""
    manifest = path.parent / '.exifframe-logo-variants.json'
    if not manifest.exists() and not manifest.is_symlink():
        return None
    if manifest.is_symlink() or not manifest.is_file():
        return False
    try:
        data = manifest.read_bytes()
        if len(data) > 1024 * 1024:
            return False
        document = json.loads(data.decode('utf-8'))
        pairs = document.get('pairs') if isinstance(document, dict) and document.get('version') == 1 else None
        if not isinstance(pairs, list):
            return False
        names = []
        for pair in pairs:
            if (not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1] or
                    any(not isinstance(item, str) or not _OWNED_NAME.fullmatch(item) for item in pair)):
                return False
            names.extend(item.casefold() for item in pair)
        if len(names) != len(set(names)):
            return False
        return manifest, data, document
    except (OSError, UnicodeError, ValueError):
        return False


def cleanup_unused_assets(candidates, protected_values=()):
    """只清理无其他引用的托管素材，深浅变体作为整体保留"""
    from processor.logo_layer import logo_variant_pair
    root = _managed_root()
    if root is None or not root.is_dir():
        return 0
    texts = []
    try:
        for folder in (_template_path('_probe').parent, _style_path('_probe').parent):
            if folder.is_dir():
                for path in folder.glob('*.json'):
                    if path.is_symlink():
                        return 0
                    texts.append(path.read_text(encoding='utf-8'))
        texts.extend(str(value) for value in protected_values if value is not None)
    except (OSError, UnicodeError):
        return 0
    normalized = [text.replace('\\\\', '/').replace('\\', '/').casefold() for text in texts]
    # 动态素材路径无法穷举时，保留所有候选素材
    if any(re.search(r'style_assets[^\"\'\n]*(?:\{\{|\{%|\+)', text) for text in normalized):
        return 0
    for text in texts:
        for match in _ASSET_FIELD.finditer(text):
            try:
                value = json.loads(match.group(2))
            except ValueError:
                return 0
            if isinstance(value, str) and ('{{' in value or '{%' in value) and 'auto_logo(' not in value:
                return 0
    removed, processed = 0, set()
    for path in candidates:
        owned = _owned_file(path, root)
        if owned is None or owned[0] in processed:
            continue
        resolved, relative = owned
        manifest = _variant_manifest(resolved)
        if manifest is False:
            continue
        pair_names = next((pair for pair in manifest[2]['pairs'] if resolved.name in pair), None) if manifest else None
        group = [owned]
        if pair_names is not None:
            pair = logo_variant_pair(resolved)
            if not pair or set(item.name for item in pair) != set(pair_names):
                continue
            group = [_owned_file(item, root) for item in pair]
            if any(item is None for item in group):
                continue
        processed.update(item[0] for item in group)
        if any(('style_assets/' + item[1].as_posix()).casefold() in text
               for item in group for text in normalized):
            continue
        try:
            for member, _ in group:
                member.unlink()
                removed += 1
            if pair_names is not None:
                marker, original, document = manifest
                remaining = [pair for pair in document['pairs'] if pair != pair_names]
                if marker.read_bytes() == original:
                    if remaining or set(document) - {'version', 'pairs'}:
                        document['pairs'] = remaining
                        _atomic_replace(marker, (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
                    else:
                        marker.unlink()
            if len(relative.parts) == 2 and _OWNED_FOLDER.fullmatch(relative.parts[0]):
                try:
                    resolved.parent.rmdir()
                except OSError:
                    pass
        except OSError:
            continue
    return removed


def duplicate_preset(name, destination, source, settings):
    """通过样式包管线复制所引用的素材，不依赖原模板文件"""
    _check_destination(destination)
    packed, style, assets = _prepare(source, settings)
    return _install(destination, packed, style, assets)


def rename_preset(name, destination):
    path, style = _check_custom(name)
    target, target_style = _check_destination(destination, old=name)
    if name == destination:
        return name
    source_data, style_data = path.read_bytes(), _snapshot(style)
    target.parent.mkdir(parents=True, exist_ok=True)
    target_style.parent.mkdir(parents=True, exist_ok=True)
    if _snapshot(path) != source_data or _snapshot(style) != style_data:
        raise OSError('模板在保存期间发生变化，请重试')
    if name.casefold() == destination.casefold():
        # Windows 大小写变更先绕过旧名，再以回滚保护两个文件
        intermediate = path.with_name(f'.preset-rename-{uuid4().hex}.tmp')
        intermediate_style = style.with_name(f'.preset-rename-{uuid4().hex}.tmp')
        moved_source = moved_style = False
        try:
            os.rename(path, intermediate)
            moved_source = True
            if style_data is not None:
                os.rename(style, intermediate_style)
                moved_style = True
            os.rename(intermediate, target)
            moved_source = False
            if moved_style:
                os.rename(intermediate_style, target_style)
                moved_style = False
        except Exception:
            if moved_source:
                os.rename(intermediate, path)
            elif target.exists() and not path.exists():
                os.rename(target, path)
            if moved_style:
                os.rename(intermediate_style, style)
            elif style_data is not None and target_style.exists() and not style.exists():
                os.rename(target_style, style)
            raise
        return destination
    written = []
    try:
        if style_data is not None:
            _write_unique(target_style, style_data)
            written.append(target_style)
        _write_unique(target, source_data)
        written.append(target)
        if _snapshot(path) != source_data or _snapshot(style) != style_data:
            raise OSError('模板在保存期间发生变化，请重试')
        path.unlink()
        if style_data is not None:
            if _snapshot(style) != style_data:
                raise OSError('模板在保存期间发生变化，请重试')
            style.unlink()
    except Exception:
        if not path.exists():
            _write_unique(path, source_data)
        if style_data is not None and not style.exists():
            _write_unique(style, style_data)
        for item in written:
            item.unlink(missing_ok=True)
        raise
    return destination


def delete_preset(name):
    path, style = _check_custom(name)
    source, style_data = path.read_bytes(), _snapshot(style)
    candidates = referenced_assets(source.decode('utf-8'), style_data)
    try:
        if _snapshot(path) != source or _snapshot(style) != style_data:
            raise OSError('模板在保存期间发生变化，请重试')
        path.unlink()
        if style_data is not None:
            if _snapshot(style) != style_data:
                raise OSError('模板在保存期间发生变化，请重试')
            style.unlink()
    except Exception:
        if not path.exists():
            _write_unique(path, source)
        if style_data is not None and not style.exists():
            _write_unique(style, style_data)
        raise
    return candidates


def overwrite_preset(name, source, settings):
    path, style_path = _check_custom(name)
    old_source, old_style = path.read_bytes(), _snapshot(style_path)
    candidates = referenced_assets(old_source.decode('utf-8'), old_style)
    packed, style, assets = _prepare(source, settings)
    stage_name = f'__exifframe_stage_{uuid4().hex}'
    stage, stage_style = _template_path(stage_name), _style_path(stage_name)
    created = set()
    wrote_source = wrote_style = completed = False
    staged_source = staged_style = None
    try:
        _install(stage_name, packed, style, assets)
        staged_source, staged_style = stage.read_bytes(), stage_style.read_bytes()
        created = referenced_assets(staged_source.decode('utf-8'), staged_style)
        if path.read_bytes() != old_source or _snapshot(style_path) != old_style:
            raise OSError('模板在保存期间发生变化，请重试')
        _atomic_replace(path, staged_source)
        wrote_source = True
        _atomic_replace(style_path, staged_style)
        wrote_style = completed = True
    except Exception:
        if wrote_source and _snapshot(path) == staged_source:
            _restore(path, old_source)
        if wrote_style and _snapshot(style_path) == staged_style:
            _restore(style_path, old_style)
        raise
    finally:
        stage.unlink(missing_ok=True)
        stage_style.unlink(missing_ok=True)
        if created and not completed:
            cleanup_unused_assets(created)
    return candidates
