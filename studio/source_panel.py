"""在检查器内编辑当前照片使用的模板源码"""

from PySide6.QtCore import QSignalBlocker, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from jinja2 import TemplateError
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget

from core.desktop_service import validate_template
from .i18n import bind, localize_error, tr
from .template_editor import PLACEHOLDERS, TemplateHighlighter, _InsertFieldButton, format_template_json


class SourcePanel(QWidget):
    changed = Signal(str)
    save_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        tools = QHBoxLayout()
        self.insert = bind(_InsertFieldButton(), '插入字段')
        self.insert.setObjectName('insertFieldButton')
        self.insert.setStyleSheet('QToolButton { padding-right:20px } QToolButton::menu-indicator { width:0px }')
        self.insert.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.insert)
        menu.aboutToShow.connect(lambda: self.insert.set_menu_open(True))
        menu.aboutToHide.connect(lambda: self.insert.set_menu_open(False))
        self.edit = QPlainTextEdit()
        self.edit.setObjectName('templateSourceEditor')
        self.edit.setMinimumHeight(230)
        self.edit.setFont(QFont('Consolas', 10))
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.highlighter = TemplateHighlighter(self.edit)
        for name, expression in PLACEHOLDERS:
            action = bind(menu.addAction(''), name)
            action.triggered.connect(lambda checked=False, value=expression: self.edit.insertPlainText(value))
        self.insert.setMenu(menu)
        tools.addWidget(self.insert)
        formatting = bind(QToolButton(), '格式化 JSON')
        formatting.clicked.connect(self.format_json)
        tools.addWidget(formatting)
        save = bind(QPushButton(), '保存模板')
        save.clicked.connect(self.save)
        tools.addWidget(save)
        close = bind(QToolButton(), '关闭')
        close.clicked.connect(self.hide)
        tools.addWidget(close)
        layout.addLayout(tools)
        layout.addWidget(self.edit)
        self.status = QLabel()
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
