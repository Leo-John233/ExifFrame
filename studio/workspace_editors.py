"""高级模板、照片信息副本和编辑会话"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable, Qt, Slot
from PySide6.QtWidgets import QDialog, QMessageBox
from core.desktop_service import list_presets, read_template, write_template
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
        """默认编辑当前照片，批量操作通过独立菜单明确选择"""
        current = self._current_path()
        if current:
            self._open_metadata_editor([current], current)
        else:
            self._set_status("尚未选择可编辑的照片")

    def _advanced_checked_metadata(self):
        self._read_checked_paths()
        paths = self.state.checked_paths
        if paths:
            current = self._editable_photo()
            self._open_metadata_editor(paths, current if current in paths else paths[0])

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
        editor = MetadataEditor(self, paths=paths, current=current, overrides=self.state.metadata_overrides)
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
        from .footer_editor import FooterEditor
        name = self._photo_settings().template_name
        previous = next((item for item in self._editors if item.name == name), None)
        if previous is not None:
            if isinstance(previous, FooterEditor):
                self._show_template_editor(previous)
            elif previous.check_format():
                self._handoff_editor(previous, previous.source(), visual=True)
            return
        try:
            self._make_template_editor(name, self._photo_settings().template_source or read_template(name), visual=True)
        except Exception as exc:
            self._record_errors("无法打开组合编辑器", [str(exc)])

    def _new_template(self):
        from .template_wizard import TemplateWizard
        active = next((editor for editor in self._editors if editor.name == self._photo_settings().template_name), None)
        try:
            current_source = active.source() if active else self._photo_settings().template_source
        except Exception as exc:
            self._record_errors("无法读取当前组合", [str(exc)])
            return
        settings = replace(self._photo_settings(), input_files=tuple(str(path) for path in self.state.checked_paths),
                               metadata_overrides=self.state.metadata_overrides)
        wizard = TemplateWizard(self, current_template=self._photo_settings().template_name, current_source=current_source,
                                settings=deepcopy(settings))
        self._active_wizard = wizard
        self._refresh_footer_examples()
        if wizard.exec() == QDialog.DialogCode.Accepted:
            try:
                write_template(wizard.name, wizard.source, create=True)
                self._template_saved(wizard.name)
                self._set_status("模板已创建：{name}", name=wizard.name)
            except Exception as exc:
                self._record_errors("创建模板失败", [str(exc)])
                QMessageBox.warning(self, tr("创建模板失败"), localize_error(exc))
        self._active_wizard = None
        wizard.deleteLater()

    def _copy_template(self):
        name = self._photo_settings().template_name
        try:
            active = next((editor for editor in self._editors if editor.name == name), None)
            source = active.source() if active else self._photo_settings().template_source or read_template(name)
            self._open_editor(name + tr("_副本"), source, True)
        except Exception as exc:
            self._record_errors("读取模板失败", [str(exc)])

    def _edit_template(self):
        name = self._photo_settings().template_name
        for editor in self._editors:
            if editor.name == name:
                if isinstance(editor, TemplateEditor):
                    self._show_template_editor(editor)
                else:
                    try:
                        self._handoff_editor(editor, editor.source(), visual=False)
                    except Exception as exc:
                        self._record_errors("无法切换编辑器", [str(exc)])
                return
        try:
            self._open_editor(name, self._photo_settings().template_source or read_template(name))
        except Exception as exc:
            self._record_errors("读取模板失败", [str(exc)])

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
