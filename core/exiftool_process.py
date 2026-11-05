"""为外部 ExifTool 隔离打包程序的动态库搜索路径"""

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from threading import Lock


_launch_lock = Lock()


def _external_environment() -> dict[str, str]:
    """移除打包资源路径，保留系统和用户的其他搜索路径"""
    environment = os.environ.copy()
    bundled = getattr(sys, '_MEIPASS', None)
    if not bundled:
        return environment
    root = Path(bundled).resolve()
    entries = []
    for item in environment.get('PATH', '').split(os.pathsep):
        try:
            if item and Path(item.strip('"')).resolve().is_relative_to(root):
                continue
        except (OSError, ValueError):
            pass
        entries.append(item)
    environment['PATH'] = os.pathsep.join(entries)
    return environment


def run_exiftool(command: list[str], *, input: bytes, timeout: int) -> subprocess.CompletedProcess:
    """仅在创建子进程期间恢复系统搜索路径，等待执行时不占用锁"""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return subprocess.run(command, input=input, capture_output=True, timeout=timeout,
                              check=True, creationflags=flags)

    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    get_directory = kernel.GetDllDirectoryW
    get_directory.argtypes = (wintypes.DWORD, wintypes.LPWSTR)
    get_directory.restype = wintypes.DWORD
    set_directory = kernel.SetDllDirectoryW
    set_directory.argtypes = (wintypes.LPCWSTR,)
    set_directory.restype = wintypes.BOOL
    environment = _external_environment()
    with _launch_lock:
        length = get_directory(0, None)
        buffer = ctypes.create_unicode_buffer(length + 1) if length else None
        if buffer is not None and not get_directory(len(buffer), buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        previous = buffer.value if buffer is not None else None
        if not set_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=flags, env=environment)
        finally:
            set_directory(previous)
    try:
        stdout, stderr = process.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        process.kill()
        error.output, error.stderr = process.communicate()
        raise
    except BaseException:
        process.kill()
        process.wait()
        raise
    result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    result.check_returncode()
    return result
