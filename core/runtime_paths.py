"""定位程序资源并保存单文件版的可编辑配置"""

import errno
import hashlib
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
_STYLE_DIRS = ('style_assets', 'style_presets')
_STYLE_PACK_MARKER = '.style-pack-1-seeded'
_STYLE_PACK = (
    '极简无框角标', '拍立得经典宽底', '毛玻璃悬浮卡片', '美术馆装裱画框',
    '35mm胶片暗房印记', '主色提取色卡栏', '红标铭牌强调风', '极简双行分割线',
)


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
    """单文件默认将可编辑数据保存在程序目录"""
    override = os.environ.get('EXIFFRAME_DATA_DIR')
    return Path(override).expanduser().resolve() if override else application_root()


def _legacy_data_root() -> Path:
    """定位旧单文件版使用的用户数据目录"""
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


# 已随旧版分发的字节签名，仅用于一次性升级完全未改动的标识
_FACTORY_LOGOS_1 = {
    'apple.png': (64742, '6d79f9ad5e269860acc5689f517ab7cd0afc904823278f597e36f96857abab54'),
    'canon.png': (112450, '43dd5f6bd7acddc4d484e51d0ed335c63afa678cac72d1cc3443a2b7205cd86c'),
    'default.png': (3470, 'cb3d86476e22db486484299d3b7f89435dcb109ea0e59b0ebb8278bad93c8816'),
    'DJI.jpg': (14199, 'e9190a733bf42ad6fd1449771308b5309e8a81eea7330cf897e5adb8c4fdce85'),
    'fujifilm.png': (46672, 'ac79d0e224ac88a6d8d6c49cf3296b9423a7630549911d20a100e3113d6c1618'),
    'hasselblad.png': (273148, '3a3b0662d20538cae7d41d3f237e8b2b9289e6a4346453b9dc93a7cdbcc86287'),
    'leica_logo.png': (156809, 'b487ec61f1ac8b29170c601130a1d615d5e3d10c7cfbad7a5e716d02a2324082'),
    'nikon.png': (263898, '16a13a565d630ff28a3c7903f34abe3c7199bd0364ab69a9155e6d168d52706f'),
    'olympus_blue_gold.png': (73567, 'c1c983257b1bf671d0aeb6added72476206e446d8981c80075ba2ed798f4d6d5'),
    'olympus_white_gold.png': (34761, '17c3a37b3f8ab4593173adaacf4bbb9e7259ec63544d4f1a3abceb30fa94f3aa'),
    'panasonic.png': (49301, '4b044cfd8d0c6b458770df453431aaa99ad7c572845173e039dc736fc18fa10a'),
    'panasonic2.png': (84578, 'c19a41c5bb932a40d44e278141edb61a94e249d0ff4448ae1048f77f70171ff5'),
    'pentax.png': (52302, '6dc8d3c211680948b03175a72144b0e9171cca6c26d272596f5fbcb0a921c04c'),
    'ricoh.png': (48397, '8f20bf3ceedac3d4e01f735d054f2a97a1a3a607e0df6c046b808d2830313723'),
    'sony.png': (85053, '38fd29b5efa86cb71820d754aac121da48a63733dd822520d945a2c45aa18643'),
    'sony_dark.png': (23660, 'f49c78b8572030d2f93784ee831815f9b38061a09ac253a831e15f08bdad50eb'),
    'xmage.png': (283512, '8632838d87c2023a3d75df10ec983732f1b09e683c92375b30a1c766558dc52f'),
}


def _upgrade_factory_logo(target, replacement, size, digest):
    if (not replacement.is_file() or target.is_symlink() or not target.is_file()
            or target.stat().st_size != size):
        return
    with target.open('rb') as stream:
        if hashlib.sha256(stream.read()).hexdigest() != digest:
            return
    if target.suffix.lower() == '.jpg':
        # 新 PNG 先就位；已有自定义 PNG 始终保留
        new_target = target.with_suffix('.png')
        if new_target.exists() and (not new_target.is_file() or new_target.is_symlink()):
            return
        _copy_seed_file(replacement, new_target)
        target.unlink()
        return
    temporary = None
    try:
        with replacement.open('rb') as source, NamedTemporaryFile(
            dir=target.parent, prefix='.logo-', suffix='.tmp', delete=False
        ) as out:
            temporary = Path(out.name)
            shutil.copyfileobj(source, out)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _upgrade_factory_logos(config, bundled):
    marker = config / '.transparent-logos-v1'
    folder = config / 'logos'
    if marker.is_file() or folder.resolve().parent != config.resolve():
        return
    complete = True
    for name, (size, digest) in _FACTORY_LOGOS_1.items():
        try:
            _upgrade_factory_logo(folder / name, bundled / Path(name).with_suffix('.png').name, size, digest)
        except PermissionError:
            # 被查看器占用的素材可继续使用，下次启动再升级
            complete = False
    if complete:
        marker.touch()


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
    target = config_path()
    bundle = Path(sys._MEIPASS).resolve()
    target_root = target.resolve()
    if target_root.is_relative_to(bundle) or bundle.is_relative_to(target_root):
        raise PermissionError(errno.EACCES, '无法写入临时解包目录', str(target))
    target_existed = target.is_dir()
    target.mkdir(parents=True, exist_ok=True)
    with _seed_lock(target / '.resources.lock'):
        # 已有锁文件也不能代替目录写入权限
        with NamedTemporaryFile(dir=target, prefix='.write-check-', suffix='.tmp'):
            pass
        marker = target / _SEEDED_MARKER
        # 兼容以前在数据根目录保存的初始化标记
        if not marker.is_file() and target_existed and (target.parent / _SEEDED_MARKER).is_file():
            marker.touch()
        if not marker.is_file():
            source = resource_path('config')
            required = (source / 'config.ini', *(source / name for name in _CONFIG_DIRS))
            if not required[0].is_file() or not all(path.is_dir() for path in required[1:]):
                raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), str(source))
            if migrate_legacy:
                # 程序旁配置优先，其次迁移旧用户目录，已有目标文件始终保留
                for legacy_base in (application_root(), _legacy_data_root()):
                    legacy = legacy_base / 'config'
                    legacy_root = legacy.resolve()
                    overlaps = legacy_root.is_relative_to(target_root) or target_root.is_relative_to(legacy_root)
                    if not legacy.is_dir() or overlaps:
                        continue
                    for name in ('config.ini', 'desktop.json', 'ui.json'):
                        if (legacy / name).is_file():
                            transform = None
                            if name == 'config.ini':
                                transform = lambda data: _migrate_ini(data, legacy_base)
                            elif name == 'desktop.json':
                                transform = lambda data: _migrate_desktop_json(data, legacy_base)
                            _copy_seed_file(legacy / name, target / name, transform)
                    for name in (*_CONFIG_DIRS, *_STYLE_DIRS):
                        folder = legacy / name
                        if folder.is_dir():
                            for item in sorted(folder.rglob('*')):
                                if item.is_file():
                                    _copy_seed_file(item, target / item.relative_to(legacy))
            _copy_seed_file(required[0], target / 'config.ini')
            for folder in (*required[1:], *(source / name for name in _STYLE_DIRS if (source / name).is_dir())):
                for item in sorted(folder.rglob('*')):
                    if item.is_file():
                        _copy_seed_file(item, target / item.relative_to(source))
            marker.touch(exist_ok=True)
        _upgrade_factory_logos(target, resource_path('config/logos'))
        # 升级时只补一次新增模板，后续保留用户删除
        style_marker = target / _STYLE_PACK_MARKER
        if not style_marker.is_file():
            bundled = resource_path('config/templates')
            additions = [bundled / f'{name}.json' for name in _STYLE_PACK]
            if all(path.is_file() for path in additions):
                for item in additions:
                    _copy_seed_file(item, target / 'templates' / item.name)
                style_marker.touch(exist_ok=True)
        # 保留目录存在，以便用户删除所有标识或模板后仍能启动
        for name in _CONFIG_DIRS:
            (target / name).mkdir(parents=True, exist_ok=True)
