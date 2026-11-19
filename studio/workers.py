"""后台读取和处理图片并向主线程发送独立的图像副本"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
from concurrent.futures import CancelledError, FIRST_COMPLETED, ThreadPoolExecutor, wait
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path
from threading import Event

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from core.desktop_service import SUPPORTED_SUFFIXES, export_photo, read_template, render_photo
from core.image_cache import photo_proxy, photo_thumbnail
from studio.canvas import image_size, set_image_size


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


def qt_image(image: Image.Image, full_size=None) -> QImage:
    """复制像素以避免后台对象释放后预览失效"""
    rgba = image.convert("RGBA")
    result = QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                    QImage.Format.Format_RGBA8888).copy()
    return set_image_size(result, full_size or image.info.get('preview_full_size') or image.size)


def original_image(path, *, full_resolution=False, cancelled=None):
    """在后台读取原图或共享代理并附上方向修正后的尺寸"""
    if cancelled and cancelled():
        raise CancelledError()
    if full_resolution:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
        size = image.size
    else:
        image, size, _ = photo_proxy(path, cancelled=cancelled)
    if cancelled and cancelled():
        raise CancelledError()
    return qt_image(image, size)


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
    batch = Signal(int, object)
    dimensions = Signal(str, int, object)
    progress = Signal(int, int, str)
    summary = Signal(object)


class ImageTask(QRunnable):
    """每项任务拥有取消标记且只在安全的单张边界停止"""

    def __init__(self, kind: str, token: int, *, paths=(), settings=None, output=None, full_resolution=False,
                 batch_size=1, pause=None, io_lock=None):
        super().__init__()
        self.kind, self.token = kind, token
        self.paths, self.settings, self.output = tuple(paths), settings, output
        self.full_resolution = full_resolution
        self.cancel = Event()
        self.pause = pause if pause is not None else Event()
        self.io_lock = io_lock
        self.batch_size = max(1, min(64, int(batch_size)))
        self.signals = WorkerSignals()

    def run(self):
        try:
            if self.cancel.is_set() and self.kind != "export":
                return
            if self.kind in ("import", "output"):
                result = self._import()
            elif self.kind == 'thumbnail':
                result = self._thumbnails()
            elif self.kind == "export":
                result = self._export()
            else:
                source = Path(os.path.abspath(self.paths[0]))
                info = source.stat()
                version = info.st_mtime_ns, info.st_size
                source_size = None
                if self.kind in ("original", "comparison"):
                    result = original_image(self.paths[0], full_resolution=self.full_resolution,
                                            cancelled=self.cancel.is_set)
                    source_size = image_size(result)
                else:
                    photo = render_photo(self.paths[0], self.settings, preview=True,
                                         full_resolution=self.full_resolution, cancelled=self.cancel.is_set)
                    source_size = photo.info.get('preview_source_size')
                    result = qt_image(photo)
                info = source.stat()
                if version != (info.st_mtime_ns, info.st_size):
                    raise OSError('照片在预览期间发生变化，请重试')
                if source_size and not self.cancel.is_set():
                    self.signals.dimensions.emit(self.kind, self.token, (source, *source_size))
            if not self.cancel.is_set() or self.kind == "export":
                self.signals.result.emit(self.kind, self.token, result)
        except CancelledError:
            pass
        except Exception as exc:
            if not self.cancel.is_set() or self.kind == "export":
                self.signals.error.emit(self.kind, self.token, str(exc))
        finally:
            self.signals.finished.emit(self.kind, self.token)

    def _ready(self):
        """暂停期间仍响应取消"""
        while self.pause.is_set():
            if self.cancel.wait(.025):
                return False
        return not self.cancel.is_set()

    def _acquire_io(self):
        """只在非暂停状态持有低优先级磁盘锁"""
        while self._ready():
            if self.io_lock is None:
                return True
            if self.io_lock.acquire(timeout=.025):
                if self.cancel.is_set() or self.pause.is_set():
                    self.io_lock.release()
                    continue
                return True
        return False

    def _release_io(self):
        if self.io_lock is not None:
            self.io_lock.release()

    def _import(self):
        """先流式提交文件路径，缩略图由可见项任务另行读取"""
        errors, seen, added, pending = [], set(), 0, []

        def flush():
            if pending:
                self.signals.batch.emit(self.token, tuple(pending))
                self.signals.progress.emit(added, 0, pending[-1][0].name)
                pending.clear()

        for root in self.paths:
            if not self._acquire_io():
                return errors
            try:
                # 目录扫描不跟随目录符号链接
                candidates = iter(self._walk(root) if root.is_dir() else (root,))
            finally:
                self._release_io()

            def stop():
                close = getattr(candidates, 'close', None)
                if close is not None:
                    close()
                return errors

            while True:
                if not self._acquire_io():
                    return stop()
                path, displayed = None, None
                try:
                    try:
                        path = next(candidates)
                    except StopIteration:
                        break
                    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                        continue
                    displayed = Path(os.path.abspath(path))
                    resolved = displayed.resolve(strict=True)
                    if not stat.S_ISREG(resolved.stat().st_mode):
                        continue
                    identity = os.path.normcase(str(resolved))
                    if identity in seen:
                        continue
                    seen.add(identity)
                except (OSError, ValueError) as exc:
                    errors.append(f"{path.name if path else root.name}：{exc}")
                    continue
                finally:
                    self._release_io()
                if self.cancel.is_set():
                    return stop()
                added += 1
                item = (displayed, None, 0, 0, identity) if self.batch_size > 1 else (displayed, None, 0, 0)
                if added == 1 or self.batch_size == 1:
                    self.signals.item.emit(self.token, item)
                    self.signals.progress.emit(added, 0, displayed.name)
                else:
                    pending.append(item)
                    if len(pending) >= self.batch_size:
                        flush()
                        # 避免连续批次挤占界面与可见项读取
                        if self.cancel.wait(.005):
                            return stop()
        if not self.cancel.is_set():
            flush()
        return errors

    def _thumbnails(self):
        """仅解码当前可见的照片并返回文件版本"""
        errors = []
        for path in self.paths:
            if not self._acquire_io():
                return errors
            try:
                source = Path(os.path.abspath(path))
                info = source.stat()
                signature = info.st_mtime_ns, info.st_size
                photo, width, height = photo_thumbnail(source, cancelled=self.cancel.is_set)
                info = source.stat()
                if signature != (info.st_mtime_ns, info.st_size):
                    raise OSError('照片在读取期间发生变化，请重试')
            except CancelledError:
                return errors
            except (OSError, ValueError) as exc:
                errors.append(f"{Path(path).name}：{exc}")
                continue
            finally:
                self._release_io()
            if not self._ready():
                return errors
            image = qt_image(photo)
            if self.cancel.is_set():
                return errors
            self.signals.item.emit(self.token, (source, image, width, height, signature))
        return errors

    def _walk(self, root):
        # 输入扫描排除位于其下的输出目录以免循环处理导出结果
        excluded = None
        root = Path(os.path.abspath(root))
        if self.kind == "import" and self.settings and self.settings.output_dir:
            output = Path(self.settings.output_dir).resolve()
            try:
                output = root / output.relative_to(root.resolve())
            except ValueError:
                pass
            excluded = os.path.normcase(os.path.abspath(output))
        pending = [root]
        while pending and not self.cancel.is_set():
            folder = pending.pop()
            # 空目录也要给调用方留出暂停和取消的机会
            yield folder
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        if self.cancel.is_set():
                            return
                        try:
                            if (entry.is_dir(follow_symlinks=False)
                                    and not getattr(entry, 'is_junction', lambda: False)()):
                                key = os.path.normcase(os.path.abspath(entry.path))
                                if key != excluded:
                                    pending.append(Path(entry.path))
                        except OSError:
                            pass
                        # 每个目录项都返回给调用方，以便暂停或取消
                        yield Path(entry.path)
            except OSError:
                continue

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
