# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
import sys
from pathlib import Path

root = Path(SPECPATH).resolve().parent
bootstrap = str(root / 'build_support')
os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [bootstrap, os.environ.get('PYTHONPATH', '')]))
numpy_target = Path(os.environ['EXIFFRAME_NUMPY_TARGET']).resolve()
mode = os.environ['EXIFFRAME_BUNDLE_MODE']
if mode not in ('onefile', 'onedir'):
    raise ValueError('无效的打包模式')

# 补充 Conda 版 Pillow 使用的图像解码库
library_dir = Path(sys.prefix) / 'Library/bin'
image_binaries = [(str(library_dir / name), '.') for name in
                  ('libwebp.dll', 'libwebpdemux.dll', 'libwebpmux.dll', 'zlib-ng2.dll')
                  if (library_dir / name).is_file()]
qt_directory = Path(importlib.util.find_spec('PySide6').origin).parent
translations = [(str(qt_directory / 'translations' / name), 'translations')
                for name in ('qtbase_zh_CN.qm', 'qt_zh_CN.qm')
                if (qt_directory / 'translations' / name).is_file()]


def resource_files(relative):
    """保持资源相对路径并排除本机界面缓存"""
    source = root / relative
    if source.is_file():
        return [(str(source), str(Path(relative).parent))]
    return [(str(item), str(item.parent.relative_to(root))) for item in sorted(source.rglob('*'))
            if item.is_file() and item.name not in {'desktop.json', 'ui.json'} and item.suffix != '.tmp']


datas = translations[:]
if mode == 'onefile':
    for relative in ('config/config.ini', 'config/fonts', 'config/logos', 'config/templates',
                     'static', 'exiftool', 'pyproject.toml'):
        datas.extend(resource_files(relative))
    datas.append((str(root / 'build_support/exifframe-onefile.marker'), '.'))

a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(numpy_target), str(root)],
    binaries=image_binaries,
    datas=datas,
    # 处理器由注册表动态导入
    hiddenimports=['processor.filters', 'processor.generators', 'processor.mergers',
                   'build_support.package_verify'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# 避免宿主上其他软件的同名 DLL 混入发布包
trusted_roots = [root, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                 Path(os.environ.get('SystemRoot', r'C:\Windows')).resolve()]
for name, source, kind in a.binaries:
    resolved = Path(source).resolve()
    if not any(resolved.is_relative_to(parent) for parent in trusted_roots):
        raise RuntimeError(f'构建依赖来自未预期目录：{name}: {resolved}')

pyz = PYZ(a.pure)
common = dict(
    name='ExifFrame',
    icon=str(root / 'static/logo.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if mode == 'onefile':
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    package = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                      upx_exclude=[], name='ExifFrame')
