"""保留完整 JSON 与 Jinja 源码的模板编辑器"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QStyle, QToolBar, QVBoxLayout,
)

from core.desktop_service import validate_template, write_template


class TemplateHighlighter(QSyntaxHighlighter):
    """区分 JSON 字段和 Jinja 表达式而不改写源码"""

    def __init__(self, editor):
        super().__init__(editor.document())
        dark = editor.palette().base().color().lightness() < 128
        colors = ("#9CDCFE", "#CE9178", "#B5CEA8", "#C586C0", "#6A9955") if dark else (
            "#0451A5", "#A31515", "#098658", "#7B3294", "#567D46")
        patterns = (
            r'"(?:[^"\\]|\\.)*"(?=\s*:)',
            r'"(?:[^"\\]|\\.)*"',
            r'\b(?:true|false|null|\d+(?:\.\d+)?)\b',
            r'\{\{.*?\}\}|\{%.*?%\}',
            r'\{#.*?#\}',
        )
        self.rules = []
        # 字段规则最后应用以覆盖普通字符串的颜色
        for index in (1, 2, 0, 3, 4):
            style = QTextCharFormat()
            style.setForeground(QColor(colors[index]))
            self.rules.append((re.compile(patterns[index]), style))

    def highlightBlock(self, text):
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                # Qt 使用 UTF-16 坐标以兼容表情等非基本平面字符
                start = len(text[:match.start()].encode("utf-16-le")) // 2
                length = len(match.group().encode("utf-16-le")) // 2
                self.setFormat(start, length, style)


class TemplateEditor(QDialog):
    """新建、编辑、预览和保存模板源码"""

    source_preview = Signal(str)
    saved = Signal(str)

    def __init__(self, parent=None, name: str = "", source: str = "", is_new: bool = False):
        super().__init__(parent)
        self.name = name
        self.is_new = is_new or not name
        self._saved_source = source if source else "[]"
        self._saved_name = name
        self._close_approved = False
        self.setObjectName("templateEditor")
        self.resize(900, 680)
        self.setMinimumSize(620, 440)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._build_ui()
        self.editor.setPlainText(self._saved_source)
        self.editor.document().setModified(False)
        self._update_title()
        self._update_position()
        self.status_label.setText("修改源码后可先检查格式，再应用到当前照片预览")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("模板名称"))
        self.name_input = QLineEdit(self.name)
        self.name_input.setObjectName("templateNameInput")
        self.name_input.setPlaceholderText("新模板名称")
        self.name_input.setReadOnly(not self.is_new)
        self.name_input.textChanged.connect(self._name_changed)
        name_row.addWidget(self.name_input, 1)
        name_row.addWidget(QLabel(".json"))
        layout.addLayout(name_row)

        toolbar = QToolBar()
        toolbar.setObjectName("templateEditorToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_action = self._action("保存", self.save, "Ctrl+S", QStyle.StandardPixmap.SP_DialogSaveButton)
        self.save_as_action = self._action("另存为", self.save_as, "Ctrl+Shift+S")
        self.validate_action = self._action("检查格式", self.check_format, "F7", QStyle.StandardPixmap.SP_DialogApplyButton)
        self.preview_action = self._action("应用到预览", self.apply_preview, "Ctrl+Return")
        for action in (self.save_action, self.save_as_action):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.validate_action)
        toolbar.addAction(self.preview_action)
        toolbar.addSeparator()
        self.undo_action = self._action("撤销", self._undo, "Ctrl+Z")
        self.redo_action = self._action("重做", self._redo, "Ctrl+Y")
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)
        toolbar.addAction(self._action("恢复已保存", self.revert))
        layout.addWidget(toolbar)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("templateSourceEditor")
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setStyleSheet("QPlainTextEdit { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 13px; }")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 2)
        self.editor.setPlaceholderText("[]")
        self.editor.setAccessibleName("JSON 和 Jinja 模板源码")
        self.editor.document().modificationChanged.connect(self._update_title)
        self.editor.textChanged.connect(self._text_changed)
        self.editor.cursorPositionChanged.connect(self._update_position)
        self.editor.undoAvailable.connect(self.undo_action.setEnabled)
        self.editor.redoAvailable.connect(self.redo_action.setEnabled)
        self.highlighter = TemplateHighlighter(self.editor)
        layout.addWidget(self.editor, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("修改源码后可先检查格式，再应用到当前照片预览")
        self.status_label.setObjectName("templateEditorStatus")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        self.position_label = QLabel()
        self.position_label.setObjectName("templateEditorPosition")
        status_row.addWidget(self.position_label)
        layout.addLayout(status_row)
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel("格式检查不会替换 Jinja 变量，照片预览会验证实际处理结果"))
        bottom.addStretch()
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.close)
        self.close_button.setAutoDefault(False)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)

    def _action(self, title, callback, shortcut="", icon=None):
        action = QAction(title, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.setToolTip(f"{title}  {shortcut}")
        action.triggered.connect(callback)
        self.addAction(action)
        return action

    def source(self) -> str:
        """返回未经格式化或插值的原始文本"""
        return self.editor.toPlainText()

    def is_dirty(self) -> bool:
        return self.is_new or self.source() != self._saved_source or self.name_input.text().strip() != self._saved_name

    def _name_changed(self):
        self._close_approved = False
        if self.is_new:
            self.name = self.name_input.text().strip()
        self._update_title()

    def _text_changed(self):
        self._close_approved = False
        self._update_title()
        self.status_label.setText("源码已修改，尚未检查格式")

    def _update_title(self):
        name = self.name_input.text().strip() or "未命名模板"
        dirty = hasattr(self, "editor") and self.is_dirty()
        self.setWindowTitle(f"{name}{' *' if dirty else ''} — 模板编辑器")

    def _update_position(self):
        cursor = self.editor.textCursor()
        self.position_label.setText(f"行 {cursor.blockNumber() + 1}，列 {cursor.positionInBlock() + 1}")

    def _undo(self):
        self.editor.undo()

    def _redo(self):
        self.editor.redo()

    def _error(self, message, exception=None):
        self.status_label.setText(message)
        self.status_label.setToolTip(message)
        if exception is not None and getattr(exception, "lineno", None):
            # 定位语法错误而不丢弃尚未保存的编辑
            block = self.editor.document().findBlockByNumber(exception.lineno - 1)
            if block.isValid():
                cursor = QTextCursor(block)
                column = max(0, getattr(exception, "colno", 1) - 1)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor,
                                    min(column, len(block.text())))
                self.editor.setTextCursor(cursor)
                self.editor.centerCursor()
                self.editor.setFocus()

    def check_format(self) -> bool:
        """使用与模板写入一致的规则校验草稿"""
        try:
            validate_template(self.source())
        except Exception as exc:
            self._error(f"格式检查失败：{exc}", exc)
            return False
        has_control = "{%" in self.source()
        self.status_label.setText("Jinja 语法通过，条件和循环的最终结果请用照片预览验证" if has_control else "格式检查通过")
        self.status_label.setToolTip("")
        return True

    def apply_preview(self) -> bool:
        if not self.check_format():
            return False
        if not self.name_input.text().strip():
            self._error("请先填写模板名称")
            self.name_input.setFocus()
            return False
        self.source_preview.emit(self.source())
        self.status_label.setText("已将当前草稿应用到照片预览，文件尚未保存" if self.is_dirty() or self.is_new else "已应用到照片预览")
        return True

    def save(self) -> bool:
        """保存成功后才更新编辑器的基准版本"""
        if not self.check_format():
            return False
        name = self.name_input.text().strip()
        if not name:
            self._error("请填写模板名称")
            self.name_input.setFocus()
            return False
        return self._write(name, create=self.is_new)

    def _write(self, name: str, create: bool) -> bool:
        source = self.source()
        try:
            write_template(name, source, create=create)
        except Exception as exc:
            self._error(f"保存失败：{exc}", exc)
            return False
        self.name = self._saved_name = name
        self.is_new = False
        self._saved_source = source
        self.name_input.setText(name)
        self.name_input.setReadOnly(True)
        self.editor.document().setModified(False)
        self._update_title()
        self.status_label.setText(f"已保存 {name}.json")
        self.status_label.setToolTip("")
        self.saved.emit(name)
        return True

    def save_as(self) -> bool:
        if not self.check_format():
            return False
        default_name = f"{self.name} 副本" if self.name else "新模板"
        name, accepted = QInputDialog.getText(self, "另存为模板", "模板名称", text=default_name)
        if not accepted:
            return False
        if not name.strip():
            self._error("模板名称不能为空")
            return False
        return self._write(name.strip(), create=True)

    def revert(self) -> bool:
        if not self.is_dirty():
            return True
        choice = QMessageBox.question(self, "恢复已保存内容", "放弃当前修改，恢复编辑器中上次保存的内容？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return False
        self.editor.setPlainText(self._saved_source)
        self.name_input.setText(self._saved_name)
        self.editor.document().setModified(False)
        self._update_title()
        self.status_label.setText("已恢复上次保存的内容")
        return True

    def confirm_close(self) -> bool:
        """关闭前允许保存、放弃或继续编辑"""
        if self._close_approved or not self.is_dirty():
            self._close_approved = True
            return True
        choice = QMessageBox.warning(
            self, "模板尚未保存", f"要保存对“{self.name or '未命名模板'}”的修改吗？",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            self._close_approved = self.save()
        else:
            self._close_approved = choice == QMessageBox.StandardButton.Discard
        return self._close_approved

    def closeEvent(self, event):
        if self._close_approved or self.confirm_close():
            self._close_approved = True
            super().closeEvent(event)
        else:
            event.ignore()

    def reject(self):
        # Esc 和标题栏关闭遵循相同的未保存检查
        if self._close_approved or self.confirm_close():
            self._close_approved = True
            super().reject()
