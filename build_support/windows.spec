# -*- mode: python ; coding: utf-8 -*-

import importlib.util
import os
import sys
from pathlib import Path
from PyInstaller.archive.writers import CArchiveWriter

root = Path(SPECPATH).resolve().parent
bootstrap = str(root / 'build_support')
os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [bootstrap, os.environ.get('PYTHONPATH', '')]))
numpy_target = Path(os.environ['EXIFFRAME_NUMPY_TARGET']).resolve()
exiftool = root / 'exiftool'
mode = os.environ['EXIFFRAME_BUNDLE_MODE']
if mode not in ('onefile', 'onedir'):
    raise ValueError('无效的打包模式')

# 使用 PyInstaller 6.20 的中等压缩等级，减少单文件打包时间
CArchiveWriter._COMPRESSION_LEVEL = 6

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
exiftool_datas = []
if mode == 'onefile':
    for relative in ('config/config.ini', 'config/fonts', 'config/logos', 'config/templates',
                     'static', 'pyproject.toml'):
        datas.extend(resource_files(relative))
    # ExifTool 自带完整运行目录，作为普通文件嵌入，避免重复分析其动态库
    exiftool_datas = [(str(Path('exiftool') / item.relative_to(exiftool)), str(item), 'DATA')
                      for item in sorted(exiftool.rglob('*')) if item.is_file()]
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
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, exiftool_datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    package = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                      upx_exclude=[], name='ExifFrame')
