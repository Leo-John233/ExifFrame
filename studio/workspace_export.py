"""导出队列、操作状态与结果反馈"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFileDialog, QPlainTextEdit, QVBoxLayout
from .about import AboutDialog
from .i18n import localize_error, tr


class WorkspaceExport:
    """导出队列、操作状态与结果反馈"""

    def _init_export(self):
        self._exporting = False
        self._errors, self._error_dialogs = [], []
        self._last_output = self._completion_refresh = self._export_finish_message = self._queued_export = None
        self._counts = {'completed': 0, 'errors': 0, 'skipped': 0}
        self._status_source, self._status_values = '就绪', {}

    def _set_status(self, source, **values):
        """保留状态原文以便处理中切换语言"""
        self._status_source, self._status_values = source, values
        rendered = dict(values)
        for key in ("title", "field"):
            if key in rendered:
                rendered[key] = tr(rendered[key])
        if "error" in rendered:
            rendered["error"] = localize_error(rendered["error"])
        self.statusBar().showMessage(tr(source, **rendered))

    def _set_preview_status(self, source, **values):
        self._preview_source, self._preview_values = source, values
        rendered = dict(values)
        if "mode" in rendered:
            rendered["mode"] = tr(rendered["mode"])
        self.preview_status.setText(tr(source, **rendered))
        if source == "正在生成预览…":
            self.photo_view.set_empty_message(source)

    def _error_details(self):
        return "\n".join(tr(error[0], **error[1]) if isinstance(error, tuple) else localize_error(error)
                         for error in self._errors) if self._errors else tr("暂无错误")

    @Slot(int, int, str)
    def _task_progress(self, current, total, name):
        if self._closing:
            return
        if total:
            self.progress.setValue(current)
            self._set_status("正在导出 {current}/{total} · {name}", current=current, total=total, name=name)
        elif not self._exporting:
            self._set_status("读取目录 · {name}", name=name)

    @Slot(object)
    def _summary_changed(self, summary):
        self._counts = dict(summary)
        self.summary_label.setText(tr("成功 {completed} / 失败 {errors} / 跳过 {skipped}", **summary))

    def _record_errors(self, title, errors):
        self._errors = errors
        self.error_button.setEnabled(True)
        self._set_status("{title}：{error}", title=title, error=errors[0])

    def _show_about(self):
        dialog = AboutDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()

    def _show_error_details(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("处理详情"))
        dialog.resize(680, 360)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(self._error_details())
        text.setReadOnly(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._error_dialogs.append((dialog, text))
        dialog.finished.connect(lambda result: self._error_dialogs.remove((dialog, text)))
        dialog.open()

    def _update_actions(self):
        if not hasattr(self, "files"):
            return
        busy = self._exporting or self._closing
        importing = any(kind == "import" for kind, _ in self._tasks)
        selected = len(self.state.checked_paths)
        self.inspector.set_counts(selected, len(self.files.items["import"]))
        current = bool(self._current_data and self._current_kind == 'import')
        count = selected or int(current)
        self.export_action.setEnabled(bool(count and self.presets and not importing and not busy))
        self.export_action.setText(tr("正在导出…") if self._exporting else
                                   tr('导出已选 ({count})', count=selected) if selected else
                                   tr('导出当前照片') if current else tr("导出照片"))
        if importing:
            self.export_action.setToolTip(tr("正在读取照片，完成后可以导出"))
        elif selected:
            self.export_action.setToolTip(tr("导出这张勾选照片，原文件保持不变（Ctrl+R）") if count == 1 else
                                         tr("导出 {count} 张勾选照片，原文件保持不变（Ctrl+R）", count=count))
        elif current:
            self.export_action.setToolTip(tr('导出当前照片，原文件保持不变（Ctrl+R）'))
        else:
            self.export_action.setToolTip(tr('选择一张输入照片或勾选要导出的照片' if self.files.items["import"]
                                             else "先添加照片，再勾选需要导出的照片"))
        self.cancel_action.setEnabled(self._exporting and not self._closing)
        self.cancel_action.setVisible(self._exporting)
        for action in (self.add_action, self.directory_action, self.refresh_action, self.new_template_action,
                       self.copy_template_action, self.edit_template_action, self.footer_action, self.lock_action):
            action.setEnabled(not busy)
        self.metadata_action.setEnabled(current and not busy)
        self.metadata_batch_action.setEnabled(bool(selected) and not busy)
        self.save_action.setEnabled(self._dirty and not busy)
        self.reset_action.setEnabled(self._dirty and not busy)
        self.inspector.set_dirty(self._dirty)
        self.original_toggle.setEnabled(bool(self._current_data) and self._current_kind == "import")
        self.original_action.setEnabled(self.original_toggle.isEnabled())
        if not self._current_data:
            self._update_empty_hint()

    def _update_empty_hint(self):
        """明确区分没有照片、尚未选中和等待导出结果"""
        output = self.files.tabs.currentIndex() == 1
        if output and not self.files.items["output"]:
            text = "此目录暂无导出照片\n\n导出后可在“输出”标签查看成品"
        elif self.files.items["output" if output else "import"]:
            text = "从左侧列表选择一张照片\n\n勾选的输入照片会一并导出"
        else:
            text = "添加照片后开始编辑水印\n\n拖入 JPG、PNG、HEIC 文件或文件夹，或点击上方“添加照片”"
        self.photo_view.set_empty_message(text)

    def _choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, tr("选择输出目录"), self.settings.output_dir,
                                                  QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.output_input.setText(folder)
            self._directories_changed()
        return folder

    def _export(self):
        """固定本轮勾选和设置快照后交由后台逐张处理"""
        self._read_checked_paths()
        paths = self.state.checked_paths
        if not paths and self._current_kind == 'import' and self._current_data:
            paths = [self._current_data[0]]
        if self._exporting or self._closing or not paths or any(kind == "import" for kind, _ in self._tasks):
            return
        if not self.settings.output_dir and not self._choose_output():
            return
        self._last_output = Path(self.settings.output_dir)
        self._set_exporting(True)
        self._errors = []
        self.error_button.setEnabled(False)
        self._summary_changed({"completed": 0, "errors": 0, "skipped": 0})
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self._set_status("正在导出 {current}/{total} · {name}", current=0, total=len(paths), name="")
        base = replace(self.settings, input_files=tuple(str(path) for path in paths),
                       protected_sources=tuple(str(path) for path in self.files.all_paths()))
        snapshot = self.state.export_snapshot(paths, base, template_sources=self._drafts)
        self._queued_export = (paths, base, self._last_output, snapshot)
        self.timer.stop()
        if self._comparison_task is not None:
            self._comparison_task.cancel.set()
        if self._rendering:
            self._render_revision_id += 1
            self._pending = True
            for task in self._tasks.values():
                if task.kind in ("preview", "original"):
                    task.cancel.set()
        for preview in self._template_previews():
            preview.suspend()
        self._start_queued_export()

    def _start_queued_export(self):
        if self._queued_export is None or self._closing:
            return
        from .preview import _task_owner
        if self._rendering or _task_owner().jobs:
            self._set_status("等待预览完成后开始导出…")
            QTimer.singleShot(100, self, self._start_queued_export)
            return
        paths, settings, output, snapshot = self._queued_export
        self._queued_export = None
        self._set_status("正在导出 {current}/{total} · {name}", current=0, total=len(paths), name="")
        self._start_task("export", paths=paths, settings=settings, output=output, export_snapshot=snapshot)

    def _set_exporting(self, active):
        self._exporting = active
        self.inspector.setEnabled(not active)
        self.files.setEnabled(not active)
        for editor in self._editors:
            editor.setEnabled(not active)
        for editor in self._metadata_editors:
            editor.setEnabled(not active)
        self.progress.setVisible(active)
        if not active and not self._closing:
            for preview in self._template_previews():
                preview.resume()
            if self._pending:
                self.timer.start(80)
        self._update_actions()

    def _cancel_export(self):
        if self._queued_export is not None:
            self._queued_export = None
            self._set_exporting(False)
            self._set_status("导出已取消，已保存 {count} 张照片", count=0)
            return
        for task in self._tasks.values():
            if task.kind == "export":
                task.cancel.set()
        self.cancel_action.setEnabled(False)
        self._set_status("正在处理的照片完成后取消导出")

    def _open_output(self):
        directory = self._last_output or (Path(self.settings.output_dir) if self.settings.output_dir else None)
        if directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))
