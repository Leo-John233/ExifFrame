"""验证出厂 Logo 的字腔、品牌色和 Alpha 合成，并生成各背景的对照图"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from processor.logo_layer import background_luma, layer_logo, logo_variant_path


def check_assets(paths):
    assert len(paths) == 17 and all(p.suffix.lower() == '.png' for p in paths)
    for path in paths:
        with Image.open(path) as image:
            assert image.mode == 'RGBA', path
            alpha = image.getchannel('A')
            if path.stem == 'default':
                assert alpha.getbbox() is None
            elif path.stem == 'nikon':
                # 正版黄色方章及白色光带都应完整保留
                assert alpha.getextrema() == (255, 255)
                assert image.getpixel((0, 0))[:3] == (255, 225, 0)
            else:
                assert alpha.getextrema() == (0, 255), path
            if path.stem in {'canon', 'DJI', 'fujifilm', 'hasselblad', 'olympus_blue_gold',
                             'panasonic', 'panasonic2', 'pentax', 'ricoh', 'sony'}:
                colors = np.asarray(image)
                assert not np.any((colors[:, :, :3].min(axis=2) > 240) & (colors[:, :, 3] > 0)), path
            if path.stem == 'canon':
                pixels = np.asarray(image)
                visible = pixels[:, :, 3] > 0
                assert np.all(pixels[:, :, :3][visible] == (255, 0, 0))
                # 坐标独立取自清洗前的原始 2048×942 素材
                for x, y in [(733, 552), (1408, 499)]:
                    assert not pixels[y-6:y+7, x-6:x+7, 3].any()
                assert np.count_nonzero(visible & (pixels[:, :, 3] < 255)) > 1000
            if path.stem in {'leica_logo', 'olympus_white_gold', 'sony_dark', 'xmage'}:
                sample = image.copy()
                sample.thumbnail((500, 500))
                rgba = np.asarray(sample)
                white = (rgba[:, :, :3].min(axis=2) > 245) & (rgba[:, :, 3] > 245)
                assert np.count_nonzero(white) > 100, path
                if path.stem == 'leica_logo':
                    assert tuple(rgba[0, 0])[-1] == 0


def render_grid(paths, output_dir):
    w, h, label, head = 154, 58, 150, 40
    bounds = (w-16, h-12)
    backgrounds = [Image.new('RGB', (w, h), color) for color in ('#FFFFFF', '#6E7176', '#1A1A1A')]
    with Image.open(ROOT/'static/preview.jpg') as photo:
        dark = ImageOps.fit(photo.convert('RGB'), (w, h)).filter(ImageFilter.GaussianBlur(6))
    backgrounds.append(Image.blend(dark, Image.new('RGB', dark.size, '#141516'), .72))
    grid = Image.new('RGB', (label+8*w, head+len(paths)*h), '#28292b')
    draw = ImageDraw.Draw(grid)
    font = ImageFont.load_default(size=14)
    for i, name in enumerate(('White', 'Mid gray', 'Dark', 'Blur')):
        for toggle in (0, 1):
            draw.text((label+(i*2+toggle)*w+5, 12), f'{name} / {"on" if toggle else "off"}', font=font)
    for row, path in enumerate(paths):
        y = head + row*h
        draw.text((8, y+20), path.stem, font=font)
        for i, bg in enumerate(backgrounds):
            for toggle in (False, True):
                luma = background_luma(bg, (0, 0, w, h))
                selected = logo_variant_path(path, luma, adaptive=toggle)
                stamp = layer_logo(path, bounds, background=luma, adaptive=toggle)
                original = layer_logo(selected, bounds, adaptive=False)
                a = np.asarray(stamp.getchannel('A'))
                assert np.array_equal(a, np.asarray(original.getchannel('A'))), path
                if path.stem in {'canon', 'leica_logo', 'nikon', 'pentax', 'ricoh', 'panasonic2'}:
                    assert stamp.tobytes() == original.tobytes(), path
                if toggle and path.stem.startswith(('sony', 'olympus')):
                    dark = luma < 125
                    pair = ('sony', 'sony_dark') if path.stem.startswith('sony') else ('olympus_blue_gold', 'olympus_white_gold')
                    assert selected.stem == pair[int(dark)]
                if toggle and luma < 125 and path.stem == 'fujifilm':
                    base = np.asarray(original)
                    deep_red = (base[:, :, 0] > 200) & (base[:, :, 1] < 40) & (a == 255)
                    black_letters = (base[:, :, :3].max(axis=2) < 20) & (a == 255)
                    assert np.any(deep_red) and np.any(black_letters)
                    adapted = np.asarray(stamp)
                    assert np.max(np.abs(adapted[deep_red,:3].astype(int) - base[deep_red,:3])) < 12
                    assert adapted[black_letters, :3].mean() > 220
                x0, y0 = (w-stamp.width)//2, (h-stamp.height)//2
                tile = bg.convert('RGBA')
                tile.alpha_composite(stamp, (x0, y0))
                region = (x0, y0, x0+stamp.width, y0+stamp.height)
                bg_pixels = np.asarray(bg.crop(region)).astype(np.int32)
                fg = np.asarray(stamp.convert('RGB')).astype(np.int32)
                alpha = a.astype(np.int32)[:, :, None]
                expected = (fg*alpha + bg_pixels*(255-alpha) + 127)//255
                actual = np.asarray(tile.crop(region).convert('RGB'))
                assert np.array_equal(actual, expected), path
                if path.stem == 'canon':
                    with Image.open(path) as asset:
                        native = asset.getchannel('A').getbbox()
                    for hx, hy in ((733, 552), (1408, 499)):
                        cx = int((hx-native[0])*stamp.width/(native[2]-native[0]))
                        cy = int((hy-native[1])*stamp.height/(native[3]-native[1]))
                        assert a[cy, cx] == 0 and np.array_equal(actual[cy, cx], bg_pixels[cy, cx])
                grid.paste(tile, (label+(i*2+toggle)*w, y))
    output_dir.mkdir(parents=True, exist_ok=True)
    grid.save(output_dir/'logo-backgrounds.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/logo-review')
    args = parser.parse_args()
    files = sorted((ROOT/'config/logos').glob('*'), key=lambda path: path.name.casefold())
    check_assets(files)
    render_grid(files, args.output)
    print('17 assets, 4 backgrounds, both adaptive settings: 136 composites checked')
