"""在隐藏状态恢复工作区，首帧画好后再交给桌面合成器"""

from PySide6.QtCore import QByteArray, QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication

from .path_memory import workspace_preferences
from .theme import apply_native_titlebar


def restore_layout(window):
    preferences = workspace_preferences()
    geometry = preferences.value('window/geometry')
    restored = isinstance(geometry, QByteArray) and window.restoreGeometry(geometry)
    if not restored and QApplication.platformName() == 'windows':
        from PySide6.QtWidgets import QStyle
        available = window.screen().availableGeometry()
        height = max(1, available.height() - window.style().pixelMetric(QStyle.PixelMetric.PM_TitleBarHeight) - 8)
        width = max(1, available.width() - 12)
        window.setMinimumSize(min(window.minimumWidth(), width), min(window.minimumHeight(), height))
        window.resize(min(window.width(), width), min(window.height(), height))
        window.move(available.center() - window.rect().center())
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    state = preferences.value('window/docks')
    if isinstance(state, QByteArray):
        window.restoreState(state, 1)
    if preferences.contains('window/filmstrip'):
        window.files._manual_size = True
        window.files.fold.setChecked(preferences.value('window/filmstrip', True, type=bool))
    splitter = getattr(window, 'preview_splitter', None)
    film_height = preferences.value('window/filmstrip_height', 0, type=int)
    if splitter is not None and 112 <= film_height <= 360:
        window._last_filmstrip_height = film_height
        total = max(400, window.height() - 40)
        if window.files.fold.isChecked():
            splitter.setSizes([max(200, total - film_height), film_height])


def save_layout(window):
    preferences = workspace_preferences()
    if window.screen() is not None:
        preferences.setValue('window/screen', window.screen().name())
    preferences.setValue('window/geometry', window.saveGeometry())
    preferences.setValue('window/docks', window.saveState(1))
    if window.files._manual_size:
        preferences.setValue('window/filmstrip', window.files.fold.isChecked())
    else:
        preferences.remove('window/filmstrip')
    splitter = getattr(window, 'preview_splitter', None)
    if splitter is not None:
        sizes = splitter.sizes()
        if len(sizes) == 2 and window.files.fold.isChecked() and sizes[1] >= 112:
            preferences.setValue('window/filmstrip_height', sizes[1])
        elif hasattr(window, '_last_filmstrip_height'):
            preferences.setValue('window/filmstrip_height', int(window._last_filmstrip_height))
    preferences.sync()


class _FirstPaint(QObject):
    def __init__(self, window, callback, native):
        super().__init__(window)
        self.window = window
        self.callback = callback
        self.native = native
        self._revealed = False
        window.installEventFilter(self)
        self._fallback = QTimer(self)
        self._fallback.setSingleShot(True)
        self._fallback.timeout.connect(self.reveal)
        self._fallback.start(350)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Paint:
            watched.removeEventFilter(self)
            QTimer.singleShot(0, self, self.reveal)
        return False

    def reveal(self):
        if self._revealed:
            return
        self._revealed = True
        self._fallback.stop()
        self.window.removeEventFilter(self)
        if self.native:
            self.window.repaint()
            self.window.setWindowOpacity(1.0)
        self.window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.callback()
        self.deleteLater()


def present_window(window, on_painted):
    """只展示一次，待首轮 Qt 绘制返回再恢复主窗口可见度"""
    window.ensurePolished()
    window.layout().activate()
    window.centralWidget().layout().activate()
    native = QApplication.platformName() == 'windows'
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    if native:
        window.setWindowOpacity(0.0)
        apply_native_titlebar(window)
    window._first_paint = _FirstPaint(window, on_painted, native)
    window.show()
    window.update()