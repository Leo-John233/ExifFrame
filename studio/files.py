"""输入和输出目录树及文件勾选操作"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QStyle,
)


class FileBrowser(QWidget):
    """显示目录层级并将输入勾选与当前预览分开管理"""

    directory_requested = Signal(str, str)
    file_selected = Signal(str, object)
    selection_changed = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = {"import": {}, "output": {}}
        self.folders = {"import": {}, "output": {}}
        self.roots = {"import": None, "output": None}
        self.tabs = QTabWidget()
        self.tabs.setObjectName("fileTabs")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.trees, self.paths = {}, {}
        self._changing = False
        self._scan_checks = {"import": {}, "output": {}}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.tabs)
        for kind, title in (("import", "输入"), ("output", "输出")):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(6, 7, 6, 5)
            layout.setSpacing(5)
            path_row = QHBoxLayout()
            path_row.setSpacing(3)
            path = QLineEdit()
            path.setObjectName("inputDirectoryInput" if kind == "import" else "outputDirectoryInput")
            path.setPlaceholderText("输入目录" if kind == "import" else "输出目录")
            path.returnPressed.connect(lambda which=kind: self._request(which))
            self.paths[kind] = path
            path_row.addWidget(path, 1)
            browse = QPushButton("…")
            browse.setFixedWidth(27)
            browse.setToolTip(f"选择{title}目录")
            browse.clicked.connect(lambda checked=False, which=kind: self._browse(which))
            path_row.addWidget(browse)
            refresh = QPushButton()
            refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            refresh.setFixedWidth(27)
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
            tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            tree.header().setStretchLastSection(False)
            tree.currentItemChanged.connect(lambda item, old, which=kind: self._selected(which, item))
            if kind == "import":
                tree.itemChanged.connect(self._item_changed)
            self.trees[kind] = tree
            layout.addWidget(tree, 1)
            if kind == "import":
                controls = QHBoxLayout()
                for text, state in (("全选", True), ("取消选择", False)):
                    button = QPushButton(text)
                    button.clicked.connect(lambda checked=False, value=state: self.select_all(value))
                    controls.addWidget(button)
                self.remove_button = QPushButton("移除")
                self.remove_button.clicked.connect(self.remove_current)
                controls.addWidget(self.remove_button)
                clear_button = QPushButton("清空")
                clear_button.clicked.connect(lambda: self.clear_requested.emit())
                controls.addWidget(clear_button)
                layout.addLayout(controls)
            self.tabs.addTab(page, title)
        self.count_label = QLabel("输入 0 张 / 已选 0 张")
        self.count_label.setObjectName("secondaryText")
        outer.addWidget(self.count_label)
        self.input_tree, self.output_tree = self.trees["import"], self.trees["output"]
        self.input_path, self.output_path = self.paths["import"], self.paths["output"]

    def _browse(self, kind):
        folder = QFileDialog.getExistingDirectory(self, "选择目录", self.paths[kind].text())
        if folder:
            self.paths[kind].setText(folder)
            self._request(kind)

    def _request(self, kind):
        value = self.paths[kind].text().strip()
        if value:
            self.directory_requested.emit(kind, value)

    def begin_scan(self, kind, root):
        # 同一目录刷新时保留用户已经取消勾选的照片
        root = Path(root).resolve() if root else None
        self._scan_checks[kind] = {key: item.checkState(0) == Qt.CheckState.Checked
                                   for key, item in self.items[kind].items()} if kind == "import" and root == self.roots[kind] else {}
        self._changing = True
        self.trees[kind].clear()
        self.items[kind].clear()
        self.folders[kind].clear()
        self.roots[kind] = root
        self._changing = False
        self._update_count()

    def add_file(self, kind, data):
        path, image, width, height = data
        identity = os.path.normcase(str(path.resolve()))
        if identity in self.items[kind]:
            item = self.items[kind][identity]
            item.setData(0, Qt.ItemDataRole.UserRole, (path, width, height))
            item.setIcon(0, QIcon(QPixmap.fromImage(image)))
            return
        root = self.roots[kind]
        parent = self.trees[kind].invisibleRootItem()
        if root:
            try:
                parts = path.relative_to(root).parts[:-1]
            except ValueError:
                parts = ("手动添加",)
            key = ()
            for part in parts:
                key += (part,)
                if key not in self.folders[kind]:
                    folder = QTreeWidgetItem(parent, [part])
                    folder.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                    folder.setExpanded(True)
                    if kind == "import":
                        folder.setFlags(folder.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                    self.folders[kind][key] = folder
                parent = self.folders[kind][key]
        self._changing = True
        item = QTreeWidgetItem(parent, [path.name, f"{width} × {height}"])
        item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        item.setData(0, Qt.ItemDataRole.UserRole, (path, width, height))
        item.setIcon(0, QIcon(QPixmap.fromImage(image)))
        item.setToolTip(0, str(path))
        if kind == "import":
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if self._scan_checks[kind].get(identity, True) else Qt.CheckState.Unchecked)
        self.items[kind][identity] = item
        self._changing = False
        self._update_count()
        if not self.trees[kind].currentItem():
            self.trees[kind].setCurrentItem(item)

    def selected_paths(self):
        return [item.data(0, Qt.ItemDataRole.UserRole)[0] for item in self.items["import"].values()
                if item.checkState(0) == Qt.CheckState.Checked]

    def select_all(self, checked):
        self._changing = True
        for item in self.items["import"].values():
            item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._changing = False
        self._update_count()

    def _selected(self, kind, item):
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if self.tabs.currentIndex() == (0 if kind == "import" else 1):
            self.file_selected.emit(kind, data)

    def _tab_changed(self, index):
        kind = "import" if index == 0 else "output"
        self._selected(kind, self.trees[kind].currentItem())

    def _item_changed(self, item, column):
        if not self._changing:
            self._update_count()

    def _update_count(self):
        self.count_label.setText(f"输入 {len(self.items['import'])} 张 / 已选 {len(self.selected_paths())} 张 / 输出 {len(self.items['output'])} 张")
        self.selection_changed.emit()

    def remove_current(self):
        item = self.input_tree.currentItem()
        if not item:
            return
        # 文件夹和其子项一并移出队列且不删除磁盘上的文件
        def forget(node):
            for index in range(node.childCount()):
                forget(node.child(index))
            data = node.data(0, Qt.ItemDataRole.UserRole)
            if data:
                self.items["import"].pop(os.path.normcase(str(data[0].resolve())), None)
        forget(item)
        parent = item.parent() or self.input_tree.invisibleRootItem()
        parent.removeChild(item)
        self.folders["import"] = {key: node for key, node in self.folders["import"].items() if node.treeWidget() is self.input_tree}
        self._update_count()
