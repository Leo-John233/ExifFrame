"""为屏幕内的自定义预设按需生成示例照片缩略图"""

from collections import OrderedDict, deque
from dataclasses import replace
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from core.desktop_service import WatermarkSettings, _template_path, render_photo
from core.sample_photo import example_photo_path
from core.style_pack import _style_path, read_preset_style
from .i18n import tr, translator
from .preview import _task_owner
from .workers import qt_image


class RenderedThumbnail(QWidget):
    """保持实际渲染图比例的缩略预览"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self._failed = False
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setMaximumWidth(260)
        translator.language_changed.connect(self.update)

    def set_image(self, image):
        self._image = QImage(image) if image is not None else QImage()
        self._failed = self._image.isNull()
        self.updateGeometry()
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(40, round(width * (self._image.height() / self._image.width()
                                     if not self._image.isNull() else 2 / 3)))

    def sizeHint(self):
        return QSize(180, self.heightForWidth(180))

    def minimumSizeHint(self):
        return QSize(1, 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._image.isNull():
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             tr('缩略图不可用' if self._failed else '正在生成缩略图…'))
            return
        size = self._image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        rect = self.rect()
        rect.setSize(size)
        rect.moveCenter(self.rect().center())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(rect, self._image)


class _Signals(QObject):
    done = Signal(object, object, bool)


class _Render(QRunnable):
    def __init__(self, key, signals, pause, stopped):
        super().__init__()
        self.key, self.signals = key, signals
        self.pause, self.stopped = pause, stopped

    def run(self):
        cancelled = lambda: self.pause.is_set() or self.stopped.is_set()
        try:
            name = self.key[0]
            settings = replace(WatermarkSettings(template_name=name), **read_preset_style(name))
            photo = example_photo_path()
            if photo is None:
                raise ValueError('sample missing')
            image = render_photo(photo, settings, preview=True, interactive=True, cancelled=cancelled)
            if cancelled():
                self.signals.done.emit(self.key, None, True)
                return
            result = qt_image(image).scaled(320, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
            self.signals.done.emit(self.key, result, False)
        except Exception:
            self.signals.done.emit(self.key, None, cancelled())


class _ThumbnailManager(QObject):
    ready = Signal(object, object)

    def __init__(self, app):
        super().__init__(app)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.pool.setExpiryTimeout(3000)
        self.priority = _task_owner()
        self.stopped = Event()
        self.cache = OrderedDict()
        self.pending = deque()
        self.queued = set()
        self.active = None
        self.invalidated = set()
        self.signals = _Signals(self)
        self.signals.done.connect(self._done)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._run)
        self.priority.background_ready.connect(self._schedule)
        app.aboutToQuit.connect(self.stopped.set)

    @staticmethod
    def key(name):
        try:
            source = _template_path(name).stat()
            try:
                style = _style_path(name).stat()
                style_version = (style.st_mtime_ns, style.st_size)
            except OSError:
                style_version = None
            return (name, source.st_mtime_ns, source.st_size, style_version)
        except (OSError, ValueError):
            return None

    def request(self, name):
        key = self.key(name)
        if key is None:
            return None, None
        if key in self.cache:
            self.cache.move_to_end(key)
            return key, self.cache[key]
        if (key != self.active or key in self.invalidated) and key not in self.queued:
            self.queued.add(key)
            self.pending.append(key)
            self._schedule()
        return key, None

    def invalidate(self, name):
        """丢弃同名模板的缓存及已排队任务"""
        self.cache = OrderedDict((key, value) for key, value in self.cache.items() if key[0] != name)
        self.pending = deque(key for key in self.pending if key[0] != name)
        self.queued = set(self.pending)
        if self.active is not None and self.active[0] == name:
            self.invalidated.add(self.active)

    def _schedule(self):
        if self.pending and self.active is None and not self.stopped.is_set():
            self.timer.start()

    def _run(self):
        if self.active is not None or not self.pending or self.stopped.is_set():
            return
        if self.priority.pause_background.is_set():
            return
        self.active = self.pending.popleft()
        self.queued.discard(self.active)
        self.pool.start(_Render(self.active, self.signals, self.priority.pause_background, self.stopped), -1)

    def _done(self, key, image, interrupted):
        if key != self.active:
            return
        self.active = None
        if key in self.invalidated:
            self.invalidated.discard(key)
            self._schedule()
            return
        if interrupted and not self.stopped.is_set():
            self.pending.appendleft(key)
            self.queued.add(key)
        else:
            self.cache[key] = image
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            self.ready.emit(key, image)
        self._schedule()


def thumbnail_manager():
    app = QApplication.instance()
    if not hasattr(app, '_preset_thumbnails'):
        app._preset_thumbnails = _ThumbnailManager(app)
    return app._preset_thumbnails
