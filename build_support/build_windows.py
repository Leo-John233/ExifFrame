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


def _wheel_prepare_command(cache_dir: Path):
    """提供不依赖当前工作目录的手动准备命令"""
    return (f'& {_powershell_quote(Path(sys.executable).resolve())} -m pip download '
            f'--index-url {NUMPY_INDEX} --only-binary=:all: --no-deps '
            f'--platform win_amd64 --python-version 3.13 --implementation cp --abi cp313 '
            f'--dest {_powershell_quote(cache_dir)} numpy=={NUMPY_VERSION}')


def _validate_wheel(wheel: Path):
    """只接受固定版本的官方 wheel"""
    if not wheel.is_file() or hashlib.sha256(wheel.read_bytes()).hexdigest() != NUMPY_SHA256:
        raise BuildPreparationError(
            f'NumPy wheel 校验失败：{_powershell_quote(wheel)}\n'
            '请移除损坏文件后重新运行构建，或将正确的 wheel 放入该目录'
        )


def _ensure_numpy_wheel():
    """优先使用缓存，缺失时校验下载内容后原子写入"""
    build_root = (ROOT / 'build').resolve()
    cache_dir = (build_root / 'wheels').resolve()
    if not build_root.is_relative_to(ROOT) or not cache_dir.is_relative_to(build_root):
        raise BuildPreparationError('构建缓存目录必须位于项目目录内')
    wheel = cache_dir / NUMPY_WHEEL
    if wheel.exists():
        _validate_wheel(wheel)
        return wheel

    help_text = (f'请检查网络，或在联网环境准备 wheel 并放入 {_powershell_quote(cache_dir)}\n'
                 f'手动准备命令：\n{_wheel_prepare_command(cache_dir)}')
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.numpy-download-', dir=cache_dir) as temporary:
            temporary = Path(temporary)
            download_dir = temporary / 'download'
            download_dir.mkdir()
            temp_dir = temporary / 'temp'
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
            try:
                # Windows 同盘重命名不会覆盖并发构建先写入的缓存
                downloaded.rename(wheel)
            except FileExistsError:
                _validate_wheel(wheel)
    except subprocess.CalledProcessError as error:
        raise BuildPreparationError(f'自动下载 NumPy wheel 失败（退出码 {error.returncode}）\n{help_text}') from None
    except OSError as error:
        raise BuildPreparationError(f'准备 NumPy wheel 失败：{error.strerror or error}\n{help_text}') from None
    return wheel


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
    return _ensure_numpy_wheel()


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


def build(onedir=False):
    """构建单文件，或将目录版发布到全新的目录"""
    wheel = _check_inputs()
    build_root = (ROOT / 'build').resolve()
    dist_root = (ROOT / 'dist').resolve()
    if not build_root.is_relative_to(ROOT) or not dist_root.is_relative_to(ROOT):
        raise ValueError('构建目录必须位于项目目录内')
    build_root.mkdir(parents=True, exist_ok=True)
    mode = 'onedir' if onedir else 'onefile'
    with tempfile.TemporaryDirectory(prefix='windows-package-', dir=build_root) as temporary:
        temporary = Path(temporary)
        numpy_target = temporary / 'numpy'
        env = _build_environment(numpy_target, mode)
        _install_numpy(wheel, numpy_target, env)
        staging = temporary / 'dist'
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(staging), '--workpath', str(temporary / 'work'),
                        str(ROOT / 'build_support/windows.spec')], cwd=ROOT, env=env, check=True)

        if onedir:
            if not (staging / 'ExifFrame/ExifFrame.exe').is_file():
                raise FileNotFoundError('目录版构建未生成程序')
            parent = (dist_root / 'onedir').resolve()
            if not parent.is_relative_to(dist_root):
                raise ValueError('发布路径超出目标目录')
            parent.mkdir(parents=True, exist_ok=True)
            # 每次使用新目录，旧二进制、配置和照片均不被覆盖
            destination = Path(tempfile.mkdtemp(prefix='ExifFrame-', dir=parent)).resolve()
            _copy_tree(staging / 'ExifFrame', destination, destination)
            for relative in ('config/fonts', 'config/logos', 'config/templates', 'static', 'exiftool'):
                _copy_tree(ROOT / relative, destination / relative, destination)
            for relative in ('config/config.ini', 'pyproject.toml'):
                _copy_file(ROOT / relative, destination / relative, destination)
            executable = destination / 'ExifFrame.exe'
        else:
            destination = (dist_root / 'single').resolve()
            if not destination.is_relative_to(dist_root):
                raise ValueError('发布路径超出目标目录')
            executable = destination / 'ExifFrame.exe'
            _copy_file(staging / 'ExifFrame.exe', executable, destination)
    print(f'构建完成：{executable}', flush=True)
    return executable


def main(argv=None):
    """显示简洁的准备错误并保留构建工具原始日志"""
    parser = argparse.ArgumentParser(description='构建 Windows 单文件或目录版')
    parser.add_argument('--onedir', action='store_true', help='构建资源外置的目录版')
    args = parser.parse_args(argv)
    try:
        build(onedir=args.onedir)
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
