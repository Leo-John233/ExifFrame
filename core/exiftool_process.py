"""管理外部 ExifTool 的搜索路径和常驻读取进程"""

import atexit
import ctypes
import os
import queue
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from threading import Condition, Event, Lock, Thread
from core.process_launch import hidden_process_kwargs


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


def _start_exiftool(command: list[str]) -> subprocess.Popen:
    """仅在创建子进程期间恢复系统搜索路径"""
    hidden = hidden_process_kwargs()
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **hidden)

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
        ctypes.set_last_error(0)
        length = get_directory(0, None)
        if not length and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(length + 1) if length else None
        if buffer is not None:
            ctypes.set_last_error(0)
            if not get_directory(len(buffer), buffer) and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())
        previous = buffer.value if buffer is not None else None
        if not set_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=environment, **hidden)
        finally:
            set_directory(previous)


def run_exiftool(command: list[str], *, input: bytes, timeout: int) -> subprocess.CompletedProcess:
    """一次性执行写入等操作，不与常驻读取进程混用"""
    process = _start_exiftool(command)
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


class _ExifToolReader:
    """串行复用一个进程并限制等待时间"""

    def __init__(self):
        self.lock = Lock()
        self.process = None
        self.signature = None
        self.stop = None
        self.stdout = None
        self.stderr = None
        self.error_condition = None
        self.errors_closed = None
        self.threads = ()
        self.sequence = 0
        self.generation = 0

    @staticmethod
    def _pipe_output(stream, messages, stopped):
        try:
            while not stopped.is_set():
                line = stream.readline(65536)
                while not stopped.is_set():
                    try:
                        messages.put(line, timeout=.1)
                        break
                    except queue.Full:
                        continue
                if not line:
                    break
        except (OSError, ValueError):
            if not stopped.is_set():
                try:
                    messages.put(b'', timeout=.1)
                except queue.Full:
                    pass

    @staticmethod
    def _pipe_errors(stream, errors, condition, closed):
        try:
            while line := stream.readline(4096):
                with condition:
                    errors.append(line)
                    condition.notify_all()
        except (OSError, ValueError):
            pass
        finally:
            with condition:
                closed.set()
                condition.notify_all()

    def _start(self, executable, signature):
        process = _start_exiftool([str(executable), '-stay_open', 'True', '-@', '-'])
        stopped, output, errors, condition = Event(), queue.Queue(maxsize=128), deque(maxlen=32), Condition()
        errors_closed = Event()
        threads = (Thread(target=self._pipe_output, args=(process.stdout, output, stopped), daemon=True),
                   Thread(target=self._pipe_errors, args=(process.stderr, errors, condition, errors_closed), daemon=True))
        self.process, self.signature, self.stop = process, signature, stopped
        self.stdout, self.stderr, self.threads = output, errors, threads
        self.error_condition = condition
        self.errors_closed = errors_closed
        for thread in threads:
            thread.start()

    def _close(self, force=False):
        process = self.process
        if process is None:
            return
        self.process, self.signature = None, None
        self.stop.set()
        if process.poll() is None:
            if not force:
                try:
                    process.stdin.write(b'-stay_open\nFalse\n')
                    process.stdin.flush()
                    process.wait(timeout=.5)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
        for thread in self.threads:
            thread.join(timeout=.2)
        for stream, thread in zip((process.stdout, process.stderr), self.threads):
            if thread.is_alive():
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def close(self):
        """退出时关闭进程，避免等待仍在运行的请求"""
        self.generation += 1
        if self.lock.acquire(timeout=.5):
            try:
                self._close()
            finally:
                self.lock.release()
        else:
            process = self.process
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass

    def _request(self, executable, path, options, deadline):
        self.sequence += 1
        marker = f'{self.sequence}'
        status_prefix = f'{{exifframe-status{marker}:'.encode('ascii')
        ready = f'{{ready{marker}}}'.encode('ascii')
        error_marker = f'{{exifframe-error{marker}}}'.encode('ascii')
        arguments = ['-charset', 'filename=UTF8', *options, str(path), '-echo3',
                     f'{{exifframe-status{marker}:${{status}}}}', '-echo4',
                     error_marker.decode('ascii'), f'-execute{marker}']
        with self.error_condition:
            self.stderr.clear()
        self.process.stdin.write(('\n'.join(arguments) + '\n').encode('utf-8'))
        self.process.stdin.flush()
        output, length, status = [], 0, None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired([str(executable)], 0)
            try:
                line = self.stdout.get(timeout=remaining)
            except queue.Empty:
                raise subprocess.TimeoutExpired([str(executable)], 0) from None
            if not line:
                raise EOFError('ExifTool 提前退出')
            value = line.rstrip(b'\r\n')
            if value == ready:
                if status is None:
                    raise EOFError('ExifTool 返回不完整')
                break
            if value.startswith(status_prefix) and value.endswith(b'}'):
                try:
                    status = int(value[len(status_prefix):-1])
                except ValueError:
                    raise EOFError('ExifTool 返回状态无效') from None
                continue
            length += len(line)
            if length > 16 * 1024 * 1024:
                raise ValueError('ExifTool 返回数据过大')
            output.append(line)
        with self.error_condition:
            while not any(line.rstrip(b'\r\n') == error_marker for line in self.stderr):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired([str(executable)], 0)
                if self.errors_closed.is_set():
                    raise EOFError('ExifTool 错误输出提前关闭')
                self.error_condition.wait(timeout=remaining)
            errors = b''.join(line for line in self.stderr if line.rstrip(b'\r\n') != error_marker)
        result = subprocess.CompletedProcess([str(executable)], status, b''.join(output), errors)
        result.check_returncode()
        return result

    def read(self, executable, path, options, timeout):
        """独占进程处理一个请求，异常时回收并在下次重启"""
        path = str(path)
        if any('\n' in item or '\r' in item for item in [path, *options]):
            raise ValueError('参数包含换行')
        deadline = time.monotonic() + timeout
        if not self.lock.acquire(timeout=max(0, timeout)):
            raise subprocess.TimeoutExpired([str(executable)], timeout)
        try:
            generation = self.generation
            info = Path(executable).stat()
            signature = (str(executable), info.st_mtime_ns, info.st_size)
            if self.process and (self.process.poll() is not None or signature != self.signature):
                self._close(force=True)
            for attempt in range(2):
                if self.process is None:
                    self._start(executable, signature)
                try:
                    return self._request(executable, path, options, deadline)
                except (BrokenPipeError, EOFError, OSError):
                    self._close(force=True)
                    if attempt or generation != self.generation or time.monotonic() >= deadline:
                        raise
                except (ValueError, subprocess.TimeoutExpired):
                    self._close(force=True)
                    raise
        finally:
            self.lock.release()


_reader = _ExifToolReader()
atexit.register(_reader.close)


def read_exiftool(executable, path, *, options=None, timeout=20):
    """从常驻进程读取单个文件的元数据"""
    if options is None:
        options = ['-j', '-l', '-lang', 'en', '-d', '%Y-%m-%d %H:%M:%S%3f%z']
    return _reader.read(executable, path, options, timeout)


def close_exiftool():
    """主动回收常驻进程，之后可以再次按需启动"""
    _reader.close()
