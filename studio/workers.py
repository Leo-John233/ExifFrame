"""后台读取和处理图片并向主线程发送独立的图像副本"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Event

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from core.desktop_service import SUPPORTED_SUFFIXES, export_photo, render_photo
from core.image_cache import photo_thumbnail


def qt_image(image: Image.Image) -> QImage:
    """复制像素以避免后台对象释放后预览失效"""
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


class WorkerSignals(QObject):
    result = Signal(str, int, object)
    error = Signal(str, int, str)
    finished = Signal(str, int)
    item = Signal(int, object)
    progress = Signal(int, int, str)
    summary = Signal(object)


class ImageTask(QRunnable):
    """每项任务拥有取消标记且只在安全的单张边界停止"""

    def __init__(self, kind: str, token: int, *, paths=(), settings=None, output=None):
        super().__init__()
        self.kind, self.token = kind, token
        self.paths, self.settings, self.output = tuple(paths), settings, output
        self.cancel = Event()
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.cancel.is_set() and self.kind != "export":
                return
            if self.kind in ("import", "output"):
                result = self._import()
            elif self.kind == "export":
                result = self._export()
            else:
                if self.kind == "original":
                    with Image.open(self.paths[0]) as source:
                        source.draft("RGB", (1600, 1600))
                        source.thumbnail((1600, 1600))
                        photo = ImageOps.exif_transpose(source).convert("RGB")
                else:
                    photo = render_photo(self.paths[0], self.settings, preview=True)
                result = qt_image(photo)
            if not self.cancel.is_set() or self.kind == "export":
                self.signals.result.emit(self.kind, self.token, result)
        except Exception as exc:
            self.signals.error.emit(self.kind, self.token, str(exc))
        finally:
            self.signals.finished.emit(self.kind, self.token)

    def _import(self):
        errors, seen, added = [], set(), 0
        for root in self.paths:
            # 目录扫描也留在后台且不跟随目录符号链接
            candidates = self._walk(root) if root.is_dir() else (root,)
            for path in candidates:
                if self.cancel.is_set():
                    return errors
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                identity = os.path.normcase(str(path.resolve()))
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    # 刷新目录时复用按文件修改时间区分的小图缓存
                    photo, width, height = photo_thumbnail(path)
                    thumb = qt_image(photo)
                    if self.cancel.is_set():
                        return errors
                    self.signals.item.emit(self.token, (path.resolve(), thumb, width, height))
                    added += 1
                    self.signals.progress.emit(added, 0, path.name)
                except Exception as exc:
                    errors.append(f"{path.name}：{exc}")
        return errors

    def _walk(self, root):
        # 输入扫描排除位于其下的输出目录以免循环处理导出结果
        excluded = None
        if self.kind == "import" and self.settings and self.settings.output_dir:
            excluded = Path(self.settings.output_dir).resolve()
        for folder, directories, names in os.walk(root):
            if self.cancel.is_set():
                return
            directories[:] = sorted(name for name in directories
                                    if not excluded or (Path(folder) / name).resolve() != excluded)
            for name in sorted(names):
                yield Path(folder) / name

    def _export(self):
        completed, errors, skipped = [], [], []
        for index, path in enumerate(self.paths):
            if self.cancel.is_set():
                break
            try:
                completed.append(export_photo(path, self.settings, self.output))
            except FileExistsError:
                skipped.append(str(path))
            except Exception as exc:
                errors.append(f"{path.name}：{exc}")
            self.signals.progress.emit(index + 1, len(self.paths), path.name)
            self.signals.summary.emit({"completed": len(completed), "errors": len(errors), "skipped": len(skipped)})
        return {"completed": completed, "errors": errors, "skipped": skipped, "cancelled": self.cancel.is_set()}
