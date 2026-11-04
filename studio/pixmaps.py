"""在解码阶段缩小模板样图以减少界面等待和内存占用"""

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader, QPixmap


@lru_cache(maxsize=32)
def _read(source, modified, file_size, width, height):
    reader = QImageReader(source)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        reader.setScaledSize(size.scaled(QSize(width, height), Qt.AspectRatioMode.KeepAspectRatio))
    return QPixmap.fromImage(reader.read())


def preview_pixmap(path, width=255, height=110):
    """仅在界面线程使用，文件更新后自动重新读取"""
    source = Path(path).resolve()
    try:
        info = source.stat()
    except OSError:
        return QPixmap()
    return QPixmap(_read(str(source), info.st_mtime_ns, info.st_size, width, height))
