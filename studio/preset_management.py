"""预设卡片动作与工作区状态联动"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import os

from PySide6.QtCore import QProcess, QSignalBlocker, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog, QMessageBox

from core.desktop_service import WatermarkSettings, _template_path, list_presets, read_template
from core.preset_management import (cleanup_unused_assets, delete_preset, duplicate_preset,
                                    is_builtin_preset, overwrite_preset, rename_preset,
                                    rollback_saved_default, update_saved_default)
from core.style_pack import read_preset_style
from .i18n import localize_error, tr
from .preset_thumbnail import thumbnail_manager


class WorkspacePresetManagement:
    """卡片管理不改变其他照片的元信息和无关草稿"""

    def _preset_feedback(self, source, **values):
        self._set_status(source, **values)
        self.inspector.show_preset_message(source, **values)

    def _preset_allowed(self, name, *, mutable=False):
        if self._locked or self._exporting or self._current_kind == 'output':
            self._preset_feedback('当前状态无法管理模板')
            return False
        if not any(preset.name == name for preset in self.presets):
            self._preset_feedback('模板文件不存在')
            return False
        if mutable and is_builtin_preset(name):
            self._preset_feedback('内置模板不可修改，请先复制为我的模板')
            return False
        return True

    def _preset_error(self, error):
        self._record_errors('模板操作失败', [str(error)])
        self._preset_feedback('模板操作失败：{error}', error=localize_error(error))
        QMessageBox.warning(self, tr('模板操作失败'), localize_error(error))

    def _preset_protected_values(self):
        values = [repr(asdict(self.settings)), repr(asdict(self._saved)), repr(self._drafts),
                  repr(self.state.per_photo_overrides)]
        if hasattr(self, 'source_panel'):
            values.extend((self.source_panel.edit.toPlainText(), repr(self.source_panel._pending),
                           self.source_panel._accepted))
        for editor in self._editors:
            try:
                if hasattr(editor, 'source'):
                    values.append(editor.source())
            except RuntimeError:
                # 已销毁的窗口不再持有可用草稿
                pass
        for index in range(self.history.stack.count()):
            command = self.history.stack.command(index)
            values.extend((repr(getattr(command, 'before', '')), repr(getattr(command, 'after', ''))))
        return values

    def _refresh_preset_cards(self):
        self.presets = list_presets()
        selected = self._photo_settings().template_name
        self.inspector.set_presets(self.presets, selected)
        self._show_effective_style()
        self._update_actions()

    def _preset_current_source(self, settings):
        panel = getattr(self, 'source_panel', None)
        if panel is not None and panel._target == (self._editable_photo(), settings.template_name):
            return panel.edit.toPlainText()
        return self._effective_template_source(settings)

    def _preset_copy(self, name):
        if not self._preset_allowed(name):
            return
        suggested = tr('{name} 副本', name=name)
        destination, accepted = QInputDialog.getText(self, tr('复制模板'), tr('请输入模板名称'), text=suggested)
        if not accepted or not destination.strip():
            return
        try:
            current = self._photo_settings()
            if current.template_name == name:
                settings = current
                source = self._preset_current_source(settings)
            else:
                settings = replace(WatermarkSettings(template_name=name), **read_preset_style(name))
                source = self._drafts.get(name) or read_template(name)
            destination = duplicate_preset(name, destination.strip(), source, settings)
            self._template_saved(destination)
            self.inspector.show_my_templates()
            self._preset_feedback('已复制模板：{name}', name=destination)
        except (OSError, ValueError, TypeError) as error:
            self._preset_error(error)

    def _preset_overwrite(self, name):
        if not self._preset_allowed(name, mutable=True):
            return
        prompt = tr('用当前照片的调整覆盖模板“{name}”？此操作会替换已保存的模板。', name=name)
        if QMessageBox.question(self, tr('覆盖模板'), prompt,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            settings = self._photo_settings()
            source = self._preset_current_source(settings)
            candidates = overwrite_preset(name, source, settings)
            getattr(self, '_frame_baselines', {}).pop(name, None)
            thumbnail_manager().invalidate(name)
            if settings.template_name == name:
                self._drafts.pop(name, None)
                self._draft_owners.pop(name, None)
                path = self._editable_photo()
                if path is not None:
                    self.state.update_style((path,), {'template_source': ''})
                elif self.settings.template_name == name:
                    self.settings = replace(self.settings, template_source='')
            self._refresh_preset_cards()
            self._style_preview_changed()
            cleanup_unused_assets(candidates, self._preset_protected_values())
            self._preset_feedback('已覆盖模板：{name}', name=name)
        except (OSError, ValueError, TypeError) as error:
            self._preset_error(error)

    @staticmethod
    def _remap_history_value(value, old, new, deleted=False):
        value = deepcopy(value)
        if isinstance(value, tuple) and len(value) == 3:
            settings, active, drafts = value
            if isinstance(settings, dict) and settings.get('template_name') == old:
                settings['template_name'] = new
                if deleted:
                    settings['template_source'] = ''
            if active == old:
                active = new
            if isinstance(drafts, dict) and old in drafts:
                draft = drafts.pop(old)
                if not deleted:
                    drafts[new] = draft
            return settings, active, drafts
        if isinstance(value, dict):
            for style in value.values():
                if isinstance(style, dict) and style.get('template_name') == old:
                    style['template_name'] = new
                    if deleted:
                        style.pop('template_source', None)
        return value

    def _remap_preset_history(self, old, new, *, deleted=False):
        for index in range(self.history.stack.count()):
            command = self.history.stack.command(index)
            if getattr(command, 'kind', None) != 'style':
                continue
            command.before = self._remap_history_value(command.before, old, new, deleted)
            command.after = self._remap_history_value(command.after, old, new, deleted)

    def _remap_preset_session(self, old, new, *, deleted=False):
        panel = getattr(self, 'source_panel', None)
        if panel is not None:
            pending = {}
            for target, draft in panel._pending.items():
                if target[1] != old:
                    pending[target] = draft
                elif not deleted:
                    pending[(target[0], new)] = draft
            panel._pending = pending
            if panel._target and panel._target[1] == old:
                if deleted:
                    panel.timer.stop()
                    panel._target = None
                    panel._accepted = ''
                else:
                    panel._target = (panel._target[0], new)
        if old in self._drafts:
            draft = self._drafts.pop(old)
            if not deleted:
                self._drafts[new] = draft
        if old in self._draft_owners:
            owner = self._draft_owners.pop(old)
            if not deleted:
                self._draft_owners[new] = owner
        mappings = {}
        for path, fields in self.state.per_photo_overrides.items():
            style = fields.get('style', {})
            if style.get('template_name') == old:
                style['template_name'] = new
                if deleted:
                    style.pop('template_source', None)
                mappings[Path(path)] = style
        old_settings = self.settings
        if self.state.active_template == old:
            self.state.set_active_template(new)
            self.settings = replace(old_settings, template_name=new,
                                    template_source='' if deleted else old_settings.template_source)
        elif self.settings.template_name == old:
            self.settings = replace(self.settings, template_name=new,
                                    template_source='' if deleted else self.settings.template_source)
        if self._saved.template_name == old:
            self._saved = replace(self._saved, template_name=new,
                                  template_source='' if deleted else self._saved.template_source)
        if mappings:
            self.state.restore_styles(mappings)
        self._remap_preset_history(old, new, deleted=deleted)
        for editor in tuple(self._editors):
            if getattr(editor, 'name', None) != old:
                continue
            if deleted:
                editor._handoff = True
                if hasattr(editor, 'close_for_handoff'):
                    editor.close_for_handoff()
                else:
                    editor.hide()
                continue
            editor.name = new
            if getattr(editor, 'preview_target', None) == old:
                editor.preview_target = new
            if getattr(editor, '_saved_name', None) == old:
                editor._saved_name = new
            if hasattr(editor, 'name_input') and editor.name_input.text() == old:
                with QSignalBlocker(editor.name_input):
                    editor.name_input.setText(new)
            if hasattr(editor, 'preview') and hasattr(editor.preview, '_settings'):
                editor.preview._settings.template_name = new
            if hasattr(editor, '_update_title'):
                editor._update_title()
        getattr(self, '_frame_baselines', {}).pop(old, None)
        getattr(self, '_frame_baselines', {}).pop(new, None)
        self._workspace_changed()

    def _preset_rename(self, name):
        if not self._preset_allowed(name, mutable=True):
            return
        destination, accepted = QInputDialog.getText(self, tr('重命名模板'), tr('请输入模板名称'), text=name)
        if not accepted or not destination.strip() or destination.strip() == name:
            return
        try:
            destination = destination.strip()
            change = update_saved_default(name, destination)
            try:
                destination = rename_preset(name, destination)
            except Exception:
                rollback_saved_default(change)
                raise
            thumbnail_manager().invalidate(name)
            self.presets = list_presets()
            self._remap_preset_session(name, destination)
            self._refresh_preset_cards()
            self._style_preview_changed()
            self._preset_feedback('已重命名模板：{name}', name=destination)
        except (OSError, ValueError, TypeError) as error:
            self._preset_error(error)

    def _preset_fallback(self, deleted):
        names = [preset.name for preset in self.presets if preset.name != deleted]
        if self.state.active_template in names:
            return self.state.active_template
        preferred = WatermarkSettings().template_name
        return preferred if not names or preferred in names else next((name for name in names if is_builtin_preset(name)), names[0])

    def _preset_delete(self, name):
        if not self._preset_allowed(name, mutable=True):
            return
        prompt = tr('删除模板“{name}”？不再使用的模板素材也将被删除。', name=name)
        if QMessageBox.question(self, tr('删除模板'), prompt,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            fallback = self._preset_fallback(name)
            change = update_saved_default(name, fallback)
            try:
                candidates = delete_preset(name)
            except Exception:
                rollback_saved_default(change)
                raise
            thumbnail_manager().invalidate(name)
            self.presets = list_presets()
            self._remap_preset_session(name, fallback, deleted=True)
            self._refresh_preset_cards()
            self._style_preview_changed()
            cleanup_unused_assets(candidates, self._preset_protected_values())
            self._preset_feedback('已删除模板：{name}', name=name)
        except (OSError, ValueError, TypeError, IndexError) as error:
            self._preset_error(error)

    def _preset_reveal(self, name):
        if not self._preset_allowed(name):
            return
        try:
            target = _template_path(name).resolve(strict=True)
            if os.name == 'nt':
                started, _ = QProcess.startDetached('explorer.exe', [f'/select,{target}'])
                if not started:
                    raise OSError(tr('无法打开模板文件夹'))
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent))):
                raise OSError(tr('无法打开模板文件夹'))
            self._preset_feedback('已在文件管理器中显示：{name}', name=name)
        except (OSError, ValueError) as error:
            self._preset_error(error)
