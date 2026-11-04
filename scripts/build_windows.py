"""在独立暂存目录构建并组装 Windows 便携版本"""

import argparse
import hashlib
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def _copy_file(source: Path, target: Path, allowed_root: Path, preserve=False):
    """只写入指定发布目录，保留已有用户资源"""
    if not target.resolve().is_relative_to(allowed_root):
        raise ValueError('发布路径超出目标目录')
    if preserve and target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
    shutil.copy2(source, target)


def _copy_tree(source: Path, target: Path, allowed_root: Path, preserve=False):
    """复制文件而不清空便携版本中的配置和照片目录"""
    for item in source.rglob('*'):
        if not item.is_file() or item.name in {'desktop.json', 'ui.json'} or item.suffix == '.tmp':
            continue
        _copy_file(item, target / item.relative_to(source), allowed_root, preserve)


def build(include_resources=True, refresh_templates=False):
    """隔离 PyInstaller 的目录清理，避免触及现有用户资源"""
    root = Path(__file__).resolve().parents[1]
    staging = (root / 'build/package-stage').resolve()
    destination = (root / 'dist/ExifFrame').resolve()
    if not staging.is_relative_to(root) or not destination.is_relative_to(root):
        raise ValueError('构建目录必须位于项目目录内')
    # 只解除生成目录中的只读属性，原始依赖和用户文件不受影响
    if staging.is_dir():
        for item in staging.rglob('*'):
            if item.is_file() and item.resolve().is_relative_to(staging):
                item.chmod(item.stat().st_mode | stat.S_IWRITE)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--distpath', str(staging),
                    str(root / 'build_win_pkg.spec')], cwd=root, check=True)
    generated = staging / 'ExifFrame'
    destination.mkdir(parents=True, exist_ok=True)
    _copy_tree(generated, destination, destination)
    if include_resources:
        for name in ('config', 'static', 'exiftool'):
            if (root / name).is_dir():
                _copy_tree(root / name, destination / name, destination, preserve=True)
        if refresh_templates:
            for template in (root / 'config/templates').glob('*.json'):
                target = destination / 'config/templates' / template.name
                if target.is_file() and target.read_bytes() != template.read_bytes():
                    version = hashlib.sha256(target.read_bytes()).hexdigest()[:12]
                    backup = destination / 'config/template-backups' / f'{template.stem}-{version}.json'
                    _copy_file(target, backup, destination, preserve=True)
                _copy_file(template, target, destination)
            _copy_tree(root / 'static', destination / 'static', destination)
        _copy_file(root / 'pyproject.toml', destination / 'pyproject.toml', destination)
    print(destination / 'ExifFrame.exe')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-resources', action='store_true')
    parser.add_argument('--refresh-templates', action='store_true')
    args = parser.parse_args()
    build(not args.no_resources, args.refresh_templates)
