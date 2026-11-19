"""输入和输出目录树及文件勾选操作"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QStyle, QStyleOptionViewItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from .i18n import bind_static_texts, register_translations, tr, translator


register_translations({
    '取消全选': 'Uncheck all', '反选': 'Invert selection',
    '已勾选 {selected} / 共 {total} 张': 'Checked {selected} / Total {total}',
})


def _identity(path):
    """不访问磁盘地统一已扫描路径"""
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class FileBrowser(QWidget):
    """显示目录层级并将输入勾选与当前预览分开管理"""

    directory_requested = Signal(str, str)
    file_selected = Signal(str, object)
    file_details_changed = Signal(str, object)
    user_navigated = Signal(str)
    visible_paths_changed = Signal(str, object)
    visible_paths_invalidated = Signal(str)
    selection_changed = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = {"import": {}, "output": {}}
        self._canonical = {"import": {}, "output": {}}
        self.folders = {"import": {}, "output": {}}
        self.roots = {"import": None, "output": None}
        self.tabs = QTabWidget()
        self.tabs.setObjectName("fileTabs")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.trees, self.paths = {}, {}
        self._changing = False
        self._scan_checks = {"import": set(), "output": set()}
        self._checked = set()
        self._order = {}
        self._next_order = 0
        self._next_item_token = 0
        self._selected_count = 0
        self._batching = False
        self._viewports = {}
        self._tree_widgets = {}
        self._checkbox_press = None
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self.selection_changed.emit)
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(80)
        self._visible_timer.timeout.connect(self._emit_visible_paths)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 4)
        outer.setSpacing(8)
        outer.addWidget(self.tabs)
        for kind, title in (("import", "输入"), ("output", "输出")):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(6, 8, 6, 6)
            layout.setSpacing(8)
            path_row = QHBoxLayout()
            path_row.setSpacing(4)
            path = QLineEdit()
            path.setObjectName("inputDirectoryInput" if kind == "import" else "outputDirectoryInput")
            path.setPlaceholderText("输入目录" if kind == "import" else "输出目录")
            path.returnPressed.connect(lambda which=kind: self._request(which))
            self.paths[kind] = path
            path_row.addWidget(path, 1)
            browse = QPushButton("…")
            browse.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            browse.setToolTip("选择输入目录" if kind == "import" else "选择输出目录")
            browse.clicked.connect(lambda checked=False, which=kind: self._browse(which))
            path_row.addWidget(browse)
            refresh = QPushButton()
            refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            refresh.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            refresh.setToolTip("刷新目录")
            refresh.clicked.connect(lambda checked=False, which=kind: self._request(which))
            path_row.addWidget(refresh)
            layout.addLayout(path_row)
            tree = QTreeWidget()
            tree.setObjectName("inputTree" if kind == "import" else "outputTree")
            tree.setColumnCount(2)
            tree.setHeaderLabels(["文件名", "尺寸"])
            tree.setUniformRowHeights(True)
            tree.setAlternatingRowColors(True)
            tree.setIconSize(QPixmap(22, 18).size())
            tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            tree.header().resizeSection(1, 100)
            tree.header().setStretchLastSection(False)
            tree.currentItemChanged.connect(lambda item, old, which=kind: self._selected(which, item))
            tree.verticalScrollBar().valueChanged.connect(lambda value, which=kind: self._invalidate_visible(which))
            tree.itemExpanded.connect(lambda item, which=kind: self._invalidate_visible(which))
            tree.itemCollapsed.connect(lambda item, which=kind: self._invalidate_visible(which))
            tree.viewport().installEventFilter(self)
            self._viewports[tree.viewport()] = kind
            tree.installEventFilter(self)
            self._tree_widgets[tree] = kind
            if kind == "import":
                tree.itemChanged.connect(self._item_changed)
            self.trees[kind] = tree
            layout.addWidget(tree, 1)
            if kind == "import":
                controls = QHBoxLayout()
                for text, action in (("全选", lambda: self.select_all(True)),
                                     ("取消全选", lambda: self.select_all(False)),
                                     ("反选", self.invert_selection)):
                    button = QPushButton(text)
                    button.clicked.connect(action)
                    controls.addWidget(button)
                layout.addLayout(controls)
                controls = QHBoxLayout()
                self.remove_button = QPushButton("移除")
                self.remove_button.clicked.connect(self.remove_current)
                controls.addWidget(self.remove_button)
                clear_button = QPushButton("清空")
                clear_button.clicked.connect(lambda: self.clear_requested.emit())
                controls.addWidget(clear_button)
                layout.addLayout(controls)
            self.tabs.addTab(page, title)
        self.count_label = QLabel("已勾选 0 / 共 0 张")
        self.count_label.setObjectName("secondaryText")
        outer.addWidget(self.count_label)
        self.input_tree, self.output_tree = self.trees["import"], self.trees["output"]
        self.input_path, self.output_path = self.paths["import"], self.paths["output"]
        bind_static_texts(self, exclude=(self.count_label,))
        translator.language_changed.connect(self._retranslate_ui)
        self._retranslate_ui()

    def _retranslate_ui(self):
        """保留目录节点和勾选状态，仅替换界面标签"""
        was_changing, self._changing = self._changing, True
        self.tabs.setTabText(0, tr("输入"))
        self.tabs.setTabText(1, tr("输出"))
        for kind, tree in self.trees.items():
            tree.setHeaderLabels([tr("文件名"), tr("尺寸")])
            manual = self.folders[kind].get(("\x00manual",))
            if manual:
                manual.setText(0, tr("手动添加"))
        self._changing = was_changing
        self._update_count(emit=False, recount=False)

    def _browse(self, kind):
        folder = QFileDialog.getExistingDirectory(self, tr("选择目录"), self.paths[kind].text(),
                                                  QFileDialog.Option.DontUseNativeDialog)
        if folder:
            self.paths[kind].setText(folder)
            self._request(kind)

    def _request(self, kind):
        value = self.paths[kind].text().strip()
        if value:
            self.directory_requested.emit(kind, value)

    def begin_scan(self, kind, root, *, preserve_checks=True):
        """仅同目录刷新时暂存已勾选项"""
        root = Path(os.path.abspath(os.fspath(root))) if root else None
        self._scan_checks[kind] = (self._checked.copy() if preserve_checks and kind == 'import'
                                   and root == self.roots[kind] else set())
        had_checked = bool(self._checked) if kind == 'import' else False
        self._changing = True
        try:
            self.trees[kind].clear()
            self.items[kind].clear()
            self._canonical[kind].clear()
            self.folders[kind].clear()
            self.roots[kind] = root
            if kind == 'import':
                self._checked.clear()
                self._order.clear()
                self._next_order = 0
                self._selected_count = 0
        finally:
            self._changing = False
        if kind == 'import':
            self._selection_timer.stop()
        self._update_count(emit=had_checked, recount=False)
        self._invalidate_visible(kind)

    def finish_scan(self, kind):
        """结束目录刷新后不再对新导入项目恢复旧勾选"""
        self._scan_checks[kind].clear()

    def add_file(self, kind, data, *, restore_checks=False):
        """添加轻量占位，缩略图稍后由后台按可见行补充"""
        path, image, width, height = data[:4]
        path = Path(os.path.abspath(os.fspath(path)))
        identity = _identity(path)
        canonical = _identity(data[4]) if len(data) > 4 and data[4] else identity
        if identity in self.items[kind] or canonical in self._canonical[kind]:
            return False
        root = self.roots[kind]
        parent = self.trees[kind].invisibleRootItem()
        self._changing = True
        try:
            if root:
                try:
                    parts = path.relative_to(root).parts[:-1]
                except ValueError:
                    parts = ('\x00manual',)
                key = ()
                for part in parts:
                    key += (part,)
                    if key not in self.folders[kind]:
                        folder = QTreeWidgetItem(parent, [tr('手动添加') if part == '\x00manual' else part])
                        folder.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                        if kind == 'import':
                            folder.setFlags(folder.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                            folder.setCheckState(0, Qt.CheckState.Unchecked)
                        folder.setData(0, Qt.ItemDataRole.UserRole + 3, key)
                        folder.setExpanded(True)
                        self.folders[kind][key] = folder
                    parent = self.folders[kind][key]
            size_text = f'{width} × {height}' if width and height else ''
            item = QTreeWidgetItem(parent, [path.name, size_text])
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setData(0, Qt.ItemDataRole.UserRole, (path, width, height))
            self._next_item_token += 1
            item.setData(0, Qt.ItemDataRole.UserRole + 4, self._next_item_token)
            item.setData(0, Qt.ItemDataRole.UserRole + 5, canonical)
            if image is not None and not image.isNull():
                item.setIcon(0, QIcon(QPixmap.fromImage(image)))
                item.setData(0, Qt.ItemDataRole.UserRole + 2, True)
            item.setToolTip(0, str(path))
            if kind == 'import':
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = bool(restore_checks and identity in self._scan_checks[kind])
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, checked)
                self._order[identity] = self._next_order
                self._next_order += 1
                if checked:
                    self._checked.add(identity)
                    self._selected_count += 1
            self.items[kind][identity] = item
            self._canonical[kind][canonical] = identity
        finally:
            self._changing = False
        if not self._batching:
            self._update_count(emit=False, recount=False)
            self._queue_visible()
        return True

    def add_files(self, kind, entries, *, restore_checks=False):
        """批量添加占位并合并界面刷新"""
        tree = self.trees[kind]
        previous = tree.updatesEnabled()
        self._batching = True
        tree.setUpdatesEnabled(False)
        try:
            added = [data[0] for data in entries if self.add_file(kind, data, restore_checks=restore_checks)]
        finally:
            self._batching = False
            tree.setUpdatesEnabled(previous)
        self._update_count(emit=False, recount=False)
        self._queue_visible()
        return added

    def needs_thumbnail(self, kind, path):
        """未加载或已移除的文件不复用旧缩略图"""
        item = self.items[kind].get(_identity(path))
        return item is not None and not item.data(0, Qt.ItemDataRole.UserRole + 2)

    def item_token(self, kind, path):
        """区分同一路径被移除后重新添加的列表项"""
        item = self.items[kind].get(_identity(path))
        return item.data(0, Qt.ItemDataRole.UserRole + 4) if item is not None else None

    def update_dimensions(self, kind, path, width, height):
        """更新已存在照片的尺寸而不改变当前选择"""
        item = self.items[kind].get(_identity(path))
        if item is None or width <= 0 or height <= 0:
            return False
        current = item.data(0, Qt.ItemDataRole.UserRole)
        data = (current[0], width, height)
        if tuple(current) == data:
            return True
        self._changing = True
        try:
            item.setData(0, Qt.ItemDataRole.UserRole, data)
            item.setText(1, f'{width} × {height}')
        finally:
            self._changing = False
        if self.trees[kind].currentItem() is item:
            self.file_details_changed.emit(kind, data)
        return True

    def update_file(self, kind, path, image, width, height, signature, item_token):
        """只为同一列表项更新后台核验过版本的缩略图"""
        item = self.items[kind].get(_identity(path))
        if (item is None or item_token is None or item.data(0, Qt.ItemDataRole.UserRole + 4) != item_token
                or image is None or image.isNull() or signature is None):
            return False
        self._changing = True
        try:
            item.setData(0, Qt.ItemDataRole.UserRole + 2, tuple(signature))
            item.setIcon(0, QIcon(QPixmap.fromImage(image)))
        finally:
            self._changing = False
        self.update_dimensions(kind, path, width, height)
        return True

    def selected_paths(self):
        ordered = sorted(self._checked, key=self._order.__getitem__)
        return [self.items['import'][identity].data(0, Qt.ItemDataRole.UserRole)[0] for identity in ordered]

    def all_paths(self):
        return [item.data(0, Qt.ItemDataRole.UserRole)[0] for item in self.items["import"].values()]

    def select_all(self, checked):
        """批量设置勾选状态，只通知一次"""
        self._selection_timer.stop()
        self._changing = True
        tree = self.input_tree
        updates = tree.updatesEnabled()
        tree.setUpdatesEnabled(False)
        try:
            for item in self.items['import'].values():
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, checked)
            self._checked = set(self.items['import']) if checked else set()
            self._selected_count = len(self._checked)
        finally:
            tree.setUpdatesEnabled(updates)
            self._changing = False
        self._update_count(recount=False)

    def invert_selection(self):
        """反转每张照片的勾选状态"""
        self._selection_timer.stop()
        self._changing = True
        tree = self.input_tree
        updates = tree.updatesEnabled()
        tree.setUpdatesEnabled(False)
        try:
            selected = set()
            for identity, item in self.items['import'].items():
                checked = item.checkState(0) != Qt.CheckState.Checked
                item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                item.setData(0, Qt.ItemDataRole.UserRole + 1, checked)
                if checked:
                    selected.add(identity)
            self._checked = selected
            self._selected_count = len(selected)
        finally:
            tree.setUpdatesEnabled(updates)
            self._changing = False
        self._update_count(recount=False)

    def _selected(self, kind, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if self.tabs.currentIndex() == (0 if kind == "import" else 1):
            self.file_selected.emit(kind, data)

    def _tab_changed(self, index):
        kind = "import" if index == 0 else "output"
        self._selected(kind, self.trees[kind].currentItem())
        self._invalidate_visible(kind)

    def _invalidate_visible(self, kind):
        """可视区域变化时先取消旧任务，再等待滚动稳定"""
        current = 'import' if self.tabs.currentIndex() == 0 else 'output'
        if kind == current:
            self.visible_paths_invalidated.emit(kind)
            self._queue_visible(restart=True)

    def _queue_visible(self, restart=False):
        """滚动停止后合并通知，导入期间限频更新"""
        if restart or not self._visible_timer.isActive():
            self._visible_timer.start()

    def _emit_visible_paths(self):
        kind = 'import' if self.tabs.currentIndex() == 0 else 'output'
        self.visible_paths_changed.emit(kind, self.visible_paths(kind))

    def visible_paths(self, kind=None, *, margin=4, missing_only=False):
        """仅读取当前展开且可见的行及相邻少量缓冲"""
        if kind is None:
            kind = 'import' if self.tabs.currentIndex() == 0 else 'output'
        tree = self.trees[kind]
        if not tree.isVisible() or tree.viewport().height() <= 0:
            return []
        item = tree.itemAt(QPoint(1, 1))
        if item is None:
            return []
        height = max(1, tree.visualItemRect(item).height())
        for _ in range(max(0, margin)):
            previous = tree.itemAbove(item)
            if previous is None:
                break
            item = previous
        limit = tree.viewport().height() + max(0, margin) * height
        paths = []
        while item is not None:
            rect = tree.visualItemRect(item)
            if rect.top() > limit:
                break
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and (not missing_only or not item.data(0, Qt.ItemDataRole.UserRole + 2)):
                paths.append(data[0])
            item = tree.itemBelow(item)
        return paths

    def eventFilter(self, watched, event):
        tree_kind = self._tree_widgets.get(watched)
        if tree_kind is not None and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                               Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
                               Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.user_navigated.emit(tree_kind)
        kind = self._viewports.get(watched)
        if kind is not None:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                self._invalidate_visible(kind)
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.FocusOut) and self._checkbox_press is watched:
                self._checkbox_press = None
            if kind == 'import' and event.type() == QEvent.Type.MouseButtonRelease and self._checkbox_press is watched:
                self._checkbox_press = None
                return True
            if (kind == 'import' and event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton):
                tree = self.trees[kind]
                position = event.position().toPoint()
                index = tree.indexAt(position)
                if index.isValid() and index.column() == 0:
                    item = tree.itemFromIndex(index)
                    if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                        option = QStyleOptionViewItem()
                        tree.itemDelegate().initStyleOption(option, index)
                        option.rect = tree.visualRect(index)
                        check = tree.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator,
                                                            option, tree)
                        if check.contains(position):
                            state = (Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked
                                     else Qt.CheckState.Checked)
                            self._checkbox_press = watched
                            self.user_navigated.emit(kind)
                            item.setCheckState(0, state)
                            return True
            if event.type() == QEvent.Type.MouseButtonPress:
                self.user_navigated.emit(kind)
        return super().eventFilter(watched, event)

    def _item_changed(self, item, column):
        if self._changing or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        previous = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        if checked != previous:
            identity = _identity(item.data(0, Qt.ItemDataRole.UserRole)[0])
            if checked:
                self._checked.add(identity)
            else:
                self._checked.discard(identity)
            self._selected_count = len(self._checked)
            self._changing = True
            item.setData(0, Qt.ItemDataRole.UserRole + 1, checked)
            self._changing = False
            self._update_count(emit=False, recount=False)
            self._selection_timer.start(0)

    def _update_count(self, emit=True, recount=True):
        # 增量导入只更新计数，避免每张照片都遍历整个文件树
        if recount:
            self._checked = {identity for identity, item in self.items['import'].items()
                             if item.checkState(0) == Qt.CheckState.Checked}
            self._selected_count = len(self._checked)
            self._changing = True
            for item in self.items["import"].values():
                item.setData(0, Qt.ItemDataRole.UserRole + 1, item.checkState(0) == Qt.CheckState.Checked)
            self._changing = False
        self.count_label.setText(tr('已勾选 {selected} / 共 {total} 张',
                                    total=len(self.items['import']), selected=self._selected_count))
        if emit:
            self.selection_changed.emit()

    def remove_current(self):
        item = self.input_tree.currentItem()
        if not item:
            return
        # 文件夹和其子项一并移出队列且不删除磁盘上的文件
        nodes = [item]
        while nodes:
            node = nodes.pop()
            nodes.extend(node.child(index) for index in range(node.childCount()))
            data = node.data(0, Qt.ItemDataRole.UserRole)
            if data:
                identity = _identity(data[0])
                self.items['import'].pop(identity, None)
                self._canonical['import'].pop(node.data(0, Qt.ItemDataRole.UserRole + 5), None)
                self._checked.discard(identity)
                self._scan_checks['import'].discard(identity)
                self._order.pop(identity, None)
            folder_key = node.data(0, Qt.ItemDataRole.UserRole + 3)
            if folder_key:
                self.folders['import'].pop(tuple(folder_key), None)
        parent = item.parent() or self.input_tree.invisibleRootItem()
        parent.removeChild(item)
        self._selected_count = len(self._checked)
        self._selection_timer.stop()
        self._update_count(recount=False)
        self._invalidate_visible('import')
