"""按实际标识轮廓等比缩放，并在暗底上保留笔画细节"""

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageStat

from core.image_cache import cached_preview_image, cache_preview_image, contain_logo, resized_logo


def _remove_matte(image):
    alpha = image.getchannel('A')
    if alpha.getextrema()[0] < 255:
        bounds = alpha.getbbox()
        return image.crop(bounds) if bounds else image
    rgb = image.convert('RGB')
    w, h = rgb.size
    corners = [rgb.getpixel(point) for point in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    white = min(min(pixel) for pixel in corners) >= 242
    if not white and max(max(pixel) for pixel in corners) > 16:
        return image
    difference = ImageOps.invert(rgb) if white else rgb
    r, g, b = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)
    shape = distance.point(lambda value: 255 if value > 20 else 0)
    bounds = shape.getbbox()
    if not bounds:
        return image
    # 单色字标的字腔也需透底，灰度边缘直接作为抗锯齿透明度
    color_spread = ImageChops.subtract(distance, ImageChops.darker(ImageChops.darker(r, g), b))
    if ImageStat.Stat(color_spread, shape).mean[0] < 15:
        ink = Image.new('RGBA', image.size, 'black' if white else 'white')
        ink.putalpha(difference.convert('L'))
    else:
        # 彩色徽标保留内部白字，仅移除与画布外沿连通的底色
        exterior = ImageOps.expand(shape, border=1, fill=0)
        ImageDraw.floodfill(exterior, (0, 0), 128)
        matte = exterior.crop((1, 1, w + 1, h + 1)).point(lambda value: 0 if value == 128 else 255)
        ink = image.copy()
        ink.putalpha(matte)
    return ink.crop(bounds)


def layer_logo(path, bounds):
    path = Path(path).resolve()
    info = path.stat()
    key = ('frame_logo', str(path), info.st_size, info.st_mtime_ns, bounds)
    cached = cached_preview_image(key)
    if cached is not None:
        return cached
    edge = max(256, 2 * max(bounds))
    art = _remove_matte(resized_logo(path, (edge, edge), contain=True))
    result = contain_logo(art, bounds)
    cache_preview_image(key, result)
    return result


def adaptive_logo(image, background):
    if background >= 125:
        return image
    sample = image.copy()
    sample.thumbnail((48, 48), Image.Resampling.BOX)
    mask = sample.getchannel('A').point(lambda value: 255 if value >= 72 else 0)
    if not mask.getbbox():
        return image
    lightness = ImageStat.Stat(sample.convert('L'), mask).mean[0]
    if lightness > max(76, background + 55):
        return image
    light = ImageOps.colorize(image.convert('L'), '#FAFAF8', '#333333').convert('RGBA')
    light.putalpha(image.getchannel('A'))
    return light
