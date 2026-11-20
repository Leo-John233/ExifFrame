"""共享文件队列模型的水平胶片带"""

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QLabel, QListView, QStackedWidget, QStyle,
    QSizePolicy, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from .files import FileBrowser
from .i18n import bind, tr


class FilmDelegate(QStyledItemDelegate):
    default_cell = QSize(112, 86)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell = QSize(self.default_cell)

    @staticmethod
    def check_rect(rect):
        return QRect(rect.left() + 6, rect.top() + 6, 16, 16)

    def set_cell_size(self, size: QSize):
        self.cell = QSize(size)

    def sizeHint(self, option, index):
        return self.cell

    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return False
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):
        painter.save()
        cell = option.rect.adjusted(2, 2, -2, -2)
        selected = option.state & QStyle.StateFlag.State_Selected
        palette = option.palette
        painter.fillRect(cell, palette.color(QPalette.ColorRole.Mid) if selected else palette.color(QPalette.ColorRole.Base))
        label_h = 18
        photo = cell.adjusted(3, 3, -3, -(label_h + 2))
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and not icon.isNull() and photo.width() > 4 and photo.height() > 4:
            icon.paint(painter, photo, Qt.AlignmentFlag.AlignCenter)
        painter.setFont(option.font)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        name = option.fontMetrics.elidedText(index.data() or '', Qt.TextElideMode.ElideMiddle, max(8, cell.width() - 6))
        painter.drawText(QRect(cell.left() + 3, cell.bottom() - label_h, cell.width() - 6, label_h),
                         Qt.AlignmentFlag.AlignCenter, name)
        if index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            check = self.check_rect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(25, 25, 25, 210))
            painter.setPen(QColor('#D0D0D0'))
            painter.drawRoundedRect(check.adjusted(0, 0, -1, -1), 3, 3)
            if index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value:
                painter.setPen(QColor('white'))
                painter.drawLine(check.left() + 3, check.top() + 8, check.left() + 6, check.top() + 11)
                painter.drawLine(check.left() + 6, check.top() + 11, check.left() + 12, check.top() + 4)
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            painter.drawRect(cell.adjusted(0, 0, -1, -1))
        painter.restore()


class FilmView(QListView):
    def __init__(self, browser, kind, tree):
        super().__init__()
        self.browser, self.kind = browser, kind
        self._delegate = FilmDelegate(self)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setGridSize(self._delegate.cell)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(74)
        self.setModel(tree.model())
        self.setSelectionModel(tree.selectionModel())
        self.setItemDelegate(self._delegate)
        self.horizontalScrollBar().valueChanged.connect(self.invalidate)
        self.viewport().installEventFilter(self)
        self._checking = False

    def cell_size(self) -> QSize:
        return self._delegate.cell

    def update_cell_for_height(self, available_height: int):
        scrollbar_h = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        cell_h = max(62, min(300, available_height - scrollbar_h - 2))
        photo_h = max(36, cell_h - 24)
        cell_w = max(84, min(380, round(photo_h * 1.42) + 8))
        new_size = QSize(cell_w, cell_h)
        if new_size != self._delegate.cell:
            self._delegate.set_cell_size(new_size)
            self.setGridSize(new_size)
            self.setIconSize(QSize(max(48, cell_w - 10), max(36, photo_h)))
            self.scheduleDelayedItemsLayout()
            self.viewport().update()
            self.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_cell_for_height(event.size().height())

    def invalidate(self, *_):
        self.browser._invalidate_visible(self.kind)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.invalidate()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        self.browser.user_navigated.emit(self.kind)
        pos = event.position().toPoint()
        index = self.indexAt(pos)
        self._checking = (event.button() == Qt.MouseButton.LeftButton and index.isValid()
                          and bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
                          and FilmDelegate.check_rect(self.visualRect(index)).contains(pos))
        if self._checking:
            item = self.browser.trees[self.kind].itemFromIndex(index)
            item.setCheckState(0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked else Qt.CheckState.Checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._checking:
            self._checking = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        delta = event.pixelDelta()
        step = self._delegate.cell.width()
        distance = delta.x() or delta.y() or (event.angleDelta().x() or event.angleDelta().y()) / 120 * step
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - round(distance))
        event.accept()

    def keyPressEvent(self, event):
        self.browser.user_navigated.emit(self.kind)
        super().keyPressEvent(event)


class FilmBrowser(FileBrowser):
    hierarchical = False
    BAR_HEIGHT = 28

    def __init__(self):
        super().__init__()
        self.tabs.hide()
        layout = self.layout()
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # 顶部单行控制条：左侧切换与计数，中间当前文件名，右侧批量勾选操作
        self.tools = QWidget()
        self.tools.setObjectName('filmControls')
        self.tools.setFixedHeight(self.BAR_HEIGHT)
        self.tools.setStyleSheet('QToolButton { min-height: 18px; padding: 1px 6px; }')
        bar = self.controls_layout = QHBoxLayout(self.tools)
        bar.setContentsMargins(2, 0, 2, 0)
        bar.setSpacing(4)

        self.fold = QToolButton()
        self.fold.setCheckable(True)
        self.fold.setChecked(True)
        self.fold.setArrowType(Qt.ArrowType.DownArrow)
        bind(self.fold, '展开或收起胶片带', 'setToolTip')
        bar.addWidget(self.fold)

        self.film_pages = QStackedWidget()
        self.film_pages.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.kinds = QButtonGroup(self)
        self.film_views = {}
        for index, (kind, title) in enumerate((('import', '输入'), ('output', '输出'))):
            button = bind(QToolButton(), title)
            button.setCheckable(True)
            self.kinds.addButton(button, index)
            bar.addWidget(button)
            view = FilmView(self, kind, self.trees[kind])
            self.film_views[kind] = view
            self.film_pages.addWidget(view)
        self.kinds.button(0).setChecked(True)
        self.kinds.idClicked.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self._switch_film)

        bar.addWidget(self.count_label)

        self.photo_name = QLabel()
        self.photo_name.setObjectName('secondaryText')
        self.photo_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(self.photo_name, 1)

        self.batch_row = QWidget()
        batch = QHBoxLayout(self.batch_row)
        batch.setContentsMargins(0, 0, 0, 0)
        batch.setSpacing(2)
        self.batch_buttons = []
        for label, callback in (('全选', lambda: self.select_all(True)), ('取消全选', lambda: self.select_all(False)),
                                ('反选', self.invert_selection), ('移除', self.remove_current),
                                ('清空', self.clear_requested.emit)):
            button = bind(QToolButton(), label)
            button.clicked.connect(callback)
            batch.addWidget(button)
            self.batch_buttons.append(button)
        bar.addWidget(self.batch_row)

        layout.addWidget(self.tools)
        layout.addWidget(self.film_pages, 1)

        self.setMinimumHeight(self.BAR_HEIGHT + 80)
        self.setMaximumHeight(360)
        self.fold.toggled.connect(self._fold_changed)
        self._manual_size = False
        self.fold.clicked.connect(self._user_fold)

    def collapsed_height(self) -> int:
        return self.BAR_HEIGHT + 6

    def _user_fold(self):
        self._manual_size = True

    def fit_workspace(self, width, height, inspector_width, toolbar_height):
        """由外层 QSplitter 管理高度，仅保留展开可见性"""
        self.setVisible(True)

    def set_status_widgets(self, photo_name, status):
        """画布 HUD 已显示完整尺寸，仅保留隐藏状态控件兼容旧信号更新"""
        photo_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setParent(self)
        status.hide()

    def _switch_film(self, index):
        self.kinds.button(index).setChecked(True)
        self.film_pages.setCurrentIndex(index)
        self.batch_row.setVisible(index == 0 and self.fold.isChecked())
        self._queue_visible(restart=True)

    def _fold_changed(self, expanded):
        self.fold.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.film_pages.setVisible(expanded)
        self.batch_row.setVisible(expanded and self.tabs.currentIndex() == 0)
        if expanded:
            self.setMinimumHeight(self.BAR_HEIGHT + 80)
            self.setMaximumHeight(360)
        else:
            collapsed = self.collapsed_height()
            self.setMinimumHeight(collapsed)
            self.setMaximumHeight(collapsed)
        self._invalidate_visible('import' if self.tabs.currentIndex() == 0 else 'output')

    def visible_paths(self, kind=None, *, margin=3, missing_only=False):
        kind = kind or ('import' if self.tabs.currentIndex() == 0 else 'output')
        view = self.film_views[kind]
        if not view.isVisible():
            return []
        model = view.model()
        cell_w = max(1, view.cell_size().width())
        first = view.indexAt(QPoint(1, 1)).row()
        if first < 0:
            first = max(0, view.horizontalScrollBar().value() // cell_w)
        count = view.viewport().width() // cell_w + 2
        result = []
        for row in range(max(0, first - margin), min(first + count + margin, model.rowCount())):
            index = model.index(row, 0)
            if not missing_only or not index.data(Qt.ItemDataRole.UserRole + 2):
                result.append(index.data(Qt.ItemDataRole.UserRole)[0])
        return result

    def _update_count(self, *args, **kwargs):
        super()._update_count(*args, **kwargs)
        self.count_label.setText(tr('已选 {selected} / 共 {total} 张', selected=self._selected_count, total=len(self.items['import'])))