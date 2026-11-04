"""启动 ExifFrame 照片水印工作台"""

import os
import sys
import json
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
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    try:
        preference = json.loads((root / 'config/ui.json').read_text(encoding='utf-8'))
        return english if preference.get('language') == 'en_US' else chinese
    except (OSError, ValueError, AttributeError):
        return chinese


def main() -> int:
    """统一资源目录后启动桌面应用"""
    if sys.platform != 'win32':
        raise SystemExit(_startup_text('ExifFrame 桌面版仅支持 Windows', 'ExifFrame desktop is available on Windows only'))
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    os.chdir(root)
    # 保留句柄直到事件循环退出，不改动环境中的动态库
    runtime_library = prepare_windows_runtime()
    smoke_test = '--smoke-test' in sys.argv
    if smoke_test:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        from PySide6.QtCore import QCoreApplication, QEvent, QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError:
        # 无控制台启动时也能看到依赖安装提示
        import ctypes
        message = _startup_text('缺少桌面依赖，请先使用当前 Python 环境安装 requirements.txt',
                                'Desktop dependencies are missing. Install requirements.txt in the current Python environment.')
        ctypes.windll.user32.MessageBoxW(0, message, 'ExifFrame', 16)
        return 1

    application = QApplication(sys.argv)
    application.setApplicationName('ExifFrame')
    application.setOrganizationName('ExifFrame')
    application.setWindowIcon(QIcon(str(root / 'static/logo.ico')))
    try:
        from studio.i18n import install_qt_translations, localize_error, tr
        from studio.theme import apply_theme
        from studio.window import MainWindow

        install_qt_translations()
        apply_theme(application)
        window = MainWindow()
        window.show()
        if smoke_test:
            QTimer.singleShot(1200, window.close)
        result = application.exec()
        # 先释放窗口及后台任务，再销毁应用对象
        window.pool.waitForDone()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return result
    except Exception as error:
        # 桌面打包隐藏控制台，错误通过原生提示框展示
        if not smoke_test:
            title = _startup_text('窗口启动失败', 'Unable to start ExifFrame')
            message = _startup_text('请检查 config 和 static 资源目录', 'Check the config and static resource folders')
            detail = localize_error(error) if 'localize_error' in locals() else str(error)
            QMessageBox.critical(None, title, f'{message}\n\n{detail}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
