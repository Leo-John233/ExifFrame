"""保留完整 JSON 与 Jinja 源码的模板编辑器"""

from __future__ import annotations

import re
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QStyle, QToolBar, QVBoxLayout, QMenu, QToolButton,
)

from core.desktop_service import validate_template, write_template
from studio.i18n import bind, tr, register_translations, translator, localize_error


PLACEHOLDERS = (
    ('相机', "{{ exif.CameraModelName | default('') }}"),
    ('镜头', "{{ exif.LensModel | default('') }}"),
    ('拍摄参数', "{{ exif.FocalLengthIn35mmFormat | default('') }} f/{{ exif.FNumber | default('') }} {{ exif.ShutterSpeed | default('') }}s ISO{{ exif.ISO | default('') }}"),
    ('拍摄日期', "{{ exif.DateTimeOriginal | default('') }}"),
    ('版权', "{{ exif.Copyright | default('') }}"),
    ('摄影师', "{{ exif.Artist | default('') }}"),
    ('品牌标识', "{{ auto_logo() }}"),
)

register_translations({
    '模板名称': 'Template name', '新模板名称': 'New template name', '保存': 'Save',
    '另存为': 'Save as', '检查格式': 'Validate', '应用到预览': 'Preview', '撤销': 'Undo',
    '重做': 'Redo', '恢复已保存': 'Revert', '关闭': 'Close', '插入字段': 'Insert field',
    '格式化 JSON': 'Format JSON', '相机': 'Camera', '镜头': 'Lens', '拍摄参数': 'Exposure',
    '拍摄日期': 'Capture date', '版权': 'Copyright', '摄影师': 'Photographer', '品牌标识': 'Brand logo',
    'JSON 和 Jinja 模板源码': 'JSON and Jinja template source',
    '修改源码后可先检查格式，再应用到当前照片预览': 'Validate changes before previewing them on the current photo',
    '格式检查不会替换 Jinja 变量，照片预览会验证实际处理结果': 'Validation preserves Jinja variables; preview checks the rendered result',
    '源码已修改，尚未检查格式': 'Source changed; validation pending',
    '未命名模板': 'Untitled template', '{name}{dirty} — 模板编辑器': '{name}{dirty} — Template editor',
    '行 {line}，列 {column}': 'Line {line}, column {column}',
    '格式检查失败：{error}': 'Validation failed: {error}',
    'Jinja 语法通过，条件和循环的最终结果请用照片预览验证': 'Jinja syntax is valid; preview to check conditions and loops',
    '格式检查通过': 'Validation passed', '请先填写模板名称': 'Enter a template name first',
    '已将当前草稿应用到照片预览，文件尚未保存': 'Draft applied to preview; file has not been saved',
    '已应用到照片预览': 'Applied to preview', '请填写模板名称': 'Enter a template name',
    '保存失败：{error}': 'Save failed: {error}', '已保存 {name}.json': 'Saved {name}.json',
    '{name} 副本': '{name} copy', '新模板': 'New template', '另存为模板': 'Save template as',
    '模板名称不能为空': 'Template name cannot be empty', '恢复已保存内容': 'Revert to saved version',
    '放弃当前修改，恢复编辑器中上次保存的内容？': 'Discard current changes and restore the last saved version?',
    '已恢复上次保存的内容': 'Restored the last saved version', '模板尚未保存': 'Unsaved template',
    '要保存对“{name}”的修改吗？': 'Save changes to “{name}”?',
    '包含 Jinja 条件或循环，保留原始排版': 'Jinja conditions or loops detected; original formatting preserved',
    '已格式化 JSON，Jinja 表达式保持不变': 'JSON formatted; Jinja expressions preserved',
    '无法安全格式化，源码保持不变：{error}': 'Cannot format safely; source unchanged: {error}',
})


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
        self._status = ('修改源码后可先检查格式，再应用到当前照片预览', {})
        self.setObjectName("templateEditor")
        self.resize(900, 680)
        self.setMinimumSize(620, 440)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._build_ui()
        self.editor.setPlainText(self._saved_source)
        self.editor.document().setModified(False)
        self._update_title()
        self._update_position()
        self._set_status('修改源码后可先检查格式，再应用到当前照片预览')
        translator.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(7)
        name_row = QHBoxLayout()
        name_label = QLabel()
        bind(name_label, '模板名称')
        name_row.addWidget(name_label)
        self.name_input = QLineEdit(self.name)
        self.name_input.setObjectName("templateNameInput")
        bind(self.name_input, '新模板名称', 'setPlaceholderText')
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
        tools = QHBoxLayout()
        insert_button = QToolButton()
        bind(insert_button, '插入字段')
        insert_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(insert_button)
        for label, expression in PLACEHOLDERS:
            action = menu.addAction('')
            bind(action, label)
            action.triggered.connect(lambda checked=False, value=expression: self.editor.insertPlainText(value))
        insert_button.setMenu(menu)
        tools.addWidget(insert_button)
        format_button = QPushButton()
        bind(format_button, '格式化 JSON')
        format_button.setAutoDefault(False)
        format_button.clicked.connect(self.format_json)
        tools.addWidget(format_button)
        tools.addStretch()
        layout.addLayout(tools)

        self.editor = QPlainTextEdit()
        self.editor.setObjectName("templateSourceEditor")
        self.editor.setFont(QFont("Consolas", 10))
        self.editor.setStyleSheet("QPlainTextEdit { font-family: Consolas, 'Cascadia Mono', monospace; font-size: 13px; }")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setTabStopDistance(self.editor.fontMetrics().horizontalAdvance(" ") * 2)
        self.editor.setPlaceholderText("[]")
        bind(self.editor, 'JSON 和 Jinja 模板源码', 'setAccessibleName')
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
        hint = QLabel()
        bind(hint, '格式检查不会替换 Jinja 变量，照片预览会验证实际处理结果')
        hint.setWordWrap(True)
        bottom.addWidget(hint)
        bottom.addStretch()
        self.close_button = QPushButton("关闭")
        bind(self.close_button, '关闭')
        self.close_button.clicked.connect(self.close)
        self.close_button.setAutoDefault(False)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)

    def _action(self, title, callback, shortcut="", icon=None):
        action = QAction(title, self)
        bind(action, title)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            bind(action, title, 'setToolTip')
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
        self._set_status('源码已修改，尚未检查格式')

    def _update_title(self):
        name = self.name_input.text().strip() or tr("未命名模板")
        dirty = hasattr(self, "editor") and self.is_dirty()
        self.setWindowTitle(tr('{name}{dirty} — 模板编辑器', name=name, dirty=' *' if dirty else ''))

    def _update_position(self):
        cursor = self.editor.textCursor()
        self.position_label.setText(tr('行 {line}，列 {column}', line=cursor.blockNumber() + 1, column=cursor.positionInBlock() + 1))

    def _set_status(self, source, **kwargs):
        self._status = (source, kwargs)
        values = {key: localize_error(value) if isinstance(value, Exception) else value for key, value in kwargs.items()}
        self.status_label.setText(tr(source, **values))

    def retranslate_ui(self):
        self._update_title()
        self._update_position()
        self._set_status(*self._status[:1], **self._status[1])

    def format_json(self):
        source = self.source()
        if '{%' in source:
            self._set_status('包含 Jinja 条件或循环，保留原始排版')
            return False
        expressions = []
        chunks = []
        position = 0
        in_string = False
        escaped = False
        # 临时占位符区分字符串内部和外部表达式
        for match in re.finditer(r'\{\{.*?\}\}|\{#.*?#\}', source, flags=re.S):
            part = source[position:match.start()]
            for char in part:
                if escaped:
                    escaped = False
                elif char == '\\' and in_string:
                    escaped = True
                elif char == '"':
                    in_string = not in_string
            marker = f'__EXIFFRAME_JINJA_{len(expressions)}__' if in_string else str(912345678900000 + len(expressions))
            if marker in source:
                self._set_status('无法安全格式化，源码保持不变：{error}', error=tr('插入字段'))
                return False
            chunks.extend((part, marker))
            expressions.append((marker, match.group()))
            position = match.end()
        chunks.append(source[position:])
        try:
            formatted = json.dumps(json.loads(''.join(chunks)), ensure_ascii=False, indent=2)
            for marker, expression in expressions:
                formatted = formatted.replace(marker, expression)
            validate_template(formatted)
        except Exception as exc:
            self._set_status('无法安全格式化，源码保持不变：{error}', error=exc)
            return False
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(formatted + '\n')
        cursor.endEditBlock()
        self._set_status('已格式化 JSON，Jinja 表达式保持不变')
        return True

    def _undo(self):
        self.editor.undo()

    def _redo(self):
        self.editor.redo()

    def _error(self, message, exception=None, **kwargs):
        self._set_status(message, **kwargs)
        self.status_label.setToolTip(self.status_label.text())
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
            self._error('格式检查失败：{error}', exc, error=exc)
            return False
        has_control = "{%" in self.source()
        self._set_status("Jinja 语法通过，条件和循环的最终结果请用照片预览验证" if has_control else "格式检查通过")
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
        self._set_status("已将当前草稿应用到照片预览，文件尚未保存" if self.is_dirty() or self.is_new else "已应用到照片预览")
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
            self._error('保存失败：{error}', exc, error=exc)
            return False
        self.name = self._saved_name = name
        self.is_new = False
        self._saved_source = source
        self.name_input.setText(name)
        self.name_input.setReadOnly(True)
        self.editor.document().setModified(False)
        self._update_title()
        self._set_status('已保存 {name}.json', name=name)
        self.status_label.setToolTip("")
        self.saved.emit(name)
        return True

    def save_as(self) -> bool:
        if not self.check_format():
            return False
        default_name = tr('{name} 副本', name=self.name) if self.name else tr("新模板")
        name, accepted = QInputDialog.getText(self, tr("另存为模板"), tr("模板名称"), text=default_name)
        if not accepted:
            return False
        if not name.strip():
            self._error("模板名称不能为空")
            return False
        return self._write(name.strip(), create=True)

    def revert(self) -> bool:
        if not self.is_dirty():
            return True
        choice = QMessageBox.question(self, tr("恢复已保存内容"), tr("放弃当前修改，恢复编辑器中上次保存的内容？"),
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if choice != QMessageBox.StandardButton.Yes:
            return False
        self.editor.setPlainText(self._saved_source)
        self.name_input.setText(self._saved_name)
        self.editor.document().setModified(False)
        self._update_title()
        self._set_status("已恢复上次保存的内容")
        return True

    def confirm_close(self) -> bool:
        """关闭前允许保存、放弃或继续编辑"""
        if self._close_approved or not self.is_dirty():
            self._close_approved = True
            return True
        choice = QMessageBox.warning(
            self, tr("模板尚未保存"), tr('要保存对“{name}”的修改吗？', name=self.name or tr('未命名模板')),
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
