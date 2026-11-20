"""摄影工作区的明暗主题与系统字体"""

import json
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from core.runtime_paths import config_path, resource_path


PREFERENCES_PATH = config_path('theme.json')
_theme = 'dark'
try:
    _stored = json.loads(PREFERENCES_PATH.read_text(encoding='utf-8'))
    if _stored.get('theme') in ('dark', 'light'):
        _theme = _stored['theme']
except (OSError, ValueError, TypeError, AttributeError):
    pass


class _ThemeNotifier(QObject):
    theme_changed = Signal(str)


theme_notifier = _ThemeNotifier()


STYLESHEET = """
QWidget { color: #DDDFE2; font-family: 'Microsoft YaHei UI', 'Segoe UI', 'Segoe UI Symbol', 'Cambria Math'; font-size: 12px; }
QMainWindow, QDialog { background: #1E1F21; }
QWidget#filesPanel, QWidget#inspectorPanel { background: #232323; }
QWidget#previewPanel, QGraphicsView#photoPreview { background: #181818; }
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
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit { background: #2C2C2C; border: 1px solid #555555; border-radius: 4px; padding: 3px 6px; selection-background-color: #48494B; selection-color: #FFFFFF; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit { min-height: 22px; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #757575; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #7C7C7C; background: #2E2E2E; border-color: #434343; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus { border: 1px solid #8B8C8E; }
QLineEdit#cameraRawValue { background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 1px 5px; min-height: 19px; }
QLineEdit#cameraRawValue:hover { background: #303133; border-color: #626262; }
QLineEdit#cameraRawValue:focus { background: #2C2C2C; border-color: #8B8C8E; }
QSlider#cameraRawTrack { background: transparent; border: none; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 20px; border: none; background: transparent; }
QComboBox::down-arrow { image: url("__COMBO_ARROW__"); width: 10px; height: 6px; }
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
QScrollArea > QWidget > QWidget { background: #232323; }
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
QFrame#inspectorSectionDivider { background: #343434; border: none; }
QToolButton#inspectorSection { text-align: left; background: transparent; border: none; border-radius: 3px; padding: 3px 1px; font-weight: 600; }
QToolButton#inspectorSection:hover { background: #343434; }
QToolButton#propertyReset { background: transparent; border: 1px solid transparent; border-radius: 3px; min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; padding: 1px; }
QToolButton#propertyReset:hover { background: #424242; border-color: #626262; }
QToolButton#propertyReset:disabled { color: #717274; background: transparent; border-color: transparent; }
QToolButton#colorSwatch { border: none; padding: 0; min-width: 0; min-height: 0; background: transparent; }
QLabel#colorPropertyValue { color: #C3C3C3; }
"""


_LIGHT_COLORS = {
    '#DDDFE2': '#282828', '#1E1F21': '#E7E7E7', '#232323': '#F2F2F2', '#181818': '#DEDEDE',
    '#252629': '#F2F2F2', '#1B1C1E': '#FAFAFA', '#353638': '#D3D3D3', '#424242': '#DEDEDE',
    '#585858': '#B0B0B0', '#48494B': '#D0D0D0', '#7B7B7B': '#777777', '#4A4A4A': '#CCCCCC',
    '#515151': '#BBBBBB', '#5F5F5F': '#A5A5A5', '#848484': '#888888', '#363739': '#E5E5E5',
    '#4C4D4F': '#BBBBBB', '#494949': '#D6D6D6', '#777777': '#8A8A8A', '#333333': '#CFCFCF',
    '#7F7F7F': '#888888', '#878787': '#888888', '#8B8C8E': '#727272', '#717274': '#929292',
    '#303030': '#F6F6F6', '#414141': '#D0D0D0', '#515254': '#676767', '#707173': '#7C7C7C',
    '#F1F3F5': '#FFFFFF', '#616264': '#777777', '#8D8E90': '#686868', '#424345': '#555555',
    '#2E2F31': '#E1E1E1', '#727375': '#999999', '#414244': '#CCCCCC', '#2C2C2C': '#FFFFFF',
    '#555555': '#C6C6C6', '#FFFFFF': '#222222', '#757575': '#888888', '#7C7C7C': '#929292',
    '#2E2E2E': '#EAEAEA', '#434343': '#D1D1D1', '#303133': '#E5E5E5', '#626262': '#A0A0A0',
    '#6E6E6E': '#AAAAAA', '#202123': '#FAFAFA', '#242527': '#F4F4F4', '#F0F2F4': '#292929',
    '#3F3F3F': '#E0E0E0', '#363636': '#E3E3E3', '#484848': '#C8C8C8', '#C3C3C3': '#505050',
    '#474747': '#C8C8C8', '#282828': '#E5E5E5', '#AAAAAA': '#6B6B6B', '#F0F0F0': '#202020',
    '#3B3B3B': '#D9D9D9', '#CBCBCB': '#555555', '#7D7D7D': '#929292', '#171819': '#D5D5D5',
    '#272727': '#E9E9E9', '#505153': '#B2B2B2', '#737476': '#929292', '#A4A4A4': '#666666',
    '#B4B4B4': '#555555', '#141516': '#E3E3E3', '#202020': '#F8F8F8', '#404040': '#BFBFBF',
    '#B77975': '#9A4C47', '#636363': '#AAAAAA', '#252525': '#E3E3E3', '#67686A': '#888888',
    '#343434': '#D5D5D5',
}


def _light_stylesheet():
    import re
    return re.sub(r'#[0-9A-Fa-f]{6}\b', lambda match: _LIGHT_COLORS.get(match.group().upper(), match.group()), STYLESHEET)


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
        dark = theme() == 'dark'
        enabled = ctypes.c_int(1 if dark else 0)
        applied = setter(handle, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0
        if not applied:
            applied = setter(handle, 19, ctypes.byref(enabled), ctypes.sizeof(enabled)) == 0
        # Windows 11 可分别设置边界、标题背景和标题文字
        title_colors = ('#353638', '#1E1F21', '#DADBDD') if dark else ('#CCCCCC', '#E7E7E7', '#282828')
        for attribute, color in zip((34, 35, 36), title_colors):
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
    """为随后打开的编辑器和对话框应用对应标题栏"""

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            apply_native_titlebar(watched)
        return False


def theme() -> str:
    """返回当前明暗主题"""
    return _theme

def reload_theme() -> str:
    """配置首次迁移或初始化后重新读取主题偏好"""
    global _theme
    try:
        stored = json.loads(PREFERENCES_PATH.read_text(encoding='utf-8'))
        if stored.get('theme') in ('dark', 'light'):
            _theme = stored['theme']
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return _theme

def set_theme(code: str, app=None) -> None:
    """保存并应用界面主题，不改变照片样式"""
    global _theme
    if code not in ('dark', 'light'):
        raise ValueError('Unsupported interface theme')
    changed = code != _theme
    _theme = code
    try:
        PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = PREFERENCES_PATH.with_suffix('.json.tmp')
        temporary.write_text(json.dumps({'theme': code}), encoding='utf-8')
        temporary.replace(PREFERENCES_PATH)
    except OSError:
        pass
    if changed:
        app = app or QApplication.instance()
        if app is not None:
            apply_theme(app)
        theme_notifier.theme_changed.emit(code)


def apply_theme(app: QApplication) -> None:
    """应用当前主题并补足无窗口测试环境的字体"""
    from .controls import install_no_wheel_filter
    install_no_wheel_filter(app)
    if os.name == "nt" and not QFontDatabase.families():
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf", "seguisym.ttf", "cambria.ttc"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
    dark = theme() == 'dark'
    if hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if dark else Qt.ColorScheme.Light)
    # 控件使用中性灰，功能图标保留系统原色和禁用状态
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI", 9)
    # 显式指定符号回退，中文标签旁的数学字母也能正常显示
    font.setFamilies(["Microsoft YaHei UI", "Segoe UI", "Segoe UI Symbol", "Cambria Math"])
    app.setFont(font)
    palette = QPalette()
    colors = {"Window": "#232323", "Base": "#2C2C2C", "AlternateBase": "#242527", "Text": "#DDDFE2",
              "WindowText": "#DDDFE2", "Button": "#363739", "ButtonText": "#DDDFE2", "Highlight": "#48494B",
              "HighlightedText": "#F0F2F4", "Light": "#757575", "Midlight": "#5C5C5C", "Mid": "#3E3E3E",
              "Dark": "#202020", "Shadow": "#141414", "ToolTipBase": "#3F3F3F", "ToolTipText": "#F0F0F0",
              "PlaceholderText": "#8F8F8F", "Link": "#B9BABC"}
    if not dark:
        colors = {"Window": "#F2F2F2", "Base": "#FFFFFF", "AlternateBase": "#F4F4F4", "Text": "#282828",
                  "WindowText": "#282828", "Button": "#E5E5E5", "ButtonText": "#282828", "Highlight": "#D0D0D0",
                  "HighlightedText": "#292929", "Light": "#FFFFFF", "Midlight": "#E5E5E5", "Mid": "#BFBFBF",
                  "Dark": "#888888", "Shadow": "#666666", "ToolTipBase": "#E0E0E0", "ToolTipText": "#202020",
                  "PlaceholderText": "#777777", "Link": "#505050"}
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#9E9FA1" if dark else "#606060"))
    if hasattr(QPalette.ColorRole, "Accent"):
        palette.setColor(QPalette.ColorRole.Accent, QColor("#707173" if dark else "#888888"))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#717274" if dark else "#929292"))
    app.setPalette(palette)
    arrow = resource_path('static/combobox-down-dark.svg' if dark else 'static/combobox-down-light.svg')
    stylesheet = STYLESHEET if dark else _light_stylesheet()
    app.setStyleSheet(stylesheet.replace('__COMBO_ARROW__', arrow.resolve().as_posix()))
    if not hasattr(app, "_native_titlebar_filter"):
        app._native_titlebar_filter = _NativeTitlebarFilter(app)
        app.installEventFilter(app._native_titlebar_filter)
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            apply_native_titlebar(widget)
