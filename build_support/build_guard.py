"""限制 Windows 构建子进程的资源占用"""

import ctypes
import subprocess
import time
from ctypes import wintypes


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ('length', wintypes.DWORD), ('load', wintypes.DWORD),
        ('total_physical', ctypes.c_uint64), ('available_physical', ctypes.c_uint64),
        ('total_page', ctypes.c_uint64), ('available_page', ctypes.c_uint64),
        ('total_virtual', ctypes.c_uint64), ('available_virtual', ctypes.c_uint64),
        ('available_extended', ctypes.c_uint64),
    ]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
        ('max_working_set', ctypes.c_size_t), ('active_processes', wintypes.DWORD),
        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
        ('scheduling', wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'read_operations', 'write_operations', 'other_operations',
        'read_bytes', 'write_bytes', 'other_bytes',
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('basic', _BasicLimits), ('io', _IoCounters),
        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ('total_user', ctypes.c_int64), ('total_kernel', ctypes.c_int64),
        ('period_user', ctypes.c_int64), ('period_kernel', ctypes.c_int64),
        ('page_faults', wintypes.DWORD), ('total_processes', wintypes.DWORD),
        ('active_processes', wintypes.DWORD), ('terminated_processes', wintypes.DWORD),
    ]


_BOOTSTRAP = '''
import runpy, sys
if sys.stdin.buffer.read(1) != b'1':
    raise SystemExit(1)
mode, target = sys.argv[1:3]
sys.argv = [target, *sys.argv[3:]]
if mode == '-m':
    runpy.run_module(target, run_name='__main__', alter_sys=True)
elif mode == '-c':
    exec(compile(target, '<string>', 'exec'), {'__name__': '__main__'})
else:
    raise SystemExit('不支持的构建命令')
'''


def _job():
    """创建限制整个子进程树的 Windows Job"""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                ctypes.c_void_p, wintypes.DWORD)
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessAffinityMask.argtypes = (wintypes.HANDLE,
                                               ctypes.POINTER(ctypes.c_size_t),
                                               ctypes.POINTER(ctypes.c_size_t))
    kernel.GetProcessAffinityMask.restype = wintypes.BOOL
    kernel.GlobalMemoryStatusEx.argtypes = (ctypes.POINTER(_MemoryStatus),)
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    memory = _MemoryStatus()
    memory.length = ctypes.sizeof(memory)
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ctypes.WinError(ctypes.get_last_error())
    memory_limit = min(4 * 1024**3, memory.available_physical // 2, memory.available_page // 2)
    if memory_limit < 1024**3:
        raise OSError('可用内存不足，无法安全启动构建，请关闭其他程序后重试')

    available = ctypes.c_size_t()
    system = ctypes.c_size_t()
    if not kernel.GetProcessAffinityMask(kernel.GetCurrentProcess(), ctypes.byref(available), ctypes.byref(system)):
        raise ctypes.WinError(ctypes.get_last_error())
    first = available.value & -available.value
    remaining = available.value ^ first
    affinity = first | (remaining & -remaining)
    if not affinity:
        raise OSError('无法确定构建可用的 CPU')

    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = _ExtendedLimits()
        # 低优先级、最多两个逻辑核心、进程树总内存上限，关闭时终止子进程
        limits.basic.flags = 0x20 | 0x10 | 0x200 | 0x2000
        limits.basic.priority = 0x4000
        limits.basic.affinity = affinity
        limits.job_memory = memory_limit
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        return kernel, job
    except BaseException:
        kernel.CloseHandle(job)
        raise


def run(command, *, cwd, env, stage, timeout):
    """先设置限制，再放行 Python 子进程"""
    kernel, job = _job()
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD,
                                                  ctypes.c_void_p)
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    child_env = env.copy()
    child_env.update({name: '1' for name in (
        'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
    )})
    process = None
    assigned = False
    try:
        process = subprocess.Popen(
            [command[0], '-c', _BOOTSTRAP, *command[1:]], cwd=cwd, env=child_env,
            stdin=subprocess.PIPE,
            creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )
        if not kernel.AssignProcessToJobObject(job, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        assigned = True
        try:
            process.communicate(input=b'1', timeout=timeout)
        except subprocess.TimeoutExpired:
            raise TimeoutError(f'{stage}超时（{timeout} 秒），已停止构建进程') from None
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    finally:
        try:
            if assigned:
                kernel.TerminateJobObject(job, 1)
                accounting = _Accounting()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if not kernel.QueryInformationJobObject(job, 1, ctypes.byref(accounting),
                                                            ctypes.sizeof(accounting), None):
                        break
                    if not accounting.active_processes:
                        break
                    time.sleep(0.05)
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            kernel.CloseHandle(job)
