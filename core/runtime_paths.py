"""定位程序资源并保存单文件版的可编辑配置"""

import errno
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile


ONEFILE_MARKER = 'exifframe-onefile.marker'
_SEEDED_MARKER = '.resources-seeded'
_CONFIG_DIRS = ('templates', 'fonts', 'logos')


def application_root() -> Path:
    """源码和目录版沿用程序所在目录"""
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1]


def is_onefile() -> bool:
    """目录版也有 _MEIPASS，因此用构建标记区分两种发行方式"""
    bundle = getattr(sys, '_MEIPASS', None)
    return bool(getattr(sys, 'frozen', False) and bundle and (Path(bundle) / ONEFILE_MARKER).is_file())


def resource_path(path: str) -> Path:
    """单文件使用内置只读资源，其他运行方式保留相对路径"""
    return Path(sys._MEIPASS) / path if is_onefile() else Path(path)


def user_data_root() -> Path:
    """单文件的数据与临时解包目录和程序位置分离"""
    override = os.environ.get('EXIFFRAME_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / 'AppData' / 'Local') / 'ExifFrame'


def config_path(path: str = '') -> Path:
    root = user_data_root() / 'config' if is_onefile() else Path('config')
    return root / path


@contextmanager
def _seed_lock(path: Path):
    """多个实例同时首次启动时等待同一份资源复制完成"""
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in (errno.EACCES, errno.EDEADLK):
                        raise
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _copy_seed_file(source: Path, target: Path, transform=None) -> None:
    """先写临时文件，再以不替换已有文件的方式发布"""
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with source.open('rb') as incoming, NamedTemporaryFile(
            mode='wb', dir=target.parent, prefix='.seed-', suffix='.tmp', delete=False
        ) as outgoing:
            temporary = Path(outgoing.name)
            if transform is None:
                shutil.copyfileobj(incoming, outgoing)
            else:
                outgoing.write(transform(incoming.read()))
        try:
            if os.name == 'nt':
                os.rename(temporary, target)
            else:
                os.link(temporary, target)
        except FileExistsError:
            pass
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _legacy_absolute(value: str, root: Path) -> str:
    """将旧工作目录中的相对照片路径绑定到原程序位置"""
    if not value.strip():
        return value
    path = Path(value).expanduser()
    return value if path.is_absolute() else str((root / path).resolve())


def _migrate_ini(data: bytes, root: Path) -> bytes:
    """只修改输入输出路径，保留其他配置和原有格式"""
    try:
        content = data.decode('utf-8')
    except UnicodeDecodeError:
        return data
    pattern = r'(?im)^([ \t]*(?:input_folder|output_folder)[ \t]*[=:][ \t]*)([^\r\n]*?)([ \t]*)(?=\r?$)'
    content = re.sub(pattern, lambda match: match.group(1) + _legacy_absolute(match.group(2), root) + match.group(3), content)
    return content.encode('utf-8')


def _migrate_desktop_json(data: bytes, root: Path) -> bytes:
    try:
        content = json.loads(data.decode('utf-8'))
        if not isinstance(content, dict):
            return data
        changed = False
        for key in ('input_dir', 'output_dir'):
            if isinstance(content.get(key), str):
                value = _legacy_absolute(content[key], root)
                changed |= value != content[key]
                content[key] = value
        return json.dumps(content, ensure_ascii=False, indent=2).encode('utf-8') if changed else data
    except (UnicodeDecodeError, ValueError):
        return data


def initialize_user_config(migrate_legacy: bool = True) -> None:
    """仅首次补齐默认配置，后续保留用户修改和删除"""
    if not is_onefile():
        return
    data_root = user_data_root()
    data_root.mkdir(parents=True, exist_ok=True)
    with _seed_lock(data_root / '.resources.lock'):
        target = config_path()
        marker = data_root / _SEEDED_MARKER
        if not marker.is_file():
            source = resource_path('config')
            required = (source / 'config.ini', *(source / name for name in _CONFIG_DIRS))
            if not required[0].is_file() or not all(path.is_dir() for path in required[1:]):
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(source))
            legacy = application_root() / 'config'
            legacy_root, target_root = legacy.resolve(), target.resolve()
            overlaps = legacy_root.is_relative_to(target_root) or target_root.is_relative_to(legacy_root)
            if migrate_legacy and legacy.is_dir() and not overlaps:
                for name in ('config.ini', 'desktop.json', 'ui.json'):
                    if (legacy / name).is_file():
                        transform = None
                        if name == 'config.ini':
                            transform = lambda data: _migrate_ini(data, legacy.parent)
                        elif name == 'desktop.json':
                            transform = lambda data: _migrate_desktop_json(data, legacy.parent)
                        _copy_seed_file(legacy / name, target / name, transform)
                for name in _CONFIG_DIRS:
                    folder = legacy / name
                    if folder.is_dir():
                        for item in sorted(folder.rglob('*')):
                            if item.is_file():
                                _copy_seed_file(item, target / item.relative_to(legacy))
            _copy_seed_file(required[0], target / 'config.ini')
            for folder in required[1:]:
                for item in sorted(folder.rglob('*')):
                    if item.is_file():
                        _copy_seed_file(item, target / item.relative_to(source))
            marker.touch(exist_ok=True)
        # 保留目录存在，以便用户删除所有标识或模板后仍能启动
        for name in _CONFIG_DIRS:
            (target / name).mkdir(parents=True, exist_ok=True)
