"""在解码阶段缩小模板样图以减少界面等待和内存占用"""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QImageIOHandler, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy


def _rotated(reader):
    return bool(reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90)


@lru_cache(maxsize=32)
def _image_size(source, modified, file_size):
    """只读图片头信息，预先获得显示方向下的比例"""
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    return size.transposed() if _rotated(reader) else size


@lru_cache(maxsize=32)
def _read(source, modified, file_size, width, height):
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        target = QSize(height, width) if _rotated(reader) else QSize(width, height)
        reader.setScaledSize(size.scaled(target, Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


def preview_pixmap(path, width=255, height=110):
    """仅在界面线程使用，文件更新后自动重新读取"""
    source = Path(path).resolve()
    try:
        info = source.stat()
    except OSError:
        return QPixmap()
    return QPixmap(_read(str(source), info.st_mtime_ns, info.st_size, width, height))


class TemplateThumbnail(QLabel):
    """让缩略图与外框共同保持原样图比例"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._source_size = QSize()
        self._version = None
        self._render_key = None
        self._display_pixmap = QPixmap()
        self.setMaximumWidth(260)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setScaledContents(False)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def set_source(self, path):
        self._source = None
        self._source_size = QSize()
        self._version = self._render_key = None
        self._display_pixmap = QPixmap()
        super().clear()
        if path is not None:
            source = Path(path).resolve()
            try:
                info = source.stat()
                version = (str(source), info.st_mtime_ns, info.st_size)
                size = _image_size(*version)
                if size.isValid() and not size.isEmpty():
                    self._source, self._version = source, version
                    self._source_size = QSize(size)
            except OSError:
                pass
        self.updateGeometry()
        self._update_pixmap()
        self.update()

    def setText(self, text):
        self._source = None
        self._source_size = QSize()
        self._version = self._render_key = None
        self._display_pixmap = QPixmap()
        super().setText(text)
        self.updateGeometry()
        self.update()

    def clear(self):
        self.set_source(None)

    def pixmap(self):
        return QPixmap(self._display_pixmap)

    def hasHeightForWidth(self):
        return self._source is not None or super().hasHeightForWidth()

    def heightForWidth(self, width):
        if self._source is None or self._source_size.isEmpty():
            return max(36, super().heightForWidth(width))
        margins = self.contentsMargins()
        inside = max(1, min(width, self.maximumWidth()) - margins.left() - margins.right() - 2 * self.margin())
        height = round(inside * self._source_size.height() / self._source_size.width())
        return max(1, height) + margins.top() + margins.bottom() + 2 * self.margin()

    def sizeHint(self):
        if self._source is not None:
            return QSize(self.maximumWidth(), self.heightForWidth(self.maximumWidth()))
        hint = super().sizeHint()
        return QSize(min(self.maximumWidth(), max(120, hint.width())), max(36, hint.height()))

    def minimumSizeHint(self):
        return QSize(1, 1) if self._source is not None else QSize(1, 36)

    def _update_pixmap(self):
        if self._source is None or self._source_size.isEmpty():
            return
        available = self.contentsRect().size() - QSize(2 * self.margin(), 2 * self.margin())
        if available.width() < 1 or available.height() < 1:
            return
        target = self._source_size.scaled(available, Qt.AspectRatioMode.KeepAspectRatio)
        ratio = self.devicePixelRatioF()
        width, height = max(1, round(target.width() * ratio)), max(1, round(target.height() * ratio))
        key = (self._version, width, height, ratio)
        if key == self._render_key:
            return
        # 缓存物理像素缩略图，控件仍使用逻辑尺寸布局
        pixmap = preview_pixmap(self._source, width, height)
        pixmap.setDevicePixelRatio(ratio)
        self._render_key = key
        self._display_pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._display_pixmap.isNull() or self._source_size.isEmpty():
            return
        available = QRectF(self.contentsRect()).adjusted(self.margin(), self.margin(), -self.margin(), -self.margin())
        if available.isEmpty():
            return
        size = QSizeF(self._source_size).scaled(available.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(available.center())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # 直接绘制完整像素，避免 QLabel 在分数缩放下改写图片比例
        painter.drawPixmap(target, self._display_pixmap, QRectF(self._display_pixmap.rect()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_pixmap()

    def event(self, event):
        result = super().event(event)
        if hasattr(self, '_source') and event.type() in (
                QEvent.Type.DevicePixelRatioChange, QEvent.Type.StyleChange):
            self._render_key = None
            self.updateGeometry()
            self._update_pixmap()
        return result
