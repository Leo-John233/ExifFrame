"""共用照片画布与缩放交互"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel,
    QSizePolicy, QToolButton, QWidget,
)

from studio.i18n import bind, tr, translator

_SIZE_KEY = 'ExifFrame/FullSize'


def set_image_size(image: QImage, size) -> QImage:
    """在独立图像副本中保存真实成品尺寸"""
    if size and len(size) == 2 and size[0] > 0 and size[1] > 0:
        image.setText(_SIZE_KEY, f'{int(size[0])},{int(size[1])}')
    return image


def image_size(image):
    """读取代理图对应的真实成品尺寸"""
    if isinstance(image, QImage):
        try:
            width, height = (int(value) for value in image.text(_SIZE_KEY).split(','))
            if width > 0 and height > 0:
                return width, height
        except (TypeError, ValueError):
            pass
    return image.width(), image.height()


def is_full_image(image):
    width, height = image_size(image)
    return image.width() >= width and image.height() >= height


class ImageCanvas(QGraphicsView):
    """按真实像素尺寸缩放预览并临时对照原图"""

    zoom_changed = Signal(float)
    original_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.photo = QGraphicsPixmapItem()
        self.original = QGraphicsPixmapItem()
        for item in (self.photo, self.original):
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            self.scene().addItem(item)
        self.original.setVisible(False)
        self._mode = 'fit'
        self._zoom = 1.0
        self._holding_original = False
        self.empty_message = ''
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor('#141516'))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(220, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        bind(self, '滚轮缩放 拖动平移 双击切换适应和100% 按住空格查看原图', 'setToolTip')
        self.hud = QWidget(self.viewport())
        self.hud.setObjectName('canvasHud')
        self.hud.setStyleSheet('QWidget#canvasHud { background: rgba(25, 25, 25, 190); border-radius: 4px; }'
                               'QLabel { color: #E5E5E5; background: transparent; }'
                               'QToolButton { min-height: 18px; padding: 2px 5px; border: 0; background: transparent; }'
                               'QToolButton:hover { background: #48494B; }')
        hud_layout = QHBoxLayout(self.hud)
        hud_layout.setContentsMargins(6, 2, 4, 2)
        hud_layout.setSpacing(4)
        self.zoom_label = QLabel()
        hud_layout.addWidget(self.zoom_label)
        self.hud_fit = bind(QToolButton(), '适应')
        self.hud_fit.clicked.connect(self.fit_photo)
        hud_layout.addWidget(self.hud_fit)
        self.hud_actual = QToolButton()
        self.hud_actual.setText('1:1')
        self.hud_actual.clicked.connect(self.actual_size)
        hud_layout.addWidget(self.hud_actual)
        self.hud.hide()
        translator.language_changed.connect(self._update_hud)

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def comparing_original(self) -> bool:
        return self._holding_original

    def set_empty_message(self, source):
        self.empty_message = source
        self.viewport().update()

    @staticmethod
    def _pixmap(image):
        if isinstance(image, QImage):
            pixmap = QPixmap.fromImage(image)
        elif isinstance(image, QPixmap):
            pixmap = QPixmap(image)
        else:
            return QPixmap()
        pixmap.setDevicePixelRatio(1.0)
        return pixmap

    @staticmethod
    def _set_item(item, image):
        pixmap = ImageCanvas._pixmap(image)
        item.setPixmap(pixmap)
        if pixmap.isNull():
            item.setTransform(QTransform())
            return 0, 0
        width, height = image_size(image)
        item.setTransform(QTransform.fromScale(width / pixmap.width(), height / pixmap.height()))
        return width, height

    def set_image(self, image):
        old_rect = self.sceneRect()
        old_center = self.mapToScene(self.viewport().rect().center())
        width, height = self._set_item(self.photo, image)
        if not width or not height:
            self.original.setPixmap(QPixmap())
            self._holding_original = False
            self.photo.setVisible(True)
            self.original.setVisible(False)
            self.setSceneRect(QRectF())
            self._mode = 'fit'
            self.hud.hide()
            self.viewport().update()
            return
        self.setSceneRect(QRectF(0, 0, width, height))
        self._position_original()
        self._show_comparison()
        if self._mode == 'fit' or old_rect.isEmpty():
            self._fit()
        else:
            self._set_transform(self._zoom)
            if old_rect.width() and old_rect.height():
                self.centerOn(old_center.x() * width / old_rect.width(),
                              old_center.y() * height / old_rect.height())
        self.hud.show()
        self._update_hud()

    def set_original_image(self, image):
        self._set_item(self.original, image)
        self._position_original()
        self._show_comparison()

    def _position_original(self):
        bounds = self.original.mapRectToScene(self.original.boundingRect())
        self.original.setPos((self.sceneRect().width() - bounds.width()) / 2,
                             (self.sceneRect().height() - bounds.height()) / 2)

    def _show_comparison(self):
        show_original = self._holding_original and not self.original.pixmap().isNull()
        self.photo.setVisible(not show_original)
        self.original.setVisible(show_original)
        self._update_hud()

    def _set_transform(self, zoom):
        scale = zoom / self.viewport().devicePixelRatioF()
        self.setTransform(QTransform.fromScale(scale, scale))
        self._zoom = zoom
        self._update_hud()
        self.zoom_changed.emit(zoom)

    def _fit(self):
        bounds = self.sceneRect()
        if bounds.isEmpty():
            return
        viewport = self.viewport().size()
        scale = min(max(1, viewport.width() - 32) / bounds.width(),
                    max(1, viewport.height() - 32) / bounds.height())
        self._set_transform(min(4.0, scale * self.viewport().devicePixelRatioF()))
        self.centerOn(bounds.center())

    def fit_photo(self):
        self._mode = 'fit'
        self._fit()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def actual_size(self):
        if self.photo.pixmap().isNull():
            return
        center = self.mapToScene(self.viewport().rect().center())
        self._mode = 'manual'
        self._set_transform(1.0)
        self.centerOn(center)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def footer_detail(self):
        if self.photo.pixmap().isNull():
            return
        self._mode = 'manual'
        self._set_transform(1.0)
        self.centerOn(self.sceneRect().center().x(), self.sceneRect().bottom())
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def wheelEvent(self, event):
        if self.photo.pixmap().isNull():
            event.ignore()
            return
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if not delta:
            event.ignore()
            return
        target = self._zoom * (2.0 ** (delta / 480.0))
        if self._zoom < 0.1 and delta < 0:
            event.accept()
            return
        target = max(0.1, min(4.0, target))
        position = event.position().toPoint()
        before = self.mapToScene(position)
        self._mode = 'manual'
        self._set_transform(target)
        after = self.mapToScene(position)
        self.centerOn(self.mapToScene(self.viewport().rect().center()) + before - after)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._mode == 'fit' or abs(self._zoom - 1.0) > 0.001:
            self.actual_size()
        else:
            self.fit_photo()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and not self.photo.pixmap().isNull():
            self._holding_original = True
            self.original_requested.emit()
            self._show_comparison()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._holding_original = False
            self._show_comparison()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self._holding_original = False
        self._show_comparison()
        super().focusOutEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._mode == 'fit':
            self._fit()
        self._update_hud()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.photo.pixmap().isNull() and self.empty_message:
            painter = QPainter(self.viewport())
            painter.setPen(QColor('#A6A7A9'))
            painter.drawText(self.viewport().rect().adjusted(20, 20, -20, -20),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, tr(self.empty_message))

    def _update_hud(self):
        if not hasattr(self, 'hud'):
            return
        percent = f'{round(self._zoom * 100)}%'
        self.zoom_label.setText(f'{tr("原图")}  {percent}' if self.original.isVisible() else percent)
        self.hud.adjustSize()
        self.hud.move(max(0, self.viewport().width() - self.hud.width() - 10), 10)
