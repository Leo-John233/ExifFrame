"""在程序的配置目录记住各类文件选择器的起始位置"""

from pathlib import Path

from PySide6.QtCore import QSettings

from core.runtime_paths import config_path


def workspace_preferences():
    settings = QSettings(str(config_path('workspace-view.ini').absolute()), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    return settings


def last_directory(key, fallback=''):
    value = workspace_preferences().value('folders/' + key, '', type=str)
    return value if value and Path(value).is_dir() else str(fallback)


def remember_directory(key, directory):
    if directory:
        settings = workspace_preferences()
        settings.setValue('folders/' + key, str(Path(directory).absolute()))
        settings.sync()
