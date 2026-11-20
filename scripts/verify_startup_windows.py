"""监测 Windows 新进程启动的窗口事件和首屏像素，不修改应用设置"""

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))


def isolated_source(output):
    """普通源码启动也会保存布局，监测只运行独立副本"""
    target = output / 'project'
    if target.exists():
        raise FileExistsError(f'Use a fresh output directory: {target}')
    target.mkdir(parents=True)
    for name in ('main.py', 'pyproject.toml'):
        shutil.copy2(ROOT / name, target / name)
    for name in ('core', 'processor', 'studio', 'build_support', 'static', 'exiftool'):
        shutil.copytree(ROOT / name, target / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    config = target / 'config'; config.mkdir()
    for item in (ROOT / 'config').iterdir():
        if item.is_file() and item.suffix in ('.ini', '.json'):
            shutil.copy2(item, config / item.name)
        elif item.is_dir() and item.name in {'fonts', 'logos', 'templates', 'style_presets', 'style_assets'}:
            shutil.copytree(item, config / item.name)
    return target / 'main.py'


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                ('name', wintypes.WCHAR * 260)]


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('mask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                ('verb', wintypes.LPCWSTR), ('file', wintypes.LPCWSTR), ('parameters', wintypes.LPCWSTR),
                ('directory', wintypes.LPCWSTR), ('show', ctypes.c_int), ('instance', wintypes.HINSTANCE),
                ('idlist', ctypes.c_void_p), ('class_name', wintypes.LPCWSTR), ('class_key', wintypes.HKEY),
                ('hotkey', wintypes.DWORD), ('icon', wintypes.HANDLE), ('process', wintypes.HANDLE)]


class BitmapInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                ('image_size', wintypes.DWORD), ('x_resolution', wintypes.LONG), ('y_resolution', wintypes.LONG),
                ('colors', wintypes.DWORD), ('important', wintypes.DWORD)]


def monitor(command, output, seconds=20, expect_dark=False, close=True):
    from PIL import Image, ImageGrab, ImageStat

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    try:
        user.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    shell.ShellExecuteExW.argtypes = (ctypes.POINTER(ShellExecuteInfo),)
    shell.ShellExecuteExW.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetLayeredWindowAttributes.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
                                              ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD))
    user.GetWindowRect.argtypes = user.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user.GetForegroundWindow.restype = wintypes.HWND
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.GetDC.argtypes = (wintypes.HWND,); user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user.PrintWindow.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    gdi.CreateCompatibleDC.argtypes = (wintypes.HDC,); gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE); gdi.SelectObject.restype = wintypes.HANDLE
    gdi.GetDIBits.argtypes = (wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                             ctypes.c_void_p, ctypes.POINTER(BitmapInfo), wintypes.UINT)
    gdi.DeleteObject.argtypes = (wintypes.HANDLE,); gdi.DeleteDC.argtypes = (wintypes.HDC,)
    event_callback_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                           wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
    enum_callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = (enum_callback_type, wintypes.LPARAM)
    user.SetWinEventHook.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, event_callback_type,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
    user.SetWinEventHook.restype = wintypes.HANDLE
    user.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
    user.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
    user.TranslateMessage.argtypes = user.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)

    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    root_pid = None
    known = set()
    processes = {}
    windows = {}
    events = []
    samples = []
    pending = set()
    unattributed_consoles = []
    last_scan = 0

    def capture(hwnd, width, height):
        dc = user.GetDC(hwnd)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        previous = gdi.SelectObject(memory, bitmap)
        try:
            if not user.PrintWindow(hwnd, memory, 3):
                raise OSError('Cannot capture target window')
            gdi.SelectObject(memory, previous)
            info = BitmapInfo(); info.size = ctypes.sizeof(info)
            info.width, info.height, info.planes, info.bits = width, -height, 1, 32
            data = ctypes.create_string_buffer(width * height * 4)
            if not gdi.GetDIBits(dc, bitmap, 0, height, data, ctypes.byref(info), 0):
                raise ctypes.WinError(ctypes.get_last_error())
            return Image.frombytes('RGB', (width, height), data.raw, 'raw', 'BGRX')
        finally:
            gdi.SelectObject(memory, previous)
            gdi.DeleteObject(bitmap); gdi.DeleteDC(memory); user.ReleaseDC(hwnd, dc)

    def elapsed():
        return round((time.perf_counter() - started) * 1000, 2)

    def process_tree():
        nonlocal last_scan
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return
        current = {}
        try:
            item = ProcessEntry(); item.size = ctypes.sizeof(item)
            exists = kernel.Process32FirstW(snapshot, ctypes.byref(item))
            while exists:
                current[item.pid] = (item.parent, item.name)
                exists = kernel.Process32NextW(snapshot, ctypes.byref(item))
        finally:
            kernel.CloseHandle(snapshot)
        if root_pid is not None:
            known.add(root_pid)
            while True:
                children = {pid for pid, (parent, _) in current.items() if parent in known}
                if children.issubset(known):
                    break
                known.update(children)
            for pid in known:
                if pid in current and pid not in processes:
                    parent, name = current[pid]
                    processes[pid] = {'pid': pid, 'parent': parent, 'name': name, 'first_seen_ms': elapsed()}
        last_scan = time.perf_counter()

    def describe(hwnd, refresh=False):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in known and refresh and time.perf_counter() - last_scan > .01:
            process_tree()
        if pid.value not in known:
            return None
        classname = ctypes.create_unicode_buffer(256)
        title = ctypes.create_unicode_buffer(512)
        user.GetClassNameW(hwnd, classname, len(classname))
        user.GetWindowTextW(hwnd, title, len(title))
        rect = wintypes.RECT()
        user.GetWindowRect(hwnd, ctypes.byref(rect))
        key, alpha, flags = wintypes.DWORD(), wintypes.BYTE(255), wintypes.DWORD()
        user.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags))
        opacity = alpha.value if flags.value & 2 else 255
        return {'hwnd': int(hwnd), 'pid': pid.value, 'class': classname.value, 'title': title.value,
                'visible': bool(user.IsWindowVisible(hwnd)), 'opacity': opacity,
                'rect': [rect.left, rect.top, rect.right, rect.bottom]}

    def event_callback(_hook, event, hwnd, object_id, child, _thread, native_time):
        if not hwnd or object_id or child or event not in (0x8000, 0x8001, 0x8002, 0x8003, 0x800B):
            return
        try:
            info = describe(hwnd, refresh=True)
            if info:
                events.append({**info, 'event': hex(event), 'time_ms': elapsed(), 'native_time': native_time})
                windows.setdefault(int(hwnd), {'first_seen_ms': elapsed(), 'samples': 0}).update(info)
                if info['visible']:
                    pending.add(int(hwnd))
            elif event == 0x8002:
                classname = ctypes.create_unicode_buffer(256)
                user.GetClassNameW(hwnd, classname, len(classname))
                if classname.value == 'ConsoleWindowClass':
                    unattributed_consoles.append({'time_ms': elapsed(), 'hwnd': int(hwnd)})
        except (OSError, ValueError):
            pass

    callback = event_callback_type(event_callback)
    hook = user.SetWinEventHook(0x8000, 0x800B, None, callback, 0, 0, 0)
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    launch = ShellExecuteInfo(); launch.size = ctypes.sizeof(launch)
    launch.mask = 0x40 | 0x400
    launch.verb = 'open'; launch.file = str(command[0]); launch.parameters = subprocess.list2cmdline(list(command[1:]))
    launch.directory = str(ROOT); launch.show = 1
    # 被测 GUI 必须可见；工具进程的隐藏策略由应用自身负责
    try:
        previous_log = os.environ.get('EXIFFRAME_STARTUP_LOG')
        previous_data = os.environ.get('EXIFFRAME_DATA_DIR')
        log_path = output / 'startup.log'
        os.environ['EXIFFRAME_STARTUP_LOG'] = str(log_path)
        if previous_data is None:
            os.environ['EXIFFRAME_DATA_DIR'] = str(output / 'runtime')
        try:
            if not shell.ShellExecuteExW(ctypes.byref(launch)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if previous_log is None:
                os.environ.pop('EXIFFRAME_STARTUP_LOG', None)
            else:
                os.environ['EXIFFRAME_STARTUP_LOG'] = previous_log
            if previous_data is None:
                os.environ.pop('EXIFFRAME_DATA_DIR', None)
        root_pid = int(kernel.GetProcessId(launch.process))
        process_tree()
        message = wintypes.MSG()
        deadline = started + seconds
        next_capture = 0
        while time.perf_counter() < deadline:
            while user.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user.TranslateMessage(ctypes.byref(message)); user.DispatchMessageW(ctypes.byref(message))
            now = time.perf_counter()
            if now - last_scan > .02:
                process_tree()
            if now >= next_capture:
                @enum_callback_type
                def enumerate_window(hwnd, _):
                    info = describe(hwnd)
                    if info and info['visible']:
                        windows.setdefault(int(hwnd), {'first_seen_ms': elapsed(), 'samples': 0}).update(info)
                        pending.add(int(hwnd))
                    return True
                user.EnumWindows(enumerate_window, 0)
                for hwnd in list(pending):
                    pending.discard(hwnd)
                    state = windows.get(hwnd)
                    if not state or not user.IsWindowVisible(hwnd) or state.get('opacity') == 0 or state['samples'] >= 120:
                        continue
                    client = wintypes.RECT(); origin = wintypes.POINT()
                    if not user.GetClientRect(hwnd, ctypes.byref(client)) or not user.ClientToScreen(hwnd, ctypes.byref(origin)):
                        continue
                    w, h = client.right, client.bottom
                    if min(w, h) < 30:
                        continue
                    box = (origin.x, origin.y, origin.x+w, origin.y+h)
                    try:
                        frame = capture(hwnd, w, h)
                        probe = frame.resize((80, 48)).convert('RGB')
                        histogram = probe.convert('L').histogram()
                        near_white = sum(histogram[248:]) / (80*48)
                        foreground = user.GetForegroundWindow()
                        foreground_pid = wintypes.DWORD(); user.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
                        record = {'time_ms': elapsed(), 'hwnd': hwnd, 'near_white_fraction': round(near_white, 4),
                                  'mean_rgb': [round(x, 2) for x in ImageStat.Stat(probe).mean],
                                  'foreground_in_test': foreground_pid.value in known, 'client_rect': box,
                                  'opacity': state.get('opacity', 255)}
                        if foreground_pid.value in known and (state['samples'] < 8 or state['samples'] % 25 == 0):
                            desktop = ImageGrab.grab(bbox=box, all_screens=True).resize((80, 48)).convert('L')
                            record['desktop_white_fraction'] = round(sum(desktop.histogram()[248:]) / (80*48), 4)
                        if state['samples'] < 8 or (expect_dark and near_white > .20) or state['samples'] % 25 == 0:
                            filename = f"{int(record['time_ms']):06d}-{hwnd:x}-{state['samples']:03d}.png"
                            frame.save(output/filename, compress_level=1); record['image'] = filename
                        samples.append(record); state['samples'] += 1
                    except (OSError, ValueError):
                        pass
                next_capture = now + .04
            status = wintypes.DWORD(); kernel.GetExitCodeProcess(launch.process, ctypes.byref(status))
            if status.value != 259:
                break
            time.sleep(.004)
        status = wintypes.DWORD(); kernel.GetExitCodeProcess(launch.process, ctypes.byref(status))
        before_close = status.value
        if close:
            for hwnd, info in windows.items():
                if info.get('visible') and user.IsWindowVisible(hwnd):
                    user.PostMessageW(hwnd, 0x0010, 0, 0)
            kernel.WaitForSingleObject(launch.process, 5000)
            kernel.GetExitCodeProcess(launch.process, ctypes.byref(status))
        consoles = [item for item in events if item['visible'] and item.get('opacity', 255) > 0
                    and item['class'] == 'ConsoleWindowClass']
        white = [item for item in samples if expect_dark and item['near_white_fraction'] > .20
                 and item['foreground_in_test'] and item.get('opacity', 255) == 255]
        dwm = [item for item in samples if expect_dark and item.get('desktop_white_fraction', 0) > .20
               and item['near_white_fraction'] < .05]
        report = {'command': list(map(str,command)), 'root_pid': root_pid, 'duration_ms': elapsed(),
                  'processes': list(processes.values()), 'windows': list(windows.values()), 'events': events,
                  'samples': samples, 'visible_console_events': consoles, 'white_fill_candidates': white,
                  'desktop_transition_candidates': dwm,
                  'unattributed_console_events': unattributed_consoles, 'exit_before_close': before_close,
                  'startup_log': log_path.read_text(encoding='utf-8') if log_path.is_file() else None,
                  'exit_after_close': status.value, 'capture_interval_ms': 40, 'capture_mode': 'PrintWindow client surface',
                  'limitation': 'Fresh process launch; OS caches are not flushed. Window surfaces exclude desktop occlusion and DWM fade. Actual capture intervals depend on capture time; shorter flashes cannot be excluded.'}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'root_pid':root_pid,'processes':len(processes),'windows':len(windows),'samples':len(samples),
                          'console_events':len(consoles),'white_candidates':len(white),'exit':status.value,
                          'report':str(output/'report.json')},ensure_ascii=False))
        return report
    finally:
        user.UnhookWinEvent(hook)
        if launch.process:
            kernel.CloseHandle(launch.process)


def main():
    parser=argparse.ArgumentParser(description='Windows startup window monitor')
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--seconds',type=float,default=20)
    parser.add_argument('--output',type=Path,default=ROOT/'build/startup-review/monitor')
    parser.add_argument('--expect-dark',action='store_true')
    parser.add_argument('--keep-open',action='store_true')
    parser.add_argument('--allow-no-window',action='store_true',help='Allow a background-tool probe with no GUI')
    args,extra=parser.parse_known_args()
    if sys.platform!='win32':
        parser.error('This monitor requires a Windows desktop')
    executable=args.exe or Path(sys.executable).with_name('pythonw.exe')
    command=[str(executable.resolve()),*([str(isolated_source(args.output.resolve()))] if args.exe is None else []),*extra]
    report=monitor(command,args.output.resolve(),args.seconds,args.expect_dark,not args.keep_open)
    return int(bool(report['visible_console_events'] or report['white_fill_candidates']
                    or (not report['samples'] and not args.allow_no_window)
                    or report['exit_after_close'] not in (0, 259)
                    or (not args.keep_open and report['exit_after_close'] != 0)))


if __name__=='__main__':
    raise SystemExit(main())
