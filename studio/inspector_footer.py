"""检查器中的页脚字段与顺序编辑"""

from copy import deepcopy

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from core.footer import (FIELD_CATALOG, clear_row_character_styles, get_footer_field,
                         read_layout, write_layout)
from .i18n import bind, localize_error, region_title, tr, translator
from .character_strip import CharacterStrip
from .controls import CollapsibleSection


def _has_character_styles(value):
    """检查保留的分段及默认样式中是否含单字设置"""
    if isinstance(value, list):
        return any(_has_character_styles(item) for item in value)
    if isinstance(value, dict):
        if value.get('char_styles') or value.get('highlight_rules'):
            return True
        return any(_has_character_styles(value.get(key)) for key in
                   ('items', 'segments', 'text_segments', 'style', 'segment_defaults'))
    return False


class InlineFooter(QWidget):
    source_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._model = None
        self._error = ''
        self._rendered_rows = {}
        self._character_region = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.region = QComboBox()
        bind(self.region, '选择要编辑的区域', 'setAccessibleName')
        layout.addWidget(self.region)
        self.region.hide()
        self.items = QListWidget()
        self.items.setFixedHeight(78)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.items)
        buttons = QHBoxLayout()
        self.up = QPushButton('↑')
        self.down = QPushButton('↓')
        for button, title, offset in ((self.up, '上移', -1), (self.down, '下移', 1)):
            bind(button, title, 'setAccessibleName')
            bind(button, title, 'setToolTip')
            button.clicked.connect(lambda checked=False, move=offset: self._edit('move', move))
            buttons.addWidget(button)
        self.remove = bind(QPushButton(), '删除')
        self.remove.clicked.connect(lambda: self._edit('remove'))
        buttons.addWidget(self.remove)
        layout.addLayout(buttons)
        fields = QHBoxLayout()
        self.field = QComboBox()
        self.field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        bind(self.field, '可添加字段', 'setAccessibleName')
        self.add = bind(QPushButton(), '添加字段')
        self.add.clicked.connect(lambda: self._edit('add'))
        fields.addWidget(self.field, 1)
        fields.addWidget(self.add)
        layout.addLayout(fields)
        literal_row = QHBoxLayout()
        self.literal = QLineEdit()
        bind(self.literal, '输入自定义文字', 'setPlaceholderText')
        self.literal.editingFinished.connect(self._save_literal)
        self.add_literal = bind(QPushButton(), '添加文字')
        self.add_literal.clicked.connect(lambda: self._edit('add_literal'))
        literal_row.addWidget(self.literal, 1)
        literal_row.addWidget(self.add_literal)
        layout.addLayout(literal_row)
        self.separator = QLineEdit()
        self.separator.setMaxLength(32)
        self.separator.editingFinished.connect(lambda: self._edit('separator'))
        layout.addWidget(bind(QLabel(), '区域内分隔符'))
        layout.addWidget(self.separator)
        self.format_toggle = QToolButton()
        self.format_toggle.setCheckable(True)
        self.format_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.format_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind(self.format_toggle, '更多格式选项')
        layout.addWidget(self.format_toggle)
        self.format_body = QWidget()
        format_form = QFormLayout(self.format_body)
        format_form.setContentsMargins(0, 0, 0, 0)
        self.prefix_input, self.suffix_input = QLineEdit(), QLineEdit()
        for editor in (self.prefix_input, self.suffix_input):
            editor.setMinimumWidth(0)
            editor.setMaxLength(256)
        self.prefix_input.editingFinished.connect(lambda: self._edit('prefix'))
        self.suffix_input.editingFinished.connect(lambda: self._edit('suffix'))
        format_form.addRow(bind(QLabel(), '字段前缀'), self.prefix_input)
        format_form.addRow(bind(QLabel(), '字段后缀'), self.suffix_input)
        self.missing = QComboBox()
        self.missing.setMinimumWidth(0)
        self.missing.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.missing.currentIndexChanged.connect(lambda _: self._edit('missing'))
        missing_label = bind(QLabel(), '缺失值')
        bind(missing_label, '缺失值策略影响所有区域', 'setToolTip')
        format_form.addRow(missing_label, self.missing)
        self.format_body.hide()
        self.format_toggle.toggled.connect(self.format_body.setVisible)
        self.format_toggle.toggled.connect(lambda expanded: self.format_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow))
        layout.addWidget(self.format_body)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.character_section = CollapsibleSection('单字染色', expanded=False)
        character_layout = QVBoxLayout(self.character_section.body)
        character_layout.setContentsMargins(0, 0, 0, 0)
        self.characters = CharacterStrip()
        self.characters.changed.connect(self._set_row_styles)
        self.characters.clear_row_requested.connect(self._clear_row_styles)
        character_layout.addWidget(self.characters)
        self.character_section.reset_requested.connect(self._clear_row_styles)
        layout.addWidget(self.character_section)
        self.region.currentIndexChanged.connect(self._show_row)
        self.items.currentRowChanged.connect(self._update_actions)
        self.items.currentRowChanged.connect(self._show_literal)
        translator.language_changed.connect(self._retranslate)
        self._retranslate()

    def set_source(self, source):
        if source == self._source:
            return
        self._source = source
        self._model, self._error = None, ''
        self._rendered_rows = {}
        self._character_region = None
        try:
            self._model = read_layout(source)
        except (ValueError, TypeError) as exc:
            self._error = str(exc)
        self._show_regions()

    def set_logo_position(self, position):
        if not self._model or self._model.get('kind') != 'footer':
            return
        model = deepcopy(self._model)
        model['logo'] = position
        try:
            source = write_layout(self._source, model)
        except (ValueError, TypeError):
            return
        if source != self._source:
            self._source, self._model = source, read_layout(source)
            self._show_row()
            self.source_changed.emit(source)

    def select_region(self, key):
        index = self.region.findData(key)
        if index >= 0:
            self.region.setCurrentIndex(index)

    def reset_region(self, baseline, key):
        if not self._model or key not in self._model['rows']:
            return
        try:
            original = read_layout(baseline)
            if key not in original['rows']:
                return
            model = deepcopy(self._model)
            model['rows'][key] = deepcopy(original['rows'][key])
            source = write_layout(self._source, model)
        except (ValueError, TypeError):
            return
        if source != self._source:
            self._source, self._model = source, model
            self._rendered_rows.pop(key, None)
            self._show_row()
            self.source_changed.emit(source)

    def adopt_style_source(self, source):
        """外围样式变化时保留不变的文字和字符选区"""
        try:
            model = read_layout(source)
        except (ValueError, TypeError):
            self.set_source(source)
            return
        if model != self._model:
            self.set_source(source)
            return
        self._source = source

    def set_rendered_rows(self, rows):
        """更新当前照片实际文本，空值立即清除旧选区"""
        self._rendered_rows = {str(key): str(value) for key, value in (rows or {}).items() if value is not None}
        self._show_characters()

    def _retranslate(self):
        separator, cursor = self.separator.text(), self.separator.cursorPosition()
        editing = self.separator.isModified()
        selected = self.field.currentData()
        self.field.clear()
        for field in FIELD_CATALOG:
            self.field.addItem(tr(field.label), field.key)
        self.field.setCurrentIndex(max(0, self.field.findData(selected)))
        with QSignalBlocker(self.missing):
            selected_missing = self.missing.currentData() or (self._model or {}).get('missing', 'hide')
            self.missing.clear()
            self.missing.addItem(tr('隐藏该字段'), 'hide')
            self.missing.addItem(tr('显示破折号'), 'dash')
            self.missing.setCurrentIndex(max(0, self.missing.findData(selected_missing)))
        self._show_regions()
        if editing:
            self.separator.setText(separator)
            self.separator.setModified(True)
            self.separator.setCursorPosition(cursor)

    def _show_regions(self):
        region = self.region.currentData()
        with QSignalBlocker(self.region):
            self.region.clear()
            for index, key in enumerate(self._model['regions'] if self._model else ()):
                label = region_title(key, index + 1)
                self.region.addItem(label, key)
            self.region.setCurrentIndex(max(0, self.region.findData(region)))
        self._show_row()
        self.message.setText(localize_error(self._error))
        self.message.setVisible(bool(self._error))

    def _show_row(self):
        index = self.items.currentRow()
        self.items.clear()
        row = self._model['rows'].get(self.region.currentData(), {}) if self._model else {}
        for item in row.get('items', ()):
            field = get_footer_field(item.get('field'))
            self.items.addItem(tr(field.label) if field else item.get('text', item.get('raw', '')))
        self.items.setCurrentRow(min(max(index, 0), self.items.count() - 1))
        self.separator.setText(row.get('separator', ''))
        with QSignalBlocker(self.missing):
            self.missing.setCurrentIndex(max(0, self.missing.findData((self._model or {}).get('missing', 'hide'))))
        self._update_actions()
        self._show_characters()
        self._show_literal()

    def _show_characters(self):
        region = self.region.currentData()
        row = self._model['rows'].get(region, {}) if self._model else {}
        changed_region = region != self._character_region
        self._character_region = region
        self.characters.set_content(self._rendered_rows.get(region, ''), row.get('char_styles', {}),
                                    row.get('highlight_rules', []), clear_selection=changed_region,
                                    has_embedded_styles=_has_character_styles(row.get('items', [])) or
                                    _has_character_styles(row.get('segment_defaults', {})))
        self.characters.setEnabled(bool(self._model and region in self._model['rows']))

    def _update_actions(self):
        index = self.items.currentRow()
        self.up.setEnabled(index > 0)
        self.down.setEnabled(0 <= index < self.items.count() - 1)
        self.remove.setEnabled(index >= 0)
        for widget in (self.field, self.add, self.separator):
            widget.setEnabled(self.region.currentIndex() >= 0)
        self.add.setEnabled(self.region.currentIndex() >= 0 and self.items.count() < 32)

    def _show_literal(self, *_):
        row = self._model['rows'].get(self.region.currentData(), {}) if self._model else {}
        index = self.items.currentRow()
        items = row.get('items', [])
        item = items[index] if 0 <= index < len(items) else {}
        with QSignalBlocker(self.literal):
            self.literal.setText(item.get('text', ''))
        field = get_footer_field(item.get('field'))
        for editor, name in ((self.prefix_input, 'prefix'), (self.suffix_input, 'suffix')):
            with QSignalBlocker(editor):
                editor.setText(str(item.get(name, getattr(field, name, ''))) if field else '')
            editor.setEnabled(field is not None)
        self.missing.setEnabled(bool(self._model))

    def _save_literal(self):
        if self.literal.isModified():
            self._edit('literal')
            self.literal.setModified(False)

    def _edit(self, action, offset=0):
        if not self._model:
            return
        model = deepcopy(self._model)
        row = model['rows'][self.region.currentData()]
        items = row['items']
        index = self.items.currentRow()
        if action == 'add_literal':
            value = self.literal.text()
            if not value:
                return
            items.append({'text': value})
            index = len(items) - 1
        elif action == 'literal' and 0 <= index < len(items) and 'text' in items[index]:
            items[index]['text'] = self.literal.text()
        elif action == 'add':
            field = get_footer_field(self.field.currentData())
            items.append({'field': field.key, 'prefix': field.prefix, 'suffix': field.suffix})
            index = len(items) - 1
        elif action == 'separator':
            row['separator'] = self.separator.text()
        elif action in ('prefix', 'suffix') and 0 <= index < len(items) and 'field' in items[index]:
            items[index][action] = (self.prefix_input if action == 'prefix' else self.suffix_input).text()
        elif action == 'missing':
            model['missing'] = self.missing.currentData()

        elif action == 'remove' and index >= 0:
            items.pop(index)
        elif action == 'move' and index >= 0 and 0 <= index + offset < len(items):
            items.insert(index + offset, items.pop(index))
            index += offset
        if model == self._model:
            return
        try:
            source = write_layout(self._source, model)
        except ValueError as exc:
            self._error = str(exc)
            self._show_regions()
            return
        self._source, self._model = source, model
        self._rendered_rows.pop(self.region.currentData(), None)
        self._show_row()
        self.items.setCurrentRow(min(index, len(items) - 1))
        self.source_changed.emit(source)

    def _set_row_styles(self, styles, rules):
        if not self._model or self.region.currentData() not in self._model['rows']:
            return
        model = deepcopy(self._model)
        row = model['rows'][self.region.currentData()]
        for key, value in (('char_styles', styles), ('highlight_rules', rules)):
            if value:
                row[key] = deepcopy(value)
            else:
                row.pop(key, None)
        if model == self._model:
            return
        try:
            source = write_layout(self._source, model)
        except ValueError as exc:
            self._error = str(exc)
            self._show_regions()
            return
        self._source, self._model = source, model
        self._show_characters()
        self.source_changed.emit(source)

    def _clear_row_styles(self):
        if not self._model or self.region.currentData() not in self._model['rows']:
            return
        region = self.region.currentData()
        try:
            source = clear_row_character_styles(self._source, region)
            model = read_layout(source)
        except ValueError as exc:
            self._error = str(exc)
            self._show_regions()
            return
        if source == self._source:
            self._show_characters()
            return
        self._source, self._model = source, model
        self._show_characters()
        self.source_changed.emit(source)
