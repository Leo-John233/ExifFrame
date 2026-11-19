"""按实际显示文字选择字符并编辑局部样式"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QRect, QSize, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QColorDialog, QComboBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton, QRubberBand, QSizePolicy,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolButton,
    QVBoxLayout, QWidget,
)

from core.configs import fonts_dir
from core.character_styles import resolve_character_styles
from .i18n import bind, tr, translator


class CharacterDelegate(QStyledItemDelegate):
    """选中时仍显示字符自身颜色"""

    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ''
        widget = styled.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, widget)
        foreground = index.data(Qt.ItemDataRole.ForegroundRole)
        color = foreground.color() if foreground is not None else styled.palette.color(QPalette.ColorRole.Text)
        painter.save()
        painter.setFont(styled.font)
        painter.setPen(color)
        painter.drawText(styled.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class CharacterGrid(QListWidget):
    """按 Unicode 码点排列字符，支持连续拖选"""

    selection_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('characterGrid')
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(CharacterDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setGridSize(QSize(32, 32))
        self.setSpacing(0)
        self.setStyleSheet('''
            QListWidget#characterGrid { background: #1B1C1E; border: 1px solid #454648; border-radius: 4px; }
            QListWidget#characterGrid::item { margin: 2px; border: 1px solid #48494B; border-radius: 3px; }
            QListWidget#characterGrid::item:hover { background: #393A3C; }
            QListWidget#characterGrid::item:selected { background: #555658; border-color: #A4A4A4; }
        ''')
        self._selected = set()
        self._anchor = None
        self._drag_start = None
        self._drag_position = None
        self._drag_linear = False
        self._drag_base = set()
        self._text = ''
        self._families = {}
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self.viewport())
        self._rubber_band.setStyleSheet('border: 1px solid #B5B5B5; background: rgba(180, 180, 180, 45);')
        self.itemSelectionChanged.connect(self._native_selection_changed)
        self.setFixedHeight(36)

    def set_text(self, text, styles=None, rules=None, *, clear_selection=False):
        """文本变化时重建网格，相同文本更新样式不破坏选区"""
        styles = styles or {}
        if text != self._text:
            self._text = text
            self._selected.clear()
            self._anchor = self._drag_start = self._drag_position = None
            self._rubber_band.hide()
            self.clear()
            for index, character in enumerate(text):
                shown = {' ': '·', '\t': '⇥', '\n': '↵', '\r': '↵'}.get(character, character)
                item = QListWidgetItem(shown)
                item.setSizeHint(QSize(30, 30))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setData(Qt.ItemDataRole.UserRole, index)
                item.setToolTip(f'{index + 1}: {character!r}')
                self.addItem(item)
            self.selection_changed.emit([])
            self._resize_height()
        elif clear_selection:
            self.clear_selection()
        effective = resolve_character_styles(text, styles, rules or [])
        for index in range(self.count()):
            style = effective[index]
            color = QColor(style.get('color', ''))
            self.item(index).setForeground(color if color.isValid() else self.palette().text())
            font = QFont(self.font())
            family = self._font_family(style.get('font', ''))
            if family:
                font.setFamily(family)
            self.item(index).setFont(font)

    def _font_family(self, name):
        if not name:
            return ''
        if name not in self._families:
            path = Path(name).expanduser()
            if not path.is_absolute():
                path = fonts_dir / path
            identifier = QFontDatabase.addApplicationFont(str(path))
            families = QFontDatabase.applicationFontFamilies(identifier) if identifier >= 0 else []
            self._families[name] = families[0] if families else ''
        return self._families[name]

    def selected_indices(self):
        return sorted(self._selected)

    def clear_selection(self):
        self._set_selection(set())
        self._anchor = self._drag_start = self._drag_position = None
        self._rubber_band.hide()

    def _native_selection_changed(self):
        """键盘导航与自定义鼠标选择共享同一组索引"""
        selected = {self.row(item) for item in self.selectedItems()}
        if selected != self._selected:
            self._selected = selected
            if self.currentRow() >= 0:
                self._anchor = self.currentRow()
            self.selection_changed.emit(self.selected_indices())

    def _set_selection(self, selected):
        selected = {index for index in selected if 0 <= index < self.count()}
        if selected == self._selected:
            return
        with QSignalBlocker(self):
            for index in self._selected.symmetric_difference(selected):
                self.item(index).setSelected(index in selected)
        self._selected = selected
        self.selection_changed.emit(self.selected_indices())

    def _resize_height(self):
        columns = max(1, self.viewport().width() // self.gridSize().width())
        rows = max(1, (self.count() + columns - 1) // columns)
        self.setFixedHeight(min(rows, 5) * self.gridSize().height() + 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self, self._resize_height)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() != Qt.MouseButton.LeftButton or item is None:
            super().mousePressEvent(event)
            return
        index = self.row(item)
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None:
            start = self._anchor
            selected = set(range(min(start, index), max(start, index) + 1))
            self._drag_linear = True
        elif modifiers & Qt.KeyboardModifier.ControlModifier:
            start = index
            selected = self._selected.symmetric_difference({index})
            self._anchor = index
            self._drag_linear = False
        else:
            start = index
            selected = {index}
            self._anchor = index
            self._drag_linear = False
        self._drag_start = start
        self._drag_position = event.position().toPoint()
        self._drag_base = self._selected - {index} if modifiers & Qt.KeyboardModifier.ControlModifier else set()
        self._set_selection(selected)
        self.setCurrentRow(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.setFocus()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            item = self.itemAt(event.position().toPoint())
            if self._drag_linear:
                if item is not None:
                    end = self.row(item)
                    selected = set(range(min(self._drag_start, end), max(self._drag_start, end) + 1))
                    self._set_selection(self._drag_base | selected)
            else:
                rect = QRect(self._drag_position, event.position().toPoint()).normalized()
                self._rubber_band.setGeometry(rect)
                self._rubber_band.show()
                selected = {index for index in range(self.count())
                            if self.visualItemRect(self.item(index)).intersects(rect)}
                self._set_selection(self._drag_base | selected)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self._drag_position = None
            self._rubber_band.hide()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CharacterStrip(QWidget):
    """编辑选中字的颜色、字体及可选文本匹配规则"""

    changed = Signal(object, object)
    clear_row_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ''
        self._styles = {}
        self._rules = []
        self._has_embedded_styles = False
        self._color = '#E60012'
        self._error = ''
        self._font_value = ''
        self._swatches = {}
        self._font_files = self._find_fonts()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.empty = bind(QLabel(), '选择照片后显示文字')
        self.empty.setObjectName('secondaryText')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.grid = CharacterGrid()
        self.grid.selection_changed.connect(self._selection_changed)
        layout.addWidget(self.grid)
        self.selection_label = QLabel()
        self.selection_label.setObjectName('secondaryText')
        layout.addWidget(self.selection_label)

        palette = QHBoxLayout()
        palette.setSpacing(4)
        self._palette_names = {'#E60012': '徕卡红', '#FF6A00': '哈苏橙', '#FFE600': '尼康黄',
                               '#00A859': '富士绿', '#8C8C8C': '灰色', '#FFFFFF': '白色', '#202020': '黑色'}
        for color in self._palette_names:
            button = QToolButton()
            button.setFixedSize(26, 24)
            button.clicked.connect(lambda checked=False, value=color: self._choose_color(value))
            self._swatches[color] = button
            palette.addWidget(button)
        self.custom_color = QPushButton('…')
        self.custom_color.setFixedWidth(32)
        bind(self.custom_color, '自定义颜色…', 'setToolTip')
        self.custom_color.clicked.connect(self._custom_color)
        palette.addWidget(self.custom_color)
        palette.addStretch()
        layout.addLayout(palette)
        self._update_palette()

        layout.addWidget(bind(QLabel(), '字符字体'))
        font_row = QHBoxLayout()
        self.font = QComboBox()
        self.font.setMinimumWidth(0)
        self.font.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.font.currentIndexChanged.connect(self._font_changed)
        font_row.addWidget(self.font, 1)
        self.apply_font = bind(QPushButton(), '应用字体')
        self.apply_font.clicked.connect(self._apply_font)
        font_row.addWidget(self.apply_font)
        layout.addLayout(font_row)
        clear_row = QHBoxLayout()
        self.clear_selected = bind(QPushButton(), '清除选中样式')
        bind(self.clear_selected, '规则高亮需单独删除', 'setToolTip')
        self.clear_selected.clicked.connect(self._clear_selected)
        self.clear_line = bind(QPushButton(), '清除本行全部样式')
        self.clear_line.clicked.connect(self._clear_line)
        clear_row.addWidget(self.clear_selected)
        clear_row.addWidget(self.clear_line)
        layout.addLayout(clear_row)

        self.rule_toggle = QToolButton()
        self.rule_toggle.setCheckable(True)
        self.rule_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.rule_toggle.setArrowType(Qt.ArrowType.RightArrow)
        bind(self.rule_toggle, '规则高亮')
        layout.addWidget(self.rule_toggle)
        self.rule_body = QWidget()
        rules_layout = QVBoxLayout(self.rule_body)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        rules_layout.setSpacing(5)
        self.pattern = QLineEdit()
        bind(self.pattern, '正则表达式', 'setPlaceholderText')
        rules_layout.addWidget(self.pattern)
        rule_actions = QHBoxLayout()
        self.rule_from_selection = bind(QPushButton(), '按选中文字添加')
        self.rule_from_selection.clicked.connect(self._rule_selected)
        self.rule_add = bind(QPushButton(), '添加规则')
        self.rule_add.clicked.connect(self._add_rule)
        rule_actions.addWidget(self.rule_from_selection)
        rule_actions.addWidget(self.rule_add)
        rules_layout.addLayout(rule_actions)
        self.rules = QListWidget()
        self.rules.setFixedHeight(70)
        self.rules.currentRowChanged.connect(self._update_actions)
        rules_layout.addWidget(self.rules)
        self.rule_remove = bind(QPushButton(), '删除规则')
        self.rule_remove.clicked.connect(self._remove_rule)
        rules_layout.addWidget(self.rule_remove)
        for button in (self.apply_font, self.clear_selected, self.clear_line, self.rule_from_selection, self.rule_add):
            button.setMinimumWidth(0)
            button.setStyleSheet('padding-left: 2px; padding-right: 2px;')
        self.message = QLabel()
        self.message.setObjectName('secondaryText')
        self.message.setWordWrap(True)
        rules_layout.addWidget(self.message)
        self.rule_body.hide()
        self.rule_toggle.toggled.connect(self.rule_body.setVisible)
        self.rule_toggle.toggled.connect(lambda value: self.rule_toggle.setArrowType(
            Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow))
        layout.addWidget(self.rule_body)
        translator.language_changed.connect(self._retranslate)
        self._retranslate()
        self.set_content('', {}, [])

    @staticmethod
    def _find_fonts():
        try:
            return [(path.stem, path.name) for path in sorted(fonts_dir.iterdir())
                    if path.suffix.lower() in {'.ttf', '.otf', '.ttc'} and path.is_file()]
        except OSError:
            return []

    def _retranslate(self):
        selected = self.font.currentData() or ''
        with QSignalBlocker(self.font):
            self.font.clear()
            self.font.addItem(tr('跟随整段'), '')
            for label, value in self._font_files:
                self.font.addItem(label, value)
            if selected and self.font.findData(selected) < 0:
                self.font.addItem(Path(selected).name, selected)
            self.font.addItem(tr('选择字体…'), '__choose__')
            self.font.setCurrentIndex(max(0, self.font.findData(selected)))
        self._selection_changed(self.grid.selected_indices())
        for color, button in self._swatches.items():
            label = f'{tr(self._palette_names[color])} {color}'
            button.setToolTip(label)
            button.setAccessibleName(label)
        if self._error:
            self.message.setText(tr(self._error))

    def set_content(self, text, styles=None, rules=None, *, clear_selection=False, has_embedded_styles=False):
        """替换当前行显示内容与样式，外部刷新不发修改信号"""
        self._text = str(text or '')
        self._styles = deepcopy(styles or {})
        self._rules = deepcopy(rules or [])
        self._has_embedded_styles = bool(has_embedded_styles)
        self.empty.setVisible(not self._text)
        self.grid.setVisible(bool(self._text))
        self.grid.set_text(self._text, self._styles, self._rules, clear_selection=clear_selection)
        self._show_rules()
        self._update_actions()

    def _selection_changed(self, indices):
        self.selection_label.setText(tr('已选 {count} 个字符', count=len(indices)))
        self._update_actions()

    def _update_actions(self, *args):
        selected = self.grid.selected_indices()
        self.apply_font.setEnabled(bool(selected))
        self.clear_selected.setEnabled(bool(selected))
        self.clear_line.setEnabled(bool(self._styles or self._rules or self._has_embedded_styles))
        contiguous = bool(selected) and selected == list(range(selected[0], selected[-1] + 1))
        self.rule_from_selection.setEnabled(contiguous)
        self.rule_from_selection.setToolTip('' if contiguous else tr('请选择连续文字'))
        self.rule_remove.setEnabled(self.rules.currentRow() >= 0)

    def _update_palette(self):
        for color, button in self._swatches.items():
            border = '#D0D0D0' if color == self._color else '#666666'
            button.setStyleSheet(f'background: {color}; border: 2px solid {border}; border-radius: 4px;')

    def _choose_color(self, color):
        self._color = color
        self._update_palette()
        self._apply('color', color)

    def _custom_color(self):
        color = QColorDialog.getColor(QColor(self._color), self)
        if color.isValid():
            self._choose_color(color.name())

    def _font_changed(self, index):
        value = self.font.currentData() or ''
        if value != '__choose__':
            self._font_value = value
            return
        previous = self._font_value
        path, _ = QFileDialog.getOpenFileName(self, tr('选择字体'), '', tr('字体文件 (*.ttf *.otf *.ttc)'))
        with QSignalBlocker(self.font):
            if path:
                value = str(Path(path).resolve())
                existing = self.font.findData(value)
                if existing < 0:
                    existing = self.font.count() - 1
                    self.font.insertItem(existing, Path(value).name, value)
                self.font.setCurrentIndex(existing)
                self._font_value = value
            else:
                self.font.setCurrentIndex(max(0, self.font.findData(previous)))

    def _apply_font(self):
        self._apply('font', self.font.currentData() or None)

    def _apply(self, key, value):
        indices = self.grid.selected_indices()
        if not indices:
            return
        styles = deepcopy(self._styles)
        for index in indices:
            name = str(index)
            style = dict(styles.get(name) or {})
            if value is None:
                style.pop(key, None)
            else:
                style[key] = value
            if style:
                styles[name] = style
            else:
                styles.pop(name, None)
        if styles != self._styles:
            self._styles = styles
            self.grid.set_text(self._text, styles, self._rules)
            self._update_actions()
            self.changed.emit(deepcopy(styles), deepcopy(self._rules))

    def _clear_selected(self):
        styles = deepcopy(self._styles)
        for index in self.grid.selected_indices():
            styles.pop(str(index), None)
        if styles != self._styles:
            self._styles = styles
            self.grid.set_text(self._text, styles, self._rules)
            self._update_actions()
            self.changed.emit(deepcopy(styles), deepcopy(self._rules))

    def _clear_line(self):
        if self._styles or self._rules or self._has_embedded_styles:
            self._styles = {}
            self._rules = []
            self._has_embedded_styles = False
            self.grid.set_text(self._text, {}, [])
            self._show_rules()
            self._update_actions()
            self.clear_row_requested.emit()

    def _rule_selected(self):
        indices = self.grid.selected_indices()
        if not indices or indices != list(range(indices[0], indices[-1] + 1)):
            return
        pattern = re.escape(''.join(self._text[index] for index in indices))
        effective = resolve_character_styles(self._text, self._styles, self._rules)
        common = {key: effective[indices[0]][key] for key in ('color', 'font')
                  if effective[indices[0]].get(key)
                  and all(effective[index].get(key) == effective[indices[0]][key] for index in indices)}
        if not common:
            common['color'] = self._color
            font = self.font.currentData()
            if font and font != '__choose__':
                common['font'] = font
        styles = deepcopy(self._styles)
        for index in indices:
            name = str(index)
            style = dict(styles.get(name) or {})
            for key, value in common.items():
                if style.get(key) == value:
                    style.pop(key)
            if style:
                styles[name] = style
            else:
                styles.pop(name, None)
        self._styles = styles
        self.pattern.setText(pattern)
        self._add_rule(style=common)

    def _add_rule(self, *, style=None):
        pattern = self.pattern.text()
        try:
            if not pattern:
                raise ValueError('empty')
            re.compile(pattern)
        except (re.error, ValueError, OverflowError, RecursionError):
            self._error = '正则表达式无效'
            self.message.setText(tr(self._error))
            return
        if style is None:
            style = {'color': self._color}
            font = self.font.currentData()
            if font and font != '__choose__':
                style['font'] = font
        rule = {'pattern': pattern, **style}
        self._rules.append(rule)
        self._error = ''
        self.message.clear()
        self.grid.set_text(self._text, self._styles, self._rules)
        self._show_rules()
        self.changed.emit(deepcopy(self._styles), deepcopy(self._rules))

    def _show_rules(self):
        current = self.rules.currentRow()
        self.rules.clear()
        for rule in self._rules:
            label = str(rule.get('pattern', ''))
            color = rule.get('color')
            if color:
                label += f'  ·  {color}'
            self.rules.addItem(label)
        if self._rules:
            self.rules.setCurrentRow(min(max(0, current), len(self._rules) - 1))
        self._update_actions()

    def _remove_rule(self):
        index = self.rules.currentRow()
        if 0 <= index < len(self._rules):
            self._rules.pop(index)
            self.grid.set_text(self._text, self._styles, self._rules)
            self._show_rules()
            self.changed.emit(deepcopy(self._styles), deepcopy(self._rules))
