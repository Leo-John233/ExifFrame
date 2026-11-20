"""后台工具统一使用无控制台窗口启动参数，不修改调用方的进程配置"""

import copy
import subprocess
import sys


def hidden_process_kwargs(*, creationflags=0, startupinfo=None):
    """Windows 同时隐藏控制台和启动窗口，其他平台不传 Windows 参数"""
    if sys.platform != 'win32':
        return {}
    if startupinfo is None:
        info = subprocess.STARTUPINFO()
    else:
        info = startupinfo.copy() if hasattr(startupinfo, 'copy') else copy.copy(startupinfo)
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    # 新控制台和 detached 标志会使 CREATE_NO_WINDOW 失效，后台工具不能携带它们
    flags = int(creationflags) & ~(subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS)
    return {'creationflags': flags | subprocess.CREATE_NO_WINDOW, 'startupinfo': info}
