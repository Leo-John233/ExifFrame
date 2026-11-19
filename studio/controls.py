"""数值调节及避免滚轮误改的共享控件"""

from __future__ import annotations

from decimal import Decimal
import math

from PySide6.QtCore import QEvent, QObject, QPointF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox, QDateTimeEdit,
    QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QSlider, QStyle,
    QStyleOptionSlider, QVBoxLayout, QWidget,
)


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
        self._drag_offset = 0
        self._dragging = False
        self._moved = False

    def _option(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return option

    def _handle(self, option):
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)

    def _set_from_x(self, x):
        option = self._option()
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self)
        handle = self._handle(option)
        span = max(1, groove.width() - handle.width())
        position = round(x - self._drag_offset - groove.x() - handle.width() / 2)
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

    def _edit_changed(self, text):
        self._begin()
        self._editing = True
        try:
            value = float(text.strip()) if self._decimals else int(text.strip())
        except ValueError:
            return
        if math.isfinite(value):
            value = max(self.minimum(), min(self.maximum(), value))
            self.track.setValue(self._encode(value))

    def _finish_edit(self):
        if not self._editing:
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
