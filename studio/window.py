"""ExifFrame 桌面工作区"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
    QSizePolicy, QSplitter, QStyle, QToolBar, QVBoxLayout, QWidget,
)

from core.desktop_service import list_presets, load_settings, save_settings
from .canvas import ImageCanvas
from .files import FileBrowser
from .i18n import bind_static_texts, install_qt_translations, set_language, translator
from .inspector import Inspector
from .state import StudioState
from .workspace_inspection import WorkspaceInspection
from .workspace_library import WorkspaceLibrary
from .workspace_preview import WorkspacePreview
from .workspace_export import WorkspaceExport
from .workspace_editors import WorkspaceEditors


class PhotoView(ImageCanvas):
    """主窗口照片画布和空态提示"""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 200)
        self.empty_message = '添加照片后开始编辑水印\n\n拖入 JPG、PNG、HEIC 文件或文件夹，或点击上方“添加照片”'
        translator.language_changed.connect(self.viewport().update)


class MainWindow(
    WorkspaceInspection, WorkspaceLibrary, WorkspacePreview, WorkspaceExport, WorkspaceEditors, QMainWindow,
):
    """桌面工作区的布局与信号装配"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ExifFrame")
        self.resize(1380, 850)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)
        self.settings = load_settings()
        self.state = StudioState(self.settings.template_name, parent=self)
        self._saved = deepcopy(self.settings)
        self.presets = list_presets()
        self._dirty = self._locked = self._closing = False
        self._init_library()
        self._init_editors()
        self._init_export()
        self._init_preview()
        self._build_actions()
        self._build_ui()
        # 固定控件绑定一次，动态内容在语言信号到达后原地更新
        bind_static_texts(self, exclude=(self.canvas_name, self.preview_status, self.summary_label,
                                        self.files.count_label, self.export_action, self.inspector,
                                        *self.inspector.findChildren(QWidget)))
        self._bind_controls()
        self._restore_controls()
        self._update_actions()
        translator.language_changed.connect(self._retranslate_ui)
        install_qt_translations()
        self._retranslate_ui()
        QTimer.singleShot(0, self, self._load_directories)

    def _action(self, text, callback, shortcut=None, icon=None, checkable=False):
        """统一菜单和工具栏使用的动作及快捷键"""
        action = QAction(text, self)
        action.setCheckable(checkable)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def _build_actions(self):
        icons = QStyle.StandardPixmap
        self.add_action = self._action("添加照片", self._pick_photos, "Ctrl+O", icons.SP_FileIcon)
        self.directory_action = self._action("输入目录", self._pick_folder, "Ctrl+Shift+O", icons.SP_DirOpenIcon)
        self.refresh_action = self._action("刷新目录", self._refresh_directories, "F5", icons.SP_BrowserReload)
        self.export_action = self._action("导出照片", self._export, "Ctrl+R", icons.SP_ArrowDown)
        self.cancel_action = self._action("取消导出", self._cancel_export, "Escape", icons.SP_MediaStop)
        self.save_action = self._action("保存设置", self._save_config, "Ctrl+S", icons.SP_DialogSaveButton)
        self.reset_action = self._action("重置设置", self._reset_config, icon=icons.SP_BrowserReload)
        self.new_template_action = self._action("新建模板…", self._new_template, "Ctrl+N", icons.SP_FileIcon)
        self.copy_template_action = self._action("模板另存为…", self._copy_template, "Ctrl+Shift+S", icons.SP_DialogSaveButton)
        self.edit_template_action = self._action("高级源码…", self._edit_template, "Ctrl+E", icons.SP_FileDialogDetailedView)
        self.footer_action = self._action("组合底部信息…", self._show_style_tab, "Ctrl+Shift+E", icons.SP_FileDialogContentsView)
        self.metadata_action = self._action("编辑照片信息…", self._show_metadata_tab, "Ctrl+I", icons.SP_FileDialogInfoView)
        self.metadata_batch_action = self._action("编辑选中照片信息…", self._show_metadata_tab, icon=icons.SP_FileDialogListView)
        self.original_action = self._action("对照原图", self._view_changed, "Ctrl+Tab", checkable=True)
        self.lock_action = self._action("锁定设置", self._set_locked, checkable=True)
        self.metadata_action.setToolTip("编辑当前照片的水印信息，原片保持不变（Ctrl+I）")
        self.footer_action.setToolTip("自由组合水印字段、顺序和分隔符（Ctrl+Shift+E）")
        self.edit_template_action.setToolTip("编辑完整 JSON / Jinja 模板（Ctrl+E）")
        file_menu = self.menuBar().addMenu("文件(&F)")
        for action in (self.add_action, self.directory_action, self.refresh_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.metadata_action)
        file_menu.addAction(self.metadata_batch_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.reset_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.cancel_action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("退出", self.close, "Alt+F4"))
        template_menu = self.menuBar().addMenu("模板(&T)")
        for action in (self.new_template_action, self.copy_template_action, self.footer_action, self.edit_template_action):
            template_menu.addAction(action)
        view_menu = self.menuBar().addMenu("查看(&V)")
        view_menu.addAction(self.original_action)
        view_menu.addAction(self.lock_action)
        view_menu.addAction(self._action("错误详情…", self._show_error_details))
        self.language_menu = view_menu.addMenu("语言")
        self.language_actions = {}
        group = QActionGroup(self)
        for code, title in (("zh_CN", "中文"), ("en_US", "英文")):
            action = self._action(title, lambda checked=False, value=code: set_language(value), checkable=True)
            group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action
        view_menu.addSeparator()
        self.about_action = self._action("关于", self._show_about)
        view_menu.addAction(self.about_action)
        self.toolbar = QToolBar("常用操作")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # 把最常用的四步操作排在一起，其余入口继续保留
        for action in (self.add_action, self.metadata_action, self.footer_action):
            self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.export_action)
        self.toolbar.addAction(self.cancel_action)
        self.toolbar.widgetForAction(self.export_action).setObjectName("primaryButton")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.toolbar.addAction(self.directory_action)
        self.toolbar.addAction(self.refresh_action)
        self.addToolBar(self.toolbar)

    def _build_ui(self):
        self.files = FileBrowser()
        self.files.setObjectName("filesPanel")
        self.files.setMinimumWidth(270)
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
        heading = QHBoxLayout()
        heading.setContentsMargins(12, 8, 12, 8)
        self.canvas_name = QLabel("预览")
        self.canvas_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.canvas_name, 1)
        self.original_toggle = QCheckBox("对照原图")
        self.original_toggle.setObjectName("originalToggle")
        self.original_toggle.setToolTip("仅切换预览，不改变导出内容（Ctrl+Tab）")
        self.original_toggle.toggled.connect(self._original_toggled)
        heading.addWidget(self.original_toggle)
        layout.addLayout(heading)
        self.photo_view = PhotoView()
        self.photo_view.setObjectName("photoPreview")
        self.photo_view.zoom_changed.connect(self._preview_zoom_changed)
        self.photo_view.original_requested.connect(self._request_original)
        layout.addWidget(self.photo_view, 1)
        self.preview_status = QLabel("未选择照片")
        self.preview_status.setObjectName("previewStatus")
        layout.addWidget(self.preview_status)
        self.inspector = Inspector()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        for widget in (self.files, preview, self.inspector):
            splitter.addWidget(widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 700, 360])
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(splitter)
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
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.summary_label)
        self.statusBar().addPermanentWidget(self.error_button)
        self.statusBar().addPermanentWidget(self.open_button)
        self._set_status("就绪")

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
            # 共享配置只在点击保存时写回，关闭时保留已保存的个人配置
            try:
                save_settings(replace(self._saved, template_source=""))
            except Exception:
                pass
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
