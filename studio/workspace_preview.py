"""主画布预览、原图对照与异步任务调度"""

from __future__ import annotations

import os
import re
import time
from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QThreadPool, QTimer, Qt, Slot
from core.desktop_service import read_template
from .canvas import image_size, is_full_image, set_image_size
from .preview import _task_owner
from .state import STYLE_FIELDS
from .i18n import localize_error
from .template_editor import TemplateEditor
from .workers import ImageTask, qt_rendered_rows


class WorkspacePreview:
    """主画布预览、原图对照与异步任务调度"""

    def _init_preview(self):
        self._tasks = {}
        self._serial = self._render_revision_id = 0
        self._rendering = self._pending = False
        self._hq_pending = self._hq_ready = self._context_pending = False
        self._comparison_task = self._comparison_image = None
        self._comparison_full = self._comparison_upgrade = False
        self._watermark_image = self._watermark_signature = self._render_signature = None
        self._rendered_rows_target = None
        self._rendered_rows_context = self._rendered_rows_job_context = None
        self._interaction_active = self._interaction_applying = self._interaction_dirty = False
        self._interaction_key = self._interaction_style_key = ''
        self._interaction_epoch = 0
        self._draft_accepting = False
        self._last_draft_displayed = -1
        self._last_draft_started = 0.0
        self._draft_signature = None
        self._preview_source, self._preview_values, self._preview_error = '未选择照片', {}, ''
        self._priority = _task_owner()
        self._priority.background_ready.connect(self._start_visible_thumbnails)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._render_preview)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._live_timer.timeout.connect(self._render_live_preview)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._settle_timer.timeout.connect(self._finish_live_preview)
        self._idle_check = QTimer(self)
        self._idle_check.setSingleShot(True)
        self._idle_check.setInterval(80)
        self._idle_check.timeout.connect(self._release_preview_if_idle)

    def _visible_footer_editors(self):
        return [editor for editor in self._editors if hasattr(editor, "set_preview")
                and editor.name == self._photo_settings().template_name and editor.isVisible() and not editor.isMinimized()]

    def _preview_signature(self, *, reuse=None):
        from core.desktop_service import _preview_file_signature

        settings = self._photo_settings()
        path = self._current_path()
        selected = tuple(str(item) for item in self.state.checked_paths)
        try:
            info = path.stat() if path else None
            version = (info.st_mtime_ns, info.st_size) if info else None
        except OSError:
            version = None
        try:
            if settings.template_source:
                source = settings.template_source
            elif reuse is not None and reuse[1][0] == settings.template_name:
                source = reuse[-2]
            else:
                source = read_template(settings.template_name)
        except (OSError, ValueError):
            source = ''
        if (reuse is not None and path == reuse[0] and selected == reuse[3]
                and bool(re.search(r'\bfiles\b', source)) == bool(re.search(r'\bfiles\b', reuse[-2]))):
            dependencies = reuse[-1]
        else:
            dependencies = _preview_file_signature(source, selected or ((str(path),) if path else ()))
        style = tuple(getattr(settings, name) for name in STYLE_FIELDS)
        return path, style, settings.metadata_overrides, selected, version, source, dependencies

    def _current_footer_image(self):
        """只复用当前照片与当前设置对应的水印结果，原图另行对照"""
        if self._watermark_image is not None and self._watermark_signature == self._preview_signature():
            return self._watermark_image
        return None

    def _ensure_watermark_mode(self):
        changed = self.original_toggle.isChecked()
        self.original_toggle.blockSignals(True)
        self.original_toggle.setChecked(False)
        self.original_toggle.blockSignals(False)
        self.original_action.setChecked(False)
        return changed

    def _send_footer_preview(self, image):
        for editor in self._visible_footer_editors():
            editor.set_preview(image)

    def _original_toggled(self, checked):
        self.original_action.setChecked(checked)
        self._schedule_preview()

    def _view_changed(self, checked):
        self.original_toggle.setChecked(checked)

    def _schedule_preview(self):
        # 先递增代次以阻止去抖等待期间旧图片覆盖当前选择
        self._invalidate_preview()
        self._pending = True
        self.timer.start(80)

    def _begin_live_interaction(self, key):
        if self._closing or self._exporting:
            return
        self._interaction_key = key
        self._interaction_active = True

    def _end_live_interaction(self, key):
        if not self._interaction_active or key != self._interaction_key:
            return
        self._interaction_active = False
        if self._interaction_dirty:
            self._settle_timer.start(120)

    def _abort_live_interaction(self):
        self._interaction_epoch += 1
        self._interaction_active = self._interaction_dirty = self._draft_accepting = False
        self._live_timer.stop()
        self._settle_timer.stop()

    def _schedule_live_preview(self):
        if self._closing or self._exporting:
            return
        if not self._draft_accepting:
            self._settle_timer.stop()
            self._interaction_epoch += 1
            self._invalidate_preview(keep_interaction=True)
            self._draft_accepting = True
            self._last_draft_displayed = -1
            self._draft_signature = None
        else:
            # 同一次交互只更新最新待处理值，不取消正在渲染的草图
            self._settle_timer.stop()
            self._render_revision_id += 1
            self._hq_pending = self._hq_ready = False
            self._priority.hold(self)
        self._interaction_dirty = self._pending = True
        if self._interaction_key in ('title', 'subtitle'):
            # 文字停顿时也升级清晰预览，不必等待输入框失焦
            self._settle_timer.start(120)
        self._queue_live_preview()

    def _queue_live_preview(self):
        if (not (self._interaction_active or self._settle_timer.isActive()) or not self._pending
                or self._rendering or self._live_timer.isActive()):
            return
        elapsed = (time.monotonic() - self._last_draft_started) * 1000
        self._live_timer.start(max(0, round(33 - elapsed)))

    def _render_live_preview(self):
        if self._interaction_dirty and (self._interaction_active or self._settle_timer.isActive()):
            self._render_preview(interactive=True)

    def _finish_live_preview(self):
        if self._closing or self._exporting or not self._interaction_dirty:
            return
        self._live_timer.stop()
        self._draft_accepting = self._interaction_dirty = False
        self._show_effective_style()
        self._invalidate_preview(keep_interaction=True)
        self._pending = True
        views = [self.photo_view, *(editor.photo_view for editor in self._visible_footer_editors())]
        self._hq_pending = any(view.zoom > 1.0 for view in views)
        self.timer.start(0)

    def _invalidate_preview(self, *, keep_interaction=False):
        # 代次递增与取消标记同步，后台据此丢弃旧任务
        if not keep_interaction:
            self._abort_live_interaction()
        self._priority.hold(self)
        self._idle_check.start()
        self._render_revision_id += 1
        self._hq_pending = self._hq_ready = False
        for task in self._tasks.values():
            if task.kind in ("preview", "original"):
                task.cancel.set()
        self._pending = False
        self.timer.stop()

    def _release_preview_if_idle(self):
        if self._interaction_dirty or self._settle_timer.isActive():
            return
        if not self._pending and not self.timer.isActive():
            if self._context_pending:
                self._context_pending = False
                self._sync_template_context(immediate=True)
            self._priority.release(self)

    def _preview_zoom_changed(self, zoom, view=None):
        view = view or self.photo_view
        if view.comparing_original:
            self._request_original(view)
        if self._interaction_dirty or self._settle_timer.isActive():
            return
        if zoom <= 1.0:
            active_views = [self.photo_view, *(editor.photo_view for editor in self._visible_footer_editors())]
            if self._hq_pending and not any(item.zoom > 1.0 for item in active_views):
                self._hq_pending = self._pending = False
                self.timer.stop()
                self._release_preview_if_idle()
            return
        active = next((task for (kind, token), task in self._tasks.items()
                       if kind in ('preview', 'original') and token == self._render_revision_id), None)
        if (self._closing or self._exporting or not self._current_path()
                or self._hq_ready or self._hq_pending or self._pending
                or (active is not None and active.full_resolution)):
            return
        self._hq_pending = self._pending = True
        self._priority.hold(self)
        self.timer.start(80)

    def _request_original(self, view=None, *, force_full=False):
        if self._closing or self._exporting or self._current_kind != 'import' or self.original_toggle.isChecked():
            return
        path = self._current_path()
        if path is None:
            return
        view = view or self.photo_view
        full_resolution = force_full or view.zoom > 1.0
        if self._comparison_image is not None:
            view.set_original_image(self._comparison_image)
            if not full_resolution or self._comparison_full:
                return
        if self._comparison_task is not None:
            self._comparison_upgrade |= full_resolution and not self._comparison_task.full_resolution
            return
        self._comparison_task = self._start_task('comparison', paths=[path], full_resolution=full_resolution)

    def _queue_selection_changed(self):
        """导入期间不反复推迟首张预览，完整批次在扫描结束后刷新"""
        if not any(kind == "import" for kind, _ in self._tasks):
            self._sync_template_context()
            self._refresh_footer_examples(request=False)
            self._schedule_preview()

    def _sync_template_context(self, *, immediate=False):
        """让已打开的编辑器使用当前勾选和照片信息快照"""
        selected = tuple(str(path) for path in self.state.checked_paths)
        for preview in self._template_previews():
            preview.update_context(selected, self.state.metadata_overrides,
                                   self._photo_settings(preview.photo_path), immediate=immediate)
        if self._active_wizard is not None:
            self._active_wizard.refresh_preview_context()

    def _template_previews(self):
        previews = [editor.preview for editor in self._editors if isinstance(editor, TemplateEditor)]
        if self._active_wizard is not None:
            previews.append(self._active_wizard.preview)
            if self._active_wizard._advanced_preview is not None:
                previews.append(self._active_wizard._advanced_preview)
        return previews

    def _render_preview(self, interactive=False):
        if self._closing or self._exporting:
            return
        if self._context_pending and not interactive:
            self._context_pending = False
            self._sync_template_context(immediate=True)
            if self._visible_footer_editors():
                self._ensure_watermark_mode()
        path = self._current_path()
        if not path:
            self._pending = False
            self._release_preview_if_idle()
            self._send_footer_preview(None)
            return
        if self._rendering or not self._pending:
            return
        self._pending, self._rendering = False, True
        full_resolution = self._hq_pending and not interactive
        self._hq_pending = False
        self._set_preview_status("正在生成预览…")
        self._preview_error = ""
        self.preview_status.setToolTip("")
        # 输出树始终读取已有成品以免重复添加水印
        kind = "original" if self._current_kind == "output" or self.original_toggle.isChecked() else "preview"
        # 与实际导出共用勾选文件快照，支持模板中的跨照片处理
        selected = tuple(str(item) for item in self.state.checked_paths)
        self._render_signature = deepcopy(self._preview_signature(reuse=self._draft_signature if interactive else None))
        if interactive:
            self._draft_signature = self._render_signature
        if kind == 'preview':
            self._rendered_rows_job_context = self._footer_text_context(self._photo_settings(), self._render_signature[-2])
        self._start_task(kind, token=self._render_revision_id, paths=[path],
                         settings=replace(self._photo_settings(), input_files=selected),
                         full_resolution=full_resolution, interactive=interactive)
        if interactive:
            self._last_draft_started = time.monotonic()
        else:
            self._priority.release(self)

    def _start_task(self, kind, token=None, **kwargs):
        # 深拷贝会话元数据以免编辑窗口修改正在处理的批次
        if kwargs.get("settings") is not None:
            kwargs["settings"] = deepcopy(kwargs["settings"])
        self._serial += 1
        task = ImageTask(kind, self._serial if token is None else token, **kwargs)
        if kind in ('preview', 'original'):
            task.preview_signature = self._render_signature
            task.rows_context = self._rendered_rows_job_context
            task.interaction_epoch = self._interaction_epoch
        self._connect_task(task)
        return task

    def _connect_task(self, task):
        """后台任务共用信号连接和安全关闭登记"""
        task.signals.result.connect(self._task_result)
        task.signals.error.connect(self._task_error)
        task.signals.finished.connect(self._task_finished)
        task.signals.item.connect(self._import_item)
        task.signals.batch.connect(self._import_batch)
        task.signals.dimensions.connect(self._task_dimensions)
        task.signals.progress.connect(self._task_progress)
        task.signals.summary.connect(self._summary_changed)
        self._tasks[(task.kind, task.token)] = task
        if task.kind in ('import', 'output'):
            self.scan_pool.start(task)
        elif task.kind == 'thumbnail':
            self.thumbnail_pool.start(task)
        else:
            self._priority.hold(task)
            priority = 2 if task.kind in ('preview', 'original', 'comparison') else 0
            self.pool.start(task, priority)

    @Slot(str, int, object)
    def _task_result(self, kind, token, result):
        if self._closing:
            return
        if kind == 'comparison':
            task = self._tasks.get((kind, token))
            if task is not None and task is self._comparison_task and task.paths[0] == self._current_path():
                self._comparison_image = result
                self._comparison_full = task.full_resolution or is_full_image(result)
                self.photo_view.set_original_image(result)
                for editor in self._visible_footer_editors():
                    editor.photo_view.set_original_image(result)
            return
        task = self._tasks.get((kind, token))
        if kind in ('preview', 'original') and task is not None and task.interactive:
            if (not self._draft_accepting or task.interaction_epoch != self._interaction_epoch
                    or token <= self._last_draft_displayed):
                return
            signature = self._preview_signature(reuse=task.preview_signature)
            old = task.preview_signature
            if (signature[0] != old[0] or signature[2:5] != old[2:5] or signature[6] != old[6]
                    or task.settings.template_name != self._photo_settings().template_name):
                self._schedule_preview()
                return
            self._last_draft_displayed = token
            self._hq_ready = False
            if (kind == 'preview' and self._watermark_image is not None and self._watermark_signature
                    and self._watermark_signature[0] == old[0]
                    and self._watermark_signature[1][0] == old[1][0]):
                previous = image_size(self._watermark_image)
                current = image_size(result)
                # 低清节点取整可能相差几像素，避免画布在两种画质间抖动
                if all(abs(a - b) <= 5 for a, b in zip(previous, current)):
                    set_image_size(result, previous)
            self.photo_view.set_image(result)
            if kind == 'preview':
                self._watermark_image = result
                self._watermark_signature = old
                if token == self._render_revision_id:
                    self._rendered_rows_context = task.rows_context
                    self.inspector.inline_footer.set_rendered_rows(qt_rendered_rows(result))
                self._send_footer_preview(result)
            return
        if kind in ("preview", "original") and token == self._render_revision_id:
            if self._render_signature != self._preview_signature():
                self._schedule_preview()
                return
            self._hq_ready = bool(task and task.full_resolution) or is_full_image(result)
            self.photo_view.set_image(result)
            if kind == "preview":
                self._watermark_image = result
                self._watermark_signature = self._render_signature
                self._rendered_rows_context = self._rendered_rows_job_context
                self.inspector.inline_footer.set_rendered_rows(qt_rendered_rows(result))
                self._send_footer_preview(self._watermark_image)
            _, width, height = self._current_data
            mode = "输出文件" if self._current_kind == "output" else "原图" if kind == "original" else "水印预览"
            if width and height:
                self._set_preview_status("{mode} · {width} × {height}", mode=mode, width=width, height=height)
            else:
                self._set_preview_status(mode)
            self._preview_zoom_changed(self.photo_view.zoom)
        elif kind in ("import", "output"):
            if kind == "output" and token == self._completion_refresh and self._export_finish_message:
                source, values = self._export_finish_message
                self._set_status(source, **values)
            else:
                self._set_status("目录读取完成")
            if result:
                self._record_errors("部分照片无法读取", result)
        elif kind == "export":
            self._summary_changed({key: len(result[key]) for key in ("completed", "errors", "skipped")})
            self._errors = result["errors"] + [("已跳过同名文件：{path}", {"path": path}) for path in result["skipped"]]
            self.error_button.setEnabled(bool(self._errors))
            count = len(result["completed"])
            message = ("导出已取消，已保存 1 张照片" if result["cancelled"] else "导出完成，已保存 1 张照片") if count == 1 else (
                "导出已取消，已保存 {count} 张照片" if result["cancelled"] else "导出完成，已保存 {count} 张照片")
            self._export_finish_message = (message, {"count": count} if count != 1 else {})
            self._set_status(message, **self._export_finish_message[1])
            if self._last_output and self._last_output.is_dir():
                # 自动刷新成品列表后继续显示导出结果
                self._completion_refresh = self._scan_directory("output", self._last_output).token
        elif kind == "footer_metadata":
            path, modified, size, metadata = result
            from core.metadata import metadata_key
            self._footer_metadata[(metadata_key(path), modified, size)] = metadata
            while len(self._footer_metadata) > 32:
                self._footer_metadata.pop(next(iter(self._footer_metadata)))
            self._refresh_footer_examples(request=False)

    @Slot(str, int, str)
    def _task_error(self, kind, token, message):
        if self._closing:
            return
        if kind == 'thumbnail':
            return
        if kind == 'comparison':
            if self._comparison_task is not None and self._tasks.get((kind, token)) is self._comparison_task:
                self._set_preview_status('原图读取失败，保留水印预览')
                self._record_errors('预览失败', [message])
            return
        if kind in ("preview", "original"):
            if token == self._render_revision_id:
                self._set_preview_status("预览失败，详情见状态栏")
                self._preview_error = message
                self.preview_status.setToolTip(localize_error(message))
                for editor in self._visible_footer_editors():
                    editor.set_preview_error(ValueError(message))
                self._record_errors("预览失败", [message])
        else:
            self._record_errors("导出失败" if kind == "export" else "处理失败", [message])

    @Slot(str, int)
    def _task_finished(self, kind, token):
        task = self._tasks.pop((kind, token), None)
        if task is not None and kind not in ('import', 'output', 'thumbnail'):
            self._priority.release(task)
        if kind in ("preview", "original"):
            self._rendering = False
            if self._interaction_dirty:
                self._queue_live_preview()
            elif self._pending and not self.timer.isActive():
                self._render_preview()
        elif kind == 'comparison' and task is not None and task is self._comparison_task:
            self._comparison_task = None
            if self._comparison_upgrade:
                self._comparison_upgrade = False
                self._request_original(force_full=True)
        elif kind == 'footer_metadata' and self._footer_metadata_pending and not self._closing:
            self._footer_metadata_pending = False
            self._refresh_footer_examples()
        elif kind == "export":
            self._set_exporting(False)
        elif kind == "import" and not any(task_kind == "import" for task_kind, _ in self._tasks):
            self._sync_template_context()
            self._refresh_footer_examples(request=False)
            if self.files._selected_count:
                self._schedule_preview()
        elif kind == "output" and token == self._completion_refresh:
            self._completion_refresh = None
        if task is not None and self._scan_tokens.get(kind) == token:
            if getattr(task, 'restore_checks', False):
                self.files.finish_scan(kind)
            self._scan_tokens.pop(kind, None)
        if kind == 'thumbnail' and task is not None and task is self._thumbnail_task:
            if not task.cancel.is_set():
                for path in task.paths:
                    key = os.path.normcase(os.path.abspath(path))
                    if key not in task.received:
                        self._thumbnail_failed.add((task.browser_kind, key))
            self._thumbnail_task = None
            self._start_visible_thumbnails()
        self._release_preview_if_idle()
        if kind in ('preview', 'original') and not self._closing:
            self._refresh_footer_examples()
        self._update_actions()
        if self._closing and not self._tasks:
            QTimer.singleShot(0, self, self.close)
