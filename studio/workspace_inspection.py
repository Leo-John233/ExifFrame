"""照片检查器与工作区状态的联动"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from core.desktop_service import read_template, save_workspace_settings
from core.metadata import FIELDS, MetadataError, normalize_watermark_changes
from .i18n import language, localize_error, tr


class WorkspaceInspection:
    """将检查器操作映射为当前照片、勾选照片或工作区设置的修改"""

    @property
    def font_slider(self):
        return self.inspector.font_slider

    def _bind_controls(self):
        panel = self.inspector
        panel.template_selected.connect(self._select_template)
        panel.use_as_default_requested.connect(self._use_as_default)
        panel.style_changed.connect(self._edit_style)
        panel.metadata_changed.connect(self._edit_field)
        panel.metadata_apply_requested.connect(self._apply_fields)
        panel.apply_current_requested.connect(self._apply_current_style)
        panel.sync_style_requested.connect(self._sync_checked_style)
        panel.new_template_requested.connect(self._new_template)
        panel.copy_template_requested.connect(self._copy_template)
        panel.advanced_source_requested.connect(self._edit_template)
        panel.footer_editor_requested.connect(self._edit_footer)
        panel.metadata_editor_requested.connect(self._open_advanced_metadata)
        panel.metadata_requested.connect(self._refresh_footer_examples)
        panel.export_changed.connect(self._export_setting_changed)
        panel.output_directory_requested.connect(self._choose_output)
        panel.save_settings_requested.connect(self._save_config)
        panel.reset_settings_requested.connect(self._reset_config)
        panel.lock_settings_toggled.connect(self._set_locked)
        self.input_input.textEdited.connect(self._directories_changed)
        self.output_input.textEdited.connect(self._directories_changed)
        self.state.selected_photo_changed.connect(self._inspect_photo)
        self.state.active_template_changed.connect(self._active_template_changed)
        self.state.checked_paths_changed.connect(self._checked_paths_changed)
        self.state.style_changed.connect(self._styles_changed)
        self.state.metadata_changed.connect(self._metadata_changed)

    def _read_checked_paths(self):
        self.state.set_checked_paths(self.files.selected_paths())

    def _checked_paths_changed(self, paths):
        self._update_actions()
        self._queue_selection_changed()

    def _editable_photo(self):
        return self.state.selected_photo if self._current_kind == 'import' else None

    def _photo_settings(self, path=None):
        path = path if path is not None else self._editable_photo()
        return self.state.settings_for(path, self.settings, template_sources=self._drafts)

    def _restore_controls(self):
        self.input_input.setText(self.settings.input_dir)
        self.output_input.setText(self.settings.output_dir)
        self.inspector.set_presets(self.presets, self.settings.template_name)
        self._inspect_photo()

    def _inspect_photo(self, *_):
        self._show_effective_style()
        self._show_photo_fields()

    def _show_effective_style(self):
        settings = self._photo_settings()
        for editor in self._editors:
            if hasattr(editor, 'set_preview') and (editor.name != settings.template_name or
                    (editor.source_photo is not None and editor.source_photo != self._editable_photo())):
                editor.hide()
        self.inspector.set_settings(settings)
        try:
            source = settings.template_source or read_template(settings.template_name)
        except (ValueError, OSError):
            source = ''
        self.inspector.inline_footer.set_source(source)

    def _show_photo_fields(self, metadata=None, *, force=False):
        path = self.state.selected_photo
        values = dict(metadata or {})
        if path:
            if metadata is None and self.inspector.metadata_visible:
                values = self._template_context()['metadata'] or {}
            values = {**values, **self.state.metadata_for(path)}
            for tag, alias in (('Model', 'CameraModelName'), ('ExposureTime', 'ShutterSpeed')):
                if not values.get(tag) and values.get(alias):
                    values[tag] = values[alias]
        self.inspector.set_photo(path, values, force=force, read_only=self._current_kind == 'output')

    def _show_style_tab(self):
        self.inspector.show_style_tab()

    def _show_metadata_tab(self):
        self.inspector.show_metadata_tab()

    def _open_advanced_metadata(self):
        path = self._editable_photo()
        if path:
            self._open_metadata_editor((path,), path)

    def _select_template(self, name):
        if not any(preset.name == name for preset in self.presets):
            return
        path = self._editable_photo()
        if path:
            if self._photo_settings().template_name != name:
                self.state.update_style((path,), {'template_name': name, 'template_source': ''})
        elif self._current_kind == 'import':
            self.state.set_active_template(name)

    def _use_as_default(self):
        name = self._photo_settings().template_name
        if name and not self._locked:
            self.state.set_active_template(name)
            self._set_status('默认模板已设为 {name}', name=name)

    def _active_template_changed(self, name):
        self.settings = replace(self.settings, template_name=name, use_template_styles=True)
        self._workspace_changed()
        self._style_preview_changed()

    def _edit_style(self, key, value):
        path = self._editable_photo()
        if self._locked or self._exporting or self._current_kind == 'output':
            return
        settings = self._photo_settings()
        changes = {key: value}
        if key == 'template_source':
            changes['template_name'] = settings.template_name
        elif key != 'use_template_styles':
            changes['use_template_styles'] = False
            if settings.use_template_styles:
                changes.update(background_override=False, text_color_override=False, border_override=False)
                if key != 'font_scale':
                    changes['font_scale'] = 1.0
            if key in ('background', 'text_color'):
                changes[key + '_override'] = True
            elif key == 'border_percent':
                changes.update(border_percent=value if value is not None else settings.border_percent,
                               border_override=value is not None)
        if path:
            self.state.update_style((path,), changes)
        else:
            if key == 'template_source':
                self._drafts[settings.template_name] = value
            else:
                self.settings = replace(self.settings, **changes)
                self._workspace_changed()
            self._style_preview_changed()

    def _apply_current_style(self):
        path = self._editable_photo()
        if path and not self._locked:
            self.state.update_style((path,), self.state.effective_style(path, self.settings, template_sources=self._drafts))
            self._set_status('样式已应用到当前照片')

    def _sync_checked_style(self):
        self._read_checked_paths()
        targets = self.state.checked_paths
        path = self._editable_photo()
        if targets and path and not self._locked:
            self.state.update_style(targets, self.state.effective_style(path, self.settings, template_sources=self._drafts))
            self._set_status('样式已同步到 {count} 张照片', count=len(targets))

    def _styles_changed(self, paths):
        if self._editable_photo() in paths:
            self._style_preview_changed()
        else:
            self._sync_template_context()

    def _style_preview_changed(self):
        self._show_effective_style()
        self._context_pending = True
        self._schedule_preview()

    def _edit_field(self, tag, value):
        path = self._editable_photo()
        if path:
            self._store_fields((path,), {tag: value})

    def _apply_fields(self, scope, values):
        self._read_checked_paths()
        targets = self.state.checked_paths if scope == 'checked' else (self._editable_photo(),)
        if self._editable_photo() and targets and values and self._store_fields(targets, values):
            self._set_status('已向 {count} 张照片应用 {fields} 个字段', count=len(targets), fields=len(values))

    def _store_fields(self, paths, fields):
        if self._locked or self._exporting:
            return False
        try:
            normalized = normalize_watermark_changes(fields)
        except MetadataError as exc:
            label = next((field.label for field in FIELDS if field.tag == exc.field), exc.field)
            self._set_status('请检查字段格式：{field}', field=label)
            return False
        updates = {}
        for path in paths:
            key = self.state.photo_key(path)
            values = self.state.metadata_for(path)
            for tag, raw in fields.items():
                if not str(raw).strip():
                    values.pop(tag, None)
            values.update(normalized)
            updates[key] = values
        self.state.update_metadata(updates)
        return True

    def _metadata_changed(self, keys):
        for editor in self._metadata_editors:
            editor.overrides = self.state.metadata_overrides
        self._sync_template_context()
        path = self._editable_photo()
        if path and self.state.photo_key(path) in keys:
            self._show_photo_fields()
            self._schedule_preview()
            self._refresh_footer_examples(request=False)

    def _export_setting_changed(self, key, value):
        self.settings = replace(self.settings, **{key: value})
        if key == 'output_dir':
            self.output_input.setText(value)
        self._workspace_changed()

    def _directories_changed(self, *_):
        self.settings = replace(self.settings, input_dir=self.input_input.text().strip(),
                                output_dir=self.output_input.text().strip())
        self.inspector.set_settings(self._photo_settings())
        self._workspace_changed()

    def _workspace_changed(self):
        self._dirty = self.settings != self._saved
        self._update_actions()

    def _set_locked(self, locked):
        self._locked = bool(locked)
        self.lock_action.setChecked(self._locked)
        self.inspector.set_locked(self._locked)
        self.input_input.setReadOnly(self._locked)
        self.output_input.setReadOnly(self._locked)

    def _save_config(self):
        try:
            save_workspace_settings(self.settings)
        except (ValueError, OSError) as exc:
            self._record_errors('保存设置失败', [str(exc)])
            return False
        self._saved = deepcopy(self.settings)
        self._workspace_changed()
        self._set_status('设置已保存')
        return True

    def _reset_config(self):
        old_directories = self.settings.input_dir, self.settings.output_dir
        restored = deepcopy(self._saved)
        self.state.set_active_template(restored.template_name)
        self.settings = restored
        self._restore_controls()
        self._workspace_changed()
        self._schedule_preview()
        if old_directories != (restored.input_dir, restored.output_dir):
            for kind, folder in (('import', restored.input_dir), ('output', restored.output_dir)):
                if folder and Path(folder).is_dir():
                    self._scan_directory(kind, folder)
                else:
                    self.files.begin_scan(kind, None)

    def _retranslate_ui(self):
        for code, action in self.language_actions.items():
            action.setChecked(code == language())
        if not self._current_data:
            self.canvas_name.setText(tr('预览'))
        self._set_status(self._status_source, **self._status_values)
        self._set_preview_status(self._preview_source, **self._preview_values)
        self.preview_status.setToolTip(localize_error(self._preview_error))
        self._summary_changed(self._counts)
        for dialog, editor in self._error_dialogs:
            dialog.setWindowTitle(tr('处理详情'))
            editor.setPlainText(self._error_details())
        self._update_actions()
