"""按区域组合底部信息并保留完整模板源码"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.desktop_service import write_template
from core.footer import FIELD_CATALOG, REGION_LABELS, FooterError, normalize_layout, preview_rows, read_layout, write_layout
from studio.i18n import bind, localize_error, register_translations, tr, translator


register_translations({
    '修改照片信息…': 'Edit photo information…',
    '底部信息组合': 'Compose footer information', '可添加字段': 'Available fields',
    '搜索字段': 'Search fields', '双击字段添加到当前区域': 'Double-click a field to add it to the selected region',
    '添加所选字段': 'Add selected field', '添加自定义文字': 'Add custom text',
    '选择要编辑的区域': 'Choose a region to edit', '文字区域 {number}': 'Text region {number}',
    '左上': 'Top left', '左下': 'Bottom left', '右上': 'Top right', '右下': 'Bottom right',
    '左上区域': 'Top left', '左下区域': 'Bottom left', '右上区域': 'Top right', '右下区域': 'Bottom right',
    '当前区域：{region}': 'Selected region: {region}', '上移': 'Move up', '下移': 'Move down',
    '删除': 'Remove', '拖动字段调整顺序，也可使用上移和下移按钮': 'Drag fields to reorder, or use Move up and Move down',
    '此区域还没有文字，从左侧添加字段': 'This region is empty; add fields from the left',
    '选中内容': 'Selected item', '前面文字': 'Text before', '后面文字': 'Text after',
    '自定义文字': 'Custom text', '文字内容': 'Text content', '自定义内容': 'Custom content',
    '选择一个字段以修改前后文字': 'Select a field to edit its surrounding text',
    '保留原有自定义表达式，可在高级源码中修改': 'Original custom expression preserved; edit it in Advanced source',
    '示例：{value}': 'Example: {value}', '区域内分隔符': 'Separator in this region',
    '空格': 'Space', '宽空格': 'Wide space', '中点 ·': 'Middle dot ·',
    '竖线 |': 'Vertical bar |', '逗号 ,': 'Comma ,', '无分隔': 'None',
    '自定义…': 'Custom…', '输入分隔符': 'Enter separator',
    '信息缺失时': 'When information is missing', '隐藏该字段': 'Hide the field',
    '显示破折号': 'Show a dash', '品牌标识位置': 'Brand logo position',
    '沿用模板': 'Keep template setting', '隐藏': 'Hidden', '左侧': 'Left', '居中': 'Center', '右侧': 'Right',
    '此样式没有底部边框，标识位置由原模板控制': 'This style has no footer frame; the original template controls its logo',
    '示例预览': 'Example preview', '照片信息预览': 'Photo information preview',
    '选择区域后，字段会按列表顺序排列': 'Fields appear in list order within the selected region',
    '（空）': '(empty)', '字段与文字': 'Fields and text',
    '模板名称': 'Template name', '未命名模板': 'Untitled template',
    '{name}{dirty} — 底部信息组合': '{name}{dirty} — Footer composer',
    '应用预览': 'Apply preview', '保存模板': 'Save template', '另存为': 'Save as',
    '高级源码…': 'Advanced source…', '关闭': 'Close',
    '组合完成后可应用到当前照片预览': 'Apply the composition to preview it on the current photo',
    '组合已修改，尚未保存': 'Composition changed; not yet saved',
    '已应用到照片预览，模板尚未保存': 'Applied to photo preview; template has not been saved',
    '模板已保存：{name}': 'Template saved: {name}', '保存失败：{error}': 'Save failed: {error}',
    '无法组合此模板：{error}': 'Cannot compose this template: {error}',
    '预览失败：{error}': 'Preview failed: {error}', '请填写模板名称': 'Enter a template name',
    '另存为模板': 'Save template as', '{name} 副本': '{name} copy', '新模板': 'New template',
    '模板尚未保存': 'Unsaved template', '要保存对“{name}”的修改吗？': 'Save changes to “{name}”?',
    '相机型号': 'Camera model', '相机品牌': 'Camera brand', '相机制造商': 'Camera manufacturer',
    '镜头型号': 'Lens model', '镜头品牌': 'Lens brand', '焦距': 'Focal length',
    '实际焦距': 'Focal length', '等效焦距': '35mm-equivalent focal length', '35mm 等效焦距': '35mm-equivalent focal length',
    '光圈': 'Aperture', '快门': 'Shutter speed', '快门速度': 'Shutter speed', 'ISO': 'ISO', '感光度': 'ISO',
    '曝光补偿': 'Exposure compensation', '拍摄日期': 'Capture date', '拍摄时间': 'Capture time',
    '日期': 'Date', '时间': 'Time', '日期和时间': 'Date and time', '拍摄日期与时间': 'Capture date and time',
    '摄影师': 'Photographer', '作者': 'Author', '版权': 'Copyright', '版权声明': 'Copyright',
    '描述': 'Description', '照片描述': 'Image description', '备注': 'Comment', '用户备注': 'User comment',
    '软件': 'Software', '处理软件': 'Software', '评分': 'Rating', '星级评分': 'Rating',
    '文件名': 'File name', '文件夹名': 'Folder name', '文件夹': 'Folder',
    '纬度': 'Latitude', '经度': 'Longitude', '海拔': 'Altitude', '海拔高度': 'Altitude',
    '时区': 'Time zone', '时区偏移': 'Time zone offset', '闪光灯': 'Flash', '白平衡': 'White balance',
    '相机与镜头': 'Camera and lens', '曝光参数': 'Exposure', '时间与位置': 'Time and location',
    '创作者与版权': 'Creator and copyright', '文件信息': 'File information',
    '设备': 'Equipment', '拍摄参数': 'Exposure', '拍摄信息': 'Capture information',
    '创作信息': 'Creator information', '其他信息': 'Other information', '位置': 'Location',
    '作者与文字': 'Creator and text', '文件': 'File', '文件名称': 'File name',
    '文件夹名称': 'Folder name', '日期与时间': 'Date and time',
    '当前模板需要使用高级源码编辑': 'Use Advanced source to edit this template',
    '模板中没有可组合的文字区域': 'This template has no text regions to compose',
    '底部信息区域无效': 'Invalid footer region', '标识位置无效': 'Invalid logo position',
    '缺失值处理方式无效': 'Invalid missing-value setting', '分隔符过长': 'The separator is too long',
    '每个区域最多放置 32 项信息': 'Each region can contain up to 32 items',
    '底部信息字段无效': 'Invalid footer field', '自定义文字过长': 'Custom text is too long',
    '文字区必须保留在原有版式内': 'Text regions must stay within the original layout',
})


def _error_text(error):
    return tr(str(error)) if isinstance(error, FooterError) else localize_error(error)


class _ItemsList(QListWidget):
    """拖放结束后一次性同步行内顺序"""

    reordered = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        if event.isAccepted():
            self.reordered.emit()


class FooterPanel(QWidget):
    """可嵌入新建流程的可视化底部编辑面板"""

    changed = Signal()

    SEPARATORS = (('空格', ' '), ('宽空格', '  '), ('中点 ·', ' · '),
                  ('竖线 |', ' | '), ('逗号 ,', ', '), ('无分隔', ''), ('自定义…', None))
    LOGOS = (('沿用模板', 'keep'), ('隐藏', 'none'), ('左侧', 'left'), ('居中', 'center'), ('右侧', 'right'))
    MISSING = (('隐藏该字段', 'hide'), ('显示破折号', 'dash'))

    def __init__(self, source: str, parent=None, metadata=None, filename='', file_dir=''):
        super().__init__(parent)
        self._source = source
        self._layout = {}
        self._region = ''
        self._load_error = None
        self._updating = False
        self._metadata = deepcopy(metadata) if metadata is not None else None
        self._filename = filename
        self._file_dir = file_dir
        self._fields = {field.key: field for field in FIELD_CATALOG}
        self._region_buttons = {}
        self._preview_labels = {}
        self._build_ui()
        self.set_source(source)
        translator.language_changed.connect(self.retranslate_ui)

    def _button(self, label, callback, parent=None):
        button = QPushButton(parent)
        bind(button, label)
        button.setAutoDefault(False)
        button.clicked.connect(callback)
        return button

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        splitter = QSplitter()
        library = QWidget()
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(0, 0, 6, 0)
        heading = QLabel()
        bind(heading, '可添加字段')
        library_layout.addWidget(heading)
        self.search = QLineEdit()
        bind(self.search, '搜索字段', 'setPlaceholderText')
        self.search.textChanged.connect(self._filter_fields)
        library_layout.addWidget(self.search)
        self.catalog = QTreeWidget()
        self.catalog.setObjectName('footerFieldCatalog')
        self.catalog.setHeaderHidden(True)
        self.catalog.setIndentation(14)
        self.catalog.setMinimumWidth(170)
        bind(self.catalog, '双击字段添加到当前区域', 'setToolTip')
        self.catalog.itemDoubleClicked.connect(lambda item, column: self.add_field(item.data(0, Qt.ItemDataRole.UserRole)))
        self._catalog_groups = {}
        self._catalog_items = {}
        for field in FIELD_CATALOG:
            if field.group not in self._catalog_groups:
                group = QTreeWidgetItem(self.catalog)
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                group.setExpanded(True)
                self._catalog_groups[field.group] = group
            item = QTreeWidgetItem(self._catalog_groups[field.group])
            item.setData(0, Qt.ItemDataRole.UserRole, field.key)
            self._catalog_items[field.key] = item
        library_layout.addWidget(self.catalog, 1)
        self.add_button = self._button('添加所选字段', self._add_selected)
        library_layout.addWidget(self.add_button)
        self.custom_button = self._button('添加自定义文字', self.add_text)
        library_layout.addWidget(self.custom_button)
        splitter.addWidget(library)

        editing = QWidget()
        edit_layout = QVBoxLayout(editing)
        edit_layout.setContentsMargins(6, 0, 0, 0)
        self.region_group = QGroupBox()
        bind(self.region_group, '选择要编辑的区域', 'setTitle')
        self.region_grid = QGridLayout(self.region_group)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        edit_layout.addWidget(self.region_group)
        self.row_heading = QLabel()
        edit_layout.addWidget(self.row_heading)
        self.items = _ItemsList()
        self.items.setObjectName('footerRegionItems')
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.items.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.setMinimumHeight(110)
        self.items.setSpacing(1)
        bind(self.items, '拖动字段调整顺序，也可使用上移和下移按钮', 'setToolTip')
        self.items.currentRowChanged.connect(self._select_item)
        self.items.reordered.connect(self._reordered)
        edit_layout.addWidget(self.items, 1)
        self.empty_label = QLabel()
        bind(self.empty_label, '此区域还没有文字，从左侧添加字段')
        self.empty_label.setObjectName('secondaryText')
        edit_layout.addWidget(self.empty_label)
        move_row = QHBoxLayout()
        self.up_button = self._button('上移', lambda: self.move_item(-1))
        self.down_button = self._button('下移', lambda: self.move_item(1))
        self.remove_button = self._button('删除', self.remove_item)
        for button in (self.up_button, self.down_button, self.remove_button):
            move_row.addWidget(button)
        move_row.addStretch()
        edit_layout.addLayout(move_row)

        self.details = QGroupBox()
        bind(self.details, '选中内容', 'setTitle')
        form = QFormLayout(self.details)
        self.item_hint = QLabel()
        self.item_hint.setWordWrap(True)
        form.addRow(self.item_hint)
        self.prefix_input = QLineEdit()
        self.suffix_input = QLineEdit()
        self.text_input = QLineEdit()
        self.prefix_label = QLabel()
        self.suffix_label = QLabel()
        self.text_label = QLabel()
        bind(self.prefix_label, '前面文字')
        bind(self.suffix_label, '后面文字')
        bind(self.text_label, '文字内容')
        form.addRow(self.prefix_label, self.prefix_input)
        form.addRow(self.suffix_label, self.suffix_input)
        form.addRow(self.text_label, self.text_input)
        self.prefix_input.textEdited.connect(lambda value: self._edit_item('prefix', value))
        self.suffix_input.textEdited.connect(lambda value: self._edit_item('suffix', value))
        self.text_input.textEdited.connect(lambda value: self._edit_item('text', value))
        edit_layout.addWidget(self.details)

        options = QGridLayout()
        separator_label = QLabel()
        bind(separator_label, '区域内分隔符')
        self.separator = QComboBox()
        for label, value in self.SEPARATORS:
            self.separator.addItem(tr(label), value)
        self.separator.currentIndexChanged.connect(self._separator_changed)
        self.custom_separator = QLineEdit()
        bind(self.custom_separator, '输入分隔符', 'setPlaceholderText')
        self.custom_separator.textEdited.connect(self._custom_separator_changed)
        options.addWidget(separator_label, 0, 0)
        options.addWidget(self.separator, 0, 1)
        options.addWidget(self.custom_separator, 0, 2)
        missing_label = QLabel()
        bind(missing_label, '信息缺失时')
        self.missing = QComboBox()
        for label, value in self.MISSING:
            self.missing.addItem(tr(label), value)
        self.missing.currentIndexChanged.connect(lambda: self._global_option('missing', self.missing.currentData()))
        options.addWidget(missing_label, 1, 0)
        options.addWidget(self.missing, 1, 1, 1, 2)
        logo_label = QLabel()
        bind(logo_label, '品牌标识位置')
        self.logo = QComboBox()
        for label, value in self.LOGOS:
            self.logo.addItem(tr(label), value)
        self.logo.currentIndexChanged.connect(lambda: self._global_option('logo', self.logo.currentData()))
        options.addWidget(logo_label, 2, 0)
        options.addWidget(self.logo, 2, 1, 1, 2)
        options.setColumnStretch(1, 1)
        options.setColumnStretch(2, 1)
        edit_layout.addLayout(options)
        splitter.addWidget(editing)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 600])
        layout.addWidget(splitter, 1)

        self.preview_group = QGroupBox()
        self.preview_grid = QGridLayout(self.preview_group)
        layout.addWidget(self.preview_group)
        self.error_label = QLabel()
        self.error_label.setObjectName('errorText')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

    def set_source(self, source: str) -> None:
        """重新读入源码时不广播用户修改事件"""
        self._source = source
        self._updating = True
        try:
            self._layout = deepcopy(read_layout(source))
            self._load_error = None
        except Exception as exc:
            self._load_error = exc
            self._layout = {'version': 1, 'kind': 'overlay', 'regions': [], 'rows': {}, 'logo': 'keep', 'missing': 'hide'}
        regions = self._layout.get('regions', [])
        if self._region not in regions:
            self._region = regions[0] if regions else ''
        self._rebuild_regions()
        self.logo.setCurrentIndex(max(0, self.logo.findData(self._layout.get('logo', 'keep'))))
        self.logo.setEnabled(self._layout.get('kind') == 'footer')
        self.missing.setCurrentIndex(max(0, self.missing.findData(self._layout.get('missing', 'hide'))))
        self.missing.setEnabled(bool(regions))
        self._updating = False
        self._refresh_items()
        self.retranslate_ui()

    def layout_data(self) -> dict:
        return deepcopy(self._layout)

    def set_metadata(self, metadata, filename=None, file_dir=None):
        """仅刷新示例数据，保留字段组合且不广播修改"""
        self._metadata = deepcopy(metadata) if metadata is not None else None
        if filename is not None:
            self._filename = filename
        if file_dir is not None:
            self._file_dir = file_dir
        self.preview_group.setTitle(tr('示例预览' if self._metadata is None else '照片信息预览'))
        self._refresh_preview()

    def composed_source(self) -> str:
        if self._load_error is not None:
            raise self._load_error
        return write_layout(self._source, normalize_layout(self.layout_data()))

    def _region_label(self, region):
        if region in REGION_LABELS:
            return tr(REGION_LABELS[region])
        if region.startswith('text_') and region[5:].isdigit():
            return tr('文字区域 {number}', number=int(region[5:]) + 1)
        return region

    def _clear_grid(self, grid):
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def _rebuild_regions(self):
        for button in self.button_group.buttons():
            self.button_group.removeButton(button)
        self._clear_grid(self.region_grid)
        self._clear_grid(self.preview_grid)
        self._region_buttons.clear()
        self._preview_labels.clear()
        positions = {'left_top': (0, 0), 'right_top': (0, 1), 'left_bottom': (1, 0), 'right_bottom': (1, 1)}
        for index, region in enumerate(self._layout.get('regions', [])):
            row, column = positions.get(region, divmod(index, 2))
            button = QToolButton()
            button.setCheckable(True)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            button.setMinimumHeight(32)
            button.clicked.connect(lambda checked=False, region=region: self.select_region(region))
            self.button_group.addButton(button)
            self.region_grid.addWidget(button, row, column)
            self._region_buttons[region] = button
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(6, 3, 6, 3)
            title = QLabel()
            title.setObjectName('secondaryText')
            text = QLabel()
            text.setWordWrap(True)
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            text.setMinimumHeight(20)
            box_layout.addWidget(title)
            box_layout.addWidget(text)
            self.preview_grid.addWidget(box, row, column)
            self._preview_labels[region] = (title, text)
        self.preview_grid.setColumnStretch(0, 1)
        self.preview_grid.setColumnStretch(1, 1)

    def select_region(self, region):
        if region not in self._layout.get('regions', []):
            return
        self._region = region
        self._refresh_items()

    def _row(self):
        return self._layout.get('rows', {}).get(self._region, {})

    def _item_label(self, item):
        field = self._fields.get(item.get('field'))
        if field:
            return f"{tr(field.label)}    {item.get('prefix', field.prefix)}{field.example}{item.get('suffix', field.suffix)}"
        if 'text' in item:
            return f"{tr('自定义文字')}    {item['text']}"
        return tr('自定义内容')

    def _refresh_items(self, selection=0):
        self._updating = True
        self.items.clear()
        for item in self._row().get('items', []):
            entry = QListWidgetItem(self._item_label(item), self.items)
            entry.setData(Qt.ItemDataRole.UserRole, deepcopy(item))
            entry.setToolTip(self._item_label(item))
            entry.setSizeHint(QSize(100, 24))
        if self.items.count():
            self.items.setCurrentRow(max(0, min(selection, self.items.count() - 1)))
        self.empty_label.setVisible(not self.items.count())
        separator = self._row().get('separator', ' ')
        index = self.separator.findData(separator)
        if index < 0:
            index = len(self.SEPARATORS) - 1
        self.separator.setCurrentIndex(index)
        self.custom_separator.setText(separator)
        self.custom_separator.setVisible(index == len(self.SEPARATORS) - 1)
        self.separator.setEnabled(bool(self._region))
        self.custom_separator.setEnabled(bool(self._region))
        self.add_button.setEnabled(bool(self._region))
        self.custom_button.setEnabled(bool(self._region))
        self.row_heading.setText(tr('当前区域：{region}', region=self._region_label(self._region)) if self._region else tr('字段与文字'))
        for region, button in self._region_buttons.items():
            button.setChecked(region == self._region)
        self._updating = False
        self._select_item(self.items.currentRow())
        self._refresh_preview()

    def _select_item(self, index):
        if self._updating:
            return
        values = self._row().get('items', [])
        item = values[index] if 0 <= index < len(values) else None
        field = self._fields.get(item.get('field')) if item else None
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < len(values) - 1)
        self.remove_button.setEnabled(item is not None)
        text_item = item is not None and 'text' in item
        for widget in (self.prefix_input, self.prefix_label, self.suffix_input, self.suffix_label):
            widget.setVisible(field is not None)
        for widget in (self.text_input, self.text_label):
            widget.setVisible(text_item)
        self.prefix_input.setText(str(item.get('prefix', field.prefix if field else '')) if item else '')
        self.suffix_input.setText(str(item.get('suffix', field.suffix if field else '')) if item else '')
        self.text_input.setText(str(item.get('text', '')) if item else '')
        if field:
            self.item_hint.setText(tr('示例：{value}', value=f"{item.get('prefix', field.prefix)}{field.example}{item.get('suffix', field.suffix)}"))
        elif text_item:
            self.item_hint.setText(tr('自定义文字'))
        elif item:
            self.item_hint.setText(tr('保留原有自定义表达式，可在高级源码中修改'))
        else:
            self.item_hint.setText(tr('选择一个字段以修改前后文字'))

    def _filter_fields(self):
        text = self.search.text().strip().casefold()
        for key, item in self._catalog_items.items():
            field = self._fields[key]
            item.setHidden(bool(text) and text not in f'{tr(field.label)} {field.label} {key} {field.example}'.casefold())
        for group in self._catalog_groups.values():
            group.setHidden(all(group.child(i).isHidden() for i in range(group.childCount())))

    def _add_selected(self):
        item = self.catalog.currentItem()
        if item:
            self.add_field(item.data(0, Qt.ItemDataRole.UserRole))

    def add_field(self, key):
        field = self._fields.get(key)
        if not field or not self._region:
            return
        items = self._row().setdefault('items', [])
        items.append({'field': key, 'prefix': field.prefix, 'suffix': field.suffix})
        self._refresh_items(len(items) - 1)
        self._changed()

    def add_text(self):
        if not self._region:
            return
        items = self._row().setdefault('items', [])
        items.append({'text': ''})
        self._refresh_items(len(items) - 1)
        self.text_input.setFocus()
        self._changed()

    def _edit_item(self, key, value):
        if self._updating:
            return
        index = self.items.currentRow()
        values = self._row().get('items', [])
        if not 0 <= index < len(values):
            return
        field = self._fields.get(values[index].get('field'))
        default = getattr(field, key, '') if field and key in ('prefix', 'suffix') else ''
        if values[index].get(key, default) == value:
            return
        values[index][key] = value
        entry = self.items.item(index)
        entry.setText(self._item_label(values[index]))
        entry.setToolTip(self._item_label(values[index]))
        entry.setData(Qt.ItemDataRole.UserRole, deepcopy(values[index]))
        if field:
            self.item_hint.setText(tr('示例：{value}', value=f"{values[index].get('prefix', field.prefix)}{field.example}{values[index].get('suffix', field.suffix)}"))
        self._changed()

    def move_item(self, direction):
        index = self.items.currentRow()
        values = self._row().get('items', [])
        target = index + direction
        if not 0 <= index < len(values) or not 0 <= target < len(values):
            return
        values[index], values[target] = values[target], values[index]
        self._refresh_items(target)
        self._changed()

    def remove_item(self):
        index = self.items.currentRow()
        values = self._row().get('items', [])
        if not 0 <= index < len(values):
            return
        del values[index]
        self._refresh_items(index)
        self._changed()

    def _reordered(self):
        if self._updating or not self._region:
            return
        self._row()['items'] = [deepcopy(self.items.item(index).data(Qt.ItemDataRole.UserRole)) for index in range(self.items.count())]
        self._select_item(self.items.currentRow())
        self._changed()

    def _separator_changed(self):
        if self._updating or not self._region:
            return
        value = self.separator.currentData()
        self.custom_separator.setVisible(value is None)
        if value is None:
            self.custom_separator.setFocus()
            value = self.custom_separator.text()
        else:
            self.custom_separator.setText(value)
        self._custom_separator_changed(value)

    def _custom_separator_changed(self, value):
        if self._updating or not self._region or self._row().get('separator', ' ') == value:
            return
        self._row()['separator'] = value
        self._changed()

    def _global_option(self, key, value):
        if self._updating or value is None or self._layout.get(key) == value:
            return
        self._layout[key] = value
        self._changed()

    def _changed(self):
        self._refresh_preview()
        self.changed.emit()

    def _refresh_preview(self):
        error = self._load_error
        rows = {}
        if error is None:
            try:
                rows = preview_rows(self.layout_data(), metadata=self._metadata, filename=self._filename, file_dir=self._file_dir)
            except Exception as exc:
                error = exc
        for region, (title, label) in self._preview_labels.items():
            title.setText(self._region_label(region))
            text = str(rows.get(region, ''))
            label.setText(text or tr('（空）'))
            label.setToolTip(text)
        self.error_label.setVisible(error is not None)
        self.error_label.setText(tr('无法组合此模板：{error}', error=_error_text(error)) if error else '')

    def retranslate_ui(self):
        selected = self.items.currentRow()
        for source, item in self._catalog_groups.items():
            item.setText(0, tr(source))
        for key, item in self._catalog_items.items():
            field = self._fields[key]
            item.setText(0, tr(field.label))
            item.setToolTip(0, tr('示例：{value}', value=f'{field.prefix}{field.example}{field.suffix}'))
        self._updating = True
        for combo, choices in ((self.separator, self.SEPARATORS), (self.missing, self.MISSING), (self.logo, self.LOGOS)):
            for index, (label, value) in enumerate(choices):
                combo.setItemText(index, tr(label))
        self._updating = False
        for region, button in self._region_buttons.items():
            button.setText(self._region_label(region))
        self.logo.setToolTip('' if self.logo.isEnabled() else tr('此样式没有底部边框，标识位置由原模板控制'))
        self.preview_group.setTitle(tr('示例预览' if self._metadata is None else '照片信息预览'))
        self._filter_fields()
        self._refresh_items(selected)


class FooterEditor(QDialog):
    """封装可视化草稿的预览、保存和高级源码交接"""

    source_preview = Signal(str)
    saved = Signal(str)
    advanced_requested = Signal(str)
    metadata_requested = Signal()

    def __init__(self, parent=None, name: str = '', source: str = '',
                 metadata=None, filename: str = '', file_dir: str = '', saved_source: str | None = None):
        super().__init__(parent)
        self.name = name
        self._saved_name = name
        self._saved_source = source if saved_source is None else saved_source
        self._initial_source = source
        self._new = not bool(name)
        self._close_approved = False
        self._status = ('组合完成后可应用到当前照片预览', {})
        self.setObjectName('footerEditor')
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1040, 790)
        self.setMinimumSize(780, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        name_row = QHBoxLayout()
        label = QLabel()
        bind(label, '模板名称')
        name_row.addWidget(label)
        self.name_input = QLineEdit(name)
        self.name_input.setReadOnly(not self._new)
        name_row.addWidget(self.name_input, 1)
        name_row.addWidget(QLabel('.json'))
        self.advanced_button = QPushButton()
        bind(self.advanced_button, '高级源码…')
        self.advanced_button.setAutoDefault(False)
        self.advanced_button.clicked.connect(self._advanced)
        name_row.addWidget(self.advanced_button)
        layout.addLayout(name_row)
        self.panel = FooterPanel(source, self, metadata, filename, file_dir)
        self._initial_layout = self.panel.layout_data()
        try:
            self._saved_layout = read_layout(self._saved_source)
        except Exception:
            self._saved_layout = self.panel.layout_data()
        layout.addWidget(self.panel, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.preview_button = QPushButton()
        bind(self.preview_button, '应用预览')
        self.preview_button.clicked.connect(self.apply_preview)
        actions.addWidget(self.preview_button)
        self.metadata_button = QPushButton()
        bind(self.metadata_button, '修改照片信息…')
        self.metadata_button.setAutoDefault(False)
        self.metadata_button.clicked.connect(lambda checked=False: self.metadata_requested.emit())
        actions.addWidget(self.metadata_button)
        actions.addStretch()
        self.save_button = QPushButton()
        bind(self.save_button, '保存模板')
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.save_as_button = QPushButton()
        bind(self.save_as_button, '另存为')
        self.save_as_button.clicked.connect(self.save_as)
        actions.addWidget(self.save_as_button)
        self.close_button = QPushButton()
        bind(self.close_button, '关闭')
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        for button in (self.preview_button, self.save_button, self.save_as_button, self.close_button):
            button.setAutoDefault(False)
        for shortcut, callback in [('Ctrl+S', self.save), ('Ctrl+Shift+S', self.save_as), ('Ctrl+Return', self.apply_preview)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.addAction(action)
        self.panel.changed.connect(self._changed)
        self.name_input.textChanged.connect(self._changed)
        translator.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def source(self) -> str:
        # 未编辑时保留原字节排版与未识别的模板内容
        if self.panel.layout_data() == self._initial_layout:
            return self._initial_source
        return self.panel.composed_source()

    def is_dirty(self) -> bool:
        return (self._new or self._initial_source != self._saved_source
                or self.panel.layout_data() != self._saved_layout
                or self.name_input.text().strip() != self._saved_name)

    def _changed(self):
        self._close_approved = False
        self._set_status('组合已修改，尚未保存')
        self._update_title()

    def _update_title(self):
        self.setWindowTitle(tr('{name}{dirty} — 底部信息组合', name=self.name_input.text().strip() or tr('未命名模板'), dirty=' *' if self.is_dirty() else ''))

    def _set_status(self, source, **kwargs):
        self._status = (source, kwargs)
        self.status_label.setText(tr(source, **{key: _error_text(value) if isinstance(value, Exception) else value for key, value in kwargs.items()}))

    def apply_preview(self):
        try:
            source = self.source()
        except Exception as exc:
            self._set_status('预览失败：{error}', error=exc)
            return False
        self.source_preview.emit(source)
        self._set_status('已应用到照片预览，模板尚未保存' if self.is_dirty() else '组合完成后可应用到当前照片预览')
        return True

    def save(self):
        name = self.name_input.text().strip()
        if not name:
            self._set_status('请填写模板名称')
            self.name_input.setFocus()
            return False
        return self._write(name, self._new)

    def _write(self, name, create):
        try:
            source = self.source()
            write_template(name, source, create=create)
        except Exception as exc:
            self._set_status('保存失败：{error}', error=exc)
            return False
        self.name = self._saved_name = name
        self._saved_source = self._initial_source = source
        self.panel.set_source(source)
        self._initial_layout = self.panel.layout_data()
        self._saved_layout = self.panel.layout_data()
        self._new = False
        self.name_input.setText(name)
        self.name_input.setReadOnly(True)
        self._close_approved = False
        self._update_title()
        self._set_status('模板已保存：{name}', name=name)
        self.saved.emit(name)
        return True

    def save_as(self):
        name, accepted = QInputDialog.getText(self, tr('另存为模板'), tr('模板名称'),
                                               text=tr('{name} 副本', name=self.name) if self.name else tr('新模板'))
        if not accepted:
            return False
        if not name.strip():
            self._set_status('请填写模板名称')
            return False
        return self._write(name.strip(), True)

    def _advanced(self):
        try:
            source = self.source()
        except Exception as exc:
            self._set_status('无法组合此模板：{error}', error=exc)
            return
        self.advanced_requested.emit(source)

    def close_for_handoff(self):
        """调用方已接管完整源码后关闭，不再次确认同一草稿"""
        self._close_approved = True
        self.close()

    def confirm_close(self):
        if self._close_approved or not self.is_dirty():
            return True
        choice = QMessageBox.warning(self, tr('模板尚未保存'),
                                     tr('要保存对“{name}”的修改吗？', name=self.name_input.text().strip() or tr('未命名模板')),
                                     QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                     QMessageBox.StandardButton.Save)
        if choice == QMessageBox.StandardButton.Save:
            return self.save()
        return choice == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self.confirm_close():
            self._close_approved = True
            super().closeEvent(event)
        else:
            event.ignore()

    def reject(self):
        if self.confirm_close():
            self._close_approved = True
            super().reject()

    def retranslate_ui(self):
        self._update_title()
        source, values = self._status
        self._set_status(source, **values)
