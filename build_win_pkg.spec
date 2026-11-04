# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

# 隔离检查 Qt 的子进程同样需要优先加载系统 ICU
bootstrap = str(Path(SPECPATH) / 'build_support')
os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [bootstrap, os.environ.get('PYTHONPATH', '')]))

# 补充 Conda 版 Pillow 使用的图像解码库
library_dir = Path(sys.prefix) / 'Library/bin'
image_binaries = [(str(library_dir / name), '.') for name in
                  ('libwebp.dll', 'libwebpdemux.dll', 'libwebpmux.dll', 'zlib-ng2.dll')
                  if (library_dir / name).is_file()]
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=image_binaries,
    # 配置和预览素材随发布目录提供，保持可替换
    datas=[],
    # 处理器由注册表动态导入，需要显式收集
    hiddenimports=['processor.filters', 'processor.generators', 'processor.mergers'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ExifFrame',
    icon='./static/logo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
