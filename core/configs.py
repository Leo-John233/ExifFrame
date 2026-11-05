import configparser
from pathlib import Path

import tomli

from core import CONFIG_PATH, PROJECT_INFO
from core.runtime_paths import config_path

fonts_dir = config_path('fonts')
logos_dir = config_path('logos')
templates_dir = config_path('templates')

def load_config() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH, encoding='utf-8')
    return config


def load_project_info():
    with open(PROJECT_INFO, "rb") as f:  # 注意：tomllib 需要以二进制模式（"rb"）打开文件
        data = tomli.load(f)
    return data
