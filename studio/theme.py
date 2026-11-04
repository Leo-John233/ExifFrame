"""专业摄影工作区的深色控件与系统字体"""

import os
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


STYLESHEET = """
QWidget { color: #D5D5D5; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QMainWindow, QDialog { background: #292929; }
QMenuBar { background: #292929; border-bottom: 1px solid #161616; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #434343; }
QMenu { background: #303030; border: 1px solid #535353; padding: 3px; }
QMenu::item { padding: 5px 25px; }
QMenu::item:selected { background: #40546B; }
QMenu::item:disabled { color: #747474; }
QMenu::separator { height: 1px; background: #4A4A4A; margin: 4px 8px; }
QToolBar { background: #303030; border-bottom: 1px solid #161616; spacing: 4px; padding: 4px; }
QToolButton { padding: 4px 7px; border: 1px solid transparent; border-radius: 2px; }
QToolButton:hover { background: #454545; border-color: #606060; }
QToolButton:checked { background: #40546B; border-color: #637E9C; }
QToolButton:disabled, QPushButton:disabled { color: #707070; }
QPushButton { background: #414141; border: 1px solid #555555; border-radius: 2px; min-height: 21px; padding: 2px 8px; }
QPushButton:hover { background: #4B4B4B; border-color: #777777; }
QPushButton:pressed, QPushButton:checked { background: #35485C; }
QPushButton:focus { border-color: #7A9DBD; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #222222; border: 1px solid #515151; border-radius: 1px; padding: 3px 5px; selection-background-color: #405B78; selection-color: #FFFFFF; }
QLineEdit, QComboBox, QSpinBox { min-height: 21px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #777777; background: #2C2C2C; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus { border: 1px solid #7A9DBD; }
QComboBox QAbstractItemView { background: #303030; border: 1px solid #606060; selection-background-color: #405B78; color: #D5D5D5; }
QTreeWidget { background: #252525; border: 1px solid #171717; alternate-background-color: #292929; }
QTreeWidget::item { height: 26px; }
QTreeWidget::item:selected { background: #40546B; color: #F0F0F0; }
QTreeWidget::item:hover { background: #373D45; }
QHeaderView::section { background: #333333; padding: 4px; border: none; border-right: 1px solid #212121; border-bottom: 1px solid #161616; color: #BFBFBF; }
QTabWidget::pane { border: 1px solid #171717; background: #303030; }
QTabBar::tab { background: #262626; color: #A4A4A4; border: 1px solid #181818; padding: 5px 21px; }
QTabBar::tab:selected { background: #393939; color: #EEEEEE; border-bottom: 1px solid #393939; }
QTabBar::tab:hover { color: #EEEEEE; }
QGroupBox { border: 1px solid #464646; margin-top: 9px; padding: 9px 7px 5px 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; color: #BFBFBF; }
QSplitter::handle { background: #191919; }
QSplitter::handle:hover { background: #52687D; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #292929; }
QScrollBar:vertical { background: #262626; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #555555; min-height: 30px; border-radius: 2px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #262626; height: 10px; }
QScrollBar::handle:horizontal { background: #555555; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel#secondaryText { color: #979797; }
QLabel#previewStatus { color: #A7A7A7; background: #1C1C1C; padding: 6px 8px; }
QLabel#templatePreview { background: #212121; border: 1px solid #181818; }
QLabel#errorText { color: #E4A39D; }
QStatusBar { border-top: 1px solid #171717; background: #303030; }
QStatusBar::item { border: none; }
QProgressBar { max-height: 14px; min-height: 14px; border: 1px solid #555555; background: #202020; text-align: center; }
QProgressBar::chunk { background: #526D87; }
QToolTip { background: #393939; color: #EEEEEE; border: 1px solid #666666; padding: 4px; }
"""


def apply_theme(app: QApplication) -> None:
    """统一深色界面并补足无窗口测试环境的字体"""
    if os.name == "nt" and not QFontDatabase.families():
        fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
        for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "consola.ttf"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    palette = QPalette()
    colors = {"Window": "#292929", "Base": "#222222", "AlternateBase": "#292929", "Text": "#D5D5D5",
              "WindowText": "#D5D5D5", "Button": "#414141", "ButtonText": "#D5D5D5", "Highlight": "#40546B",
              "HighlightedText": "#F0F0F0", "Light": "#5B5B5B", "Midlight": "#4B4B4B", "Mid": "#323232",
              "Dark": "#181818", "Shadow": "#111111", "ToolTipBase": "#393939", "ToolTipText": "#EEEEEE",
              "PlaceholderText": "#838383", "Link": "#8DB2D2"}
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#707070"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
