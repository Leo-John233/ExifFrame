"""使用隔离的 NumPy 构建 Windows 单文件或目录版"""

import argparse
import hashlib
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
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUMPY_VERSION = '2.5.2'
NUMPY_WHEEL = f'numpy-{NUMPY_VERSION}-cp313-cp313-win_amd64.whl'
NUMPY_SHA256 = '85aaccb24182c25df891ad0ec333585967e115269d5f1b17f2c9ae005bc96657'
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


def _validate_wheel(wheel: Path):
    """只接受固定版本的官方 wheel"""
    if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest() != NUMPY_SHA256:
        raise BuildPreparationError(
            f'NumPy wheel 校验失败：{_powershell_quote(wheel)}\n'
            '请提供正确版本的 wheel 后重新运行构建'
        )


def _ensure_numpy_wheel(temporary: Path, wheel_input=None, onedir=False):
    """读取用户提供的 wheel 或下载到本次构建的临时目录"""
    if wheel_input is not None:
        wheel = Path(wheel_input).expanduser().resolve()
        if wheel.name.casefold() != NUMPY_WHEEL.casefold():
            raise BuildPreparationError(f'需要指定 {_powershell_quote(NUMPY_WHEEL)}')
        _validate_wheel(wheel)
        return wheel

    offline_dir = ROOT / 'build/offline-wheels'
    offline_wheel = offline_dir / NUMPY_WHEEL
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
                    'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        print(f'正在下载 NumPy {NUMPY_VERSION} wheel', flush=True)
        command = [sys.executable, '-m', 'pip', 'download', '--index-url', NUMPY_INDEX,
                   '--only-binary=:all:', '--no-deps', '--platform', 'win_amd64',
                   '--python-version', '3.13', '--implementation', 'cp', '--abi', 'cp313',
                   '--disable-pip-version-check', '--progress-bar', 'off', '--timeout', '20',
                   '--retries', '2', '--dest', str(download_dir), f'numpy=={NUMPY_VERSION}']
        subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True)
        downloaded = download_dir / NUMPY_WHEEL
        if not downloaded.is_file() or hashlib.sha256(downloaded.read_bytes()).hexdigest() != NUMPY_SHA256:
            raise BuildPreparationError(f'下载的 NumPy wheel 校验失败，已丢弃临时文件\n{help_text}')
    except subprocess.CalledProcessError as error:
        raise BuildPreparationError(f'自动下载 NumPy wheel 失败（退出码 {error.returncode}）\n{help_text}') from None
    except OSError as error:
        raise BuildPreparationError(f'准备 NumPy wheel 失败：{error.strerror or error}\n{help_text}') from None
    return downloaded


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
    """检查构建环境和完整资源，缺失时拒绝生成不完整的程序"""
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
    for relative in ('config/fonts', 'config/logos', 'config/templates', 'exiftool/exiftool_files'):
        directory = ROOT / relative
        if not directory.is_dir() or not any(item.is_file() for item in directory.rglob('*')):
            raise BuildPreparationError(f'发布资源目录为空或不存在：{directory}')
    if not any((ROOT / 'exiftool' / name).is_file() for name in ('exiftool.exe', 'exiftool(-k).exe')):
        raise BuildPreparationError('exiftool 目录中缺少 exiftool.exe 或 exiftool(-k).exe')


def _is_redirected(path: Path):
    """拒绝符号链接和 Windows junction 指向其他目录"""
    return path.is_symlink() or path.is_junction()


def _build_root():
    """限制发布和临时文件位于实际的项目构建目录"""
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


def _install_numpy(wheel: Path, numpy_target: Path, env: dict):
    """只在工作目录的临时位置安装并验证官方 wheel"""
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--no-compile', '--disable-pip-version-check', '--target', str(numpy_target),
                    str(wheel)], cwd=ROOT, env=env, check=True)
    check = '''
import importlib.metadata as metadata
import os
from pathlib import Path
import numpy
target = Path(os.environ['EXIFFRAME_NUMPY_TARGET']).resolve()
distribution = metadata.distribution('numpy')
module_path = Path(numpy.__file__).resolve()
metadata_path = Path(distribution.locate_file('')).resolve()
installer = (distribution.read_text('INSTALLER') or '').strip()
if not module_path.is_relative_to(target):
    raise RuntimeError(f'NumPy 模块路径不在构建目录: {module_path}')
if not metadata_path.is_relative_to(target):
    raise RuntimeError(f'NumPy 元数据路径不在构建目录: {metadata_path}')
if numpy.__version__ != distribution.version or numpy.__version__ != '2.5.2':
    raise RuntimeError('NumPy 版本不匹配')
if installer != 'pip':
    raise RuntimeError(f'NumPy 安装来源不是 pip: {installer}')
print(f'NumPy {numpy.__version__}: {module_path} (INSTALLER={installer})', flush=True)
'''
    subprocess.run([sys.executable, '-c', check], cwd=ROOT, env=env, check=True)


def build(onedir=False, numpy_wheel=None):
    """构建单文件，或将目录版发布到全新的目录"""
    _check_inputs()
    build_root = _build_root()
    if onedir:
        _onedir_parent(build_root)
    elif _is_redirected(build_root / 'ExifFrame.exe'):
        raise BuildPreparationError('单文件发布位置不能是符号链接')
    mode = 'onedir' if onedir else 'onefile'
    with tempfile.TemporaryDirectory(prefix='windows-package-', dir=build_root) as temporary:
        temporary = Path(temporary)
        wheel = _ensure_numpy_wheel(temporary, numpy_wheel, onedir)
        numpy_target = temporary / 'numpy'
        env = _build_environment(numpy_target, mode)
        _install_numpy(wheel, numpy_target, env)
        staging = temporary / 'package'
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(staging), '--workpath', str(temporary / 'work'),
                        str(ROOT / 'build_support/windows.spec')], cwd=ROOT, env=env, check=True)

        if onedir:
            package = staging / 'ExifFrame'
            if not (package / 'ExifFrame.exe').is_file():
                raise FileNotFoundError('目录版构建未生成程序')
            for relative in ('config/fonts', 'config/logos', 'config/templates', 'static', 'exiftool'):
                _copy_tree(ROOT / relative, package / relative, package)
            for relative in ('config/config.ini', 'pyproject.toml'):
                _copy_file(ROOT / relative, package / relative, package)
            parent = _onedir_parent(build_root)
            parent.mkdir(parents=True, exist_ok=True)
            # 整目录发布避免混入旧二进制，也不覆盖旧版用户文件
            destination = parent / f'ExifFrame-{uuid.uuid4().hex}'
            _publish_onedir(package, destination, temporary, build_root)
            executable = destination / 'ExifFrame.exe'
        else:
            executable = build_root / 'ExifFrame.exe'
            generated = staging / 'ExifFrame.exe'
            if (_is_redirected(executable) or _is_redirected(generated)
                    or not generated.resolve().is_relative_to(temporary.resolve())
                    or executable.resolve().parent != build_root):
                raise BuildPreparationError('单文件发布路径不安全')
            os.replace(generated, executable)
    print(f'构建完成：{executable}', flush=True)
    return executable


def main(argv=None):
    """显示简洁的准备错误并保留构建工具原始日志"""
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
