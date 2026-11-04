"""目录、模板源码和批量处理的原生桌面窗口"""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSizePolicy, QSlider, QSpinBox, QSplitter, QStyle, QToolBar, QVBoxLayout, QWidget,
)

from core.desktop_service import (
    SUPPORTED_SUFFIXES, list_presets, load_settings, read_template,
    save_settings, save_workspace_settings, write_template,
)
from .files import FileBrowser
from .i18n import bind_static_texts, install_qt_translations, language, localize_error, set_language, tr, translator
from .template_editor import TemplateEditor
from .workers import ImageTask, WorkerSignals
from .pixmaps import preview_pixmap


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
                modified = path.stat().st_mtime_ns
                metadata = _metadata(str(path), modified)
                if not self.cancel.is_set():
                    self.signals.result.emit(self.kind, self.token, (path, modified, metadata))
        except Exception as exc:
            self.signals.error.emit(self.kind, self.token, str(exc))
        finally:
            self.signals.finished.emit(self.kind, self.token)


class PhotoView(QWidget):
    """在深灰画布上等比显示照片或简短空态提示"""

    def __init__(self):
        super().__init__()
        self.pixmap = QPixmap()
        self.setMinimumSize(220, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        translator.language_changed.connect(self.update)

    def set_image(self, image):
        """保留原始预览像素供窗口缩放时重新绘制"""
        self.pixmap = QPixmap.fromImage(image) if image is not None else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1C1C1C"))
        if self.pixmap.isNull():
            painter.setPen(QColor("#989898"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("选择照片以预览\n\n可拖入 JPG、PNG、HEIC 文件或文件夹"))
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        bounds = self.rect().adjusted(16, 16, -16, -16)
        size = self.pixmap.size().scaled(bounds.size(), Qt.AspectRatioMode.KeepAspectRatio)
        painter.drawPixmap(bounds.center().x() - size.width() // 2,
                           bounds.center().y() - size.height() // 2, size.width(), size.height(), self.pixmap)


class MainWindow(QMainWindow):
    """用独立任务和预览代次保持界面响应及状态一致"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ExifFrame")
        self.resize(1380, 850)
        self.setMinimumSize(1080, 680)
        self.setAcceptDrops(True)
        self.settings = load_settings()
        self._saved = deepcopy(self.settings)
        self.presets = list_presets()
        self._tasks, self._drafts, self._editors = {}, {}, []
        self._draft_owners = {}
        self._serial = self._generation = 0
        self._rendering = self._pending = self._closing = self._exporting = self._restoring = False
        self._dirty = self._locked = False
        self._current_data, self._current_kind = None, "import"
        self._last_output, self._errors = None, []
        self._metadata_editors = []
        self._error_dialogs = []
        self._counts = {"completed": 0, "errors": 0, "skipped": 0}
        self._status_source, self._status_values = "就绪", {}
        self._preview_source, self._preview_values = "未选择照片", {}
        self._preview_error = ""
        self._metadata_close_job = None
        self._footer_metadata = {}
        self._active_wizard = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._render_preview)
        self._build_actions()
        self._build_ui()
        # 固定控件绑定一次，动态内容在语言信号到达后原地更新
        bind_static_texts(self, exclude=(self.canvas_name, self.preview_status, self.summary_label,
                                        self.saved_label, self.mode_label, self.template_description,
                                        self.template_preview, self.lock_button, self.files.count_label,
                                        self.background_button, self.text_button))
        self._restore_controls()
        self._bind_controls()
        self._update_actions()
        translator.language_changed.connect(self._retranslate_ui)
        install_qt_translations()
        self._retranslate_ui()
        QTimer.singleShot(0, self._load_directories)

    def _action(self, text, callback, shortcut=None, icon=None, checkable=False):
        """统一菜单和工具栏使用的动作及快捷键"""
        action = QAction(text, self)
        action.setCheckable(checkable)
        if icon is not None:
            artwork = self.style().standardIcon(icon)
            if icon in (QStyle.StandardPixmap.SP_MediaPlay, QStyle.StandardPixmap.SP_MediaStop):
                pixmap = artwork.pixmap(16, 16)
                painter = QPainter(pixmap)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                painter.fillRect(pixmap.rect(), QColor("#CFD6DE"))
                painter.end()
                artwork = QIcon(pixmap)
            action.setIcon(artwork)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def _build_actions(self):
        icons = QStyle.StandardPixmap
        self.add_action = self._action("添加照片", self._pick_photos, "Ctrl+O", icons.SP_FileIcon)
        self.directory_action = self._action("输入目录", self._pick_folder, "Ctrl+Shift+O", icons.SP_DirOpenIcon)
        self.refresh_action = self._action("刷新目录", self._refresh_directories, "F5", icons.SP_BrowserReload)
        self.export_action = self._action("处理选中照片", self._export, "Ctrl+R", icons.SP_MediaPlay)
        self.cancel_action = self._action("停止", self._cancel_export, "Escape", icons.SP_MediaStop)
        self.save_action = self._action("保存配置", self._save_config, "Ctrl+S", icons.SP_DialogSaveButton)
        self.reset_action = self._action("重置配置", self._reset_config, icon=icons.SP_BrowserReload)
        self.new_template_action = self._action("新建模板…", self._new_template, "Ctrl+N", icons.SP_FileIcon)
        self.copy_template_action = self._action("模板另存为…", self._copy_template, "Ctrl+Shift+S", icons.SP_DialogSaveButton)
        self.edit_template_action = self._action("高级源码…", self._edit_template, "Ctrl+E", icons.SP_FileDialogDetailedView)
        self.footer_action = self._action("组合底部信息…", self._edit_footer, "Ctrl+Shift+E", icons.SP_FileDialogContentsView)
        self.metadata_action = self._action("编辑照片信息…", self._edit_metadata, "Ctrl+I", icons.SP_FileDialogInfoView)
        self.metadata_batch_action = self._action("编辑选中照片信息…", self._edit_checked_metadata, icon=icons.SP_FileDialogListView)
        self.original_action = self._action("显示原图", self._view_changed, "Ctrl+Tab", checkable=True)
        self.lock_action = self._action("锁定配置", self._set_locked, checkable=True)
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
        self.toolbar = QToolBar("常用操作")
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(16, 16))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (self.add_action, self.directory_action, self.refresh_action):
            self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.save_action)
        self.toolbar.addAction(self.edit_template_action)
        self.toolbar.addAction(self.metadata_action)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.export_action)
        self.toolbar.addAction(self.cancel_action)
        self.addToolBar(self.toolbar)

    def _build_ui(self):
        self.files = FileBrowser()
        self.files.setMinimumWidth(270)
        self.files.directory_requested.connect(self._directory_requested)
        self.files.file_selected.connect(self._file_selected)
        self.files.selection_changed.connect(self._update_actions)
        self.files.selection_changed.connect(self._queue_selection_changed)
        self.files.clear_requested.connect(self._clear_photos)
        self.input_tree, self.output_tree = self.files.input_tree, self.files.output_tree
        self.input_input, self.output_input = self.files.input_path, self.files.output_path
        preview = QWidget()
        layout = QVBoxLayout(preview)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        heading = QHBoxLayout()
        heading.setContentsMargins(7, 5, 7, 5)
        self.canvas_name = QLabel("预览")
        self.canvas_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.canvas_name, 1)
        self.original_toggle = QCheckBox("原图")
        self.original_toggle.setObjectName("originalToggle")
        self.original_toggle.toggled.connect(self._original_toggled)
        heading.addWidget(self.original_toggle)
        layout.addLayout(heading)
        self.photo_view = PhotoView()
        self.photo_view.setObjectName("photoPreview")
        layout.addWidget(self.photo_view, 1)
        self.preview_status = QLabel("未选择照片")
        self.preview_status.setObjectName("previewStatus")
        layout.addWidget(self.preview_status)
        self.inspector = self._build_inspector()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("mainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(5)
        for widget in (self.files, preview, self.inspector):
            splitter.addWidget(widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 710, 310])
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(5, 5, 5, 5)
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

    def _build_inspector(self):
        panel = QWidget()
        panel.setMinimumWidth(280)
        panel.setMaximumWidth(360)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(5)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 2, 0)
        form.setSpacing(8)
        template_group = QGroupBox("水印模板")
        template_layout = QVBoxLayout(template_group)
        template_layout.setSpacing(5)
        self.template_combo = QComboBox()
        self.template_combo.setObjectName("templateCombo")
        template_layout.addWidget(self.template_combo)
        self.template_preview = QLabel()
        self.template_preview.setObjectName("templatePreview")
        self.template_preview.setFixedHeight(95)
        self.template_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        template_layout.addWidget(self.template_preview)
        self.template_description = QLabel()
        self.template_description.setWordWrap(True)
        self.template_description.setObjectName("secondaryText")
        template_layout.addWidget(self.template_description)
        controls = QHBoxLayout()
        for text, callback in (("新建", self._new_template), ("另存为", self._copy_template), ("高级源码", self._edit_template)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        template_layout.addLayout(controls)
        self.footer_button = QPushButton("组合底部信息…")
        self.footer_button.setObjectName("composeFooterButton")
        self.footer_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
        self.footer_button.clicked.connect(self._edit_footer)
        template_layout.addWidget(self.footer_button)
        self.template_styles_check = QCheckBox("按模板原样处理")
        self.template_styles_check.setObjectName("useTemplateStylesCheck")
        self.template_styles_check.setToolTip("保留模板中的文字、颜色、字号和布局；调整下方参数后切换为自定义")
        template_layout.addWidget(self.template_styles_check)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("secondaryText")
        self.mode_label.setWordWrap(True)
        template_layout.addWidget(self.mode_label)
        form.addWidget(template_group)
        self.style_group = QGroupBox("快捷调整")
        fields = QFormLayout(self.style_group)
        fields.setContentsMargins(8, 12, 8, 8)
        fields.setSpacing(6)
        self.title_input, self.subtitle_input = QLineEdit(), QLineEdit()
        self.title_input.setObjectName("titleInput")
        self.subtitle_input.setObjectName("subtitleInput")
        self.title_input.setPlaceholderText("留空使用照片信息")
        self.subtitle_input.setPlaceholderText("留空使用照片信息")
        fields.addRow("相机显示文字", self.title_input)
        fields.addRow("镜头显示文字", self.subtitle_input)
        self.logo_check = QCheckBox("显示品牌标识")
        self.logo_check.setObjectName("showLogoCheck")
        fields.addRow("", self.logo_check)
        self.font_slider = self._slider(50, 200, "fontScaleSlider")
        self.border_slider = self._slider(6, 30, "borderSlider")
        self.font_value, self.border_value = QLabel(), QLabel()
        for caption, slider, value in (("文字大小", self.font_slider, self.font_value), ("底部留白", self.border_slider, self.border_value)):
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            value.setFixedWidth(36)
            row.addWidget(value)
            fields.addRow(caption, row)
        self.background_button = QPushButton("底色")
        self.text_button = QPushButton("文字颜色")
        self.background_button.setObjectName("backgroundColorButton")
        self.text_button.setObjectName("textColorButton")
        self.background_button.clicked.connect(lambda: self._choose_color("background"))
        self.text_button.clicked.connect(lambda: self._choose_color("text_color"))
        colors = QHBoxLayout()
        colors.setSpacing(6)
        colors.addWidget(self.background_button)
        colors.addWidget(self.text_button)
        fields.addRow(colors)
        form.addWidget(self.style_group)
        export_group = QGroupBox("输出选项")
        options = QFormLayout(export_group)
        options.setSpacing(6)
        self.quality_spin = QSpinBox()
        self.quality_spin.setObjectName("qualitySpin")
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setSuffix(" %")
        options.addRow("JPEG 质量", self.quality_spin)
        self.overwrite_check = QCheckBox("覆盖同名输出文件")
        self.overwrite_check.setObjectName("overwriteCheck")
        self.overwrite_check.setToolTip("只替换输出文件，始终保护输入原片")
        self.structure_check = QCheckBox("保留输入目录结构")
        self.structure_check.setObjectName("preserveStructureCheck")
        options.addRow(self.overwrite_check)
        options.addRow(self.structure_check)
        form.addWidget(export_group)
        form.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        controls = QHBoxLayout()
        self.lock_button = QPushButton("锁定配置")
        self.lock_button.setCheckable(True)
        self.lock_button.toggled.connect(self._set_locked)
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self._save_config)
        self.reset_button = QPushButton("重置")
        self.reset_button.clicked.connect(self._reset_config)
        for button in (self.lock_button, self.save_button, self.reset_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.saved_label = QLabel("配置已载入")
        self.saved_label.setObjectName("secondaryText")
        layout.addWidget(self.saved_label)
        self.config_body = body
        return panel

    @staticmethod
    def _slider(low, high, name):
        """创建具有稳定测试名称的滑块"""
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(low, high)
        slider.setObjectName(name)
        return slider

    def _restore_controls(self):
        """恢复配置时屏蔽由程序赋值产生的参数覆盖"""
        self._restoring = True
        self._reload_presets(self.settings.template_name)
        self.title_input.setText(self.settings.title)
        self.subtitle_input.setText(self.settings.subtitle)
        self.logo_check.setChecked(self.settings.show_logo)
        self.font_slider.setValue(round(self.settings.font_scale * 100))
        self.border_slider.setValue(self.settings.border_percent)
        self.quality_spin.setValue(self.settings.quality)
        self.overwrite_check.setChecked(self.settings.overwrite_existing)
        self.structure_check.setChecked(self.settings.preserve_structure)
        self.template_styles_check.setChecked(self.settings.use_template_styles)
        self.input_input.setText(self.settings.input_dir)
        self.output_input.setText(self.settings.output_dir)
        self._restoring = False
        self._show_template()
        self._update_labels()

    def _reload_presets(self, selected=None):
        self.presets = list_presets()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for preset in self.presets:
            title = "品牌标识居中" if preset.name == "logo居中" else preset.name
            self.template_combo.addItem(tr(title), preset.name)
        self.template_combo.setCurrentIndex(max(0, self.template_combo.findData(selected or self.settings.template_name)))
        self.template_combo.blockSignals(False)

    def _bind_controls(self):
        self.template_combo.currentIndexChanged.connect(self._template_changed)
        for signal in (self.title_input.textChanged, self.subtitle_input.textChanged, self.logo_check.toggled,
                       self.font_slider.valueChanged, self.border_slider.valueChanged):
            signal.connect(self._style_changed)
        for signal in (self.quality_spin.valueChanged, self.overwrite_check.toggled, self.structure_check.toggled,
                       self.template_styles_check.toggled, self.input_input.textEdited, self.output_input.textEdited):
            signal.connect(self._settings_changed)

    def _show_template(self):
        index = self.template_combo.currentIndex()
        if index < 0:
            return
        preset = self.presets[index]
        self.template_description.setText(tr(preset.description))
        self.template_preview.clear()
        if preset.thumbnail:
            self.template_preview.setPixmap(preview_pixmap(preset.thumbnail, 255, 91))
        else:
            self.template_preview.setText(tr("自定义模板"))
        self.border_slider.setEnabled(preset.supports_footer)
        self.background_button.setEnabled(preset.supports_footer)

    def _template_changed(self):
        if self._restoring:
            return
        name = self.template_combo.currentData()
        self.settings = replace(self.settings, template_name=name, template_source=self._drafts.get(name, ""))
        self.template_styles_check.setChecked(True)
        self._show_template()
        self._settings_changed()

    def _style_changed(self):
        if self._restoring:
            return
        # 用户主动调整才覆盖模板参数且界面始终显示当前处理模式
        self.template_styles_check.blockSignals(True)
        self.template_styles_check.setChecked(False)
        self.template_styles_check.blockSignals(False)
        self._settings_changed()

    def _settings_changed(self):
        if self._restoring:
            return
        self.settings = replace(self.settings, template_name=self.template_combo.currentData(),
                                title=self.title_input.text(), subtitle=self.subtitle_input.text(),
                                show_logo=self.logo_check.isChecked(), font_scale=self.font_slider.value() / 100,
                                border_percent=self.border_slider.value(), quality=self.quality_spin.value(),
                                input_dir=self.input_input.text().strip(), output_dir=self.output_input.text().strip(),
                                overwrite_existing=self.overwrite_check.isChecked(), preserve_structure=self.structure_check.isChecked(),
                                use_template_styles=self.template_styles_check.isChecked())
        self._dirty = replace(self.settings, template_source="", metadata_overrides={}) != replace(self._saved, template_source="", metadata_overrides={})
        self._update_labels()
        self._update_actions()
        self._schedule_preview()

    def _update_labels(self):
        self.font_value.setText(f"{self.font_slider.value()}%")
        self.border_value.setText(f"{self.border_slider.value()}%")
        self.mode_label.setText(tr("使用模板定义的样式" if self.settings.use_template_styles else "自定义模式 · 快捷参数覆盖模板样式"))
        self.saved_label.setText(tr("配置有修改，尚未保存" if self._dirty else "配置已保存"))
        for widget, caption, color in ((self.background_button, "底色", self.settings.background),
                                       (self.text_button, "文字颜色", self.settings.text_color)):
            # 色块左侧保留透明间距，两个按钮维持紧凑并排
            swatch = QPixmap(24, 16)
            swatch.fill(Qt.GlobalColor.transparent)
            painter = QPainter(swatch)
            painter.fillRect(8, 1, 14, 14, QColor(color))
            painter.setPen(QColor("#949494"))
            painter.drawRect(8, 1, 13, 13)
            painter.end()
            widget.setIcon(QIcon(swatch))
            widget.setIconSize(QSize(24, 16))
            widget.setText(tr(caption))
            widget.setToolTip(tr("点击选择{label}，当前颜色 {color}", label=tr(caption), color=color.upper()))
            widget.setAccessibleName(widget.toolTip())

    def _set_status(self, source, **values):
        """保留状态原文以便处理中切换语言"""
        self._status_source, self._status_values = source, values
        rendered = dict(values)
        if "title" in rendered:
            rendered["title"] = tr(rendered["title"])
        if "error" in rendered:
            rendered["error"] = localize_error(rendered["error"])
        self.statusBar().showMessage(tr(source, **rendered))

    def _set_preview_status(self, source, **values):
        self._preview_source, self._preview_values = source, values
        rendered = dict(values)
        if "mode" in rendered:
            rendered["mode"] = tr(rendered["mode"])
        self.preview_status.setText(tr(source, **rendered))

    @Slot()
    def _retranslate_ui(self):
        """原地更新文案而不重建队列或丢弃未保存的编辑内容"""
        for code, action in self.language_actions.items():
            action.setChecked(code == language())
        self._reload_presets(self.settings.template_name)
        self._show_template()
        self._update_labels()
        self.lock_button.setText(tr("编辑配置" if self._locked else "锁定配置"))
        if not self._current_data:
            self.canvas_name.setText(tr("预览"))
        self._set_status(self._status_source, **self._status_values)
        self._set_preview_status(self._preview_source, **self._preview_values)
        self.preview_status.setToolTip(localize_error(self._preview_error))
        self._summary_changed(self._counts)
        for dialog, editor in self._error_dialogs:
            dialog.setWindowTitle(tr("处理详情"))
            editor.setPlainText(self._error_details())

    def _error_details(self):
        return "\n".join(tr(error[0], **error[1]) if isinstance(error, tuple) else localize_error(error)
                         for error in self._errors) if self._errors else tr("暂无错误")

    def _choose_color(self, field):
        color = QColorDialog.getColor(QColor(getattr(self.settings, field)), self, tr("选择颜色"),
                                      QColorDialog.ColorDialogOption.DontUseNativeDialog)
        if color.isValid():
            self.settings = replace(self.settings, **{field: color.name()})
            self._style_changed()

    def _set_locked(self, locked):
        self._locked = locked
        self.lock_action.blockSignals(True)
        self.lock_button.blockSignals(True)
        self.lock_action.setChecked(locked)
        self.lock_button.setChecked(locked)
        self.lock_button.setText(tr("编辑配置" if locked else "锁定配置"))
        self.lock_action.blockSignals(False)
        self.lock_button.blockSignals(False)
        self.config_body.setEnabled(not locked)
        self.input_input.setReadOnly(locked)
        self.output_input.setReadOnly(locked)

    def _save_config(self):
        """显式保存同时更新原版共享配置和桌面个人配置"""
        try:
            save_workspace_settings(self.settings)
            self._saved, self._dirty = deepcopy(replace(self.settings, template_source="")), False
            self._update_labels()
            self._update_actions()
            self._set_status("配置已保存")
            return True
        except Exception as exc:
            self._record_errors("保存配置失败", [str(exc)])
            return False

    def _reset_config(self):
        old_directories = (self.settings.input_dir, self.settings.output_dir)
        overrides = deepcopy(self.settings.metadata_overrides)
        self.settings = deepcopy(self._saved)
        self.settings.metadata_overrides = overrides
        self._dirty = False
        self._restore_controls()
        self._schedule_preview()
        self._update_actions()
        if old_directories != (self.settings.input_dir, self.settings.output_dir):
            for kind, folder in (("import", self.settings.input_dir), ("output", self.settings.output_dir)):
                if folder and Path(folder).is_dir():
                    self._scan_directory(kind, folder)
                else:
                    self.files.begin_scan(kind, None)

    def _pick_photos(self):
        if self._exporting or self._closing:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr("添加照片"), self.settings.input_dir,
                                              tr("照片 (*.jpg *.jpeg *.png *.heic *.heif)"),
                                              options=QFileDialog.Option.DontUseNativeDialog)
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
        self._settings_changed()
        self._scan_directory(kind, folder)

    def _scan_directory(self, kind, folder):
        """刷新目录前取消旧扫描以丢弃迟到的文件信号"""
        for task in self._tasks.values():
            if task.kind == kind:
                task.cancel.set()
        self.files.begin_scan(kind, folder)
        if self._current_kind == kind:
            self._current_data = None
            self._generation += 1
            self.photo_view.set_image(None)
            self.canvas_name.setText(tr("预览"))
        self._start_task(kind, paths=[Path(folder)], settings=replace(self.settings))
        self._update_actions()

    def _refresh_directories(self):
        self._load_directories()

    def add_paths(self, paths):
        """手动添加与拖入均在后台解码缩略图"""
        if self._exporting or self._closing:
            return
        accepted = [Path(path) for path in paths if Path(path).is_dir() or Path(path).suffix.lower() in SUPPORTED_SUFFIXES]
        known = self.files.items["import"]
        accepted = [path for path in accepted if os.path.normcase(str(path.resolve())) not in known]
        if accepted:
            self._start_task("import", paths=accepted, settings=replace(self.settings))
            self._update_actions()

    def _clear_photos(self):
        """清空输入队列并取消仍在进行的目录扫描"""
        if self._exporting:
            return
        for task in self._tasks.values():
            if task.kind == "import":
                task.cancel.set()
        self.files.begin_scan("import", self.files.roots["import"])
        if self._current_kind == "import":
            self._file_selected("import", None)
        self._set_status("输入队列已清空")

    def _remove_photo(self):
        if not self._exporting:
            self.files.remove_current()

    @Slot(int, object)
    def _import_item(self, token, data):
        task = next((task for (kind, key), task in self._tasks.items() if key == token and kind in ("import", "output")), None)
        if self._closing or not task or task.cancel.is_set():
            return
        self.files.add_file(task.kind, data)

    @Slot(str, object)
    def _file_selected(self, kind, data):
        self._current_kind, self._current_data = kind, data
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
        self._set_preview_status("{width} × {height} · {mode}", width=width, height=height,
                                 mode="输出文件" if kind == "output" else "输入文件")
        self._update_actions()
        self._schedule_preview()
        self._refresh_footer_examples()

    def _current_path(self):
        return self._current_data[0] if self._current_data else None

    def _original_toggled(self, checked):
        self.original_action.setChecked(checked)
        self._schedule_preview()

    def _view_changed(self, checked):
        self.original_toggle.setChecked(checked)

    def _schedule_preview(self):
        # 先递增代次以阻止去抖等待期间旧图片覆盖当前选择
        self._generation += 1
        self._pending = True
        self.timer.start()

    def _queue_selection_changed(self):
        """导入期间不反复推迟首张预览，完整批次在扫描结束后刷新"""
        if not any(kind == "import" for kind, _ in self._tasks):
            self._schedule_preview()

    def _render_preview(self):
        path = self._current_path()
        if self._closing or self._rendering or not self._pending or not path:
            return
        self._pending, self._rendering = False, True
        self._set_preview_status("正在生成预览…")
        self._preview_error = ""
        self.preview_status.setToolTip("")
        # 输出树始终读取已有成品以免重复添加水印
        kind = "original" if self._current_kind == "output" or self.original_toggle.isChecked() else "preview"
        # 与实际导出共用勾选文件快照，支持模板中的跨照片处理
        selected = tuple(str(item) for item in self.files.selected_paths())
        self._start_task(kind, token=self._generation, paths=[path],
                         settings=replace(self.settings, input_files=selected))

    def _start_task(self, kind, token=None, **kwargs):
        # 深拷贝会话元数据以免编辑窗口修改正在处理的批次
        if kwargs.get("settings") is not None:
            kwargs["settings"] = deepcopy(kwargs["settings"])
        self._serial += 1
        task = ImageTask(kind, self._serial if token is None else token, **kwargs)
        self._connect_task(task)

    def _connect_task(self, task):
        """后台任务共用信号连接和安全关闭登记"""
        task.signals.result.connect(self._task_result)
        task.signals.error.connect(self._task_error)
        task.signals.finished.connect(self._task_finished)
        task.signals.item.connect(self._import_item)
        task.signals.progress.connect(self._task_progress)
        task.signals.summary.connect(self._summary_changed)
        self._tasks[(task.kind, task.token)] = task
        self.pool.start(task)

    @Slot(str, int, object)
    def _task_result(self, kind, token, result):
        if self._closing:
            return
        if kind in ("preview", "original") and token == self._generation:
            self.photo_view.set_image(result)
            _, width, height = self._current_data
            mode = "输出文件" if self._current_kind == "output" else "原图" if kind == "original" else "水印预览"
            self._set_preview_status("{mode} · {width} × {height} · 适应窗口", mode=mode, width=width, height=height)
        elif kind in ("import", "output"):
            self._set_status("目录读取完成")
            if kind == "import":
                self._schedule_preview()
            if result:
                self._record_errors("部分照片无法读取", result)
        elif kind == "export":
            self._summary_changed({key: len(result[key]) for key in ("completed", "errors", "skipped")})
            self._errors = result["errors"] + [("已跳过同名文件：{path}", {"path": path}) for path in result["skipped"]]
            self.error_button.setEnabled(bool(self._errors))
            self._set_status("处理已取消" if result["cancelled"] else "处理完成")
            if self._last_output and self._last_output.is_dir():
                self._scan_directory("output", self._last_output)
        elif kind == "footer_metadata":
            path, modified, metadata = result
            from core.metadata import metadata_key
            self._footer_metadata[(metadata_key(path), modified)] = metadata
            while len(self._footer_metadata) > 32:
                self._footer_metadata.pop(next(iter(self._footer_metadata)))
            self._refresh_footer_examples(request=False)

    @Slot(str, int, str)
    def _task_error(self, kind, token, message):
        if self._closing:
            return
        if kind in ("preview", "original"):
            if token == self._generation:
                self._set_preview_status("预览失败，详情见状态栏")
                self._preview_error = message
                self.preview_status.setToolTip(localize_error(message))
                self._record_errors("预览失败", [message])
        else:
            self._record_errors("处理失败", [message])

    @Slot(str, int)
    def _task_finished(self, kind, token):
        self._tasks.pop((kind, token), None)
        if kind in ("preview", "original"):
            self._rendering = False
            if self._pending and not self.timer.isActive():
                self._render_preview()
        elif kind == "export":
            self._set_exporting(False)
        self._update_actions()
        if self._closing and not self._tasks:
            QTimer.singleShot(0, self.close)

    @Slot(int, int, str)
    def _task_progress(self, current, total, name):
        if self._closing:
            return
        if total:
            self.progress.setValue(current)
            self._set_status("处理 {current}/{total} · {name}", current=current, total=total, name=name)
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
        self.export_action.setEnabled(bool(self.files._selected_count and self.presets and not importing and not busy))
        self.cancel_action.setEnabled(self._exporting and not self._closing)
        for action in (self.add_action, self.directory_action, self.refresh_action, self.new_template_action,
                       self.copy_template_action, self.edit_template_action, self.footer_action, self.lock_action):
            action.setEnabled(not busy)
        self.metadata_action.setEnabled(bool(self._current_path()) and not busy)
        self.metadata_batch_action.setEnabled(bool(self.files._selected_count) and not busy)
        self.save_action.setEnabled(self._dirty and not busy)
        self.reset_action.setEnabled(self._dirty and not busy)
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(self._dirty and not busy)
            self.reset_button.setEnabled(self._dirty and not busy)

    def _choose_output(self):
        folder = QFileDialog.getExistingDirectory(self, tr("选择输出目录"), self.settings.output_dir,
                                                  QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.output_input.setText(folder)
            self._settings_changed()
        return folder

    def _export(self):
        """固定本轮勾选和设置快照后交由后台逐张处理"""
        paths = self.files.selected_paths()
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
        self._set_status("处理 {current}/{total} · {name}", current=0, total=len(paths), name="")
        self._start_task("export", paths=paths,
                         settings=replace(self.settings, input_files=tuple(str(path) for path in paths)),
                         output=self._last_output)

    def _set_exporting(self, active):
        self._exporting = active
        self.inspector.setEnabled(not active)
        self.files.setEnabled(not active)
        for editor in self._editors:
            editor.setEnabled(not active)
        for editor in self._metadata_editors:
            editor.setEnabled(not active)
        self.progress.setVisible(active)
        self._update_actions()

    def _cancel_export(self):
        for task in self._tasks.values():
            if task.kind == "export":
                task.cancel.set()
        self.cancel_action.setEnabled(False)
        self._set_status("当前照片完成后停止")

    def _open_output(self):
        directory = self._last_output or (Path(self.settings.output_dir) if self.settings.output_dir else None)
        if directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _edit_metadata(self):
        """默认编辑当前照片，批量操作通过独立菜单明确选择"""
        current = self._current_path()
        if current:
            self._open_metadata_editor([current], current)
        else:
            self._set_status("尚未选择可编辑的照片")

    def _edit_checked_metadata(self):
        paths = self.files.selected_paths()
        if paths:
            current = self._current_path()
            self._open_metadata_editor(paths, current if current in paths else paths[0])

    def _open_metadata_editor(self, paths, current):
        from .metadata_editor import MetadataEditor
        if self._exporting or self._closing:
            return
        # 同时仅保留一个编辑会话，避免旧的完整映射覆盖较新的修改
        if self._metadata_editors:
            editor = self._metadata_editors[0]
            editor.show()
            editor.raise_()
            editor.activateWindow()
            return
        editor = MetadataEditor(self, paths=paths, current=current, overrides=deepcopy(self.settings.metadata_overrides))
        editor.applied.connect(self._metadata_applied)
        editor.finished.connect(lambda result, window=editor: self._metadata_editor_closed(window))
        self._metadata_editors.append(editor)
        editor.show()

    @Slot(dict)
    def _metadata_applied(self, overrides):
        """替换会话覆盖值并使进行中的预览失效"""
        from core.metadata import metadata_key
        normalized = {metadata_key(Path(path)): deepcopy(changes) for path, changes in overrides.items()}
        self.settings = replace(self.settings, metadata_overrides=normalized)
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
        result = {"metadata": None, "filename": path.stem if path else "", "file_dir": path.parent.as_posix() if path else ""}
        if path:
            try:
                values = self._footer_metadata.get((metadata_key(path), path.stat().st_mtime_ns))
            except OSError:
                values = None
            overrides = self.settings.metadata_overrides.get(metadata_key(path), {})
            if values is not None:
                try:
                    result["metadata"] = merge_overrides(values, overrides)
                except ValueError:
                    result["metadata"] = None
        return result

    def _refresh_footer_examples(self, request=True):
        """异步刷新示例，不重载或改写正在组合的内容"""
        panels = [editor.panel for editor in self._editors if hasattr(editor, "panel")]
        if self._active_wizard is not None:
            panels.append(self._active_wizard.footer_panel)
        if not panels:
            return
        context = self._template_context()
        for panel in panels:
            panel.set_metadata(**context)
        for editor in self._editors:
            if hasattr(editor, 'metadata_button'):
                editor.metadata_button.setEnabled(bool(self._current_path()) and not self._exporting)
        path = self._current_path()
        pending = any(task.kind == "footer_metadata" and task.paths[0] == path for task in self._tasks.values())
        if request and path and context["metadata"] is None and not pending and not self._closing:
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
        self._editors.append(editor)
        editor.show()
        self._refresh_footer_examples()
        return editor

    def _make_template_editor(self, name, source, visual=False, is_new=False, saved_source=None):
        if saved_source is None and not is_new:
            saved_source = read_template(name)
        if visual:
            from .footer_editor import FooterEditor
            editor = FooterEditor(self, name=name, source=source, saved_source=saved_source, **self._template_context())
        else:
            editor = TemplateEditor(self, name=name, source=source, is_new=is_new, saved_source=saved_source)
        return self._track_template_editor(editor)

    def _open_editor(self, name, source, is_new=False):
        editor = next((item for item in self._editors if item.name == name), None)
        if editor is not None:
            if isinstance(editor, TemplateEditor):
                editor.show()
                editor.raise_()
                editor.activateWindow()
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
        for target, owner in list(self._draft_owners.items()):
            if owner is previous:
                self._draft_owners[target] = editor
        previous._handoff = True
        previous.close_for_handoff()
        self._preview_draft(editor, source)
        return editor

    def _edit_footer(self):
        from .footer_editor import FooterEditor
        name = self.settings.template_name
        previous = next((item for item in self._editors if item.name == name), None)
        if previous is not None:
            if isinstance(previous, FooterEditor):
                previous.show()
                previous.raise_()
                previous.activateWindow()
            elif previous.check_format():
                self._handoff_editor(previous, previous.source(), visual=True)
            return
        try:
            self._make_template_editor(name, self._drafts.get(name) or read_template(name), visual=True)
        except Exception as exc:
            self._record_errors("无法打开组合编辑器", [str(exc)])

    def _new_template(self):
        from .template_wizard import TemplateWizard
        active = next((editor for editor in self._editors if editor.name == self.settings.template_name), None)
        try:
            current_source = active.source() if active else self._drafts.get(self.settings.template_name)
        except Exception as exc:
            self._record_errors("无法读取当前组合", [str(exc)])
            return
        wizard = TemplateWizard(self, current_template=self.settings.template_name, current_source=current_source,
                                **self._template_context())
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
        name = self.settings.template_name
        try:
            active = next((editor for editor in self._editors if editor.name == name), None)
            source = active.source() if active else self._drafts.get(name) or read_template(name)
            self._open_editor(name + tr("_副本"), source, True)
        except Exception as exc:
            self._record_errors("读取模板失败", [str(exc)])

    def _edit_template(self):
        name = self.settings.template_name
        for editor in self._editors:
            if editor.name == name:
                if isinstance(editor, TemplateEditor):
                    editor.show()
                    editor.raise_()
                    editor.activateWindow()
                else:
                    try:
                        self._handoff_editor(editor, editor.source(), visual=False)
                    except Exception as exc:
                        self._record_errors("无法切换编辑器", [str(exc)])
                return
        try:
            self._open_editor(name, self._drafts.get(name) or read_template(name))
        except Exception as exc:
            self._record_errors("读取模板失败", [str(exc)])

    def _preview_draft(self, editor, source):
        """未保存的源码只作用于当前会话预览和处理"""
        name = editor.name
        target = name if self.template_combo.findData(name) >= 0 else self.settings.template_name
        editor.preview_target = target
        self._drafts[target] = source
        self._draft_owners[target] = editor
        if target == self.settings.template_name:
            self.settings = replace(self.settings, template_source=source, use_template_styles=True)
            self.template_styles_check.setChecked(True)
            self._update_labels()
            self._schedule_preview()
            self._set_status("模板草稿已应用，尚未保存到模板文件")

    def _template_saved(self, name, owner=None):
        if self._draft_owners.get(name) in (None, owner):
            self._drafts.pop(name, None)
            self._draft_owners.pop(name, None)
        self._reload_presets(name)
        self.settings = replace(self.settings, template_name=name, template_source=self._drafts.get(name, ""))
        self.template_styles_check.setChecked(True)
        self._show_template()
        self._settings_changed()

    def _editor_saved(self, editor, name):
        for target, owner in list(self._draft_owners.items()):
            if owner is editor and target != name:
                self._drafts.pop(target, None)
                self._draft_owners.pop(target, None)
        editor.preview_target = name
        self._template_saved(name, owner=editor)

    def _editor_closed(self, editor):
        if editor in self._editors:
            self._editors.remove(editor)
        if not getattr(editor, "_handoff", False):
            for target, owner in list(self._draft_owners.items()):
                if owner is editor:
                    self._drafts.pop(target, None)
                    self._draft_owners.pop(target, None)
                    if target == self.settings.template_name:
                        self.settings = replace(self.settings, template_source="")
                        self._schedule_preview()
        editor.deleteLater()

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
                        QTimer.singleShot(0, self._resume_close_after_metadata)
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
        QTimer.singleShot(0, self.close)
