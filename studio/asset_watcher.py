"""监听当前模板引用的图片素材"""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from core.style_pack import asset_signature


class AssetWatcher(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = self._logo = ''
        self._signature = ()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._queue_check)
        self._watcher.directoryChanged.connect(self._queue_check)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._check)

    def set_source(self, source, logo='', *, signature=None):
        source, logo = source or '', logo or ''
        signature = asset_signature(source, logo) if signature is None else signature
        if signature == self._signature:
            self._source, self._logo = source, logo
            return
        self._source, self._logo, self._signature = source, logo, signature
        self._refresh_watches()

    def _queue_check(self, *_):
        self._timer.start(80)

    def _check(self):
        signature = asset_signature(self._source, self._logo)
        changed = signature != self._signature
        self._signature = signature
        self._refresh_watches()
        if changed:
            self.changed.emit()

    def _refresh_watches(self):
        wanted = set()
        for value, modified, _ in self._signature:
            path = Path(value).expanduser().absolute()
            if modified is not None and path.is_file():
                wanted.add(str(path))
            parent = path.parent
            while not parent.is_dir() and parent != parent.parent:
                parent = parent.parent
            if parent.is_dir():
                wanted.add(str(parent))
        current = set(self._watcher.files()) | set(self._watcher.directories())
        if removed := current - wanted:
            self._watcher.removePaths(list(removed))
        if added := wanted - current:
            self._watcher.addPaths(list(added))
