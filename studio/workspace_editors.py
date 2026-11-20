"""高级模板、照片信息副本和编辑会话"""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable, Qt, Slot
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
from core.desktop_service import WatermarkSettings, list_presets, read_template, render_photo, write_template
from core.sample_photo import example_photo_path
from core.style_pack import (export_style_json, export_style_pack, export_style_png, import_style_pack,
                             read_preset_style, save_custom_template)
from studio.path_memory import last_directory, remember_directory
from .i18n import localize_error, tr
from .template_editor import TemplateEditor
from .workers import WorkerSignals


class FooterMetadataTask(QRunnable):
    """后台读取与水印渲染一致的照片信息供组合区预览"""

    def __init__(self, token, path):
        super().__init__()
        self.kind, self.token = "footer_metadata", token
        self.paths = (Path(path),)
        self.cancel = Event()
        self.signals = WorkerSignals()

    def run(self):
        try:
            if not self.cancel.is_set():
                from core.desktop_service import _metadata
                path = self.paths[0].resolve()
                info = path.stat()
                modified, size = info.st_mtime_ns, info.st_size
                if self.cancel.is_set():
                    return
                metadata = _metadata(str(path), modified)
                if not self.cancel.is_set():
                    self.signals.result.emit(self.kind, self.token, (path, modified, size, metadata))
        except Exception as exc:
            if not self.cancel.is_set():
                self.signals.error.emit(self.kind, self.token, str(exc))
        finally:
            self.signals.finished.emit(self.kind, self.token)


class StyleCardTask(QRunnable):
    """在后台按冻结的模板和照片生成完整卡片"""

    def __init__(self, token, path, photo, name, source, settings, overwrite):
        super().__init__()
        self.kind, self.token = 'style_card', token
        self.path, self.photo, self.name = Path(path), Path(photo), name
        self.source, self.settings, self.overwrite = source, deepcopy(settings), overwrite
        self.cancel = Event()
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.cancel.is_set():
                return
            image = render_photo(self.photo, self.settings, preview=True, cancelled=self.cancel.is_set)
            if self.cancel.is_set():
                return
            export_style_png(self.path, self.name, self.source, self.settings, image, overwrite=self.overwrite)
            if not self.cancel.is_set():
                self.signals.result.emit(self.kind, self.token, str(self.path))
        except Exception as exc:
            if not self.cancel.is_set():
                self.signals.error.emit(self.kind, self.token, str(exc))
        finally:
            self.signals.finished.emit(self.kind, self.token)


class WorkspaceEditors:
    """高级模板、照片信息副本和编辑会话"""

    def _init_editors(self):
        self._drafts, self._draft_owners = {}, {}
        self._editors, self._metadata_editors = [], []
        self._metadata_close_job = self._active_wizard = None
        self._footer_metadata = {}
        self._footer_metadata_pending = False

    def _show_template_editor(self, editor):
        """恢复收起的编辑器并补上当前预览，不重建草稿"""
        if hasattr(editor, "set_preview"):
            # 组合水印使用输入原片，输出成品仍只作结果查看
            if self.files.tabs.currentIndex() != 0:
                self.files.tabs.setCurrentIndex(0)
            if self._current_path() is None and self.files.items["import"]:
                items = list(self.files.items["import"].values())
                selected = next((item for item in items if item.checkState(0) == Qt.CheckState.Checked), items[0])
                self.input_tree.setCurrentItem(selected)
            for other in self._editors:
                if other is not editor and hasattr(other, "set_preview"):
                    other.hide()
            if editor.name != self._photo_settings().template_name:
                self._select_template(editor.name)
            original = self._ensure_watermark_mode()
            image = self._current_footer_image()
            editor.set_preview(image)
            if self._comparison_image is not None:
                editor.photo_view.set_original_image(self._comparison_image)
            if self._current_path() and (original or image is None):
                self._schedule_preview()
        # 只取消最小化，保留用户已有的最大化状态
        editor.setWindowState(editor.windowState() & ~Qt.WindowState.WindowMinimized)
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _show_main_from_editor(self, editor):
        """收起编辑窗口前提交有效预览，尚未保存的组合仍留在窗口中"""
        editor.apply_preview()
        editor.hide()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _edit_metadata(self):
        self.inspector.show_metadata_tab()

    def _advanced_checked_metadata(self):
        self.inspector.show_metadata_tab()

    def _open_metadata_editor(self, paths, current):
        from .metadata_editor import MetadataEditor
        if self._exporting or self._closing:
            return
        # 同时仅保留一个编辑会话，避免旧的完整映射覆盖较新的修改
        if self._metadata_editors:
            editor = self._metadata_editors[0]
            same_scope = tuple(editor.paths) == tuple(paths) and editor.current == current
            if same_scope or editor._job is not None or not editor.close():
                editor.show()
                editor.raise_()
                editor.activateWindow()
                return
        editor = MetadataEditor(self, paths=paths, current=current, overrides=self.state.metadata_overrides, copy_only=True)
        editor.applied.connect(self._metadata_applied)
        editor.finished.connect(lambda result, window=editor: self._metadata_editor_closed(window))
        self._metadata_editors.append(editor)
        editor.show()

    @Slot(dict)
    def _metadata_applied(self, overrides):
        """替换会话覆盖值并使进行中的预览失效"""
        current = self.state.metadata_overrides
        updates = {key: overrides.get(key, {}) for key in current.keys() | overrides.keys()
                   if current.get(key) != overrides.get(key)}
        self.state.update_metadata(updates)
        self._show_photo_fields(force=True)
        if self._visible_footer_editors():
            self._ensure_watermark_mode()
        self._schedule_preview()
        self._refresh_footer_examples()
        self._set_status("照片信息已更新，仅用于水印")

    def _metadata_editor_closed(self, editor):
        if editor in self._metadata_editors:
            self._metadata_editors.remove(editor)
        editor.deleteLater()

    def _template_context(self):
        """只复用已经读取的信息，打开组合窗口时不阻塞界面"""
        from core.metadata import merge_overrides, metadata_key
        path = self._current_path()
        selected = tuple(str(item) for item in self.state.checked_paths)
        result = {"metadata": None, "filename": path.stem if path else "",
                  "file_dir": path.parent.as_posix() if path else "",
                  "file_path": path.as_posix() if path else "",
                  "files": selected or ((str(path),) if path else ())}
        if path:
            try:
                info = path.stat()
                values = self._footer_metadata.get((metadata_key(path), info.st_mtime_ns, info.st_size))
            except OSError:
                values = None
            overrides = self.state.metadata_for(path)
            if values is not None:
                try:
                    result["metadata"] = merge_overrides(values, overrides)
                except ValueError:
                    result["metadata"] = None
        return result

    def _refresh_footer_examples(self, request=True):
        """异步刷新示例，不重载或改写正在组合的内容"""
        panels = [editor.panel for editor in self._editors if hasattr(editor, "panel")]
        if (self._active_wizard is not None
                and self._active_wizard.preview.photo_path == self._current_path()):
            panels.append(self._active_wizard.footer_panel)
        inspecting = self.inspector.metadata_visible and self._current_path() is not None
        if not panels and not inspecting:
            return
        context = self._template_context()
        if inspecting:
            self._show_photo_fields(context["metadata"] or {})
        for panel in panels:
            panel.set_metadata(**context)
        for editor in self._editors:
            if hasattr(editor, 'metadata_button'):
                editor.metadata_button.setEnabled(bool(self._current_path()) and not self._exporting)
        path = self._current_path()
        tasks = [task for task in self._tasks.values() if task.kind == "footer_metadata"]
        pending = any(task.paths[0] == path and not task.cancel.is_set() for task in tasks)
        # 先等当前水印任务填充共享的 EXIF 缓存
        waiting_for_preview = self._pending or self.timer.isActive() or (self._rendering and self._watermark_image is None)
        if request and not waiting_for_preview and path and context["metadata"] is None and not pending and not self._closing:
            if tasks:
                self._footer_metadata_pending = True
            else:
                self._footer_metadata_pending = False
                self._serial += 1
                self._connect_task(FooterMetadataTask(self._serial, path))

    def _track_template_editor(self, editor):
        """源码与组合编辑共用草稿、保存和关闭处理"""
        editor.source_preview.connect(lambda text, window=editor: self._preview_draft(window, text))
        editor.saved.connect(lambda name, window=editor: self._editor_saved(window, name))
        editor.finished.connect(lambda result, window=editor: self._editor_closed(window))
        if isinstance(editor, TemplateEditor):
            editor.visual_requested.connect(lambda source, window=editor: self._handoff_editor(window, source, visual=True))
        else:
            editor.advanced_requested.connect(lambda source, window=editor: self._handoff_editor(window, source, visual=False))
            editor.metadata_requested.connect(self._edit_metadata)
            editor.view_main_requested.connect(lambda window=editor: self._show_main_from_editor(window))
            editor.preview_invalidated.connect(self._invalidate_preview)
            editor.photo_view.zoom_changed.connect(
                lambda zoom, view=editor.photo_view: self._preview_zoom_changed(zoom, view))
            editor.photo_view.original_requested.connect(
                lambda view=editor.photo_view: self._request_original(view))
        self._editors.append(editor)
        self._show_template_editor(editor)
        self._refresh_footer_examples()
        return editor

    def _make_template_editor(self, name, source, visual=False, is_new=False, saved_source=None):
        if saved_source is None and not is_new:
            saved_source = read_template(name)
        if visual:
            from .footer_editor import FooterEditor
            editor = FooterEditor(self, name=name, source=source, saved_source=saved_source,
                                  **self._template_context())
        else:
            settings = replace(self._photo_settings(), input_files=tuple(str(path) for path in self.state.checked_paths),
                               metadata_overrides=self.state.metadata_overrides)
            editor = TemplateEditor(self, name=name, source=source, is_new=is_new, saved_source=saved_source,
                                    photo_path=self._current_path(), settings=deepcopy(settings))
        path = self._editable_photo()
        local = self.state.style_for(path) if path else {}
        # 从单张组合进入高级编辑时，草稿预览继续限定在这张照片
        editor.source_photo = path if local.get('template_source') and not is_new else None
        editor.original_photo_source = local.get('template_source', '')
        return self._track_template_editor(editor)

    def _open_editor(self, name, source, is_new=False):
        editor = next((item for item in self._editors if item.name == name), None)
        if editor is not None:
            if isinstance(editor, TemplateEditor):
                self._show_template_editor(editor)
                return editor
            try:
                return self._handoff_editor(editor, editor.source(), visual=False)
            except Exception as exc:
                self._record_errors("无法切换编辑器", [str(exc)])
                return None
        return self._make_template_editor(name, source, is_new=is_new)

    def _handoff_editor(self, previous, source, visual=False):
        """确认后携带当前草稿切换模式，同一模板仅保留一个编辑窗口"""
        if getattr(previous, "is_new", False) and visual:
            # 未命名或尚未落盘的模板继续由源码编辑器管理保存路径
            if not previous.save():
                return None
            source = previous.source()
        if previous.is_dirty():
            destination = tr("可视化组合" if visual else "高级源码编辑器")
            answer = QMessageBox.question(self, tr("切换编辑方式"),
                                          tr("将未保存的修改带到{editor}继续编辑？", editor=destination),
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return None
        try:
            baseline = getattr(previous, "_saved_source", None)
            editor = self._make_template_editor(previous.name, source, visual=visual, saved_source=baseline)
        except Exception as exc:
            self._record_errors("无法切换编辑器", [str(exc)])
            return None
        editor.preview_target = getattr(previous, "preview_target", previous.name)
        editor.source_photo = previous.source_photo
        editor.original_photo_source = previous.original_photo_source
        for target, owner in list(self._draft_owners.items()):
            if owner is previous:
                self._draft_owners[target] = editor
        previous._handoff = True
        previous.close_for_handoff()
        self._preview_draft(editor, source)
        return editor

    def _edit_footer(self):
        self.inspector.show_style_tab()

    def _new_template(self):
        name, accepted = QInputDialog.getText(self, tr('新建空白预设'), tr('请输入模板名称'))
        if not accepted or not name.strip():
            return
        rows = {key: {'processor_name': 'rich_text', 'text': ''}
                for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom')}
        source = json.dumps([{'processor_name': 'watermark', 'color': 'white', **rows}], indent=2)
        try:
            name = save_custom_template(name.strip(), source, WatermarkSettings())
        except (ValueError, OSError) as exc:
            self._record_errors('创建模板失败', [str(exc)])
            return
        self._template_saved(name)
        self.inspector.show_my_templates()
        self.inspector.select_slot('left_top')

    def _effective_template_source(self, settings):
        path = self._editable_photo()
        local_source = self.state.style_for(path).get('template_source') if path else ''
        editor = next((item for item in self._editors if item.name == settings.template_name
                       and item.isVisible() and getattr(item, 'source_photo', None) in (None, path)
                       and (not local_source or getattr(item, 'source_photo', None) == path)), None)
        return editor.source() if editor is not None else settings.template_source or read_template(settings.template_name)

    def _copy_template(self):
        settings = self._photo_settings()
        name, accepted = QInputDialog.getText(self, tr('另存我的模板'), tr('请输入模板名称'),
                                               text=settings.template_name + tr('_副本'))
        if not accepted or not name.strip():
            return
        try:
            source = self._effective_template_source(settings)
            name = save_custom_template(name.strip(), source, settings)
            self._template_saved(name)
            self.inspector.show_my_templates()
            self._set_status('模板已保存到我的模板：{name}', name=name)
        except Exception as exc:
            self._record_errors('无法保存模板', [str(exc)])
            QMessageBox.warning(self, tr('无法保存模板'), localize_error(exc))

    def _export_style_pack(self, template_name=None, format_hint=None):
        try:
            current = self._photo_settings()
            name = template_name or current.template_name
            if name == current.template_name:
                settings = current
                source = self._effective_template_source(settings)
            else:
                settings = replace(WatermarkSettings(template_name=name), **read_preset_style(name))
                source = self._drafts.get(name) or read_template(name)
                settings = replace(settings, metadata_overrides=deepcopy(current.metadata_overrides))
            photo = self._editable_photo() or example_photo_path()
            selected_paths = tuple(str(item) for item in self.state.checked_paths) if self._editable_photo() else ()
            settings = replace(settings, template_name=name, template_source=source,
                               input_files=selected_paths or (str(photo),))
            if self._editable_photo() is None:
                settings = replace(settings, metadata_overrides={}, protected_sources=())
        except Exception as exc:
            self._record_errors('无法导出模板', [str(exc)])
            QMessageBox.warning(self, tr('无法导出模板'), localize_error(exc))
            return
        filters = {'png': tr('PNG 模板卡片 (*.png)'), 'json': tr('JSON 纯配置 (*.json)'),
                   'zip': tr('ZIP 样式包 (*.zip)'), 'efstyle': tr('样式包 (*.efstyle)')}
        initial_format = format_hint if format_hint in filters else 'png'
        selected, selected_filter = QFileDialog.getSaveFileName(
            self, tr('导出模板'), str(Path(last_directory('preset_export')) / f'{name}.{initial_format}'),
            filters[initial_format] if format_hint else ';;'.join(filters.values()))
        if not selected:
            return
        path = Path(selected)
        remember_directory('preset_export', path.parent)
        filter_choice = next((key for key, label in filters.items() if selected_filter == label), None)
        chosen = filter_choice or initial_format
        suffix = path.suffix.casefold().lstrip('.')
        if format_hint:
            chosen = initial_format
            if suffix != chosen:
                path = path.with_name(path.name + '.' + chosen)
        elif filter_choice:
            if suffix != chosen:
                path = path.with_suffix('.' + chosen) if suffix in filters else path.with_name(path.name + '.' + chosen)
        elif suffix in filters:
            chosen = suffix
        else:
            path = path.with_name(path.name + '.' + chosen)
        try:
            # 所有已导入照片和内置示例始终受覆盖保护
            protected = [*self.files.all_paths(), photo, example_photo_path()]
            target = path.resolve()
            for item in protected:
                existing = Path(item).resolve()
                if target == existing or (target.exists() and existing.exists() and target.samefile(existing)):
                    raise ValueError('不能覆盖已导入的原照片，请选择独立的输出目录')
            overwrite = path == Path(selected) and path.is_file()
            if chosen == 'png':
                self._serial += 1
                task = StyleCardTask(self._serial, path, photo, name, source, settings, overwrite)
                task.signals.result.connect(self._style_card_result)
                task.signals.error.connect(self._style_card_error)
                task.signals.finished.connect(self._task_finished)
                self._tasks[(task.kind, task.token)] = task
                self._priority.hold(task)
                self.pool.start(task)
                self._preset_feedback('正在导出模板卡片…')
            elif chosen == 'json':
                export_style_json(path, name, source, settings, overwrite=overwrite)
                self._preset_feedback('模板已导出：{path}', path=str(path))
            else:
                export_style_pack(path, name, source, settings, overwrite=overwrite)
                self._preset_feedback('模板已导出：{path}', path=str(path))
        except Exception as exc:
            self._record_errors('无法导出模板', [str(exc)])
            QMessageBox.warning(self, tr('无法导出模板'), localize_error(exc))

    @Slot(str, int, object)
    def _style_card_result(self, kind, token, path):
        if not self._closing:
            self._preset_feedback('模板已导出：{path}', path=path)

    @Slot(str, int, str)
    def _style_card_error(self, kind, token, message):
        if not self._closing:
            self._record_errors('无法导出模板', [message])
            QMessageBox.warning(self, tr('无法导出模板'), localize_error(message))

    def _import_style_pack(self):
        selected, _ = QFileDialog.getOpenFileName(self, tr('导入模板'), last_directory('preset_import'),
                                                   tr('模板文件 (*.png *.json *.zip *.efstyle)'))
        if not selected:
            return
        try:
            name = import_style_pack(selected)
            remember_directory('preset_import', Path(selected).parent)
            self._template_saved(name)
            self.inspector.show_my_templates()
            self._preset_feedback('模板已导入：{name}', name=name)
        except Exception as exc:
            self._record_errors('无法导入模板', [str(exc)])
            QMessageBox.warning(self, tr('无法导入模板'), localize_error(exc))

    def _edit_template(self):
        from .source_panel import SourceDialog
        self._show_preset_sample()
        if not hasattr(self, '_source_dialog'):
            self._source_dialog = SourceDialog(self)
            self.source_panel = self._source_dialog.panel
            self.source_panel.changed.connect(lambda value: self._edit_style('template_source', value))
            self.source_panel.save_requested.connect(self._save_inline_source)
        settings = self._photo_settings()
        try:
            source = self._effective_template_source(settings)
        except (OSError, ValueError) as exc:
            self._record_errors('读取模板失败', [str(exc)])
            return
        self.source_panel.sync((self._editable_photo(), settings.template_name), source)
        self._source_dialog.set_template_name(settings.template_name)
        self._source_dialog.setWindowState(self._source_dialog.windowState() & ~Qt.WindowState.WindowMinimized)
        self._source_dialog.show()
        self._source_dialog.raise_()
        self._source_dialog.activateWindow()
        self.source_panel.edit.setFocus()

    def _save_inline_source(self, source):
        name = self._photo_settings().template_name
        if self._locked or self._exporting or self._current_kind == 'output':
            return
        try:
            write_template(name, source)
        except (OSError, ValueError) as exc:
            self._record_errors('无法保存模板', [str(exc)])
            return
        self._template_saved(name)
        self._set_status('模板已保存：{name}', name=name)

    def _preview_draft(self, editor, source):
        """未保存的源码只作用于当前会话预览和处理"""
        name = editor.name
        target = name if any(p.name == name for p in self.presets) else self._photo_settings().template_name
        editor.preview_target = target
        if editor.source_photo is not None:
            self.state.update_style((editor.source_photo,), {'template_name': target, 'template_source': source})
            return
        self._drafts[target] = source
        self._draft_owners[target] = editor
        if hasattr(editor, "set_preview") and not editor.isVisible():
            return
        if target == self._photo_settings().template_name:
            self._ensure_watermark_mode()
            self._sync_template_context()
            self._show_effective_style()
            self._schedule_preview()
            # 编辑器已完成去抖，主窗直接排入后台预览
            self.timer.start(0)
            self._set_status("模板草稿已应用，尚未保存到模板文件")

    def _template_saved(self, name, owner=None):
        getattr(self, '_frame_baselines', {}).pop(name, None)
        if self._draft_owners.get(name) in (None, owner):
            self._drafts.pop(name, None)
            self._draft_owners.pop(name, None)
        self.presets = list_presets()
        self.inspector.set_presets(self.presets, name)
        self._select_template(name)
        self._style_preview_changed()
        self._update_actions()

    def _editor_saved(self, editor, name):
        for target, owner in list(self._draft_owners.items()):
            if owner is editor and target != name:
                self._drafts.pop(target, None)
                self._draft_owners.pop(target, None)
        editor.preview_target = name
        if editor.source_photo is not None:
            self.state.update_style((editor.source_photo,), {'template_name': name, 'template_source': ''})
            editor.original_photo_source = ''
        self._template_saved(name, owner=editor)

    def _editor_closed(self, editor):
        if editor in self._editors:
            self._editors.remove(editor)
        if not getattr(editor, "_handoff", False):
            if editor.source_photo is not None and editor.is_dirty():
                self.state.update_style((editor.source_photo,), {'template_source': editor.original_photo_source})
            for target, owner in list(self._draft_owners.items()):
                if owner is editor:
                    self._drafts.pop(target, None)
                    self._draft_owners.pop(target, None)
                    if target == self._photo_settings().template_name:
                        self._style_preview_changed()
        editor.deleteLater()
