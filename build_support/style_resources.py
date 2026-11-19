"""收集项目模板实际引用的便携素材和样式设置"""

import json
import re
from pathlib import Path
from core.logo_variants import VARIANT_MAP_NAME, logo_variant_pair

_IMAGE_FIELD = re.compile(r'"(?:left_logo|right_logo|center_logo|logo_choice|path)"\s*:\s*("(?:\\.|[^"\\])*")')


def bundled_style_files(root: Path):
    config = root / 'config'
    assets = config / 'style_assets'
    styles = config / 'style_presets'
    if not assets.is_dir() and not styles.is_dir():
        return []
    config_root = config.resolve()
    asset_root = assets.resolve()
    found = set()
    for template in (config / 'templates').glob('*.json'):
        files = [template]
        sidecar = styles / template.name
        if sidecar.is_file() and sidecar.resolve().is_relative_to(config_root):
            found.add(sidecar)
            files.append(sidecar)
        for file in files:
            source = file.read_text(encoding='utf-8')
            for match in _IMAGE_FIELD.finditer(source):
                if 'style_assets' not in match[1]:
                    continue
                try:
                    ref = Path(json.loads(match[1]))
                except ValueError:
                    continue
                if ref.is_absolute() or ref.parts[:2] != ('config', 'style_assets'):
                    continue
                path = (root / ref).resolve()
                if (path.suffix.lower() in ('.png', '.jpg', '.jpeg')
                        and path.is_relative_to(asset_root) and path.is_relative_to(config_root)
                        and path.is_file()):
                    found.add(path)
                    pair = logo_variant_pair(path)
                    if pair and all(item.resolve().is_relative_to(asset_root) for item in pair):
                        found.update(pair)
                        manifest = path.parent / VARIANT_MAP_NAME
                        if manifest.is_file() and not manifest.is_symlink():
                            found.add(manifest)
    return sorted(found)
