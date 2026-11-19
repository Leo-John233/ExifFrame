"""统一加载、净化和适配标识，保持前景颜色与真实透明度"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from core.image_cache import cached_preview_image, cache_preview_image


_LOGO_VERSION = 6
_VARIANTS = {'sony': ('sony.png', 'sony_dark.png'),
             'sony_dark': ('sony.png', 'sony_dark.png'),
             'olympus_blue_gold': ('olympus_blue_gold.png', 'olympus_white_gold.png'),
             'olympus_white_gold': ('olympus_blue_gold.png', 'olympus_white_gold.png')}


def resolve_logo_path(path):
    """只迁移内置 DJI 旧名，外部同名文件保持用户选择"""
    from core.configs import logos_dir
    result = Path(path).expanduser().resolve()
    if result.parent == logos_dir.resolve() and result.name.casefold() == 'dji.jpg' and not result.exists():
        replacement = logos_dir.resolve() / 'DJI.png'
        if replacement.is_file():
            return replacement
    return result


def _variant_path(path, background, adaptive, variant):
    if variant not in {'auto', 'original', 'light', 'dark'}:
        raise ValueError('标识深浅版本无效')
    pair = _VARIANTS.get(path.stem.casefold())
    if not pair or variant == 'original' or (variant == 'auto' and (not adaptive or background is None)):
        return path
    # light/dark 描述标识前景；带 dark 后缀的旧素材用于深色背景
    light = variant == 'light' or (variant == 'auto' and background < 125)
    candidate = path.with_name(pair[1 if light else 0])
    return candidate if candidate.is_file() else path


def logo_variant_path(path, background=None, *, adaptive=True, variant='auto'):
    return _variant_path(resolve_logo_path(path), background, adaptive, variant)


def _remove_matte(image, policy='auto'):
    """对白/黑实底反解边缘覆盖率；已有透明通道和徽章内白字保持不变"""
    if policy not in {'auto', 'none', 'white', 'black'}:
        raise ValueError('标识底色清理模式无效')
    image = image.convert('RGBA')
    alpha = image.getchannel('A')
    if policy == 'none':
        return image
    rgb = image.convert('RGB')
    width, height = rgb.size
    points = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    corners = [rgb.getpixel(point) for point in points]
    if alpha.getextrema()[0] < 255 and not all(alpha.getpixel(point) >= 250 for point in points):
        if policy in {'white', 'black'}:
            # 明确指定消除预混色时只反解 RGB，保留用户已有的每一个 alpha 值
            values = np.asarray(image).copy()
            coverage = values[:, :, 3:4].astype(np.float32) / 255
            matte = 255 if policy == 'white' else 0
            straight = np.divide(values[:, :, :3] - matte * (1 - coverage), coverage,
                                 out=np.zeros_like(values[:, :, :3], dtype=np.float32), where=coverage > 0)
            values[:, :, :3] = np.clip(straight, 0, 255).round().astype('uint8')
            return Image.fromarray(values, 'RGBA')
        return image
    white = min(min(pixel) for pixel in corners) >= 242
    black = max(max(pixel) for pixel in corners) <= 16
    if policy == 'auto' and not (white or black):
        return image
    white = policy == 'white' or (policy == 'auto' and white)
    working = rgb if white else ImageOps.invert(rgb)
    pixels = np.asarray(working, dtype=np.float32)
    distance = 255 - pixels.min(axis=2)
    shape = distance > 24
    bounds = Image.fromarray(shape.astype('uint8') * 255).getbbox()
    if not bounds:
        return image
    left, top, right, bottom = bounds
    fill = float(shape[top:bottom, left:right].mean())
    spread = pixels.max(axis=2) - pixels.min(axis=2)
    colorful = float((spread[shape] > 35).mean()) > .08
    # 紧凑实心彩色徽章保留内部白字；字标的封闭字腔则与外部一起透底
    badge = policy == 'auto' and colorful and fill > .60 and (right-left) / max(1, bottom-top) < 1.8
    editable = np.ones(shape.shape, dtype=bool)
    if badge:
        exterior = ImageOps.expand(Image.fromarray(shape.astype('uint8') * 255), border=1, fill=0)
        ImageDraw.floodfill(exterior, (0, 0), 128)
        outside = exterior.crop((1, 1, width + 1, height + 1)).point(lambda value: 255 if value == 128 else 0)
        editable = np.asarray(outside.filter(ImageFilter.MaxFilter(7))) > 0
    # 邻域内的实体色作为前景参考，避免把金色、灰色等非零通道误当作半透明
    reference = np.asarray(working.filter(ImageFilter.MinFilter(5)), dtype=np.float32)
    delta = 255 - pixels
    denominator = 255 - reference
    ratios = np.divide(delta, denominator, out=np.zeros_like(delta), where=denominator > 1)
    coverage = np.clip(ratios.max(axis=2), 0, 1)
    coverage[distance <= 5] = 0
    near_ink = np.asarray(Image.fromarray(shape.astype('uint8') * 255).filter(ImageFilter.MaxFilter(5))) > 0
    coverage[(distance <= 24) & ~near_ink] = 0
    coverage[~editable] = 1
    restored = np.divide(pixels - 255 * (1 - coverage[..., None]), coverage[..., None],
                         out=np.zeros_like(pixels), where=coverage[..., None] > 0)
    restored = np.clip(restored, 0, 255)
    if not white:
        restored = 255 - restored
    result = np.dstack((restored, coverage * np.asarray(alpha, dtype=np.float32))).round().astype('uint8')
    result[result[:, :, 3] == 0, :3] = 0
    return Image.fromarray(result, 'RGBA')


def load_logo(path, *, matte='auto', trim=True, max_edge=None):
    """按文件版本缓存清理后的原始比例图，不随拖拽重复解码或净化"""
    path = resolve_logo_path(path)
    info = path.stat()
    key = ('clean_logo', _LOGO_VERSION, str(path), info.st_mtime_ns, info.st_size, matte, trim, max_edge)
    cached = cached_preview_image(key)
    if cached is not None:
        return cached
    with Image.open(path) as opened:
        if max_edge:
            opened.draft('RGB', (max_edge, max_edge))
        # Pillow 对 RGBA 的非最近邻 resize 使用内部 RGBa 预乘路径
        image = ImageOps.exif_transpose(opened).convert('RGBA')
        if max_edge:
            image.thumbnail((max_edge, max_edge), Image.Resampling.HAMMING)
    image = _remove_matte(image, matte)
    if trim:
        bounds = image.getchannel('A').getbbox()
        if bounds:
            image = image.crop(bounds)
    if (path.stat().st_mtime_ns, path.stat().st_size) != (info.st_mtime_ns, info.st_size):
        raise OSError('标识图片在读取期间发生变化，请重试')
    image.info['_logo_path'] = path.as_posix()
    cache_preview_image(key, image)
    return image


def adaptive_logo(image, background):
    """彩色标保留品牌原色，单色标仅按干净 alpha 着对比色"""
    sample = image.copy()
    sample.thumbnail((64, 64), Image.Resampling.BOX)
    values = np.asarray(sample.convert('RGBA'))
    visible = values[:, :, 3] >= 72
    if not visible.any():
        return image
    rgb = values[:, :, :3][visible].astype(np.float32)
    spread = rgb.max(axis=1) - rgb.min(axis=1)
    saturation = spread / np.maximum(1, rgb.max(axis=1))
    color_fraction = float(((saturation > .22) & (spread > 25)).mean())
    if color_fraction > .01:
        # 富士等宽字标只有少量品牌强调色；仅增强中性正文，不触碰彩色徽章
        if color_fraction >= .12 or image.width / max(1, image.height) < 2.5:
            return image
        full = np.asarray(image.convert('RGBA')).copy()
        colors = full[:, :, :3].astype(np.float32)
        chroma = colors.max(axis=2) - colors.min(axis=2)
        saturation = chroma / np.maximum(1, colors.max(axis=2))
        neutral = (chroma <= 20) & (saturation <= .12) & (full[:, :, 3] > 0)
        luma = colors @ np.array([.2126, .7152, .0722])
        change = neutral & ((luma < max(76, background + 55)) if background < 125 else (luma > background - 55))
        full[:, :, :3][change] = 255 if background < 125 else 32
        result = Image.fromarray(full, 'RGBA')
        result.info.update(image.info)
        return result
    lightness = float((rgb @ np.array([.2126, .7152, .0722])).mean())
    if background < 125:
        if lightness > max(76, background + 55):
            return image
        color = (255, 255, 255, 0)
    else:
        if lightness < background - 55:
            return image
        color = (32, 32, 32, 0)
    result = Image.new('RGBA', image.size, color)
    result.putalpha(image.getchannel('A'))
    result.info.update(image.info)
    return result


def layer_logo(path, bounds, *, background=None, adaptive=True, matte='auto', variant='auto', trim=True):
    """优先选品牌深浅素材，再按前景轮廓等比缩放到目标范围"""
    path = _variant_path(resolve_logo_path(path), background, adaptive, variant)
    info = path.stat()
    tone = round(background) if adaptive and background is not None else None
    bounds = tuple(max(1, int(value)) for value in bounds)
    key = ('frame_logo', _LOGO_VERSION, str(path), info.st_mtime_ns, info.st_size, bounds, matte, trim, tone)
    cached = cached_preview_image(key)
    if cached is not None:
        return cached
    # 小尺寸共享同一清理缓存，大尺寸按桶回到原始素材，避免固定低清图再次放大
    edge = max(1600, 1 << (max(bounds) - 1).bit_length())
    image = load_logo(path, matte=matte, trim=trim, max_edge=edge)
    if adaptive and background is not None:
        image = adaptive_logo(image, background)
    result = fit_logo(image, bounds)
    cache_preview_image(key, result)
    return result


def fit_logo(image, bounds):
    """正权重预乘采样不在透明字腔内生成 Lanczos 振铃"""
    scale = min(bounds[0] / image.width, bounds[1] / image.height)
    size = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    if size == image.size:
        return image.copy()
    sampling = Image.Resampling.HAMMING if scale < 1 else Image.Resampling.BILINEAR
    result = image.convert('RGBa').resize(size, sampling).convert('RGBA')
    result.info.update(image.info)
    return result


def logo_options(ctx):
    """旧模板缺省自动适配，显式关闭和原色策略继续生效"""
    return {'adaptive': bool(ctx.get('adaptive_logo_invert', True)),
            'matte': ctx.get('logo_matte', 'auto'), 'variant': ctx.get('logo_variant', 'auto')}


def background_luma(canvas, box):
    left, top, right, bottom = box
    clipped = max(0, left), max(0, top), min(canvas.width, right), min(canvas.height, bottom)
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        return 255
    return canvas.resize((1, 1), Image.Resampling.BOX, box=clipped).convert('L').getpixel((0, 0))
