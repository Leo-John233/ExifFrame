"""独立非模态浮窗中编辑当前照片使用的模板源码"""

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from jinja2 import TemplateError
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from core.desktop_service import validate_template
from .i18n import bind, localize_error, tr, translator
from .template_editor import PLACEHOLDERS, TemplateHighlighter, _InsertFieldButton, format_template_json


class SourcePanel(QWidget):
    changed = Signal(str)
    save_requested = Signal(str)
    close_requested = Signal()
    target_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        self.insert = bind(_InsertFieldButton(), '插入字段')
        self.insert.setObjectName('insertFieldButton')
        self.insert.setStyleSheet('QToolButton { padding-right:20px } QToolButton::menu-indicator { width:0px }')
        self.insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.insert)
        menu.aboutToShow.connect(lambda: self.insert.set_menu_open(True))
        menu.aboutToHide.connect(lambda: self.insert.set_menu_open(False))
        self.edit = QPlainTextEdit()
        self.edit.setObjectName('templateSourceEditor')
        self.edit.setMinimumHeight(300)
        self.edit.setFont(QFont('Consolas', 10))
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = TemplateHighlighter(self.edit)
        for name, expression in PLACEHOLDERS:
            action = bind(menu.addAction(''), name)
            action.triggered.connect(lambda checked=False, value=expression: self.edit.insertPlainText(value))
        self.insert.setMenu(menu)
        tools.addWidget(self.insert)
        formatting = bind(QPushButton(), '格式化 JSON')
        formatting.setAutoDefault(False)
        formatting.clicked.connect(self.format_json)
        tools.addWidget(formatting)
        tools.addStretch(1)
        save = bind(QPushButton(), '保存模板')
        save.setObjectName('primaryButton')
        save.setAutoDefault(False)
        save.clicked.connect(self.save)
        tools.addWidget(save)
        close = bind(QPushButton(), '关闭')
        close.setAutoDefault(False)
        close.clicked.connect(self.close_requested.emit)
        tools.addWidget(close)
        layout.addLayout(tools)
        layout.addWidget(self.edit, 1)
        self.status = QLabel()
        self.status.setObjectName('errorText')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.timer = QTimer(self)
        self.timer.setInterval(180)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        self.edit.textChanged.connect(self.timer.start)
        self._target = None
        self._accepted = ''
        self._pending = {}

    def sync(self, target, source):
        if target == self._target and source == self._accepted:
            return
        if self._target is not None and self.edit.toPlainText() != self._accepted:
            self._pending[self._target] = self._accepted, self.edit.toPlainText()
        self.timer.stop()
        self._target, self._accepted = target, source
        baseline, draft = self._pending.pop(target, (None, None))
        with QSignalBlocker(self.edit):
            self.edit.setPlainText(draft if baseline == source else source)
        self.status.clear()
        template_name = target[1] if isinstance(target, tuple) and len(target) > 1 else ''
        self.target_changed.emit(template_name or '')
        if baseline == source and draft != source:
            self.timer.start()

    def apply(self):
        self.timer.stop()
        value = self.edit.toPlainText()
        try:
            validate_template(value)
        except (TypeError, ValueError, TemplateError) as exc:
            self.status.setText(localize_error(exc))
            return False
        self.status.clear()
        if value != self._accepted:
            self._accepted = value
            self.changed.emit(value)
        return True

    def format_json(self):
        def status(message, **values):
            self.status.setText(tr(message, **{k: localize_error(v) for k, v in values.items()}))

        def replace_text(text):
            cursor = self.edit.textCursor()
            cursor.beginEditBlock()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(text + '\n')
            cursor.endEditBlock()

        return format_template_json(self.edit.toPlainText(), status, replace_text)

    def save(self):
        if self.apply():
            self.save_requested.emit(self._accepted)


class SourceDialog(QDialog):
    """可自由拉伸和随时关闭的非模态源码编辑窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('templateSourceDialog')
        self.setModal(False)
        self.resize(760, 560)
        self.setMinimumSize(520, 360)
        self._template_name = ''
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.panel = SourcePanel(self)
        self.panel.close_requested.connect(self.close)
        self.panel.target_changed.connect(self.set_template_name)
        layout.addWidget(self.panel, 1)
        translator.language_changed.connect(self._update_title)
        self._update_title()

    def set_template_name(self, name: str):
        self._template_name = name or ''
        self._update_title()

    def _update_title(self):
        base = tr('高级源码')
        self.setWindowTitle(f'{base} — {self._template_name}' if self._template_name else base)

    def closeEvent(self, event):
        if self.panel.timer.isActive():
            self.panel.apply()
        self.hide()
        event.accept()

    def reject(self):
        self.close()