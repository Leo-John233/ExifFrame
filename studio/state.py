"""集中管理当前照片、逐张样式与会话元数据"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from PySide6.QtCore import QObject, Signal

from core.desktop_service import WatermarkSettings
from core.metadata import metadata_key


STYLE_FIELDS = (
    'template_name', 'template_source', 'title', 'subtitle', 'show_logo', 'font_scale',
    'border_percent', 'border_override', 'background', 'text_color', 'background_override',
    'text_color_override', 'use_template_styles', 'logo_choice', 'font_path', 'text_alignment',
    'text_spacing', 'line_spacing',
)


def _path(path):
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def _key(path):
    return os.path.normcase(str(_path(path)))


def _freeze(value):
    """递归冻结会话快照，避免后台任务观察到后续修改"""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    if isinstance(value, frozenset):
        return set(_thaw(item) for item in value)
    return deepcopy(value)


def _settings(base, identity, photo, template_sources, active_template):
    """只为当前照片组装样式与会话信息"""
    values = {field.name: getattr(base, field.name) for field in fields(WatermarkSettings)}
    style = photo.get('style', {})
    values.update({key: _thaw(value) for key, value in style.items() if key in STYLE_FIELDS})
    name = style.get('template_name') or active_template or base.template_name
    values['template_name'] = name
    source = style.get('template_source') or template_sources.get(name)
    if not source and name == base.template_name:
        source = base.template_source
    values['template_source'] = source or ''
    metadata = photo.get('metadata') if 'metadata' in photo else base.metadata_overrides.get(identity)
    values['metadata_overrides'] = {identity: _thaw(metadata)} if identity is not None and metadata is not None else {}
    return WatermarkSettings(**values)


@dataclass(frozen=True)
class ExportSnapshot:
    """冻结导出参数，避免后续界面编辑改变正在排队的任务"""

    paths: tuple[Path, ...]
    _base: Mapping
    _photos: Mapping
    _aliases: Mapping
    _templates: Mapping
    _active_template: str

    def __deepcopy__(self, memo):
        return self

    def _base_settings(self):
        values = dict(self._base)
        values['input_files'] = tuple(values.get('input_files', ()))
        values['protected_sources'] = tuple(values.get('protected_sources', ()))
        return WatermarkSettings(**values)

    @property
    def template_specs(self):
        """列出本批实际使用的模板和已冻结源码"""
        result = set()
        base = self._base_settings()
        for path in self.paths:
            identity = self._aliases.get(_key(path), _key(path))
            settings = _settings(base, identity, self._photos.get(identity, {}), self._templates,
                                 self._active_template)
            result.add((settings.template_name, settings.template_source))
        return tuple(sorted(result))

    @property
    def template_names(self):
        return tuple(sorted({name for name, _ in self.template_specs}))

    def with_template_sources(self, sources):
        """补齐后台加载的模板源码，保留已有草稿优先级"""
        templates = dict(sources)
        templates.update(self._templates)
        return replace(self, _templates=_freeze(templates))

    def settings_for(self, path):
        identity = self._aliases.get(_key(path), _key(path))
        return _settings(self._base_settings(), identity, self._photos.get(identity, {}),
                         self._templates, self._active_template)


class StudioState(QObject):
    """为界面和后台任务维护统一的照片会话状态"""

    changed = Signal()
    selected_photo_changed = Signal(object)
    checked_paths_changed = Signal(object)
    active_template_changed = Signal(str)
    style_changed = Signal(object)
    metadata_changed = Signal(object)

    def __init__(self, active_template='', parent=None):
        super().__init__(parent)
        self.selected_photo = None
        self.checked_paths = ()
        self.active_template = str(active_template)
        self._photos = {}
        self._aliases = {}

    @property
    def per_photo_overrides(self):
        return {key: {'style': deepcopy(value.get('style', {})),
                      'metadata': deepcopy(value.get('metadata', {}))}
                for key, value in self._photos.items()}

    @property
    def metadata_overrides(self):
        return {key: deepcopy(value['metadata']) for key, value in self._photos.items() if 'metadata' in value}

    def register_photo(self, path, canonical_identity):
        """复用后台扫描的真实路径，避免界面反复访问磁盘"""
        self._aliases[_key(path)] = _key(canonical_identity)

    def _identity(self, path):
        alias = _key(path)
        if alias not in self._aliases:
            self._aliases[alias] = metadata_key(_path(path))
        return self._aliases[alias]

    def photo_key(self, path):
        """返回当前照片的规范身份"""
        return self._identity(path)

    def metadata_for(self, path):
        """返回单张照片的独立会话信息"""
        if path is None:
            return {}
        return deepcopy(self._photos.get(self._identity(path), {}).get('metadata', {}))

    def set_selected_photo(self, path):
        selected = _path(path) if path is not None else None
        if selected != self.selected_photo:
            self.selected_photo = selected
            self.selected_photo_changed.emit(selected)
            self.changed.emit()

    def set_checked_paths(self, paths):
        unique = {}
        for path in paths:
            path = _path(path)
            unique.setdefault(self._aliases.get(_key(path), _key(path)), path)
        checked = tuple(unique.values())
        if checked != self.checked_paths:
            self.checked_paths = checked
            self.checked_paths_changed.emit(checked)
            self.changed.emit()

    def set_active_template(self, name):
        name = str(name)
        if name != self.active_template:
            self.active_template = name
            self.active_template_changed.emit(name)
            self.changed.emit()

    def update_style(self, paths, changes):
        unknown = set(changes) - set(STYLE_FIELDS)
        if unknown:
            raise ValueError(f'未知样式字段：{sorted(unknown)}')
        updated = []
        for path in paths:
            path = _path(path)
            key = self._identity(path)
            photo = self._photos.setdefault(key, {})
            values = {**photo.get('style', {}), **deepcopy(changes)}
            if values != photo.get('style', {}):
                photo['style'] = values
                updated.append(path)
        if updated:
            self.style_changed.emit(tuple(updated))
            self.changed.emit()

    def update_metadata(self, mapping):
        """替换所给照片的完整会话信息，其他照片保持不变"""
        updated = []
        for path, values in mapping.items():
            key = _key(path)
            values = deepcopy(dict(values))
            photo = self._photos.setdefault(key, {})
            if 'metadata' not in photo or values != photo['metadata']:
                photo['metadata'] = values
                updated.append(key)
        if updated:
            self.metadata_changed.emit(tuple(updated))
            self.changed.emit()

    def style_for(self, path):
        if path is None:
            return {}
        return deepcopy(self._photos.get(self._identity(path), {}).get('style', {}))

    def settings_for(self, path, base, *, template_sources=None):
        if path is None:
            return _settings(base, None, {}, template_sources or {}, self.active_template)
        identity = self._identity(path)
        return _settings(base, identity, self._photos.get(identity, {}), template_sources or {},
                         self.active_template)

    def effective_style(self, path, base, *, template_sources=None):
        """返回可复制的完整样式，不包含照片信息和导出参数"""
        settings = self.settings_for(path, base, template_sources=template_sources)
        return {name: deepcopy(getattr(settings, name)) for name in STYLE_FIELDS}

    def export_snapshot(self, paths, base, *, template_sources=None):
        paths = tuple(_path(path) for path in paths)
        aliases = {_key(path): self._identity(path) for path in paths}
        identities = set(aliases.values())
        photos = {key: self._photos[key] for key in identities if key in self._photos}
        values = {field.name: getattr(base, field.name) for field in fields(WatermarkSettings)}
        values['input_files'] = tuple(str(path) for path in paths)
        return ExportSnapshot(paths, _freeze(values), _freeze(photos), _freeze(aliases),
                              _freeze(template_sources or {}), self.active_template)
