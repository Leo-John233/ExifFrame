"""模板编辑共用的异步实际照片预览"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from threading import Event

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from core.desktop_service import WatermarkSettings, _metadata, list_presets, render_photo
from core.metadata import merge_overrides, metadata_key
from studio.i18n import bind, localize_error, register_translations, tr, translator
from studio.workers import qt_image


register_translations({
    '选择照片': 'Choose photo', '选择预览照片': 'Choose a preview photo',
    '适应': 'Fit', '水印细节': 'Watermark detail',
    '未选择照片': 'No photo selected',
    '选择一张照片查看实际水印效果': 'Choose a photo to see the actual watermark',
    '模板有效后显示照片预览': 'The photo preview appears when the template is valid',
    '等待有效模板': 'Waiting for a valid template',
    '正在更新照片预览…': 'Updating photo preview…',
    '照片预览已更新': 'Photo preview updated',
    '模板有误，保留上次预览：{error}': 'Template error; previous preview retained: {error}',
    '预览失败，保留上次结果：{error}': 'Preview failed; previous result retained: {error}',
    '预览已停止': 'Preview stopped',
    '预览照片：{name}': 'Preview photo: {name}',
    '照片 (*.jpg *.jpeg *.png *.heic *.heif)': 'Photos (*.jpg *.jpeg *.png *.heic *.heif)',
})


class _PreviewSignals(QObject):
    result = Signal(int, object, object, str, str)
    error = Signal(int, object)
    finished = Signal(int)


class _PreviewTask(QRunnable):
    """使用独立设置和像素副本，后台任务不持有界面控件"""

    def __init__(self, job_id, version, path, settings, owner_stopped, signals):
        super().__init__()
        self.job_id, self.version = job_id, version
        self.path, self.settings = path, settings
        self.owner_stopped, self.signals = owner_stopped, signals
        self.cancel = Event()

    def _cancelled(self):
        return self.cancel.is_set() or self.owner_stopped.is_set()

    def run(self):
        try:
            if self._cancelled():
                return
            settings = self.settings
            names = [preset.name for preset in list_presets()]
            # 未保存的新模板只借用现有名称通过校验，实际渲染使用完整草稿
            if settings.template_name not in names and names:
                settings = replace(settings, template_name=names[0])
            path = self.path.resolve()
            photo = render_photo(path, settings, preview=True)
            if self._cancelled():
                return
            metadata = dict(_metadata(str(path), path.stat().st_mtime_ns))
            metadata = merge_overrides(metadata, settings.metadata_overrides.get(metadata_key(path), {}))
            if 'ImageWidth' not in metadata or 'ImageHeight' not in metadata:
                with Image.open(path) as source:
                    metadata.setdefault('ImageWidth', str(source.width))
                    metadata.setdefault('ImageHeight', str(source.height))
            image = qt_image(photo)
            if not self._cancelled():
                self.signals.result.emit(self.version, image, metadata, path.stem, path.parent.as_posix())
        except Exception as error:
            if not self._cancelled():
                self.signals.error.emit(self.version, error.with_traceback(None))
        finally:
            self.signals.finished.emit(self.job_id)


class _PreviewTasks(QObject):
    """任务由应用持有，关闭编辑窗口无需等待当前图像处理"""

    def __init__(self, app):
        super().__init__(app)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.jobs = {}
        self._serial = 0
        app.aboutToQuit.connect(self.cancel_all)

    def create(self, version, path, settings, owner_stopped):
        self._serial += 1
        signals = _PreviewSignals(self)
        job = _PreviewTask(self._serial, version, path, settings, owner_stopped, signals)
        self.jobs[job.job_id] = job
        signals.finished.connect(self._release)
        return job

    @Slot(int)
    def _release(self, job_id):
        job = self.jobs.pop(job_id, None)
        if job is not None:
            job.signals.deleteLater()

    @Slot()
    def cancel_all(self):
        for job in self.jobs.values():
            job.cancel.set()


def _task_owner():
    app = QApplication.instance()
    if not hasattr(app, '_template_preview_tasks'):
        app._template_preview_tasks = _PreviewTasks(app)
    return app._template_preview_tasks


class TemplatePreview(QWidget):
    """只渲染最新有效草稿，错误和语言切换不丢弃已有图像"""

    metadata_ready = Signal(object, str, str)

    def __init__(self, parent=None, photo_path=None, settings=None):
        super().__init__(parent)
        # 延迟导入使源码编辑器也能复用图像视图
        from studio.footer_editor import _ImageView

        self.setObjectName('templatePreviewWidget')
        self._settings = deepcopy(settings if settings is not None else WatermarkSettings())
        self._settings.use_template_styles = True
        self._photo_path = None
        self._source = ''
        self._valid_source = False
        self._version = 0
        self._pending = False
        self._active = None
        self._failed = False
        self._closed = False
        self._stopped = Event()
        self._last_metadata = None
        self._status = ('未选择照片', {})
        self._owner = _task_owner()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self._start_latest)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.view = _ImageView(self)
        self.fit_button = bind(QPushButton(), '适应')
        self.actual_button = QPushButton('100%')
        self.detail_button = bind(QPushButton(), '水印细节')
        self.choose_button = bind(QPushButton(), '选择照片')
        self.choose_button.setObjectName('templatePreviewChoosePhoto')
        self.fit_button.clicked.connect(self.view.fit_photo)
        self.actual_button.clicked.connect(self.view.actual_size)
        self.detail_button.clicked.connect(self.view.footer_detail)
        self.choose_button.clicked.connect(self._choose_photo)
        for button in (self.fit_button, self.actual_button, self.detail_button):
            button.setAutoDefault(False)
            tools.addWidget(button)
        tools.addStretch()
        self.choose_button.setAutoDefault(False)
        layout.addLayout(tools)
        self.filename_label = QLabel()
        self.filename_label.setObjectName('secondaryText')
        self.filename_label.setMinimumWidth(0)
        self.filename_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.filename_label.setTextFormat(Qt.TextFormat.PlainText)
        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        file_row.addWidget(self.filename_label, 1)
        file_row.addWidget(self.choose_button)
        layout.addLayout(file_row)
        self.stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.addStretch()
        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        self.empty_choose = bind(QPushButton(), '选择照片')
        self.empty_choose.setAutoDefault(False)
        self.empty_choose.clicked.connect(self._choose_photo)
        empty_layout.addWidget(self.empty_choose, alignment=Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addStretch()
        self.stack.addWidget(empty)
        self.stack.addWidget(self.view)
        layout.addWidget(self.stack, 1)
        self.status_label = QLabel()
        self.status_label.setObjectName('secondaryText')
        self.status_label.setMinimumWidth(0)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.setMaximumHeight(self.fontMetrics().lineSpacing() * 3)
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status_label)
        translator.language_changed.connect(self._retranslate)
        # 控件销毁也会置取消标记，避免调用方遗漏 shutdown 时继续投递结果
        self.destroyed.connect(lambda *args, stopped=self._stopped: stopped.set())
        self._show_image(None)
        self.set_photo(photo_path)
        self._retranslate()

    @property
    def photo_path(self):
        return self._photo_path

    @property
    def settings(self):
        return deepcopy(replace(self._settings, template_source=self._source, use_template_styles=True))

    def set_source(self, source: str):
        """有效源码去抖渲染，父编辑器对无效源码调用 set_error"""
        if self._closed:
            return
        if not source.strip():
            self.set_error(ValueError('水印模板需要至少一个处理步骤'))
            return
        if source == self._source and self._valid_source and not self._failed:
            return
        self._source = source
        self._valid_source = True
        self._failed = False
        self._invalidate()
        self._request()

    def set_error(self, message):
        """保留已有图像并立即令所有旧结果失效"""
        if self._closed:
            return
        self._invalidate()
        self._valid_source = False
        self._pending = False
        self.timer.stop()
        self._set_status('模板有误，保留上次预览：{error}', error=message)
        self._retranslate()

    def set_photo(self, path):
        """照片仅来自调用方或文件选择器，不使用模板样图"""
        if self._closed:
            return
        selected = Path(path).expanduser().absolute() if path else None
        changed = selected != self._photo_path
        self._photo_path = selected
        self._failed = False
        self._invalidate()
        if changed:
            self._show_image(None)
            self._publish_metadata(None, '', '')
        self._request()
        self._retranslate()

    def _invalidate(self):
        self._version += 1
        if self._active is not None:
            self._active.cancel.set()

    def _request(self):
        self.timer.stop()
        self._pending = bool(self._photo_path and self._valid_source)
        if not self._photo_path:
            self._set_status('未选择照片')
        elif not self._valid_source:
            self._set_status('等待有效模板')
        else:
            self._set_status('正在更新照片预览…')
            self.timer.start()

    @Slot()
    def _start_latest(self):
        if self._closed or not self._pending or self._active is not None:
            return
        if not self._photo_path or not self._valid_source:
            return
        self._pending = False
        snapshot = self.settings
        task = self._owner.create(self._version, self._photo_path, snapshot, self._stopped)
        self._active = task
        task.signals.result.connect(self._result)
        task.signals.error.connect(self._error)
        task.signals.finished.connect(self._finished)
        self._owner.pool.start(task)

    @Slot(int, object, object, str, str)
    def _result(self, version, image, metadata, filename, file_dir):
        if self._closed or version != self._version or not self._valid_source:
            return
        self._failed = False
        self._show_image(image)
        self._set_status('照片预览已更新')
        self._publish_metadata(metadata, filename, file_dir)

    @Slot(int, object)
    def _error(self, version, error):
        if self._closed or version != self._version:
            return
        self._failed = True
        self._set_status('预览失败，保留上次结果：{error}', error=error)

    @Slot(int)
    def _finished(self, job_id):
        if self._active is not None and self._active.job_id == job_id:
            self._active = None
        if not self._closed and self._pending and not self.timer.isActive():
            self._start_latest()

    def _publish_metadata(self, metadata, filename, file_dir):
        value = (metadata, filename, file_dir)
        if value != self._last_metadata:
            self._last_metadata = deepcopy(value)
            self.metadata_ready.emit(deepcopy(metadata), filename, file_dir)

    def _show_image(self, image):
        self.view.set_image(image)
        available = not self.view.photo.pixmap().isNull()
        self.stack.setCurrentIndex(1 if available else 0)
        for button in (self.fit_button, self.actual_button, self.detail_button):
            button.setEnabled(available)

    def _choose_photo(self):
        initial = str(self._photo_path.parent) if self._photo_path else ''
        filename, _ = QFileDialog.getOpenFileName(self, tr('选择预览照片'), initial,
                                                  tr('照片 (*.jpg *.jpeg *.png *.heic *.heif)'),
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if filename:
            self.set_photo(filename)

    def _set_status(self, source, **values):
        self._status = (source, values)
        self._render_status()

    def _render_status(self):
        source, values = self._status
        rendered = {key: localize_error(value) if key == 'error' else value for key, value in values.items()}
        self.status_label.setText(tr(source, **rendered))
        self.status_label.setToolTip(self.status_label.text())

    @Slot()
    def _retranslate(self):
        self.filename_label.setText(tr('预览照片：{name}', name=self._photo_path.name) if self._photo_path else tr('未选择照片'))
        self.filename_label.setToolTip(str(self._photo_path) if self._photo_path else '')
        self.empty_label.setText(tr('选择一张照片查看实际水印效果' if not self._photo_path else '模板有效后显示照片预览'))
        self._render_status()

    def shutdown(self):
        """关闭只取消后续更新，当前处理在后台安全收尾"""
        if self._closed:
            return
        self._closed = True
        self._stopped.set()
        self._version += 1
        self._pending = False
        self.timer.stop()
        if self._active is not None:
            self._active.cancel.set()
        self.choose_button.setEnabled(False)
        self.empty_choose.setEnabled(False)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
