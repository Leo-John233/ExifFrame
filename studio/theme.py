"""专业摄影工作区的深色控件与系统字体"""

import os
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication


STYLESHEET = """
QWidget { color: #DDDFE2; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 12px; }
QMainWindow, QDialog { background: #242629; }
QWidget#filesPanel, QWidget#inspectorPanel { background: #292C30; }
QWidget#previewPanel { background: #202226; }
QMenuBar { background: #242629; border-bottom: 1px solid #383C42; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #3C4148; border-radius: 4px; }
QMenu { background: #2B2E33; border: 1px solid #505761; padding: 4px; }
QMenu::item { padding: 6px 25px; border-radius: 4px; }
QMenu::item:selected { background: #485565; }
QMenu::item:disabled { color: #747A82; }
QMenu::separator { height: 1px; background: #434951; margin: 5px 8px; }
QToolBar { background: #2B2E32; border-bottom: 1px solid #3C4147; spacing: 6px; padding: 6px 8px; }
QToolBar::separator { background: #4A5058; width: 1px; margin: 6px 4px; }
QToolButton { min-height: 23px; padding: 4px 8px; border: 1px solid transparent; border-radius: 5px; }
QToolButton:hover { background: #3B4149; border-color: #555E6A; }
QToolButton:checked { background: #485565; border-color: #718298; }
QPushButton { background: #363B42; border: 1px solid #4B525C; border-radius: 5px; min-height: 22px; padding: 3px 8px; }
QPushButton:hover { background: #424951; border-color: #6B7684; }
QPushButton:pressed, QToolButton:pressed { background: #29323D; border-color: #6A7D95; }
QPushButton:checked { background: #485565; border-color: #73869C; }
QPushButton:focus, QToolButton:focus { border-color: #91ACC8; }
QPushButton:disabled, QToolButton:disabled { color: #737982; background: #2C3035; border-color: #3B4148; }
QPushButton#primaryButton, QToolButton#primaryButton { background: #52647B; border-color: #6E839D; color: #F1F3F5; }
QPushButton#primaryButton:hover, QToolButton#primaryButton:hover { background: #617690; border-color: #91A7C1; }
QPushButton#primaryButton:pressed, QToolButton#primaryButton:pressed { background: #43546B; }
QPushButton#primaryButton:disabled, QToolButton#primaryButton:disabled { background: #333D49; color: #818C99; border-color: #414E5D; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit { background: #202327; border: 1px solid #4D545E; border-radius: 4px; padding: 3px 6px; selection-background-color: #52657C; selection-color: #FFFFFF; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit { min-height: 22px; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover { border-color: #6A7482; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color: #747B84; background: #2A2E33; border-color: #3B424B; }
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus { border: 1px solid #91ACC8; }
QComboBox QAbstractItemView { background: #2B3036; border: 1px solid #616D7C; selection-background-color: #48596E; color: #DDDFE2; padding: 3px; }
QTreeWidget, QListWidget { background: #23262A; border: 1px solid #3B4047; border-radius: 4px; alternate-background-color: #282C31; outline: none; }
QTreeWidget:focus, QListWidget:focus { border-color: #7D94AE; }
QTreeWidget::item { height: 27px; }
QTreeWidget::item:selected, QListWidget::item:selected { background: #48596D; color: #F0F2F4; }
QTreeWidget::item:hover, QListWidget::item:hover { background: #353E49; }
QHeaderView::section { background: #30353C; padding: 5px; border: none; border-right: 1px solid #41474F; border-bottom: 1px solid #41474F; color: #BCC3CB; }
QTabWidget::pane { border: 1px solid #40464E; border-radius: 4px; background: #292D32; }
QTabBar::tab { background: #24282D; color: #A1A9B3; border: 1px solid #3B424A; border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 6px 21px; margin-right: 2px; }
QTabBar::tab:selected { background: #3A424D; color: #EDF0F3; border-color: #677689; }
QTabBar::tab:hover { background: #333A44; color: #EDF0F3; }
QGroupBox { border: 1px solid #41474F; border-radius: 5px; margin-top: 11px; padding: 9px 7px 5px 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; color: #C5CBD2; }
QCheckBox { spacing: 7px; padding: 2px 0; }
QCheckBox:disabled { color: #757C85; }
QSplitter::handle { background: #1C1F23; }
QSplitter::handle:hover { background: #657A93; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: #292C30; }
QScrollBar:vertical { background: #23272C; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #505965; min-height: 30px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: #738196; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { background: #23272C; height: 10px; }
QScrollBar::handle:horizontal { background: #505965; min-width: 30px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QLabel#secondaryText { color: #9BA3AE; }
QLabel#previewStatus { color: #ABB3BF; background: #141517; padding: 7px 9px; }
QLabel#templatePreview { background: #1D2024; border: 1px solid #383F48; border-radius: 4px; }
QLabel#errorText { color: #E5A59E; }
QStatusBar { border-top: 1px solid #40464E; background: #2B2F35; }
QStatusBar::item { border: none; }
QProgressBar { max-height: 14px; min-height: 14px; border: 1px solid #566272; border-radius: 3px; background: #20252B; text-align: center; }
QProgressBar::chunk { background: #647D99; border-radius: 2px; }
QToolTip { background: #363E48; color: #EDF0F3; border: 1px solid #77879A; padding: 5px; }
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
    colors = {"Window": "#242629", "Base": "#202327", "AlternateBase": "#282C31", "Text": "#DDDFE2",
              "WindowText": "#DDDFE2", "Button": "#363B42", "ButtonText": "#DDDFE2", "Highlight": "#48596D",
              "HighlightedText": "#F0F2F4", "Light": "#687483", "Midlight": "#505B68", "Mid": "#363D46",
              "Dark": "#1C2025", "Shadow": "#111417", "ToolTipBase": "#363E48", "ToolTipText": "#EDF0F3",
              "PlaceholderText": "#858E9B", "Link": "#A0BBD6"}
    for role, color in colors.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#737B87"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
