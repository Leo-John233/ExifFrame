"""让打包隔离进程避开 Conda 与系统 ICU 的同名冲突"""

import ctypes
import os
import sys
from pathlib import Path

if sys.platform == 'win32':
    try:
        # 仅影响本次构建的子进程，不替换环境中的库文件
        system_icu = ctypes.WinDLL(str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icuuc.dll'))
    except OSError:
        pass
