"""使用隔离的 NumPy 构建 Windows 单文件或目录版"""

import argparse
import importlib.metadata
import os
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

if __package__:
    from .build_guard import run as _run_limited
else:
    from build_guard import run as _run_limited


ROOT = Path(__file__).resolve().parents[1]
NUMPY_VERSION = '2.5.2'
NUMPY_WHEEL = f'numpy-{NUMPY_VERSION}-cp313-cp313-win_amd64.whl'
PYINSTALLER_VERSION = '6.20.0'
NUMPY_INDEX = 'https://pypi.org/simple'


class BuildPreparationError(Exception):
    """构建依赖或资源准备失败"""


def _powershell_quote(value):
    """安全引用包含空格或单引号的 PowerShell 路径"""
    return "'" + str(value).replace("'", "''") + "'"


def _wheel_prepare_command(directory: Path):
    """提供不依赖当前工作目录的手动准备命令"""
    return (f'& {_powershell_quote(Path(sys.executable).resolve())} -m pip download '
            f'--index-url {NUMPY_INDEX} --only-binary=:all: --no-deps '
            f'--platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 '
            f'--dest {_powershell_quote(directory)} numpy=={NUMPY_VERSION}')


def _ensure_numpy_wheel(cache: Path, temporary: Path, wheel_input=None, onedir=False):
    """使用指定 wheel，或将自动下载的 wheel 保存在缓存中"""
    if wheel_input is not None:
        wheel = Path(wheel_input).expanduser().resolve()
        if wheel.name.casefold() != NUMPY_WHEEL.casefold():
            raise BuildPreparationError(f'需要指定 {_powershell_quote(NUMPY_WHEEL)}')
        if not wheel.is_file():
            raise BuildPreparationError(f'找不到 NumPy wheel：{_powershell_quote(wheel)}')
        return wheel

    cached = cache / NUMPY_WHEEL
    if cached.is_file():
        print(f'使用已缓存的 NumPy wheel：{cached}', flush=True)
        return cached

    offline_dir = cache
    offline_wheel = cached
    offline_build = (f'& {_powershell_quote(Path(sys.executable).resolve())} '
                     f'{_powershell_quote(ROOT / "build_support/build_windows.py")} '
                     f'{"--onedir " if onedir else ""}--numpy-wheel {_powershell_quote(offline_wheel)}')
    help_text = (f'请检查网络，或在联网环境准备 wheel：\n{_wheel_prepare_command(offline_dir)}\n'
                 f'使用已有 wheel 构建：\n{offline_build}')
    try:
        download_dir = temporary / 'download'
        download_dir.mkdir()
        temp_dir = temporary / 'download-temp'
        temp_dir.mkdir()
        env = os.environ.copy()
        # 保留代理和证书设置，不读取自定义 pip 软件源
        allowed_pip_settings = {'PIP_PROXY', 'PIP_CERT', 'PIP_CLIENT_CERT'}
        for name in list(env):
            if name.upper().startswith('PIP_') and name.upper() not in allowed_pip_settings:
                env.pop(name)
        env.update({'TMP': str(temp_dir), 'TEMP': str(temp_dir),
                    'PIP_CONFIG_FILE': os.devnull, 'PIP_NO_CACHE_DIR': '1',
                    'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUTF8': '1',
                    'PYTHONIOENCODING': 'utf-8:backslashreplace'})
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        print(f'正在下载 NumPy {NUMPY_VERSION} wheel', flush=True)
        command = [sys.executable, '-m', 'pip', 'download', '--index-url', NUMPY_INDEX,
                   '--only-binary=:all:', '--no-deps', '--platform', 'win_amd64',
                   '--python-version', '3.13', '--implementation', 'cp', '--abi', 'cp313',
                   '--disable-pip-version-check', '--progress-bar', 'off', '--timeout', '20',
                   '--retries', '2', '--dest', str(download_dir), f'numpy=={NUMPY_VERSION}']
        _run_limited(command, cwd=ROOT, env=env, stage='下载 NumPy', timeout=300)
        downloaded = download_dir / NUMPY_WHEEL
        if not downloaded.is_file():
            raise BuildPreparationError(f'下载后未找到 NumPy wheel\n{help_text}')
        _publish_file(downloaded, cached)
    except subprocess.CalledProcessError as error:
        raise BuildPreparationError(f'自动下载 NumPy wheel 失败（退出码 {error.returncode}）\n{help_text}') from None
    except OSError as error:
        raise BuildPreparationError(f'准备 NumPy wheel 失败：{error.strerror or error}\n{help_text}') from None
    return cached


def _publish_file(source: Path, destination: Path):
    """跨磁盘复制到目标目录，再原子替换目标"""
    with tempfile.NamedTemporaryFile(prefix='.exifframe-', suffix='.tmp',
                                     dir=destination.parent, delete=False) as output:
        staged = Path(output.name)
    try:
        shutil.copyfile(source, staged)
        os.replace(staged, destination)
    finally:
        staged.unlink(missing_ok=True)


def _copy_file(source: Path, target: Path, allowed_root: Path):
    """只写入指定发布目录"""
    if not target.resolve().is_relative_to(allowed_root):
        raise ValueError('发布路径超出目标目录')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path, allowed_root: Path):
    """复制发布资源，不携带用户界面缓存和临时文件"""
    for item in source.rglob('*'):
        if not item.is_file() or item.name in {'desktop.json', 'ui.json'} or item.suffix == '.tmp':
            continue
        _copy_file(item, target / item.relative_to(source), allowed_root)


def _check_inputs():
    """检查构建环境和必需资源"""
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13) or sysconfig.get_platform() != 'win-amd64':
        raise BuildPreparationError('需要 Windows x64 和 Python 3.13')
    try:
        version = importlib.metadata.version('PyInstaller')
    except importlib.metadata.PackageNotFoundError:
        raise BuildPreparationError(f'缺少 PyInstaller {PYINSTALLER_VERSION}') from None
    if version != PYINSTALLER_VERSION:
        raise BuildPreparationError(f'需要 PyInstaller {PYINSTALLER_VERSION}，当前版本为 {version}')

    for relative in ('config/config.ini', 'static/logo.ico', 'static/preview.jpg', 'pyproject.toml'):
        if not (ROOT / relative).is_file():
            raise BuildPreparationError(f'缺少发布资源：{ROOT / relative}')
    for relative in ('config/fonts', 'config/logos', 'config/templates'):
        directory = ROOT / relative
        if not directory.is_dir():
            raise BuildPreparationError(f'发布资源目录不存在：{directory}')
    exiftool = ROOT / 'exiftool'
    if not any((exiftool / name).is_file() for name in ('exiftool.exe', 'exiftool(-k).exe')):
        raise BuildPreparationError(f'缺少 ExifTool 程序，请将 exiftool.exe 放入 {exiftool}')
    if not (exiftool / 'exiftool_files').is_dir():
        raise BuildPreparationError(f'缺少 ExifTool 支持文件，请补全 {exiftool / "exiftool_files"}')


def _is_redirected(path: Path):
    """拒绝符号链接和 Windows junction 指向其他目录"""
    return path.is_symlink() or path.is_junction()


def _build_root():
    """限制发布和下载缓存位于实际的项目构建目录"""
    directory = ROOT / 'build'
    if _is_redirected(directory) or not directory.resolve().is_relative_to(ROOT):
        raise BuildPreparationError('构建目录不能是符号链接或指向项目外')
    directory.mkdir(parents=True, exist_ok=True)
    return directory.resolve()


def _onedir_parent(build_root: Path):
    parent = build_root / 'onedir'
    if _is_redirected(parent) or not parent.resolve().is_relative_to(build_root):
        raise BuildPreparationError('目录版发布位置不能是符号链接或指向构建目录外')
    return parent


def _publish_onedir(package: Path, destination: Path, temporary: Path, build_root: Path):
    """安全发布目录，短暂占用时有限重试原子重命名"""
    for attempt in range(5):
        parent = _onedir_parent(build_root)
        if (_is_redirected(package) or _is_redirected(destination)
                or not temporary.resolve().is_relative_to(build_root)
                or not package.resolve().is_relative_to(temporary.resolve())
                or destination.resolve().parent != parent.resolve()):
            raise BuildPreparationError('目录版发布路径不安全')
        try:
            package.rename(destination)
            return
        except OSError as error:
            if sys.platform != 'win32' or getattr(error, 'winerror', None) not in (5, 32) or attempt == 4:
                raise
            time.sleep(0.05 * 2**attempt)


def _build_environment(numpy_target: Path, mode: str):
    """限定搜索路径，避免从其他软件目录收集同名动态库"""
    env = os.environ.copy()
    windows = Path(env.get('SystemRoot', r'C:\Windows'))
    prefix = Path(sys.prefix)
    temporary = numpy_target.parent / 'temp'
    temporary.mkdir(parents=True, exist_ok=True)
    env['PATH'] = os.pathsep.join(str(path) for path in (
        windows / 'System32', windows, prefix, prefix / 'Scripts',
        prefix / 'Library/bin', prefix / 'DLLs', windows / 'System32/Wbem',
    ) if path.is_dir())
    env['PYTHONPATH'] = os.pathsep.join((str(numpy_target), str(ROOT / 'build_support')))
    env['PYTHONNOUSERSITE'] = '1'
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8:backslashreplace'
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['TMP'] = env['TEMP'] = str(temporary)
    env['PYINSTALLER_CONFIG_DIR'] = str(temporary / 'pyinstaller')
    env['PIP_NO_CACHE_DIR'] = '1'
    env['PIP_CONFIG_FILE'] = os.devnull
    env['EXIFFRAME_NUMPY_TARGET'] = str(numpy_target)
    env['EXIFFRAME_BUNDLE_MODE'] = mode
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONOPTIMIZE', None)
    return env


def _prepare_numpy(wheel: Path, numpy_target: Path):
    """直接解压 wheel 到本次构建的临时目录"""
    try:
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(numpy_target)
    except (OSError, zipfile.BadZipFile) as error:
        raise BuildPreparationError(f'无法解压 NumPy wheel：{wheel}') from error
    print('NumPy 准备完成', flush=True)


def build(onedir=False, numpy_wheel=None):
    """构建单文件，或将目录版发布到全新的目录"""
    _check_inputs()
    build_root = _build_root()
    cache = build_root / 'download'
    cache.mkdir(parents=True, exist_ok=True)
    if onedir:
        _onedir_parent(build_root)
    elif _is_redirected(build_root / 'ExifFrame.exe'):
        raise BuildPreparationError('单文件发布位置不能是符号链接')
    mode = 'onedir' if onedir else 'onefile'
    with tempfile.TemporaryDirectory(prefix='exifframe-package-') as temporary:
        temporary = Path(temporary)
        wheel = _ensure_numpy_wheel(cache, temporary, numpy_wheel, onedir)
        numpy_target = temporary / 'numpy'
        _prepare_numpy(wheel, numpy_target)
        env = _build_environment(numpy_target, mode)
        staging = temporary / 'package'
        print('开始打包', flush=True)
        _run_limited([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                      '--distpath', str(staging), '--workpath', str(temporary / 'work'),
                      str(ROOT / 'build_support/windows.spec')], cwd=ROOT, env=env,
                     stage='PyInstaller 打包', timeout=1800)

        if onedir:
            package = staging / 'ExifFrame'
            if not (package / 'ExifFrame.exe').is_file():
                raise FileNotFoundError('目录版构建未生成程序')
            for relative in ('config/fonts', 'config/logos', 'config/templates', 'static'):
                _copy_tree(ROOT / relative, package / relative, package)
            _copy_tree(ROOT / 'exiftool', package / 'exiftool', package)
            for relative in ('config/config.ini', 'pyproject.toml'):
                _copy_file(ROOT / relative, package / relative, package)
            parent = _onedir_parent(build_root)
            parent.mkdir(parents=True, exist_ok=True)
            # 整目录发布避免混入旧二进制，也不覆盖旧版用户文件
            destination = parent / f'ExifFrame-{uuid.uuid4().hex}'
            with tempfile.TemporaryDirectory(prefix='exifframe-publish-', dir=build_root) as staging_dir:
                staged_package = Path(staging_dir) / 'ExifFrame'
                shutil.copytree(package, staged_package)
                _publish_onedir(staged_package, destination, Path(staging_dir), build_root)
            executable = destination / 'ExifFrame.exe'
        else:
            executable = build_root / 'ExifFrame.exe'
            generated = staging / 'ExifFrame.exe'
            if (_is_redirected(executable) or _is_redirected(generated)
                    or not generated.resolve().is_relative_to(temporary.resolve())
                    or executable.resolve().parent != build_root):
                raise BuildPreparationError('单文件发布路径不安全')
            _publish_file(generated, executable)
    print(f'构建完成：{executable}', flush=True)
    return executable


def _configure_output():
    """兼容使用非 UTF-8 编码的终端和输出管道"""
    for stream in (sys.stdout, sys.stderr):
        configure = getattr(stream, 'reconfigure', None)
        if callable(configure):
            try:
                configure(encoding='utf-8', errors='backslashreplace')
            except (OSError, ValueError):
                pass


def main(argv=None):
    """显示简洁的准备错误并保留构建工具原始日志"""
    _configure_output()
    parser = argparse.ArgumentParser(description='构建 Windows 单文件或目录版')
    parser.add_argument('--onedir', action='store_true', help='构建资源外置的目录版')
    parser.add_argument('--numpy-wheel', type=Path, help='离线构建时使用已下载的官方 NumPy wheel')
    args = parser.parse_args(argv)
    try:
        build(onedir=args.onedir, numpy_wheel=args.numpy_wheel)
    except BuildPreparationError as error:
        print(f'构建准备失败：{error}', file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f'构建命令失败（退出码 {error.returncode}），请查看上方日志', file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f'构建失败：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
