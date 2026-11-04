"""按区域组合底部信息并保留完整模板源码"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QScrollArea,
    QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy,
    QSplitter, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.desktop_service import validate_template, write_template
from core.footer import FIELD_CATALOG, REGION_LABELS, FooterError, get_footer_field, normalize_layout, preview_rows, read_layout, write_layout
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
    '地理位置': 'Location', '水印区域': 'Watermark region',
    '添加「{field}」': 'Add {field}', '添加到{region}': 'Add to {region}',
    '先选择要添加的字段': 'Select a field to add', '拖动排序': 'Drag to reorder',
    '双击左侧字段，或添加自定义文字': 'Double-click a field on the left, or add custom text',
    '合并已有经纬度': 'Combine latitude and longitude',
    '合并本区域的经纬度，使用首个坐标项的文字样式': 'Combine coordinates in this region using the first coordinate’s text style',
    '{region}的内容': '{region} content',
    '纬度（旧字段）': 'Latitude (legacy)', '经度（旧字段）': 'Longitude (legacy)',
    '添加字段…': 'Add field…', '文字…': 'Text…', '格式与布局': 'Format and layout',
    '文字示例': 'Text example', '点击“添加字段”或“文字”开始组合': 'Use Add field or Text to begin',
    '前面': 'Before', '后面': 'After', '适应': 'Fit', '水印细节': 'Watermark detail',
    '滚轮缩放，拖动查看；双击适应窗口': 'Scroll to zoom, drag to pan; double-click to fit',
    '选择照片后显示水印预览': 'Select a photo to see the watermark preview',
    '等待照片预览': 'Waiting for photo preview', '正在更新预览…': 'Updating preview…',
    '预览已更新': 'Preview updated', '实时预览': 'Live preview', '更新预览': 'Update preview',
    '收起编辑': 'View main window', '保留草稿并查看主窗口': 'Keep the draft and return to the main window',
    '预览失败，保留上次结果：{error}': 'Preview failed; previous result kept: {error}',
    '修改会自动更新左侧预览，保存后写入模板': 'Changes update the preview; Save template writes them to the template file',
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


class _ImageView(QGraphicsView):
    """保留缩放状态的照片预览与底部细节导航"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.photo = QGraphicsPixmapItem()
        self.photo.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.scene().addItem(self.photo)
        self._mode = 'fit'
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumSize(220, 160)
        bind(self, '滚轮缩放，拖动查看；双击适应窗口', 'setToolTip')

    def set_image(self, image):
        pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else QPixmap(image) if isinstance(image, QPixmap) else QPixmap()
        old_size = self.photo.pixmap().size()
        self.photo.setPixmap(pixmap)
        self.setSceneRect(QRectF(pixmap.rect()))
        if old_size != pixmap.size() and self._mode is None:
            self._mode = 'fit'
        self._apply_mode()

    def _apply_mode(self):
        if self.photo.pixmap().isNull():
            return
        if self._mode == 'fit':
            self.fitInView(self.photo, Qt.AspectRatioMode.KeepAspectRatio)
        elif self._mode == 'detail':
            self.resetTransform()
            self.centerOn(self.sceneRect().center().x(), self.sceneRect().bottom() - self.viewport().height() / 2)

    def fit_photo(self):
        self._mode = 'fit'
        self._apply_mode()

    def actual_size(self):
        self._mode = None
        self.resetTransform()

    def footer_detail(self):
        self._mode = 'detail'
        self._apply_mode()

    def wheelEvent(self, event):
        if self.photo.pixmap().isNull():
            event.ignore()
            return
        factor = 1.0015 ** event.angleDelta().y()
        current = self.transform().m11()
        target = max(0.05, min(20, current * factor))
        self._mode = None
        self.scale(target / current, target / current)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.fit_photo()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_mode()


def _fit_editor_window(window, width, height):
    """按当前屏幕可用区域设置初始窗口尺寸"""
    screen = window.screen() or QApplication.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        window.resize(min(width, max(640, available.width() - 64)),
                      min(height, max(440, available.height() - 72)))
    else:
        window.resize(width, height)


class FooterPanel(QWidget):
    """可嵌入新建流程的可视化底部编辑面板"""

    changed = Signal()

    SEPARATORS = (('空格', ' '), ('宽空格', '  '), ('中点 ·', ' · '),
                  ('竖线 |', ' | '), ('逗号 ,', ', '), ('无分隔', ''), ('自定义…', None))
    LOGOS = (('沿用模板', 'keep'), ('隐藏', 'none'), ('左侧', 'left'), ('居中', 'center'), ('右侧', 'right'))
    MISSING = (('隐藏该字段', 'hide'), ('显示破折号', 'dash'))

    def __init__(self, source: str, parent=None, metadata=None, filename='', file_dir='', compact=True):
        super().__init__(parent)
        self.compact = bool(compact)
        self._source = source
        self._layout = {}
        self._region = ''
        self._load_error = None
        self._updating = False
        self._metadata = deepcopy(metadata) if metadata is not None else None
        self._filename = filename
        self._file_dir = file_dir
        self._fields = {field.key: field for field in FIELD_CATALOG}
        for key in ('gps_latitude', 'gps_longitude'):
            field = get_footer_field(key)
            if field:
                self._fields[key] = field
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8 if self.compact else 12)
        layout.addWidget(bind(QLabel(), '水印区域'))
        self.region_group = QWidget()
        self.region_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.region_grid = QGridLayout(self.region_group)
        self.region_grid.setContentsMargins(0, 0, 0, 0)
        self.region_grid.setSpacing(8)
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)
        layout.addWidget(self.region_group)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.row_heading = QLabel()
        row.addWidget(self.row_heading, 1)
        self.open_catalog_button = self._button('添加字段…', self._open_catalog)
        self.open_catalog_button.setObjectName('primaryButton')
        row.addWidget(self.open_catalog_button)
        self.custom_button = self._button('文字…', self.add_text)
        row.addWidget(self.custom_button)
        layout.addLayout(row)
        self.items = _ItemsList()
        self.items.setObjectName('footerRegionItems')
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.items.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.items.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.items.setSpacing(1)
        bind(self.items, '拖动字段调整顺序，也可使用上移和下移按钮', 'setToolTip')
        self.items.currentRowChanged.connect(self._select_item)
        self.items.reordered.connect(self._reordered)
        layout.addWidget(self.items)
        self.empty_label = QLabel()
        bind(self.empty_label, '点击“添加字段”或“文字”开始组合')
        self.empty_label.setWordWrap(True)
        self.empty_label.setObjectName('secondaryText')
        layout.addWidget(self.empty_label)
        move_row = QHBoxLayout()
        move_row.setSpacing(8)
        move_row.addWidget(bind(QLabel(), '拖动排序'))
        move_row.addStretch()
        self.up_button = QPushButton('↑')
        self.down_button = QPushButton('↓')
        for button, label, direction in ((self.up_button, '上移', -1), (self.down_button, '下移', 1)):
            button.setFixedWidth(32)
            button.setAutoDefault(False)
            bind(button, label, 'setToolTip')
            bind(button, label, 'setAccessibleName')
            button.clicked.connect(lambda checked=False, direction=direction: self.move_item(direction))
        self.remove_button = self._button('删除', self.remove_item)
        for button in (self.up_button, self.down_button, self.remove_button):
            move_row.addWidget(button)
        layout.addLayout(move_row)
        self.merge_location_button = self._button('合并已有经纬度', self.merge_location)
        bind(self.merge_location_button, '合并本区域的经纬度，使用首个坐标项的文字样式', 'setToolTip')
        self.merge_location_button.hide()
        layout.addWidget(self.merge_location_button)
        delete_action = QAction(self.items)
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        delete_action.triggered.connect(self.remove_item)
        self.items.addAction(delete_action)

        self.details = QWidget()
        self.details.setMaximumWidth(440)
        form = QGridLayout(self.details)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)
        self.item_hint = QLabel()
        self.item_hint.setWordWrap(True)
        self.item_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.item_hint.setObjectName('secondaryText')
        form.addWidget(self.item_hint, 0, 0, 1, 4)
        self.prefix_input, self.suffix_input, self.text_input = QLineEdit(), QLineEdit(), QLineEdit()
        for editor in (self.prefix_input, self.suffix_input):
            editor.setMaximumWidth(144)
        self.text_input.setMaximumWidth(360)
        self.prefix_label, self.suffix_label, self.text_label = QLabel(), QLabel(), QLabel()
        bind(self.prefix_label, '前面')
        bind(self.suffix_label, '后面')
        bind(self.text_label, '文字内容')
        form.addWidget(self.prefix_label, 1, 0)
        form.addWidget(self.prefix_input, 1, 1)
        form.addWidget(self.suffix_label, 1, 2)
        form.addWidget(self.suffix_input, 1, 3)
        form.addWidget(self.text_label, 2, 0)
        form.addWidget(self.text_input, 2, 1, 1, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        self.prefix_input.textEdited.connect(lambda value: self._edit_item('prefix', value))
        self.suffix_input.textEdited.connect(lambda value: self._edit_item('suffix', value))
        self.text_input.textEdited.connect(lambda value: self._edit_item('text', value))
        layout.addWidget(self.details, 0, Qt.AlignmentFlag.AlignLeft)

        self.format_toggle = QToolButton()
        bind(self.format_toggle, '格式与布局')
        self.format_toggle.setCheckable(True)
        self.format_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.format_toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.format_toggle)
        self.format_body = QWidget()
        options = QGridLayout(self.format_body)
        options.setContentsMargins(0, 0, 0, 0)
        options.setHorizontalSpacing(12)
        options.setVerticalSpacing(8)
        self.separator = QComboBox()
        for label, value in self.SEPARATORS:
            self.separator.addItem(tr(label), value)
        self.separator.currentIndexChanged.connect(self._separator_changed)
        self.custom_separator = QLineEdit()
        bind(self.custom_separator, '输入分隔符', 'setPlaceholderText')
        self.custom_separator.textEdited.connect(self._custom_separator_changed)
        options.addWidget(bind(QLabel(), '区域内分隔符'), 0, 0)
        options.addWidget(self.separator, 0, 1)
        options.addWidget(self.custom_separator, 1, 1)
        self.missing = QComboBox()
        for label, value in self.MISSING:
            self.missing.addItem(tr(label), value)
        self.missing.currentIndexChanged.connect(lambda: self._global_option('missing', self.missing.currentData()))
        options.addWidget(bind(QLabel(), '信息缺失时'), 2, 0)
        options.addWidget(self.missing, 2, 1)
        self.logo = QComboBox()
        for label, value in self.LOGOS:
            self.logo.addItem(tr(label), value)
        self.logo.currentIndexChanged.connect(lambda: self._global_option('logo', self.logo.currentData()))
        options.addWidget(bind(QLabel(), '品牌标识位置'), 3, 0)
        options.addWidget(self.logo, 3, 1)
        options.setColumnStretch(1, 1)
        self.format_body.hide()
        self.format_toggle.toggled.connect(lambda checked: self._fold(self.format_toggle, self.format_body, checked))
        layout.addWidget(self.format_body)
        self.text_preview_toggle = QToolButton()
        bind(self.text_preview_toggle, '文字示例')
        self.text_preview_toggle.setCheckable(True)
        self.text_preview_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.text_preview_toggle.setArrowType(Qt.ArrowType.RightArrow)
        layout.addWidget(self.text_preview_toggle)
        self.preview_group = QGroupBox()
        self.preview_grid = QGridLayout(self.preview_group)
        self.preview_grid.setSpacing(8)
        self.preview_group.hide()
        self.text_preview_toggle.toggled.connect(lambda checked: self._fold(self.text_preview_toggle, self.preview_group, checked))
        layout.addWidget(self.preview_group)
        self.error_label = QLabel()
        self.error_label.setObjectName('errorText')
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        layout.addStretch()

        # 字段库按需弹出，避免长期占用预览宽度
        self.catalog_popup = QFrame(self, Qt.WindowType.Popup)
        self.catalog_popup.setFrameShape(QFrame.Shape.StyledPanel)
        popup_layout = QVBoxLayout(self.catalog_popup)
        popup_layout.setContentsMargins(12, 12, 12, 12)
        popup_layout.setSpacing(8)
        self.search = QLineEdit()
        bind(self.search, '搜索字段', 'setPlaceholderText')
        self.search.textChanged.connect(self._filter_fields)
        popup_layout.addWidget(self.search)
        self.catalog = QTreeWidget()
        self.catalog.setObjectName('footerFieldCatalog')
        self.catalog.setHeaderHidden(True)
        self.catalog.setIndentation(14)
        bind(self.catalog, '双击字段添加到当前区域', 'setToolTip')
        self.catalog.itemActivated.connect(lambda item, column: self._add_from_popup(item.data(0, Qt.ItemDataRole.UserRole)))
        self.catalog.currentItemChanged.connect(self._update_add_button)
        self.search.returnPressed.connect(self._add_selected)
        self._catalog_groups, self._catalog_items = {}, {}
        for field in FIELD_CATALOG:
            if field.group not in self._catalog_groups:
                group = QTreeWidgetItem(self.catalog)
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                group.setExpanded(True)
                self._catalog_groups[field.group] = group
            item = QTreeWidgetItem(self._catalog_groups[field.group])
            item.setData(0, Qt.ItemDataRole.UserRole, field.key)
            self._catalog_items[field.key] = item
        popup_layout.addWidget(self.catalog, 1)
        self.add_button = self._button('添加所选字段', self._add_selected)
        self.add_button.setObjectName('primaryButton')
        popup_layout.addWidget(self.add_button)
        self.catalog_popup.resize(300, 400)

    def _fold(self, button, body, expanded):
        body.setVisible(expanded)
        button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _open_catalog(self):
        point = self.open_catalog_button.mapToGlobal(QPoint(0, self.open_catalog_button.height() + 4))
        screen = self.screen()
        if screen:
            bounds = screen.availableGeometry()
            point.setX(max(bounds.left(), min(point.x(), bounds.right() - self.catalog_popup.width())))
            point.setY(max(bounds.top(), min(point.y(), bounds.bottom() - self.catalog_popup.height())))
        self.catalog_popup.move(point)
        self.catalog_popup.show()
        self.search.setFocus()
        self.search.selectAll()

    def _add_from_popup(self, key):
        if key in self._catalog_items:
            self.add_field(key)
            self.catalog_popup.hide()

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
        self._refresh_items(self.items.currentRow())

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
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda checked=False, region=region: self.select_region(region))
            self.button_group.addButton(button)
            self.region_grid.addWidget(button, row, column)
            self._region_buttons[region] = button
            box = QWidget()
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(8, 6, 8, 6)
            box_layout.setSpacing(8)
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

    def _item_preview(self, item):
        """使用当前照片生成字段显示值，尚未读取照片时才使用示例"""
        field = self._fields.get(item.get('field'))
        if self._metadata is None and field:
            return f"{item.get('prefix', field.prefix)}{field.example}{item.get('suffix', field.suffix)}"
        region = self._region or 'left_top'
        model = {'kind': self._layout.get('kind', 'footer'), 'regions': [region],
                 'rows': {region: {'items': [item], 'separator': ''}},
                 'missing': self._layout.get('missing', 'hide')}
        values = preview_rows(model, self._metadata, self._filename, self._file_dir)
        return values.get(region, '') or '—'

    def _item_label(self, item):
        field = self._fields.get(item.get('field'))
        if field:
            return f"{tr(field.label)}    {self._item_preview(item)}"
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
            entry.setSizeHint(QSize(100, max(24, self.items.fontMetrics().height() + 8)))
        self._fit_item_list()
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
        self._update_add_button()
        self.custom_button.setEnabled(bool(self._region))
        self.open_catalog_button.setEnabled(bool(self._region))
        self.row_heading.setText(tr('{region}的内容', region=self._region_label(self._region)) if self._region else tr('字段与文字'))
        legacy = {item.get('field') for item in self._row().get('items', [])}
        self.merge_location_button.setVisible({'gps_latitude', 'gps_longitude'} <= legacy)
        for region, button in self._region_buttons.items():
            button.setChecked(region == self._region)
        self._updating = False
        self._select_item(self.items.currentRow())
        self._refresh_preview()

    def _fit_item_list(self):
        """按实际行高显示二至五行，更多内容在列表内滚动"""
        row_height = self.items.sizeHintForRow(0) if self.items.count() else max(24, self.items.fontMetrics().height() + 8)
        visible_rows = min(5, max(2, self.items.count()))
        height = visible_rows * (row_height + 2 * self.items.spacing()) + 2 * self.items.frameWidth()
        self.items.setFixedHeight(height)

    def _select_item(self, index):
        if self._updating:
            return
        values = self._row().get('items', [])
        item = values[index] if 0 <= index < len(values) else None
        self.details.setVisible(item is not None)
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
            self.item_hint.setText(tr('示例：{value}', value=self._item_preview(item)))
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
        current = self.catalog.currentItem()
        if text and (current is None or current.isHidden()):
            first = next((item for item in self._catalog_items.values() if not item.isHidden()), None)
            self.catalog.setCurrentItem(first)

    def _add_selected(self):
        item = self.catalog.currentItem()
        if item:
            self._add_from_popup(item.data(0, Qt.ItemDataRole.UserRole))

    def _update_add_button(self, *args):
        if not hasattr(self, 'add_button'):
            return
        selected = self.catalog.currentItem()
        field = self._fields.get(selected.data(0, Qt.ItemDataRole.UserRole)) if selected else None
        self.add_button.setEnabled(bool(field and self._region))
        self.add_button.setText(tr('添加「{field}」', field=tr(field.label)) if field else tr('添加所选字段'))
        self.add_button.setToolTip(tr('添加到{region}', region=self._region_label(self._region)) if field else tr('先选择要添加的字段'))

    def merge_location(self):
        """仅在明确点击后合并当前区域的旧坐标字段"""
        items = self._row().get('items', [])
        legacy_keys = {'gps_latitude', 'gps_longitude'}
        if not legacy_keys <= {item.get('field') for item in items}:
            return
        first = next(index for index, item in enumerate(items) if item.get('field') in legacy_keys)
        combined = deepcopy(items[first])
        for key in ('expression', 'raw', 'segments', 'text', 'label'):
            combined.pop(key, None)
        combined.update(field='location', prefix='', suffix='')
        rows = []
        for index, item in enumerate(items):
            if index == first:
                rows.append(combined)
            if item.get('field') not in legacy_keys:
                rows.append(item)
        self._row()['items'] = rows
        self._refresh_items(first)
        self._changed()

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
            self.item_hint.setText(tr('示例：{value}', value=self._item_preview(values[index])))
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
    view_main_requested = Signal()

    def __init__(self, parent=None, name: str = '', source: str = '',
                 metadata=None, filename: str = '', file_dir: str = '', saved_source: str | None = None,
                 preview_image=None):
        super().__init__(parent)
        self.name = name
        self._saved_name = name
        self._saved_source = source if saved_source is None else saved_source
        self._initial_source = source
        self._new = not bool(name)
        self._close_approved = False
        self._last_preview_source = None
        self._status = ('修改会自动更新左侧预览，保存后写入模板', {})
        self._image_status = ('等待照片预览', {})
        self.setObjectName('footerEditor')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumSize(680, 430)
        _fit_editor_window(self, 1120, 710)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(bind(QLabel(), '模板名称'))
        self.name_input = QLineEdit(name)
        self.name_input.setMaximumWidth(320)
        self.name_input.setReadOnly(not self._new)
        name_row.addWidget(self.name_input, 1)
        name_row.addWidget(QLabel('.json'))
        name_row.addStretch()
        self.advanced_button = bind(QPushButton(), '高级源码…')
        self.advanced_button.clicked.connect(self._advanced)
        name_row.addWidget(self.advanced_button)
        self.main_button = bind(QPushButton(), '收起编辑')
        bind(self.main_button, '保留草稿并查看主窗口', 'setToolTip')
        self.main_button.clicked.connect(lambda: self.view_main_requested.emit())
        name_row.addWidget(self.main_button)
        layout.addLayout(name_row)

        self.splitter = QSplitter()
        preview_area = QWidget()
        preview_layout = QVBoxLayout(preview_area)
        preview_layout.setContentsMargins(0, 8, 12, 0)
        preview_layout.setSpacing(8)
        preview_tools = QHBoxLayout()
        preview_tools.setSpacing(8)
        self.photo_view = _ImageView()
        self.fit_button = bind(QPushButton(), '适应')
        self.fit_button.clicked.connect(self.photo_view.fit_photo)
        self.actual_button = QPushButton('100%')
        self.actual_button.clicked.connect(self.photo_view.actual_size)
        self.detail_button = bind(QPushButton(), '水印细节')
        self.detail_button.clicked.connect(self.photo_view.footer_detail)
        for button in (self.fit_button, self.actual_button, self.detail_button):
            preview_tools.addWidget(button)
        preview_tools.addStretch()
        preview_layout.addLayout(preview_tools)
        self.empty_preview = QLabel()
        bind(self.empty_preview, '选择照片后显示水印预览')
        self.empty_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_preview.setWordWrap(True)
        preview_layout.addWidget(self.empty_preview, 1)
        preview_layout.addWidget(self.photo_view, 1)
        self.image_status_label = QLabel()
        self.image_status_label.setWordWrap(True)
        self.image_status_label.setObjectName('secondaryText')
        preview_layout.addWidget(self.image_status_label)
        self.splitter.addWidget(preview_area)

        self.panel = FooterPanel(source, self, metadata, filename, file_dir, compact=True)
        self._initial_layout = self.panel.layout_data()
        try:
            self._saved_layout = read_layout(self._saved_source)
        except Exception:
            self._saved_layout = self.panel.layout_data()
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(self.panel)
        self.settings_scroll.setMinimumWidth(335)
        self.splitter.addWidget(self.settings_scroll)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([650, 430])
        layout.addWidget(self.splitter, 1)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.live_preview = bind(QCheckBox(), '实时预览')
        self.live_preview.setChecked(True)
        self.live_preview.toggled.connect(self._live_toggled)
        actions.addWidget(self.live_preview)
        self.preview_button = bind(QPushButton(), '更新预览')
        self.preview_button.clicked.connect(self.apply_preview)
        actions.addWidget(self.preview_button)
        self.metadata_button = bind(QPushButton(), '修改照片信息…')
        self.metadata_button.clicked.connect(lambda checked=False: self.metadata_requested.emit())
        actions.addWidget(self.metadata_button)
        actions.addStretch()
        self.save_button = bind(QPushButton(), '保存模板')
        self.save_button.setObjectName('primaryButton')
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.save_as_button = bind(QPushButton(), '另存为')
        self.save_as_button.clicked.connect(self.save_as)
        actions.addWidget(self.save_as_button)
        self.close_button = bind(QPushButton(), '关闭')
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        for shortcut, callback in [('Ctrl+S', self.save), ('Ctrl+Shift+S', self.save_as), ('Ctrl+Return', self.apply_preview)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.addAction(action)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(400)
        self.preview_timer.timeout.connect(self._auto_preview)
        self.panel.changed.connect(self._composition_changed)
        self.name_input.textChanged.connect(self._changed)
        translator.language_changed.connect(self.retranslate_ui)
        self.set_preview(preview_image)
        self.retranslate_ui()

    def set_preview(self, image):
        valid = isinstance(image, (QImage, QPixmap)) and not image.isNull()
        self.photo_view.set_image(image if valid else None)
        self.photo_view.setVisible(valid)
        self.empty_preview.setVisible(not valid)
        for button in (self.fit_button, self.actual_button, self.detail_button):
            button.setEnabled(valid)
        self._set_image_status('预览已更新' if valid else '等待照片预览')

    def set_preview_error(self, error):
        self._set_image_status('预览失败，保留上次结果：{error}', error=error)

    def _set_image_status(self, source, **kwargs):
        self._image_status = (source, kwargs)
        self.image_status_label.setText(tr(source, **{key: _error_text(value) if isinstance(value, Exception) else value for key, value in kwargs.items()}))

    def _composition_changed(self):
        self._changed()
        if self.live_preview.isChecked():
            self.preview_timer.start()

    def _live_toggled(self, enabled):
        if not hasattr(self, 'preview_timer'):
            return
        self.preview_timer.stop()
        if enabled and self.is_dirty():
            self.preview_timer.start()

    def _auto_preview(self):
        if self.live_preview.isChecked():
            self._request_preview(force=False)

    def _request_preview(self, force=True):
        self.preview_timer.stop()
        try:
            source = self.source()
            validate_template(source)
        except Exception as exc:
            self._set_status('预览失败：{error}', error=exc)
            return False
        if not force and source == self._last_preview_source:
            return True
        self._last_preview_source = source
        self._set_image_status('正在更新预览…')
        self.source_preview.emit(source)
        return True

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
        return self._request_preview(force=True)

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
        self.preview_timer.stop()
        self._last_preview_source = source
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
        self.preview_timer.stop()
        self.advanced_requested.emit(source)

    def close_for_handoff(self):
        """调用方已接管完整源码后关闭，不再次确认同一草稿"""
        self._close_approved = True
        self.preview_timer.stop()
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
            self.preview_timer.stop()
            super().closeEvent(event)
        else:
            event.ignore()

    def reject(self):
        if self.confirm_close():
            self._close_approved = True
            self.preview_timer.stop()
            super().reject()

    def retranslate_ui(self):
        self._update_title()
        source, values = self._status
        self._set_status(source, **values)
        source, values = self._image_status
        self._set_image_status(source, **values)
