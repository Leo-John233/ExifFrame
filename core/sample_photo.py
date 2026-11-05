"""定位随项目和便携版提供的无水印示例照片"""

import sys
from pathlib import Path
from core.runtime_paths import is_onefile, resource_path


def example_photo_path() -> Path:
    """优先使用程序旁的素材，兼容打包资源且不依赖工作目录"""
    if is_onefile():
        return resource_path('static/preview.jpg')
    if getattr(sys, 'frozen', False):
        roots = [Path(sys.executable).resolve().parent]
        bundled = getattr(sys, '_MEIPASS', None)
        if bundled:
            roots.append(Path(bundled))
    else:
        roots = [Path(__file__).resolve().parents[1]]
    for root in roots:
        candidate = root / 'static' / 'preview.jpg'
        if candidate.is_file():
            return candidate
    # 素材缺失时保留明确路径，禁止退回已经带水印的展示缩略图
    return roots[0] / 'static' / 'preview.jpg'
