"""ExifFrame 桌面工作区"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from core.desktop_service import list_presets, load_settings, save_settings
from .canvas import ImageCanvas
from .filmstrip import FilmBrowser
from .history import ParameterHistory
from .i18n import bind, bind_static_texts, translator
from .inspector import Inspector
from .workspace_actions import WorkspaceActions
from .state import StudioState
from .workspace_inspection import WorkspaceInspection
from .preset_management import WorkspacePresetManagement
from .workspace_library import WorkspaceLibrary
from .workspace_preview import WorkspacePreview
from .workspace_export import WorkspaceExport
from .workspace_editors import WorkspaceEditors
from .window_presentation import restore_layout, save_layout


class PhotoView(ImageCanvas):
    """主窗口照片画布和空态提示"""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 200)
        self.empty_message = '添加照片后开始编辑水印\n\n拖入 JPG、PNG、HEIC 文件或文件夹，或点击上方“添加照片”'
        translator.language_changed.connect(self.viewport().update)


class MainWindow(
    WorkspaceActions, WorkspacePresetManagement, WorkspaceInspection, WorkspaceLibrary, WorkspacePreview, WorkspaceExport, WorkspaceEditors, QMainWindow,
):
    """桌面工作区的布局与信号装配"""

    def __init__(self, *, settings=None, progress=None, remember_layout=True):
        super().__init__()
        self._remember_layout = remember_layout
        self._initial_scan_queued = False
        self.setWindowTitle("ExifFrame")
        self.resize(1540, 940)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)
        self.settings = settings if settings is not None else load_settings()
        self.state = StudioState(self.settings.template_name, parent=self)
        self._saved = deepcopy(self.settings)
        self.presets = list_presets()
        self._dirty = self._locked = self._closing = False
        self._init_library()
        self._init_editors()
        self._init_export()
        self._init_preview()
        self.history = ParameterHistory(self)
        self._build_actions()
        self._build_ui(progress)
        # 固定控件绑定一次，动态内容在语言信号到达后原地更新
        bind_static_texts(self, exclude=(self.canvas_name, self.preview_status, self.summary_label,
                                        self.files.count_label, self.export_action, self.inspector,
                                        *self.inspector.findChildren(QWidget)))
        self._bind_controls()
        self._restore_controls()
        self._update_actions()
        translator.language_changed.connect(self._retranslate_ui)
        self._retranslate_ui()
        if remember_layout:
            restore_layout(self)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_scan_queued:
            self._initial_scan_queued = True
            QTimer.singleShot(0, self, self._load_directories)

    def show_startup_notice(self, title, message):
        """以工作区内提示保留源码版补全 ExifTool 的指引"""
        from PySide6.QtWidgets import QMessageBox, QToolButton
        panel = self.photo_view.parentWidget()
        row = QWidget(panel)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.addWidget(bind(QLabel(), '请补全 exiftool 文件夹以读取完整照片信息'), 1)
        details = bind(QPushButton(), '详情')
        details.clicked.connect(lambda: QMessageBox.information(self, title, message))
        layout.addWidget(details)
        close = QToolButton(row)
        close.setText('×')
        bind(close, '关闭', 'setAccessibleName')
        close.clicked.connect(row.hide)
        layout.addWidget(close)
        panel.layout().insertWidget(0, row)

    def _build_ui(self, progress):
        self.files = FilmBrowser()
        self.files.fold.toggled.connect(self.filmstrip_action.setChecked)
        self.files.fold.toggled.connect(self._sync_filmstrip_splitter)
        self.filmstrip_action.setChecked(self.files.fold.isChecked())
        self.files.setObjectName("filesPanel")
        self.files.directory_requested.connect(self._directory_requested)
        self.files.file_selected.connect(self._file_selected)
        self.files.selection_changed.connect(self._read_checked_paths)
        self.files.user_navigated.connect(self._user_navigated)
        self.files.visible_paths_invalidated.connect(self._visible_paths_invalidated)
        self.files.visible_paths_changed.connect(self._visible_paths_changed)
        self.files.file_details_changed.connect(self._file_details_changed)
        self.files.clear_requested.connect(self._clear_photos)
        self.input_tree, self.output_tree = self.files.input_tree, self.files.output_tree
        self.input_input, self.output_input = self.files.input_path, self.files.output_path
        preview = QWidget()
        preview.setObjectName("previewPanel")
        layout = QVBoxLayout(preview)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas_name = self.files.photo_name
        self.canvas_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.original_toggle = QCheckBox(self)
        self.original_toggle.hide()
        self.original_toggle.toggled.connect(self._original_toggled)
        self.photo_view = PhotoView()
        self.photo_view.setObjectName("photoPreview")
        self.photo_view.zoom_changed.connect(self._preview_zoom_changed)
        self.photo_view.original_requested.connect(self._request_original)
        self.preview_status = QLabel("未选择照片")
        self.preview_status.setObjectName("previewStatus")
        self._last_filmstrip_height = 148
        self.preview_splitter = QSplitter(Qt.Orientation.Vertical, preview)
        self.preview_splitter.setObjectName("previewSplitter")
        self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.setHandleWidth(5)
        self.preview_splitter.addWidget(self.photo_view)
        self.preview_splitter.addWidget(self.files)
        self.preview_splitter.setStretchFactor(0, 1)
        self.preview_splitter.setStretchFactor(1, 0)
        self.preview_splitter.setSizes([720, self._last_filmstrip_height])
        layout.addWidget(self.preview_splitter, 1)
        if progress:
            progress('正在构建工作台…', .74)
        self.inspector = Inspector(progress=progress)
        self.inspector.setFixedWidth(348)
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(1)
        outer.addWidget(preview, 1)
        outer.addWidget(self.inspector)
        self.setCentralWidget(central)
        self.summary_label = QLabel("成功 0 / 失败 0 / 跳过 0")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(150)
        self.progress.hide()
        self.error_button = QPushButton("详情")
        self.error_button.clicked.connect(self._show_error_details)
        self.error_button.setEnabled(False)
        self.open_button = QPushButton("打开输出目录")
        self.open_button.clicked.connect(self._open_output)
        self.statusBar().setStyleSheet('QPushButton { min-height: 16px; padding: 1px 5px; } '
                                      'QLabel#previewStatus { padding: 0px 3px; background: transparent; }')
        self.files.set_status_widgets(self.canvas_name, self.preview_status)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.summary_label)
        self.statusBar().addPermanentWidget(self.error_button)
        self.statusBar().addPermanentWidget(self.open_button)
        self.statusBar().hide()
        self._set_status("就绪")

        def _sync_filmstrip_splitter(self, expanded):
        if not hasattr(self, 'preview_splitter'):
            return
        total = max(320, self.preview_splitter.height() or (self.height() - 40))
        if expanded:
            film_h = max(112, min(getattr(self, '_last_filmstrip_height', 148), int(total * 0.45), 360))
            self.preview_splitter.setSizes([max(200, total - film_h), film_h])
        else:
            current = self.preview_splitter.sizes()[1]
            if current >= 100:
                self._last_filmstrip_height = current
            bar_h = self.files.collapsed_height()
            self.preview_splitter.setSizes([max(200, total - bar_h), bar_h])

    def _toggle_filmstrip(self, checked):
        self.files.show()
        self.files._user_fold()
        self.files.fold.setChecked(checked)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'inspector'):
            width = 340 if self.width() < 1250 else 348
            self.inspector.setFixedWidth(width)

    def dragEnterEvent(self, event):
        if not self._exporting and event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def closeEvent(self, event):
        if not self._closing:
            # 等待信息写入结束后重新走关闭确认，避免销毁仍在运行的线程
            active_job = next((editor._job for editor in self._metadata_editors if editor._job is not None), None)
            if active_job is not None:
                if self._metadata_close_job is not active_job:
                    self._metadata_close_job = active_job
                    active_job.finished.connect(self._resume_close_after_metadata)
                    if active_job.isFinished():
                        QTimer.singleShot(0, self, self._resume_close_after_metadata)
                self._set_status("等待照片信息处理结束…")
                event.ignore()
                return
            for editor in list(self._metadata_editors):
                if not editor.close():
                    event.ignore()
                    return
            for editor in list(self._editors):
                if not editor.close():
                    event.ignore()
                    return
            # 输入与输出路径自动记忆，其他会话调整仍需显式保存
            if self._remember_layout:
                self._remember_workspace_dirs()
                save_layout(self)
            try:
                save_settings(replace(self._saved, template_source=""))
            except Exception:
                pass
        self._abort_live_interaction()
        self.timer.stop()
        self._idle_check.stop()
        self._priority.release(self)
        if self._tasks:
            self._closing = True
            self.centralWidget().setEnabled(False)
            self.toolbar.setEnabled(False)
            self._set_status("等待当前照片处理结束…")
            for task in self._tasks.values():
                task.cancel.set()
            event.ignore()
        else:
            self._closing = True
            event.accept()

    @Slot()
    def _resume_close_after_metadata(self):
        self._metadata_close_job = None
        QTimer.singleShot(0, self, self.close)
