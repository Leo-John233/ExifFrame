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
    cell = QSize(87, 50)

    @staticmethod
    def check_rect(rect):
        return QRect(rect.left() + 4, rect.top() + 4, 15, 15)

    def sizeHint(self, option, index):
        return self.cell

    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
            return False
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):
        painter.save()
        cell = option.rect.adjusted(1, 1, -2, -2)
        selected = option.state & QStyle.StateFlag.State_Selected
        palette = option.palette
        painter.fillRect(cell, palette.color(QPalette.ColorRole.Mid) if selected else palette.color(QPalette.ColorRole.Base))
        photo = cell.adjusted(2, 2, -2, -15)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon and not icon.isNull():
            icon.paint(painter, photo, Qt.AlignmentFlag.AlignCenter)
        painter.setFont(option.font)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        name = option.fontMetrics.elidedText(index.data() or '', Qt.TextElideMode.ElideMiddle, cell.width() - 4)
        painter.drawText(QRect(cell.left()+2, photo.bottom()+1, cell.width()-4, 15), Qt.AlignmentFlag.AlignCenter, name)
        if index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            check = self.check_rect(option.rect)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(25, 25, 25, 210))
            painter.setPen(QColor('#D0D0D0'))
            painter.drawRoundedRect(check.adjusted(0, 0, -1, -1), 3, 3)
            if index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value:
                painter.setPen(QColor('white'))
                painter.drawLine(check.left()+3, check.top()+7, check.left()+6, check.top()+10)
                painter.drawLine(check.left()+6, check.top()+10, check.left()+12, check.top()+4)
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            painter.drawRect(cell.adjusted(0, 0, -1, -1))
        painter.restore()


class FilmView(QListView):
    def __init__(self, browser, kind, tree):
        super().__init__()
        self.browser, self.kind = browser, kind
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setGridSize(FilmDelegate.cell)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setHorizontalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(FilmDelegate.cell.height() + self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
        self.setModel(tree.model())
        self.setSelectionModel(tree.selectionModel())
        self.setItemDelegate(FilmDelegate(self))
        self.horizontalScrollBar().valueChanged.connect(self.invalidate)
        self.viewport().installEventFilter(self)
        self._checking = False

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
        distance = delta.x() or delta.y() or (event.angleDelta().x() or event.angleDelta().y()) / 120 * FilmDelegate.cell.width()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - round(distance))
        event.accept()

    def keyPressEvent(self, event):
        self.browser.user_navigated.emit(self.kind)
        super().keyPressEvent(event)


class FilmBrowser(FileBrowser):
    hierarchical = False

    def __init__(self):
        super().__init__()
        self.tabs.hide()
        layout = self.layout()
        layout.setContentsMargins(3, 0, 3, 0)
        layout.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(3)
        dock = QHBoxLayout()
        dock.setContentsMargins(0, 0, 0, 0)
        dock.setSpacing(6)
        layout.addLayout(dock)
        self.tools = QWidget()
        self.tools.setObjectName('filmControls')
        self.tools.setStyleSheet('QToolButton { min-height: 16px; padding: 1px 4px; }')
        column = self.controls_layout = QVBoxLayout(self.tools)
        column.setSpacing(0)
        column.setContentsMargins(1, 0, 1, 0)
        column.addLayout(bar)
        self.batch_row = QWidget()
        batch = QHBoxLayout(self.batch_row)
        batch.setContentsMargins(0, 0, 0, 0)
        batch.setSpacing(1)
        column.addWidget(self.batch_row)
        dock.addWidget(self.tools)
        self.fold = QToolButton()
        self.fold.setCheckable(True)
        self.fold.setChecked(True)
        self.fold.setArrowType(Qt.ArrowType.DownArrow)
        bind(self.fold, '展开或收起胶片带', 'setToolTip')
        bar.addWidget(self.fold)
        self.film_pages = QStackedWidget()
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
        self.batch_buttons = []
        for label, callback in (('全选', lambda: self.select_all(True)), ('取消全选', lambda: self.select_all(False)),
                                ('反选', self.invert_selection), ('移除', self.remove_current),
                                ('清空', self.clear_requested.emit)):
            button = bind(QToolButton(), label)
            button.clicked.connect(callback)
            batch.addWidget(button)
            self.batch_buttons.append(button)
        bar.addWidget(self.count_label)
        self.photo_name = QLabel()
        self.photo_name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bar.addStretch()
        self.film_pages.setFixedHeight(view.height())
        dock.addWidget(self.film_pages, 1)
        self.fold.toggled.connect(self._fold_changed)
        self._manual_size = False
        self.fold.clicked.connect(self._user_fold)

    def _user_fold(self):
        self._manual_size = True

    def fit_workspace(self, width, height, inspector_width, toolbar_height):
        """首次布局为小屏保留画布面积，手动展开后以用户选择为准"""
        remaining_width = max(1, width - inspector_width - 1)
        budget = height - toolbar_height - .65 * width * height / remaining_width
        if not self._manual_size:
            self.fold.setChecked(budget >= self.film_pages.height())
        self.setVisible(self.fold.isChecked() or budget >= self.fold.sizeHint().height())

    def set_status_widgets(self, photo_name, status):
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(3, 0, 3, 0)
        line.setSpacing(3)
        photo_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        status.setStyleSheet('padding:0; background:transparent')
        status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        line.addWidget(photo_name, 1)
        line.addWidget(status, 1)
        self.controls_layout.addWidget(row)
        self.fold.toggled.connect(row.setVisible)

    def _switch_film(self, index):
        self.kinds.button(index).setChecked(True)
        self.film_pages.setCurrentIndex(index)
        self.batch_row.setVisible(index == 0 and self.fold.isChecked())
        self._queue_visible(restart=True)

    def _fold_changed(self, expanded):
        self.fold.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.film_pages.setVisible(expanded)
        self.batch_row.setVisible(expanded and self.tabs.currentIndex() == 0)
        self._invalidate_visible('import' if self.tabs.currentIndex() == 0 else 'output')

    def visible_paths(self, kind=None, *, margin=3, missing_only=False):
        kind = kind or ('import' if self.tabs.currentIndex() == 0 else 'output')
        view = self.film_views[kind]
        if not view.isVisible():
            return []
        model = view.model()
        first = view.indexAt(QPoint(1, 1)).row()
        if first < 0:
            first = max(0, view.horizontalScrollBar().value() // FilmDelegate.cell.width())
        count = view.viewport().width() // FilmDelegate.cell.width() + 2
        result = []
        for row in range(max(0, first-margin), min(first+count+margin, model.rowCount())):
            index = model.index(row, 0)
            if not missing_only or not index.data(Qt.ItemDataRole.UserRole + 2):
                result.append(index.data(Qt.ItemDataRole.UserRole)[0])
        return result

    def _update_count(self, *args, **kwargs):
        super()._update_count(*args, **kwargs)
        self.count_label.setText(tr('已选 {selected} / 共 {total} 张', selected=self._selected_count, total=len(self.items['import'])))
