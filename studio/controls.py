"""数值调节及避免滚轮误改的共享控件"""

from __future__ import annotations

from decimal import Decimal
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRect, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractSlider, QAbstractSpinBox, QApplication, QColorDialog, QComboBox, QDateTimeEdit,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QSlider, QStyle,
    QStyleOptionSlider, QToolButton, QVBoxLayout, QWidget,
)

from .i18n import bind, tr, translator


class _SliderLabel(QLabel):
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.parentWidget().reset_to_default()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _ValueEdit(QLineEdit):
    def focusInEvent(self, event):
        super().focusInEvent(event)
        owner = self.parentWidget()
        if owner._special_text and owner.value() == owner.minimum():
            self.selectAll()

    def mousePressEvent(self, event):
        owner = self.parentWidget()
        special = not self.hasFocus() and owner._special_text and owner.value() == owner.minimum()
        super().mousePressEvent(event)
        if special:
            self.selectAll()

    def keyPressEvent(self, event):
        owner = self.parentWidget()
        if event.key() == Qt.Key.Key_Escape:
            owner._cancel_edit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            owner._finish_edit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            owner._adjust(step if event.key() == Qt.Key.Key_Up else -step)
            event.accept()
            return
        super().keyPressEvent(event)


class _SliderTrack(QSlider):
    """点击轨道直接定位，拖动时避免手柄跳动"""

    def __init__(self, parent):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFixedHeight(18)
        self._drag_offset = 0
        self._dragging = False
        self._moved = False
        self.setMouseTracking(True)

    def _option(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return option

    def _handle(self, option):
        width = min(12, self.width())
        start = QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), self.sliderPosition(),
                                              self.width() - width, option.upsideDown)
        return QRect(start, 3, width, 12)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = QApplication.palette().color(QPalette.ColorRole.Window).lightness() < 128
        rail_color = QColor('#3A3A3A' if dark else '#C5C5C5')
        filled_color = QColor('#A3A3A3' if dark else '#686868')
        highlighted = self.underMouse() or self.hasFocus()
        handle_color = QColor(('#E4E4E4' if highlighted else '#C1C1C1') if dark else
                              ('#404040' if highlighted else '#707070'))
        if not self.isEnabled():
            painter.setOpacity(.45)
        handle = self._handle(self._option())
        start = handle.width() / 2
        end = max(start, self.width() - handle.width() / 2)
        center = handle.center().x() + .5
        painter.setPen(QPen(rail_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(start, 9), QPointF(end, 9))
        painter.setPen(QPen(filled_color, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(start, 9), QPointF(center, 9))
        painter.setPen(QPen(QColor('#272727' if dark else '#F6F6F6'), 1))
        painter.setBrush(handle_color)
        painter.drawEllipse(QPointF(center, 9), 4.5, 4.5)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def _set_from_x(self, x):
        option = self._option()
        handle = self._handle(option)
        span = max(1, self.width() - handle.width())
        position = round(x - self._drag_offset - (handle.width() - 1) / 2)
        value = QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), max(0, min(span, position)), span, option.upsideDown)
        if value != self.maximum():
            value = self.minimum() + round((value - self.minimum()) / self.singleStep()) * self.singleStep()
        self.setValue(value)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        owner = self.parentWidget()
        owner._begin()
        handle = self._handle(self._option())
        self._drag_offset = event.position().x() - handle.center().x() if handle.contains(event.position().toPoint()) else 0
        self._dragging = True
        self._moved = False
        self.setSliderDown(True)
        if not handle.contains(event.position().toPoint()):
            self._set_from_x(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._moved = True
            self._set_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            if self._moved:
                self._set_from_x(event.position().x())
            self._dragging = False
            self.setSliderDown(False)
            self.parentWidget()._finish()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self._handle(self._option()).contains(event.position().toPoint())):
            self._dragging = False
            self.setSliderDown(False)
            self.parentWidget().reset_to_default()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Up):
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
                step = -step
            self.parentWidget()._adjust(step)
            event.accept()
            return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown, Qt.Key.Key_Home, Qt.Key.Key_End):
            owner = self.parentWidget()
            owner._begin()
            super().keyPressEvent(event)
            owner._finish()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        event.ignore()


class CameraRawSlider(QWidget):
    """双行滑杆，程序设置和用户交互分别保留 Qt 信号语义"""

    valueChanged = Signal(object)
    liveValueChanged = Signal(object)
    committedValueChanged = Signal(object)
    interaction_started = Signal()
    interaction_finished = Signal()

    def __init__(self, minimum=0, maximum=100, default=0, *, step=1, decimals=None, suffix='', parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if decimals is None:
            decimals = max(0, *(-Decimal(str(value)).as_tuple().exponent
                                for value in (minimum, maximum, default, step)))
        self._decimals = int(decimals)
        self._factor = 10 ** self._decimals
        self._default = default
        self._active = False
        self._changed = False
        self._programmatic = False
        self._editing = False
        self._before = default
        self._special_text = ''
        self.label = _SliderLabel(self)
        self.label.setWordWrap(True)
        self.edit = _ValueEdit(self)
        self.edit.setObjectName('cameraRawValue')
        self.edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit.setFixedWidth(70)
        self.suffix = QLabel(suffix, self)
        self.track = _SliderTrack(self)
        self.track.setObjectName('cameraRawTrack')
        self.track.setRange(self._encode(minimum), self._encode(maximum))
        self.track.setSingleStep(max(1, self._encode(step)))
        self.track.setPageStep(self.track.singleStep() * 10)
        self.track.setValue(self._encode(default))
        self.track.setMinimumWidth(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.label, 1)
        row.addWidget(self.edit)
        if suffix:
            row.addWidget(self.suffix)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addLayout(row)
        layout.addWidget(self.track)
        self.track.valueChanged.connect(self._track_changed)
        self.edit.textEdited.connect(self._edit_changed)
        self.edit.editingFinished.connect(self._finish_edit)
        self._sync_text()

    def setText(self, text):
        self.label.setText(text)
        self.edit.setAccessibleName(text)
        self.track.setAccessibleName(text)

    def setSpecialValueText(self, text):
        self._special_text = text
        if not self._editing:
            self._sync_text()

    def setValue(self, value):
        value = max(self.minimum(), min(self.maximum(), value))
        self._programmatic = True
        try:
            self.track.setValue(self._encode(value))
        finally:
            self._programmatic = False
        if not self._editing:
            self._sync_text()

    def value(self):
        return self._decode(self.track.value())

    def minimum(self):
        return self._decode(self.track.minimum())

    def maximum(self):
        return self._decode(self.track.maximum())

    def setRange(self, minimum, maximum):
        self._programmatic = True
        try:
            self.track.setRange(self._encode(minimum), self._encode(maximum))
        finally:
            self._programmatic = False
        if not self._editing:
            self._sync_text()

    def setSingleStep(self, step):
        self.track.setSingleStep(max(1, self._encode(step)))
        self.track.setPageStep(self.track.singleStep() * 10)

    def singleStep(self):
        return self._decode(self.track.singleStep())

    def _encode(self, value):
        return round(value * self._factor)

    def _decode(self, value):
        return value if not self._decimals else value / self._factor

    def _sync_text(self):
        value = self.value()
        special = bool(self._special_text and value == self.minimum())
        text = (self._special_text if special else
                f'{value:.{self._decimals}f}' if self._decimals else str(value))
        self.edit.setFixedWidth(max(70, min(150, self.edit.fontMetrics().horizontalAdvance(text) + 16)) if special else 70)
        self.edit.setToolTip(text if special else '')
        self.suffix.setVisible(bool(self.suffix.text()) and not special)
        if self.edit.text() != text:
            with QSignalBlocker(self.edit):
                self.edit.setText(text)

    def _track_changed(self, value):
        value = self._decode(value)
        if not self._editing:
            self._sync_text()
        if self._active and not self._programmatic:
            self._changed = True
            self.liveValueChanged.emit(value)
        self.valueChanged.emit(value)

    def _begin(self):
        if not self._active:
            self._before = self.value()
            self._changed = False
            self._active = True
            self.interaction_started.emit()

    def _finish(self, *, commit=True):
        if self._active:
            self._active = False
            if commit and self._changed:
                self.committedValueChanged.emit(self.value())
            self.interaction_finished.emit()

    def _entered_value(self, text):
        value = float(text.strip()) if self._decimals else int(text.strip())
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError
        return max(self.minimum(), min(self.maximum(), value))

    def _edit_changed(self, text):
        self._begin()
        self._editing = True
        try:
            value = self._entered_value(text)
        except ValueError:
            return
        self.track.setValue(self._encode(value))

    def _finish_edit(self):
        if not self._editing:
            return
        try:
            self._entered_value(self.edit.text())
        except ValueError:
            self._cancel_edit()
            return
        self._editing = False
        self._sync_text()
        self._finish()

    def _cancel_edit(self):
        if self._editing:
            self.track.setValue(self._encode(self._before))
            self._editing = False
            self._sync_text()
            self._finish(commit=False)

    def _adjust(self, step):
        self._begin()
        self.track.setValue(self.track.value() + step * self.track.singleStep())
        self._editing = False
        self._sync_text()
        self._finish()

    def reset_to_default(self):
        self._begin()
        self._editing = False
        self.track.setValue(self._encode(self._default))
        self._finish()


def _display_color(value):
    """按渲染管线的 RRGGBBAA 顺序读取透明色"""
    text = str(value or '')
    if len(text) == 9 and text.startswith('#'):
        try:
            return QColor(*(int(text[i:i + 2], 16) for i in (1, 3, 5, 7)))
        except ValueError:
            pass
    return QColor(text)


def _color_text(color):
    result = color.name(QColor.NameFormat.HexRgb).upper()
    return result if color.alpha() == 255 else f'{result}{color.alpha():02X}'


class _ColorSwatch(QToolButton):
    """在透明棋盘上绘制可点击的圆角色块"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('colorSwatch')
        self.setFixedSize(32, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color = QColor()

    def set_color(self, color):
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, 4, 4)
        painter.save()
        painter.setClipPath(path)
        tile = 5
        for y in range(0, self.height(), tile):
            for x in range(0, self.width(), tile):
                color = '#ECECEC' if (x // tile + y // tile) % 2 == 0 else '#A8A8A8'
                painter.fillRect(x, y, tile, tile, QColor(color))
        if self._color.isValid():
            painter.fillRect(rect, self._color)
        painter.restore()
        border = self.palette().color(QPalette.ColorRole.Text)
        border.setAlpha(190 if self.underMouse() or self.hasFocus() else 110)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


class ColorProperty(QWidget):
    """颜色、实际值及恢复模板默认的紧凑属性行"""

    color_changed = Signal(str)
    reset_requested = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._value = '#FFFFFF'
        self._inherited = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.label = QLabel()
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bind(self.label, title)
        self.swatch = _ColorSwatch()
        bind(self.swatch, '选择颜色', 'setToolTip')
        self.swatch.clicked.connect(self._choose_color)
        self.value_label = QLabel()
        self.value_label.setObjectName('colorPropertyValue')
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.reset_button = QToolButton()
        self.reset_button.setObjectName('propertyReset')
        self.reset_button.setText('↶')
        bind(self.reset_button, '重置为模板默认', 'setToolTip')
        self.reset_button.clicked.connect(self.reset_requested)
        row.addWidget(self.label, 1)
        row.addWidget(self.swatch)
        row.addWidget(self.value_label)
        row.addWidget(self.reset_button)
        translator.language_changed.connect(self._update_display)
        self._update_display()

    def set_color(self, value, inherited=False):
        self._value = str(value or '')
        self._inherited = bool(inherited)
        self._update_display()

    def _update_display(self):
        color = _display_color(self._value)
        value = _color_text(color) if color.isValid() else self._value
        self.swatch.set_color(color)
        self.value_label.setText(tr('沿用模板 · {color}', color=value) if self._inherited else value)
        self.value_label.setToolTip(self.value_label.text())
        self.reset_button.setEnabled(not self._inherited)

    def _choose_color(self):
        initial = _display_color(self._value)
        if not initial.isValid():
            initial = QColor('#FFFFFF')
        selected = QColorDialog.getColor(initial, self, tr('选择颜色'),
                                         QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if selected.isValid():
            self.color_changed.emit(_color_text(selected))


class CollapsibleSection(QWidget):
    """细分隔线、扁平标题与分组重置"""

    reset_requested = Signal()

    def __init__(self, title, *, expanded=True, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        divider = QFrame()
        divider.setObjectName('inspectorSectionDivider')
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.toggle = QToolButton()
        self.toggle.setObjectName('inspectorSection')
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind(self.toggle, title)
        self.reset_button = QToolButton()
        self.reset_button.setObjectName('propertyReset')
        self.reset_button.setText('↶')
        bind(self.reset_button, '重置此分组', 'setToolTip')
        self.reset_button.clicked.connect(self.reset_requested)
        header.addWidget(self.toggle, 1)
        header.addWidget(self.reset_button)
        layout.addLayout(header)
        self.body = QWidget()
        self.body.setVisible(expanded)
        self.toggle.toggled.connect(self.body.setVisible)
        self.toggle.toggled.connect(lambda opened: self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow))
        layout.addWidget(self.body)


class NoWheelEventFilter(QObject):
    """数值和选项控件把滚轮交给最近的外层滚动区"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._forwarding = False

    @staticmethod
    def _wheel_owner(widget):
        popup = QApplication.activePopupWidget()
        if popup is not None and (widget is popup or popup.isAncestorOf(widget)):
            for candidate in QApplication.allWidgets():
                if isinstance(candidate, QComboBox):
                    view = candidate.view()
                    if widget is view or view.isAncestorOf(widget):
                        return candidate
                elif isinstance(candidate, QDateTimeEdit) and candidate.calendarPopup():
                    calendar = candidate.calendarWidget()
                    if widget is calendar or calendar.isAncestorOf(widget):
                        return candidate
        current = widget
        while isinstance(current, QWidget):
            if isinstance(current, (QLineEdit, QAbstractSpinBox, QComboBox, QAbstractSlider)):
                # 滚动条和文件列表保留正常滚动
                if current.inherits('QScrollBar'):
                    return None
                return current
            current = current.parentWidget()
        return None

    def eventFilter(self, watched, event):
        if self._forwarding or event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        owner = self._wheel_owner(watched)
        if owner is None:
            return False
        current = owner.parentWidget()
        while current is not None and not isinstance(current, QScrollArea):
            current = current.parentWidget()
        if current is not None:
            # 弹出菜单打开时 Qt 会阻止向后台视口投递事件
            if QApplication.activePopupWidget() is not None:
                horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                bar = current.horizontalScrollBar() if horizontal else current.verticalScrollBar()
                pixel = event.pixelDelta().x() if horizontal else event.pixelDelta().y()
                angle = event.angleDelta().x() if horizontal else event.angleDelta().y()
                if horizontal and not pixel and not angle:
                    pixel, angle = event.pixelDelta().y(), event.angleDelta().y()
                delta = pixel if pixel else round(angle / 120 * QApplication.wheelScrollLines() * bar.singleStep())
                bar.setValue(bar.value() - delta)
                event.accept()
                return True
            target = current.viewport()
            position = QPointF(target.mapFromGlobal(event.globalPosition().toPoint()))
            forwarded = QWheelEvent(position, event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                                    event.buttons(), event.modifiers(), event.phase(), event.inverted(),
                                    event.source(), event.pointingDevice())
            self._forwarding = True
            try:
                QApplication.sendEvent(target, forwarded)
            finally:
                self._forwarding = False
        event.accept()
        return True


def install_no_wheel_filter(app):
    """应用级过滤器也覆盖之后创建的对话框"""
    if not hasattr(app, '_no_wheel_filter'):
        app._no_wheel_filter = NoWheelEventFilter(app)
        app.installEventFilter(app._no_wheel_filter)
    return app._no_wheel_filter
