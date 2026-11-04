"""后台读取和处理图片并向主线程发送独立的图像副本"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from threading import Event

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from core.desktop_service import SUPPORTED_SUFFIXES, export_photo, read_template, render_photo
from core.image_cache import photo_thumbnail


# 仅为已检查内存规模的内置源码启用双路，模板变化后需重新核验
_BOUNDED_TEMPLATES = {
    '标准水印': 'db73f2259fdfee96b721144cfa997ebedb036575215121e6dd2d6046b3c573d3',
    '标准水印2': 'c7b66f9bdbc60b1be59435547deaae6d66fa21f63e15ca67316dea2db397ae66',
    '背景模糊': '5f02ae1bd10c1f7e570c711ea4de514e0f339f730768b2699c1f9c84b0e1c76b',
    '尼康专用背景模糊': '849930f293ef2c37a24464ac49c5709f92c54f43cc4e9691a225c302df8d103f',
    '右下角参数': 'a2f4b098a0439066be77d19338d1ccc3a2f629f3f1c8dd932f808a3419927cc8',
    '文件夹名+右下角参数': 'ad9913412a56b4bb87ed4538c5dd1c7aa9d3825bfca52dc81626c9d491bef29f',
    'logo居中': 'e62e6e3ec24c3050bb815bf69715240313f7f6c5a9d7eddaa971e7d59498fabe',
    '仅标识居中': '4e3281fca43dd727a0d085dcb799d15ac29f79bb48508feeafc8123d1abcba0d',
}


def qt_image(image: Image.Image) -> QImage:
    """复制像素以避免后台对象释放后预览失效"""
    rgba = image.convert("RGBA")
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()


def _available_physical_memory():
    """无法获取可用内存时退回单线程"""
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                    ('physical_total', ctypes.c_ulonglong), ('physical_available', ctypes.c_ulonglong),
                    ('page_total', ctypes.c_ulonglong), ('page_available', ctypes.c_ulonglong),
                    ('virtual_total', ctypes.c_ulonglong), ('virtual_available', ctypes.c_ulonglong),
                    ('extended_virtual_available', ctypes.c_ulonglong)]

    try:
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.physical_available
    except (AttributeError, OSError):
        pass
    return 0


def _conflicting_outputs(paths, settings, output, cancel):
    """同名目标和手动导入的编号目标按原顺序处理"""
    root = Path(settings.input_dir).expanduser().resolve() if settings.input_dir else None
    destination = Path(output).expanduser().resolve()
    targets, numbered, directories = set(), set(), set()
    for path in paths:
        if cancel.is_set():
            return True
        source = Path(path).resolve()
        in_workspace = root is not None and source.is_relative_to(root)
        directory = destination / source.relative_to(root).parent if in_workspace and settings.preserve_structure else destination
        stem = source.stem if in_workspace else f'{source.stem}_watermarked'
        extension = '.png' if source.suffix.lower() == '.png' else '.jpg'
        key = (os.path.normcase(str(directory.resolve())), stem.casefold(), extension)
        if key in targets:
            return True
        targets.add(key)
        directories.add(Path(key[0]))
        if not in_workspace and not settings.overwrite_existing:
            numbered.add(key)

    def numbered_conflict(key):
        directory, stem, extension = key
        match = re.fullmatch(r'(.+)_([1-9]\d*)', stem)
        return bool(match and (directory, match.group(1), extension) in numbered)

    if any(numbered_conflict(key) for key in targets):
        return True
    for directory in directories:
        if cancel.is_set():
            return True
        for parent in (directory, *directory.parents):
            key = (os.path.normcase(str(parent.parent)), parent.stem.casefold(), parent.suffix.lower())
            if key in targets or numbered_conflict(key):
                return True
    return False


def _export_workers(paths, settings, output, cancel):
    """按内存和输出冲突保守选择一或两个并行任务"""
    if len(paths) < 2 or (os.cpu_count() or 1) < 2:
        return 1
    if _available_physical_memory() <= 4 * 1024 ** 3:
        return 1
    try:
        expected = _BOUNDED_TEMPLATES.get(settings.template_name)
        source = settings.template_source or read_template(settings.template_name)
        if not expected or hashlib.sha256(source.encode('utf-8')).hexdigest() != expected:
            return 1
        if _conflicting_outputs(paths, settings, output, cancel):
            return 1
        largest = 0
        for path in paths:
            if cancel.is_set():
                return 1
            with Image.open(path) as image:
                largest = max(largest, image.width * image.height)
        # 按最大照片估算双路缓冲并预留 4 GiB 系统内存
        required = 4 * 1024 ** 3 + 224 * largest
        return 2 if _available_physical_memory() >= required else 1
    except (OSError, ValueError, UnicodeError):
        return 1


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
            if not self.cancel.is_set() or self.kind == "export":
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
        processed = 0
        settings = self.settings
        source_unavailable = False
        if not settings.template_source:
            try:
                settings = replace(settings, template_source=read_template(settings.template_name))
            except (OSError, ValueError):
                source_unavailable = True

        def process(path):
            if self.cancel.is_set():
                return 'cancelled', None
            try:
                return 'completed', export_photo(path, settings, self.output)
            except FileExistsError:
                return 'skipped', str(path)
            except Exception as exc:
                return 'errors', f"{path.name}：{exc}"

        def record(path, result):
            nonlocal processed
            status, value = result
            if status == 'cancelled':
                return
            {'completed': completed, 'errors': errors, 'skipped': skipped}[status].append(value)
            processed += 1
            self.signals.progress.emit(processed, len(self.paths), path.name)
            self.signals.summary.emit({"completed": len(completed), "errors": len(errors), "skipped": len(skipped)})

        workers = 1 if source_unavailable else _export_workers(self.paths, settings, self.output, self.cancel)
        if workers == 1:
            for path in self.paths:
                if self.cancel.is_set():
                    break
                record(path, process(path))
        else:
            remaining = iter(self.paths)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                pending = {}

                def fill():
                    while len(pending) < workers and not self.cancel.is_set():
                        path = next(remaining, None)
                        if path is None:
                            break
                        pending[pool.submit(process, path)] = path

                fill()
                while pending:
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        path = pending.pop(future)
                        record(path, future.result())
                    fill()
        return {"completed": completed, "errors": errors, "skipped": skipped, "cancelled": self.cancel.is_set()}
