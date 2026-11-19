"""验证 PNG 卡片在改名、移走原始素材后仍能无损恢复"""

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.desktop_service import WatermarkSettings, read_template, render_photo
from core.exiftool_process import close_exiftool
from core.style_pack import export_style_png, import_style_pack, read_preset_style


def verify():
    name = 'Card round trip'
    templates = Path('config/templates')
    templates.mkdir(parents=True)
    photo = ROOT/'static/preview.jpg'
    assets = {}
    for kind, size, color in (('border', (120, 90), '#B52B62A0'), ('logo', (64, 40), '#387ED7C0')):
        image = Image.new('RGBA', size)
        ImageDraw.Draw(image).rounded_rectangle((2, 2, size[0]-3, size[1]-3), radius=4, outline=color, width=3)
        path = Path(f'{kind}.png')
        image.save(path)
        assets[kind] = hashlib.sha256(path.read_bytes()).digest()
    chars = {'0': {'color': '#E60012'}, '1': {'color': '#147241'}}
    node = {'processor_name': 'watermark', 'center_logo': 'logo.png',
            'left_top': {'processor_name': 'rich_text', 'text': 'AB 50mm', 'char_styles': chars},
            'custom_frame': {'geometry': {'canvas_mode': 'aspect_ratio', 'ratio': '4:5'},
                             'background': {'type': 'solid', 'color': '#6E7176'},
                             'decorations': [{'type': 'png_frame_overlay', 'path': 'border.png'}]}}
    source = json.dumps([node], ensure_ascii=False)
    template = templates / f'{name}.json'
    template.write_text(source, encoding='utf-8')
    settings = WatermarkSettings(template_name=name, template_source=source)
    full = render_photo(photo, settings, preview=False)
    preview = render_photo(photo, settings)
    card = Path('preview.png')
    export_style_png(card, name, source, settings, preview)
    card = card.rename('renamed.png')
    with Image.open(card) as image:
        assert 'ExifFramePreset' in image.info and max(image.size) == 1200
    for path in (template, Path('logo.png'), Path('border.png')):
        path.unlink()
    assert import_style_pack(card) == name
    restored = json.loads(read_template(name))[0]
    assert restored['left_top']['char_styles'] == chars
    for key, path in (('border', restored['custom_frame']['decorations'][0]['path']), ('logo', restored['center_logo'])):
        assert hashlib.sha256(Path(path).read_bytes()).digest() == assets[key]
    new = render_photo(photo, replace(WatermarkSettings(template_name=name), **read_preset_style(name)), preview=False)
    assert new.size == full.size and not ImageChops.difference(full.convert('RGB'), new.convert('RGB')).getbbox()
    assert import_style_pack(ROOT/'docs/examples/吸色双线框.efstyle') == '吸色双线框'


if __name__ == '__main__':
    old = Path.cwd()
    with TemporaryDirectory() as folder:
        os.chdir(folder)
        try:
            verify()
        finally:
            close_exiftool()
            os.chdir(old)
    print('PNG card, renamed file, original asset bytes, character colors, output pixels and legacy pack verified')
