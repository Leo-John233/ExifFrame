"""启动 ExifFrame 照片水印工作台"""

import os
import sys
import json
import traceback
from pathlib import Path


def prepare_windows_runtime():
    """优先加载系统 ICU，避免 Conda 同名动态库与 Qt 冲突"""
    if sys.platform == 'win32':
        import ctypes
        try:
            return ctypes.WinDLL(str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icuuc.dll'))
        except OSError:
            pass
    return None


def _startup_text(chinese, english):
    """Qt 尚未加载时也按已保存语言显示启动错误"""
    from core.runtime_paths import application_root, config_path, is_onefile
    try:
        path = config_path('ui.json')
        if not is_onefile():
            path = application_root() / path
        preference = json.loads(path.read_text(encoding='utf-8'))
        return english if preference.get('language') == 'en_US' else chinese
    except (OSError, ValueError, AttributeError):
        return chinese


def _warn_missing_exiftool(directory: Path, parent, warning, *, smoke_test: bool = False) -> None:
    """源码运行时提示缺失的 ExifTool 文件"""
    if smoke_test or getattr(sys, 'frozen', False):
        return
    missing_zh, missing_en = [], []
    if not directory.is_dir():
        missing_zh.append('exiftool 文件夹')
        missing_en.append('exiftool folder')
    if not any((directory / name).is_file() for name in ('exiftool.exe', 'exiftool(-k).exe')):
        missing_zh.append('exiftool.exe 或 exiftool(-k).exe')
        missing_en.append('exiftool.exe or exiftool(-k).exe')
    if not (directory / 'exiftool_files').is_dir():
        missing_zh.append('exiftool_files 文件夹')
        missing_en.append('exiftool_files folder')
    if not missing_zh:
        return
    title = _startup_text('ExifTool 文件不完整', 'ExifTool files are incomplete')
    message = _startup_text(
        f'请补全 ExifTool 目录：\n{directory}\n\n应包含：\n'
        '  exiftool.exe 或 exiftool(-k).exe\n  exiftool_files/\n\n'
        f'缺少：{"、".join(missing_zh)}\n\n'
        '水印预览和导出仍可使用，部分 EXIF 信息及照片信息编辑可能不可用',
        f'Complete the ExifTool folder:\n{directory}\n\nRequired contents:\n'
        '  exiftool.exe or exiftool(-k).exe\n  exiftool_files/\n\n'
        f'Missing: {", ".join(missing_en)}\n\n'
        'Watermark preview and export remain available, but some EXIF information and photo metadata editing may be unavailable',
    )
    warning(parent, title, message)


def _startup_log(path: Path | None, message: str, *, reset: bool = False) -> None:
    """将冒烟检查进度写入显式指定的日志"""
    if path is None:
        return
    try:
        with path.open('w' if reset else 'a', encoding='utf-8', errors='backslashreplace') as stream:
            stream.write(message.rstrip() + '\n')
    except (OSError, ValueError):
        pass


def _run_application(smoke_test: bool, startup_log: Path | None) -> int:
    """统一资源目录后启动桌面应用"""
    _startup_log(startup_log, 'stage: parse arguments')
    report_path = None
    if '--verify-package' in sys.argv:
        index = sys.argv.index('--verify-package')
        if index + 1 >= len(sys.argv):
            return 2
        report_path = Path(sys.argv[index + 1]).expanduser().resolve()
        # 验证结果与临时配置均限制在报告所在目录
        os.environ['EXIFFRAME_DATA_DIR'] = str(report_path.parent / f'.{report_path.stem}-data')
    _startup_log(startup_log, 'stage: import runtime paths')
    from core.runtime_paths import application_root, config_path, initialize_user_config, is_onefile, resource_path, user_data_root
    if sys.platform != 'win32':
        raise SystemExit(_startup_text('ExifFrame 桌面版仅支持 Windows', 'ExifFrame desktop is available on Windows only'))
    _startup_log(startup_log, 'stage: set working directory')
    root = user_data_root() if is_onefile() else application_root()
    if is_onefile():
        root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    # 保留句柄直到事件循环退出，不改动环境中的动态库
    _startup_log(startup_log, 'stage: prepare Windows runtime')
    runtime_library = prepare_windows_runtime()
    if smoke_test or report_path is not None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _startup_log(startup_log, 'stage: import Qt')
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        if smoke_test or report_path is not None:
            raise
        # 无控制台启动时也能看到依赖安装提示
        import ctypes
        message = _startup_text('缺少桌面依赖，请先使用当前 Python 环境安装 requirements.txt',
                                'Desktop dependencies are missing. Install requirements.txt in the current Python environment.')
        ctypes.windll.user32.MessageBoxW(0, message, 'ExifFrame', 16)
        return 1

    _startup_log(startup_log, 'stage: create QApplication')
    application = QApplication([sys.argv[0]] if report_path is not None else sys.argv)
    application.setApplicationName('ExifFrame')
    application.setOrganizationName('ExifFrame')
    application.setWindowIcon(QIcon(str(resource_path('static/logo.ico'))))
    try:
        if report_path is not None:
            from build_support.package_verify import verify_package
            return verify_package(report_path)
        _startup_log(startup_log, 'stage: initialize user config')
        try:
            initialize_user_config()
        except PermissionError as error:
            message = _startup_text(
                f'无法访问配置目录 {config_path()}，请检查权限或将程序移至可写目录',
                f'Cannot access the configuration folder {config_path()}. Check permissions or move the program to a writable folder',
            )
            raise PermissionError(f'{message}\n{error}') from error
        _startup_log(startup_log, 'stage: import desktop modules')
        from studio.i18n import install_qt_translations, localize_error, tr
        from studio.theme import apply_theme
        from studio.window import MainWindow

        _startup_log(startup_log, 'stage: install translations and theme')
        install_qt_translations()
        apply_theme(application)
        _startup_log(startup_log, 'stage: create main window')
        window = MainWindow()
        _startup_log(startup_log, 'stage: show main window')
        window.show()
        _warn_missing_exiftool(application_root() / 'exiftool', window, QMessageBox.warning, smoke_test=smoke_test)
        if smoke_test:
            QTimer.singleShot(1200, window.close)
        _startup_log(startup_log, 'stage: enter event loop')
        result = application.exec()
        _startup_log(startup_log, f'stage: event loop returned {result}')
        # 先释放窗口及后台任务，再销毁应用对象
        _startup_log(startup_log, 'stage: release main window')
        window.pool.waitForDone()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return result
    except Exception as error:
        if smoke_test:
            if startup_log is not None:
                _startup_log(startup_log, 'stage: startup failed\n' + traceback.format_exc())
            return 1
        if report_path is not None:
            raise
        # 桌面打包隐藏控制台，错误通过原生提示框展示
        title = _startup_text('窗口启动失败', 'Unable to start ExifFrame')
        message = _startup_text('请检查 config 和 static 资源目录', 'Check the config and static resource folders')
        detail = localize_error(error) if 'localize_error' in locals() else str(error)
        QMessageBox.critical(None, title, f'{message}\n\n{detail}')
        return 1


def main() -> int:
    smoke_test = '--smoke-test' in sys.argv
    log_name = os.environ.get('EXIFFRAME_STARTUP_LOG') if smoke_test else None
    log_path = Path(os.path.abspath(log_name)) if log_name else None
    _startup_log(log_path, 'stage: process start', reset=True)
    try:
        result = _run_application(smoke_test, log_path)
    except BaseException as error:
        if log_path is not None:
            _startup_log(log_path, 'stage: startup failed\n' + traceback.format_exc())
        if smoke_test and isinstance(error, Exception):
            return 1
        raise
    _startup_log(log_path, f'stage: process exit code {result}')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
