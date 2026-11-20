"""素材导入、选中和可见缩略图调度"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from threading import Lock

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtWidgets import QFileDialog
from studio.path_memory import last_directory, remember_directory
from .i18n import tr


class WorkspaceLibrary:
    """素材导入、选中和可见缩略图调度"""

    def _init_library(self):
        self._current_data, self._current_kind = None, 'import'
        self._background_io_lock = Lock()
        self._scan_tokens = {}
        self._selection_revision = 0
        self._auto_selecting = False
        self._latest_manual_import = None
        self._visible_paths = {'import': (), 'output': ()}
        self._thumbnail_task = None
        self._thumbnail_failed = set()
        self.scan_pool = QThreadPool(self)
        self.scan_pool.setMaxThreadCount(1)
        self.thumbnail_pool = QThreadPool(self)
        self.thumbnail_pool.setMaxThreadCount(1)

    def _pick_photos(self):
        if self._exporting or self._closing:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("添加照片"), last_directory("photos", self.settings.input_dir),
                                              tr("照片 (*.jpg *.jpeg *.png *.heic *.heif)"),
                                              options=QFileDialog.Option.DontUseNativeDialog)
        if paths:
            remember_directory("photos", Path(paths[0]).parent)
        self.add_paths(paths)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("选择输入目录"), self.settings.input_dir,
                                                  QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self._directory_requested("import", folder)

    def _load_directories(self):
        if self._closing:
            return
        for kind, folder in (("import", self.settings.input_dir), ("output", self.settings.output_dir)):
            if folder and Path(folder).is_dir():
                self._scan_directory(kind, folder)

    def _directory_requested(self, kind, folder):
        if self._exporting or self._closing:
            return
        if not Path(folder).is_dir():
            self._record_errors("目录无法读取", [folder])
            return
        self.files.paths[kind].setText(str(Path(folder).resolve()))
        self._directories_changed()
        self._remember_workspace_dirs()
        self._scan_directory(kind, folder)

    def _scan_directory(self, kind, folder):
        """刷新目录前取消旧扫描以丢弃迟到的文件信号"""
        if kind == 'import':
            self._latest_manual_import = None
        for task in self._tasks.values():
            if task.kind == kind:
                task.cancel.set()
        self.files.begin_scan(kind, folder)
        self._thumbnail_failed = {item for item in self._thumbnail_failed if item[0] != kind}
        if self._thumbnail_task is not None and self._thumbnail_task.browser_kind == kind:
            self._thumbnail_task.cancel.set()
        if self._current_kind == kind:
            self._current_data = None
            self.state.set_selected_photo(None)
            self._invalidate_preview()
            if self._comparison_task is not None:
                self._comparison_task.cancel.set()
            self._comparison_task = self._comparison_image = None
            self._comparison_full = self._comparison_upgrade = False
            self.photo_view.set_image(None)
            self.canvas_name.setText(tr("预览"))
        scan_settings = replace(self.settings, metadata_overrides={}, input_files=(), protected_sources=())
        task = self._start_task(kind, paths=[Path(folder)], settings=scan_settings, batch_size=8,
                                pause=self._priority.pause_background, io_lock=self._background_io_lock)
        task.restore_checks = kind == 'import'
        task.manual_import = False
        task.select_first = True
        task.selection_revision = self._selection_revision
        self._scan_tokens[kind] = task.token
        self._update_actions()
        return task

    def _refresh_directories(self):
        self._load_directories()

    def add_paths(self, paths):
        """手动添加与拖入均在后台扫描"""
        if self._exporting or self._closing:
            return
        accepted = [Path(path) for path in paths if path]
        if accepted:
            scan_settings = replace(self.settings, metadata_overrides={}, input_files=(), protected_sources=())
            task = self._start_task("import", paths=accepted, settings=scan_settings, batch_size=8,
                                    pause=self._priority.pause_background, io_lock=self._background_io_lock)
            task.restore_checks = False
            task.manual_import = True
            task.select_first = True
            task.selection_revision = self._selection_revision
            self._latest_manual_import = task.token
            self._update_actions()

    def _clear_photos(self):
        """清空输入队列并取消仍在进行的目录扫描"""
        if self._exporting:
            return
        for task in self._tasks.values():
            if task.kind == "import":
                task.cancel.set()
        self._latest_manual_import = None
        if self._thumbnail_task is not None and self._thumbnail_task.browser_kind == 'import':
            self._thumbnail_task.cancel.set()
        self.files.begin_scan("import", self.files.roots["import"], preserve_checks=False)
        if self._current_kind == "import":
            self._file_selected("import", None)
        self._set_status("输入队列已清空")

    def _remove_photo(self):
        if not self._exporting:
            self.files.remove_current()

    @Slot(int, object)
    def _import_item(self, token, data):
        task = next((task for (kind, key), task in self._tasks.items()
                     if key == token and kind in ("import", "output", "thumbnail")), None)
        if self._closing or not task or task.cancel.is_set():
            return
        if task.kind == 'thumbnail':
            path, image, width, height, signature = data
            key = os.path.normcase(os.path.abspath(path))
            if self.files.update_file(task.browser_kind, path, image, width, height, signature,
                                      task.item_tokens.get(key)):
                task.received.add(key)
            return
        self._add_scan_items(task, (data,))

    @Slot(int, object)
    def _import_batch(self, token, items):
        task = next((task for (kind, key), task in self._tasks.items()
                     if key == token and kind in ('import', 'output')), None)
        if not self._closing and task is not None and not task.cancel.is_set():
            self._add_scan_items(task, items)

    def _add_scan_items(self, task, items):
        kind = task.kind
        for data in items:
            if len(data) > 4:
                self.state.register_photo(data[0], data[4])
        added = self.files.add_files(kind, items, restore_checks=task.restore_checks)
        if kind == 'import':
            if task.restore_checks and self.files._selected_count != len(self.state.checked_paths):
                self._read_checked_paths()
            self.inspector.set_counts(len(self.state.checked_paths), len(self.files.items['import']))
        for path in added:
            self._thumbnail_failed.discard((kind, os.path.normcase(os.path.abspath(path))))
        first = added[0] if added else None
        if first is not None and task.select_first:
            task.select_first = False
            older_manual = (kind == 'import' and task.manual_import
                            and task.token != self._latest_manual_import)
            if older_manual and self.input_tree.currentItem() is not None:
                return
            if task.selection_revision == self._selection_revision:
                item = self.files.items[kind].get(os.path.normcase(os.path.abspath(first)))
                if item is not None:
                    self._auto_selecting = True
                    try:
                        if kind == 'import':
                            self.files.tabs.setCurrentIndex(0)
                        self.files.trees[kind].setCurrentItem(item)
                    finally:
                        self._auto_selecting = False

    @Slot(str)
    def _user_navigated(self, kind):
        self._selection_revision += 1

    @Slot(str)
    def _visible_paths_invalidated(self, kind):
        self._visible_paths[kind] = ()
        if self._thumbnail_task is not None:
            self._thumbnail_task.cancel.set()

    @Slot(str, object)
    def _visible_paths_changed(self, kind, paths):
        self._visible_paths[kind] = tuple(paths)
        task = self._thumbnail_task
        current_kind = 'import' if self.files.tabs.currentIndex() == 0 else 'output'
        wanted = {os.path.normcase(os.path.abspath(path)) for path in self._visible_paths[current_kind]}
        if task is not None and (task.browser_kind != current_kind
                                 or any(os.path.normcase(os.path.abspath(path)) not in wanted for path in task.paths)):
            task.cancel.set()
        self._start_visible_thumbnails()

    @Slot(str, object)
    def _file_details_changed(self, kind, data):
        if not self._current_data or kind != self._current_kind or data[0] != self._current_data[0]:
            return
        self._current_data = data
        self.photo_view.set_source_size(data[1:3])
        if not self._rendering and not self._preview_error and not self.photo_view.photo.pixmap().isNull():
            _, width, height = data
            mode = '输出文件' if kind == 'output' else '原图' if self.original_toggle.isChecked() else '水印预览'
            self._set_preview_status('{mode} · {width} × {height}', mode=mode, width=width, height=height)

    @Slot(str, int, object)
    def _task_dimensions(self, kind, token, data):
        task = self._tasks.get((kind, token))
        if self._closing or task is None or task.cancel.is_set() or not self._current_data:
            return
        if kind in ('preview', 'original') and token != self._render_revision_id:
            return
        if kind == 'comparison' and task is not self._comparison_task:
            return
        path, width, height = data
        if path == self._current_data[0]:
            self.files.update_dimensions(self._current_kind, path, width, height)

    @Slot()
    def _start_visible_thumbnails(self):
        if (self._closing or self._exporting or self._priority.pause_background.is_set()
                or self._thumbnail_task is not None or not hasattr(self, 'files')):
            return
        kind = 'import' if self.files.tabs.currentIndex() == 0 else 'output'
        paths = []
        for path in self._visible_paths[kind]:
            key = (kind, os.path.normcase(os.path.abspath(path)))
            if key not in self._thumbnail_failed and self.files.needs_thumbnail(kind, path):
                paths.append(path)
                if len(paths) == 8:
                    break
        if not paths:
            return
        task = self._start_task('thumbnail', paths=paths, pause=self._priority.pause_background,
                                io_lock=self._background_io_lock)
        task.browser_kind = kind
        task.received = set()
        task.item_tokens = {os.path.normcase(os.path.abspath(path)): self.files.item_token(kind, path)
                            for path in paths}
        self._thumbnail_task = task

    @Slot(str, object)
    def _file_selected(self, kind, data):
        if not self._auto_selecting:
            self._selection_revision += 1
        for task in self._tasks.values():
            if task.kind == 'footer_metadata' and (not data or task.paths[0] != data[0]):
                task.cancel.set()
        self._sample_data = None
        self._current_kind, self._current_data = kind, data
        self.state.set_selected_photo(data[0] if data else None)
        if self._comparison_task is not None:
            self._comparison_task.cancel.set()
        self._comparison_task = self._comparison_image = None
        self._comparison_full = self._comparison_upgrade = False
        self._watermark_image = self._watermark_signature = None
        self._send_footer_preview(None)
        if not data:
            self.canvas_name.setText(tr("预览"))
            self.canvas_name.setToolTip("")
            self.photo_view.set_image(None)
            self._set_preview_status("未选择照片")
            self._update_actions()
            self._schedule_preview()
            self._refresh_footer_examples()
            return
        path, width, height = data
        self.canvas_name.setText(path.name)
        self.canvas_name.setToolTip(str(path))
        self.original_toggle.setEnabled(kind == "import")
        self.original_action.setEnabled(kind == "import")
        self.photo_view.set_image(None)
        if width and height:
            self._set_preview_status("{width} × {height} · {mode}", width=width, height=height,
                                     mode="输出文件" if kind == "output" else "输入文件")
        else:
            self._set_preview_status("正在读取照片…")
        self._update_actions()
        if kind == "import" and self._visible_footer_editors():
            self._ensure_watermark_mode()
        self._schedule_preview()
        self._refresh_footer_examples()

    def _current_path(self):
        return self.state.selected_photo
