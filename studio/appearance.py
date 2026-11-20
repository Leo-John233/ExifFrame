"""主题与启动画面的轻量外观设置"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImageReader, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from core.runtime_paths import resource_path
from core.splash_settings import (SplashSettings, load_splash_settings,
                                  resolve_splash_image, save_splash_settings, validate_splash_image)
from .controls import CameraRawSlider
from .i18n import bind, localize_error, tr, translator
from .path_memory import last_directory, remember_directory
from .theme import set_theme, theme, theme_notifier


class _BackgroundThumbnail(QLabel):
    """对选定背景显示等比填充的紧凑缩略图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('splashBackgroundThumbnail')
        self.setFixedSize(196, 110)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode, self._path = 'follow', None
        theme_notifier.theme_changed.connect(self.update)

    def set_background(self, mode, path):
        self._mode, self._path = mode, path
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        path = resource_path('static/preview.jpg') if self._mode == 'photo' else self._path if self._mode == 'custom' else None
        image = None
        if path:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            native = reader.size()
            if native.isValid():
                reader.setScaledSize(native.scaled(QSize(392, 220), Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
        if image is not None and not image.isNull():
            scale = max(self.width() / image.width(), self.height() / image.height())
            width, height = self.width() / scale, self.height() / scale
            source = QRectF((image.width() - width) / 2, (image.height() - height) / 2, width, height)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(QRectF(self.rect()), image, source)
        else:
            dark = theme() == 'dark'
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0, QColor('#363636' if dark else '#E5E5E5'))
            gradient.setColorAt(1, QColor('#111111' if dark else '#BFBFBF'))
            painter.fillRect(self.rect(), gradient)
            painter.setPen(QPen(QColor('#626262' if dark else '#A0A0A0'), 1))
            for radius in (28, 42, 56):
                painter.drawEllipse(self.rect().center(), radius, radius)
            if self._mode == 'custom':
                painter.setPen(QColor('#E7E7E7' if dark else '#333333'))
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr('图片不可用'))
        painter.setPen(QPen(QColor('#6A6A6A' if theme() == 'dark' else '#AAAAAA'), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class AppearanceDialog(QDialog):
    """不改变照片设置的主题与启动画面选项"""

    def __init__(self, parent=None):
        super().__init__(parent)
        bind(self, '外观与主题设置', 'setWindowTitle')
        self.resize(570, 555)
        self.setMinimumWidth(500)
        self._loaded = load_splash_settings()
        self._image_path = self._loaded.image_path
        self._preview = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(11)
        heading = bind(QLabel(), '外观与主题设置')
        heading.setStyleSheet('font-size: 18px; font-weight: 600;')
        outer.addWidget(heading)
        description = bind(QLabel(), '选择工作台主题并自定义启动画面')
        description.setObjectName('secondaryText')
        outer.addWidget(description)
        outer.addSpacing(4)

        theme_row = QHBoxLayout()
        theme_row.addWidget(bind(QLabel(), '主题'))
        theme_row.addStretch()
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons = {}
        for code, title in (('dark', '深色'), ('light', '浅色')):
            button = bind(QToolButton(), title)
            button.setCheckable(True)
            button.setMinimumWidth(66)
            button.setChecked(theme() == code)
            button.clicked.connect(lambda checked=False, value=code: set_theme(value))
            self.theme_group.addButton(button)
            self.theme_buttons[code] = button
            theme_row.addWidget(button)
        theme_notifier.theme_changed.connect(self._theme_changed)
        outer.addLayout(theme_row)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(divider)

        title = bind(QLabel(), '启动画面')
        title.setStyleSheet('font-weight: 600;')
        outer.addWidget(title)
        self.enabled = bind(QCheckBox(), '启用启动画面')
        self.enabled.setChecked(self._loaded.enabled)
        outer.addWidget(self.enabled)

        background_row = QHBoxLayout()
        background_row.setSpacing(12)
        self.thumbnail = _BackgroundThumbnail()
        background_row.addWidget(self.thumbnail, alignment=Qt.AlignmentFlag.AlignTop)
        choices = QVBoxLayout()
        choices.setSpacing(7)
        choices.addWidget(bind(QLabel(), '启动背景'))
        self.background = QComboBox()
        self.background.setMinimumWidth(0)
        self.background.currentIndexChanged.connect(self._background_changed)
        choices.addWidget(self.background)
        self.choose_button = bind(QPushButton(), '自定义图片…')
        self.choose_button.clicked.connect(self._choose_image)
        choices.addWidget(self.choose_button)
        self.restore_button = bind(QPushButton(), '恢复默认背景')
        self.restore_button.clicked.connect(self._restore_background)
        choices.addWidget(self.restore_button)
        choices.addStretch()
        background_row.addLayout(choices, 1)
        outer.addLayout(background_row)

        self.opacity = CameraRawSlider(0, 100, 40, suffix='%')
        bind(self.opacity, '底部文字遮罩暗度')
        self.opacity.setValue(self._loaded.overlay_opacity)
        outer.addWidget(self.opacity)
        flags = QHBoxLayout()
        self.show_version = bind(QCheckBox(), '显示版本号')
        self.show_status = bind(QCheckBox(), '显示加载文字')
        self.show_version.setChecked(self._loaded.show_version)
        self.show_status.setChecked(self._loaded.show_status)
        flags.addWidget(self.show_version)
        flags.addWidget(self.show_status)
        flags.addStretch()
        outer.addLayout(flags)
        timing = QHBoxLayout()
        timing.addWidget(bind(QLabel(), '最短展示时长'))
        timing.addStretch()
        self.minimum = QComboBox()
        timing.addWidget(self.minimum)
        outer.addLayout(timing)
        self.preview_button = bind(QPushButton(), '立即预览启动画面')
        self.preview_button.clicked.connect(self._preview_splash)
        outer.addWidget(self.preview_button)
        outer.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

        translator.language_changed.connect(self._retranslate)
        self._retranslate(initial=True)

    def _theme_changed(self, code):
        self.theme_buttons[code].setChecked(True)
        self.thumbnail.update()

    def _retranslate(self, initial=False):
        mode = self._loaded.background_mode if initial else self.background.currentData()
        minimum = self._loaded.minimum_ms if initial else self.minimum.currentData()
        self.background.blockSignals(True)
        self.background.clear()
        for title, value in (('跟随主题（暗房深色 / 极简浅色）', 'follow'),
                             ('精选摄影背景', 'photo'), ('自定义图片', 'custom')):
            self.background.addItem(tr(title), value)
        self.background.setCurrentIndex(max(0, self.background.findData(mode)))
        self.background.blockSignals(False)
        self.minimum.clear()
        for title, value in (('极速（加载完即关）', 0), ('标准（0.8 秒）', 800), ('展示（1.5 秒）', 1500)):
            self.minimum.addItem(tr(title), value)
        self.minimum.setCurrentIndex(max(0, self.minimum.findData(minimum)))
        self._background_changed()

    def _background_changed(self, *_):
        self.thumbnail.set_background(self.background.currentData(), resolve_splash_image(self._image_path))
        self.thumbnail.setToolTip(str(resolve_splash_image(self._image_path) or '') if self.background.currentData() == 'custom' else '')

    def _choose_image(self):
        selected, _ = QFileDialog.getOpenFileName(self, tr('选择启动背景'), last_directory('splash_image'),
                                                  tr('图片 (*.png *.jpg *.jpeg *.webp)'))
        if not selected:
            return
        try:
            validate_splash_image(selected)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr('无法使用启动图片'), localize_error(error))
            return
        self._image_path = str(Path(selected).expanduser().resolve())
        remember_directory('splash_image', Path(selected).expanduser().resolve().parent)
        self.background.setCurrentIndex(self.background.findData('custom'))
        self._background_changed()

    def _restore_background(self):
        self._image_path = ''
        self.background.setCurrentIndex(self.background.findData('follow'))
        self._background_changed()

    def _settings(self):
        return SplashSettings(enabled=self.enabled.isChecked(), background_mode=self.background.currentData(),
                              image_path=self._image_path, overlay_opacity=int(self.opacity.value()),
                              show_version=self.show_version.isChecked(), show_status=self.show_status.isChecked(),
                              minimum_ms=self.minimum.currentData())

    def _preview_splash(self):
        from .splash import preview_splash
        self._preview = preview_splash(self._settings(), parent=self)

    def _save(self):
        try:
            settings = self._settings()
            source = self._image_path if self._image_path and Path(self._image_path).is_absolute() else None
            save_splash_settings(settings, image_source=source)
        except (OSError, ValueError, TypeError) as error:
            QMessageBox.warning(self, tr('无法保存启动画面设置'), localize_error(error))
            return
        self.accept()
