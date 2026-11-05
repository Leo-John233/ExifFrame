"""使用隔离的 NumPy 构建 Windows 单文件或目录版"""

import argparse
import hashlib
import importlib.metadata
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUMPY_VERSION = '2.5.2'
NUMPY_WHEEL = f'numpy-{NUMPY_VERSION}-cp313-cp313-win_amd64.whl'
NUMPY_SHA256 = '85aaccb24182c25df891ad0ec333585967e115269d5f1b17f2c9ae005bc96657'
PYINSTALLER_VERSION = '6.20.0'


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
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 13) or sys.maxsize <= 2**32:
        raise RuntimeError('需要 64 位 Windows 和 Python 3.13')
    version = importlib.metadata.version('PyInstaller')
    if version != PYINSTALLER_VERSION:
        raise RuntimeError(f'需要 PyInstaller {PYINSTALLER_VERSION}，当前版本为 {version}')

    wheel = ROOT / 'build/wheels' / NUMPY_WHEEL
    if not wheel.is_file():
        raise FileNotFoundError(
            f'缺少 {wheel}\n请运行：{sys.executable} -m pip download '
            f'--only-binary=:all: --no-deps --dest build/wheels numpy=={NUMPY_VERSION}'
        )
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != NUMPY_SHA256:
        raise ValueError(f'NumPy wheel 校验失败：{wheel}')

    for relative in ('config/config.ini', 'static/logo.ico', 'static/preview.jpg', 'pyproject.toml'):
        if not (ROOT / relative).is_file():
            raise FileNotFoundError(f'缺少发布资源：{ROOT / relative}')
    for relative in ('config/fonts', 'config/logos', 'config/templates', 'exiftool/exiftool_files'):
        directory = ROOT / relative
        if not directory.is_dir() or not any(item.is_file() for item in directory.rglob('*')):
            raise FileNotFoundError(f'发布资源目录为空或不存在：{directory}')
    if not any((ROOT / 'exiftool' / name).is_file() for name in ('exiftool.exe', 'exiftool(-k).exe')):
        raise FileNotFoundError('exiftool 目录中缺少 exiftool.exe 或 exiftool(-k).exe')
    return wheel


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


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='构建 Windows 单文件或目录版')
    parser.add_argument('--onedir', action='store_true', help='构建资源外置的目录版')
    args = parser.parse_args()
    build(onedir=args.onedir)
