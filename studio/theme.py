"""专业摄影工作区的深色控件与系统字体"""

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget


STYLESHEET = """
QWidget { color: #DDDFE2; font-family: 'Microsoft YaHei UI', 'Segoe UI', 'Segoe UI Symbol', 'Cambria Math'; font-size: 12px; }
QMainWindow, QDialog { background: #1E1F21; }
QWidget#filesPanel, QWidget#inspectorPanel { background: #252629; }
QWidget#previewPanel { background: #1B1C1E; }
QMenuBar { background: #1E1F21; border-bottom: 1px solid #353638; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #424242; border-radius: 4px; }
QMenu { background: #252629; border: 1px solid #585858; padding: 4px; }
QMenu::item { padding: 6px 25px; border-radius: 4px; }
QMenu::item:selected { background: #48494B; }
QMenu::item:disabled { color: #7B7B7B; }
QMenu::separator { height: 1px; background: #4A4A4A; margin: 5px 8px; }
QToolBar { background: #252629; border-bottom: 1px solid #353638; spacing: 8px; padding: 8px 12px; }
QToolBar::separator { background: #515151; width: 1px; margin: 6px 4px; }
QToolButton { min-height: 23px; padding: 4px 8px; border: 1px solid transparent; border-radius: 5px; }
QToolButton:hover { background: #424242; border-color: #5F5F5F; }
QToolButton:checked { background: #48494B; border-color: #848484; }
QPushButton { background: #363739; border: 1px solid #4C4D4F; border-radius: 5px; min-height: 22px; padding: 3px 8px; }
QPushButton:hover { background: #494949; border-color: #777777; }
QPushButton:pressed, QToolButton:pressed { background: #333333; border-color: #7F7F7F; }
QPushButton:checked { background: #48494B; border-color: #878787; }
QPushButton:focus, QToolButton:focus { border-color: #8B8C8E; }
QPushButton:disabled, QToolButton:disabled { color: #717274; background: #303030; border-color: #414141; }
QPushButton#primaryButton, QToolButton#primaryButton { background: #515254; border-color: #707173; color: #F1F3F5; }
QPushButton#primaryButton:hover, QToolButton#primaryButton:hover { background: #616264; border-color: #8D8E90; }
QPushButton#primaryButton:pressed, QToolButton#primaryButton:pressed { background: #424345; }
QPushButton#primaryButton:disabled, QToolButton#primaryButton:disabled { background: #2E2F31; color: #727375; border-color: #414244; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit { background: #1B1C1E; border: 1px solid #555555; border-radius: 4px; padding: 3px 6px; selection-background-color: #48494B; selection-color: #FFFFFF; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit { min-height: 22px; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #757575; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #7C7C7C; background: #2E2E2E; border-color: #434343; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus { border: 1px solid #8B8C8E; }
QComboBox QAbstractItemView { background: #303030; border: 1px solid #6E6E6E; selection-background-color: #48494B; color: #DDDFE2; padding: 3px; }
QTreeWidget, QListWidget { background: #202123; border: 1px solid #353638; border-radius: 4px; alternate-background-color: #242527; outline: none; }
QTreeWidget:focus, QListWidget:focus { border-color: #8B8C8E; }
QTreeWidget::item { height: 27px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #48494B; color: #F0F2F4; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #3F3F3F; }
QHeaderView::section { background: #363636; padding: 5px; border: none; border-right: 1px solid #484848; border-bottom: 1px solid #484848; color: #C3C3C3; }
QTabWidget::pane { border: 1px solid #474747; border-radius: 4px; background: #252629; }
QTabBar::tab { background: #282828; color: #AAAAAA; border: 1px solid #424242; border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 6px 21px; margin-right: 2px; }
QTabBar::tab:selected { background: #434343; color: #F0F0F0; border-color: #777777; }
QTabBar::tab:hover { background: #3B3B3B; color: #F0F0F0; }
QGroupBox { border: 1px solid #484848; border-radius: 5px; margin-top: 11px; padding: 9px 7px 5px 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; color: #CBCBCB; }
QCheckBox { spacing: 7px; padding: 2px 0; }
QCheckBox:disabled { color: #7D7D7D; }
QSplitter::handle { background: #171819; }
QSplitter::handle:hover { background: #7B7B7B; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #252629; }
QScrollBar:vertical { background: #272727; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #505153; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #737476; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #272727; height: 10px; }
QScrollBar::handle:horizontal { background: #505153; min-width: 30px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel#secondaryText { color: #A4A4A4; }
QLabel#previewStatus { color: #B4B4B4; background: #141516; padding: 7px 9px; }
QLabel#templatePreview { background: #202020; border: 1px solid #404040; border-radius: 4px; }
QLabel#errorText { color: #B77975; }
QStatusBar { border-top: 1px solid #474747; background: #252629; padding: 4px 12px; }
QStatusBar::item { border: none; }
QProgressBar { max-height: 14px; min-height: 14px; border: 1px solid #636363; border-radius: 3px; background: #252525; text-align: center; }
QProgressBar::chunk { background: #67686A; border-radius: 2px; }
QToolTip { background: #3F3F3F; color: #F0F0F0; border: 1px solid #707173; padding: 5px; }
"""


def apply_native_titlebar(widget: QWidget) -> bool:
    """只调整本应用的 Windows 标题栏，不改变系统外观设置"""
    app = QApplication.instance()
    if (os.name != "nt" or app is None or app.platformName() in {"offscreen", "minimal"}
            or not widget.isWindow() or not widget.windowFlags() & Qt.WindowType.WindowTitleHint):
        return False
    try:
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL("dwmapi", use_last_error=True)
        setter = api.DwmSetWindowAttribute
        setter.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        setter.restype = ctypes.c_long
        handle = wintypes.HWND(int(widget.winId()))
        enabled = ctypes.c_int(1)
        applied = setter(handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0
        if not applied:
            applied = setter(handle, 19, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0
        # Windows 11 可分别设置边界、标题背景和标题文字
        for attribute, color in ((34, "#353638"), (35, "#1E1F21"), (36, "#DADBDD")):
            rgb = QColor(color)
            value = wintypes.DWORD(rgb.red() | rgb.green() << 8 | rgb.blue() << 16)
            applied = setter(handle, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0 or applied
        if applied:
            user = ctypes.WinDLL("user32", use_last_error=True)
            user.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, wintypes.UINT)
            user.SetWindowPos(handle, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
        return applied
    except (OSError, AttributeError, RuntimeError):
        return False


class _NativeTitlebarFilter(QObject):
    """为随后打开的编辑器和对话框应用相同暗色标题栏"""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            apply_native_titlebar(watched)
        return False


def apply_theme(app: QApplication) -> None:
    """统一深色界面并补足无窗口测试环境的字体"""
    if os.name == "nt" and not QFontDatabase.families():
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf", "seguisym.ttf", "cambria.ttc"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
    if hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    # 控件使用中性灰，功能图标保留系统原色和禁用状态
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 9)
    # 显式指定符号回退，中文标签旁的数学字母也能正常显示
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "Segoe UI Symbol", "Cambria Math"])
    app.setFont(font)
    palette = QPalette()
    colors = {"Window": "#1E1F21", "Base": "#1B1C1E", "AlternateBase": "#242527", "Text": "#DDDFE2",
              "WindowText": "#DDDFE2", "Button": "#363739", "ButtonText": "#DDDFE2", "Highlight": "#48494B",
              "HighlightedText": "#F0F2F4", "Light": "#757575", "Midlight": "#5C5C5C", "Mid": "#3E3E3E",
              "Dark": "#202020", "Shadow": "#141414", "ToolTipBase": "#3F3F3F", "ToolTipText": "#F0F0F0",
              "PlaceholderText": "#8F8F8F", "Link": "#B9BABC"}
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#9E9FA1"))
    if hasattr(QPalette.ColorRole, "Accent"):
        palette.setColor(QPalette.ColorRole.Accent, QColor("#707173"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#717274"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
    if not hasattr(app, "_native_titlebar_filter"):
        app._native_titlebar_filter = _NativeTitlebarFilter(app)
        app.installEventFilter(app._native_titlebar_filter)
