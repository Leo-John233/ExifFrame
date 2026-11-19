"""自定义画框几何、背景材质与照片表面"""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from core.image_cache import cache_preview_image, cached_preview_image, dominant_palette


def _available_bytes():
    """估计当前可用物理与提交内存"""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                        ('physical_total', ctypes.c_ulonglong), ('physical_available', ctypes.c_ulonglong),
                        ('page_total', ctypes.c_ulonglong), ('page_available', ctypes.c_ulonglong),
                        ('virtual_total', ctypes.c_ulonglong), ('virtual_available', ctypes.c_ulonglong),
                        ('extended_virtual_available', ctypes.c_ulonglong)]

        try:
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return min(status.physical_available, status.page_available)
        except (AttributeError, OSError):
            pass
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, OSError, ValueError):
        return None


def _value(data, key, default, low, high):
    value = float(data.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} 参数超出范围')
    return value


def _color(value):
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        return tuple(value) if len(value) == 4 else (*value, 255)
    return ImageColor.getcolor(str(value), 'RGBA')


def _ratio(value):
    try:
        if isinstance(value, str) and ':' in value:
            left, right = value.split(':', 1)
            result = float(left) / float(right)
        else:
            result = float(value)
    except (ValueError, TypeError, ZeroDivisionError) as error:
        raise ValueError('目标画幅比例无效') from error
    if not math.isfinite(result) or not .001 <= result <= 1000:
        raise ValueError('目标画幅比例无效')
    return result


def default_custom_frame():
    """返回不改变现有画面的空白自定义框"""
    return {'geometry': {'canvas_mode': 'expand', 'top': 0, 'bottom': 0, 'left': 0, 'right': 0,
                         'locked': False, 'ratio': '4:5', 'offset_x': 0, 'offset_y': 0},
            'background': {'type': 'solid', 'color': '#FFFFFF',
                           'texture': {'type': 'none', 'opacity': .12, 'scale': 1, 'seed': 0}},
            'photo_surface': {'radius': 0, 'stroke': {'width': 0, 'color': '#FFFFFF', 'opacity': 1},
                              'shadow': {'blur': 0, 'offset_x': 0, 'offset_y': 0, 'spread': 0,
                                         'opacity': .25, 'color': '#000000'}},
            'decorations': []}


def legacy_custom_frame(node, source_size=None):
    """把旧声明式画框映射为可编辑初值，复杂旧版保留原结果"""
    from processor.frame_layers import _DEFAULTS, _parameters

    result = default_custom_frame()
    style = node.get('frame_style')
    inset = node.get('overlay_mode') == 'inset_overlay'
    if not style and (node.get('palette_bar') or node.get('adaptive_logo_invert')):
        style = 'solid_border'
    if style not in _DEFAULTS and not inset:
        if node.get('processor_name') in ('watermark', 'watermark_with_timestamp'):
            result['legacy_composite'] = True
        return result
    style = style if style in _DEFAULTS else 'solid_border'
    parameters = _parameters(node, style)
    if not inset:
        bottom = parameters['bottom']
        if parameters['fixed_bottom'] is not None and source_size:
            bottom = parameters['fixed_bottom'] / min(source_size)
        result['geometry'].update(top=parameters['margin'], left=parameters['margin'],
                                  right=parameters['margin'], bottom=bottom)
        result['_legacy_geometry'] = {
            'style': style, 'margin': parameters['margin'], 'bottom': parameters['bottom'],
            'fixed_bottom': parameters['fixed_bottom'],
            'values': {key: result['geometry'][key] for key in ('canvas_mode', 'top', 'bottom', 'left', 'right')},
        }
    result['background']['color'] = node.get('frame_color', node.get('color', _DEFAULTS[style][2]))
    if style == 'blurred_glass' and not inset:
        result['background'].update(type='blurred_photo', blur=parameters['blur'],
                                    brightness=parameters['brightness'], saturation=1,
                                    vignette=parameters['vignette'], legacy_glass=True)
        result['photo_surface'].update(radius=parameters['radius'], legacy_glass=True)
        result['photo_surface']['shadow'].update(blur=parameters['shadow'],
                                                  offset_y=parameters['shadow'] / 3,
                                                  opacity=100 / 255)
    if style == 'gallery_mat' and not inset:
        result['decorations'].append({'type': 'border_line', 'legacy_style': 'gallery_mat', 'enabled': True})
    if style == 'film_strip' and not inset:
        result['decorations'].append({'type': 'film_sprockets', 'legacy_style': 'film_strip', 'enabled': True})
    if node.get('palette_bar'):
        result['decorations'].append({'type': 'palette_bar', 'legacy_palette': True, 'enabled': True})
        result['legacy_palette_migrated'] = True
    return result


def custom_geometry(source_size, frame, *, inset=False, legacy_bottom=None):
    """按短边扩展或目标画幅放置完整原图"""
    width, height = map(int, source_size)
    if width <= 0 or height <= 0:
        raise ValueError('照片尺寸无效')
    geometry = frame.get('geometry') or {}
    if not isinstance(geometry, dict):
        raise ValueError('画框几何格式无效')
    unit = min(width, height)
    mode = geometry.get('canvas_mode', 'expand')
    if mode == 'expand':
        left = round(unit * _value(geometry, 'left', 0, 0, 8))
        right = round(unit * _value(geometry, 'right', 0, 0, 8))
        top = round(unit * _value(geometry, 'top', 0, 0, 8))
        bottom = round(unit * _value(geometry, 'bottom', 0, 0, 8))
        canvas_size = (width + left + right, height + top + bottom)
    elif mode == 'aspect_ratio':
        left_min = round(unit * _value(geometry, 'left', 0, 0, 8))
        right_min = round(unit * _value(geometry, 'right', 0, 0, 8))
        top_min = round(unit * _value(geometry, 'top', 0, 0, 8))
        bottom_min = round(unit * _value(geometry, 'bottom', 0, 0, 8))
        required_width, required_height = width + left_min + right_min, height + top_min + bottom_min
        value = geometry.get('ratio', '4:5')
        ratio = _ratio(value)
        parts = value.split(':', 1) if isinstance(value, str) and ':' in value else ()
        if len(parts) == 2 and all(part.strip().isdigit() for part in parts):
            rw, rh = (int(part.strip()) for part in parts)
            common = math.gcd(rw, rh)
            rw, rh = rw // common, rh // common
            multiple = max((required_width + rw - 1) // rw, (required_height + rh - 1) // rh)
            canvas_size = (rw * multiple, rh * multiple)
        elif required_width / required_height > ratio:
            canvas_size = (required_width, max(required_height, math.ceil(required_width / ratio)))
        else:
            canvas_size = (max(required_width, math.ceil(required_height * ratio)), required_height)
        dx = _value(geometry, 'offset_x', 0, -1, 1)
        dy = _value(geometry, 'offset_y', 0, -1, 1)
        left = left_min + round((canvas_size[0] - required_width) * (dx + 1) / 2)
        top = top_min + round((canvas_size[1] - required_height) * (dy + 1) / 2)
    else:
        raise ValueError('画布模式无效')
    legacy_layout = False
    legacy = frame.get('_legacy_geometry')
    if not inset and isinstance(legacy, dict) and isinstance(legacy.get('values'), dict):
        keys = ('canvas_mode', 'top', 'bottom', 'left', 'right')
        if all(key in legacy['values'] and geometry.get(key) == legacy['values'][key] for key in keys):
            from processor.frame_layers import _DEFAULTS, _layout
            style = legacy.get('style')
            if style in _DEFAULTS:
                fixed_bottom = legacy.get('fixed_bottom')
                if fixed_bottom is not None and legacy_bottom is not None:
                    fixed_bottom = int(legacy_bottom)
                if fixed_bottom is not None:
                    fixed_bottom = int(fixed_bottom)
                    if fixed_bottom < 0:
                        raise ValueError('画框底部留白无效')
                parameters = {'margin': _value(legacy, 'margin', 0, 0, 1),
                              'bottom': _value(legacy, 'bottom', 0, 0, 1), 'fixed_bottom': fixed_bottom}
                old = _layout((width, height), style, parameters)
                canvas_size = old['canvas_size']
                left, top = old['photo_box'][:2]
                legacy_layout = True
    right, bottom = left + width, top + height
    photo_box = (left, top, right, bottom)
    if inset:
        padding = min(max(1, round(unit * .035)), max(0, (unit - 1) // 2))
        caption_box = (left + padding, top + padding, right - padding, bottom - padding)
    elif legacy_layout:
        caption_box = (left, bottom, right, canvas_size[1])
    else:
        below = canvas_size[1] - bottom
        above = top
        if below:
            caption_box = (left, bottom, right, canvas_size[1])
        elif above:
            caption_box = (left, 0, right, top)
        elif canvas_size[0] - right:
            caption_box = (right, top, canvas_size[0], bottom)
        else:
            caption_box = (0, top, left, bottom)
    # 旧胶片齿孔占据底部，文字不得落入孔位
    if not inset and any(item.get('type') == 'film_sprockets' and item.get('legacy_style') == 'film_strip'
                         and item.get('enabled', True) for item in frame.get('decorations', [])):
        x1, y1, x2, y2 = caption_box
        caption_box = (x1, y1, x2, max(y1, y2 - max(2, round(unit * .055))))
    return {'photo_box': photo_box, 'caption_box': caption_box, 'canvas_size': canvas_size,
            'unit': unit, 'inset_overlay': bool(inset), 'frame_style': 'custom_frame'}


def legacy_composite_size(source_size, node):
    """无需解码即可估算旧版完整结果的画布尺寸"""
    from processor.core import uses_frame_layers
    from processor.watermark_1521 import uses_default_layout, watermark_scale

    previous = {key: value for key, value in node.items() if key != 'custom_frame'}
    if uses_frame_layers(previous):
        from processor.frame_layers import frame_geometry
        return frame_geometry(source_size, previous)['canvas_size']
    width, height = source_size
    if previous.get('processor_name') == 'watermark_with_timestamp':
        return width, height
    scale = watermark_scale(previous)
    if uses_default_layout(previous):
        ratio = .08 if width >= height else .13
        virtual_width = max(1, int(int(1000 / ratio) / scale))
        footer = max(1, round(1000 * width / virtual_width))
    else:
        base = int(previous.get('bottom_margin', int(height * .12)))
        footer = base if 'bottom_margin' in previous or scale == 1 else max(1, round(base * scale))
    return (width + int(previous.get('left_margin', 0)) + int(previous.get('right_margin', 0)),
            height + int(previous.get('top_margin', 0)) + footer)


def _asset_version(background):
    path = background.get('path') if background.get('type') == 'custom_image' else None
    if not path:
        return None
    source = Path(path).expanduser().resolve()
    try:
        info = source.stat()
    except OSError as error:
        raise ValueError('背景图片不存在或不可读取') from error
    if not source.is_file():
        raise ValueError('背景图片不存在或不可读取')
    return str(source), info.st_mtime_ns, info.st_size


def _gradient(size, background, draft):
    width, height = size
    limit = 900 if draft else 1600
    scale = min(1.0, limit / max(size))
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    start = np.array(_color(background.get('start_color', '#FFFFFF')), dtype=np.float32)
    end = np.array(_color(background.get('end_color', '#E5E5E5')), dtype=np.float32)
    x = (np.linspace(-.5, .5, w, dtype=np.float32) if w > 1 else np.zeros(1, dtype=np.float32))[None, :]
    y = (np.linspace(-.5, .5, h, dtype=np.float32) if h > 1 else np.zeros(1, dtype=np.float32))[:, None]
    kind = background.get('gradient_type', 'linear')
    if kind == 'linear':
        angle = math.radians(_value(background, 'angle', 0, -3600, 3600))
        dx, dy = math.cos(angle), math.sin(angle)
        span_x, span_y = max(0, width - 1), max(0, height - 1)
        extent = max(1e-9, (abs(dx) * span_x + abs(dy) * span_y) / 2)
        mix = np.clip((x * dx * span_x + y * dy * span_y) / (2 * extent) + .5, 0, 1)
    elif kind == 'radial':
        mix = np.clip(np.sqrt(x*x + y*y) / math.sqrt(.5), 0, 1)
    else:
        raise ValueError('渐变类型无效')
    pixels = np.rint(start + (end - start) * mix[:, :, None]).clip(0, 255).astype('uint8')
    image = Image.fromarray(pixels, 'RGBA')
    if (w, h) != size:
        image = image.resize(size, Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS)
    return image


@lru_cache(maxsize=32)
def _texture_tile(kind, seed):
    """生成可复用的小纹理，不缓存完整大图"""
    rng = np.random.default_rng(seed)
    if kind == 'grain':
        pixels = rng.normal(128, 38, (128, 128)).clip(0, 255).astype('uint8')
    elif kind == 'paper':
        noise = rng.normal(128, 24, (128, 128)).clip(0, 255).astype('uint8')
        pixels = np.asarray(Image.fromarray(noise, 'L').filter(ImageFilter.GaussianBlur(.7)))
    else:
        raise ValueError('纹理类型无效')
    return Image.fromarray(pixels, 'L')


def _apply_texture(image, spec, unit, draft):
    kind = spec.get('type', 'none')
    opacity = _value(spec, 'opacity', .12, 0, 1)
    if kind == 'none' or opacity == 0:
        return image
    scale = _value(spec, 'scale', 1, .05, 8)
    seed = int(spec.get('seed', 0))
    tile = _texture_tile(kind, seed)
    edge = max(1, min(2048, round(unit * .20 * scale)))
    tile = tile.resize((edge, edge), Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS)
    texture = Image.new('L', image.size, 128)
    for y in range(0, image.height, edge):
        for x in range(0, image.width, edge):
            texture.paste(tile, (x, y))
    rgba = image.convert('RGBA')
    gray = Image.merge('RGBA', (texture, texture, texture, rgba.getchannel('A')))
    return Image.blend(rgba, gray, opacity * .35)


def _image_background(path, size, fit, draft, fallback):
    if not path:
        return Image.new('RGBA', size, fallback)
    sampling = Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS
    with Image.open(path) as opened:
        rotated = opened.getexif().get(274, 1) in (5, 6, 7, 8)
        original = opened.size[::-1] if rotated else opened.size
        ratios = (size[0] / original[0], size[1] / original[1])
        scale = min(1.0, min(ratios) if fit == 'contain' else max(ratios))
        target = (max(1, math.ceil(original[0] * scale)), max(1, math.ceil(original[1] * scale)))
        target = target[::-1] if rotated else target
        opened.draft('RGB', target)
        opened.thumbnail(target, sampling)
        image = ImageOps.exif_transpose(opened).convert('RGBA')
    if fit == 'cover':
        return ImageOps.fit(image, size, method=sampling)
    if fit == 'stretch':
        return image.resize(size, sampling)
    if fit == 'contain':
        canvas = Image.new('RGBA', size, fallback)
        fitted = ImageOps.contain(image, size, method=sampling)
        canvas.alpha_composite(fitted, ((size[0]-fitted.width)//2, (size[1]-fitted.height)//2))
        return canvas
    raise ValueError('背景图片适配方式无效')


def _background(source, size, unit, background, image_id, draft):
    from processor.frame_layers import _blurred_background
    kind = background.get('type', 'solid')
    color = _color(background.get('color', '#FFFFFF'))
    if kind == 'solid':
        canvas = Image.new('RGBA', size, color)
    elif kind == 'gradient':
        canvas = _gradient(size, background, draft)
    elif kind == 'auto_dominant':
        canvas = Image.new('RGBA', size, (*dominant_palette(source, image_id)[0], 255))
    elif kind == 'blurred_photo':
        params = {'blur': _value(background, 'blur', .08, 0, 1),
                  'brightness': _value(background, 'brightness', .72, 0, 2),
                  'vignette': _value(background, 'vignette', .2, 0, 1)}
        canvas = _blurred_background(source, size, unit, params)
    elif kind == 'custom_image':
        canvas = _image_background(background.get('path', ''), size, background.get('fit', 'cover'), draft, color)
    else:
        raise ValueError('背景材质类型无效')
    saturation = _value(background, 'saturation', 1, 0, 4)
    if saturation != 1:
        canvas = ImageEnhance.Color(canvas).enhance(saturation)
    if kind != 'blurred_photo':
        brightness = _value(background, 'brightness', 1, 0, 2)
        if brightness != 1:
            canvas = ImageEnhance.Brightness(canvas).enhance(brightness)
    return _apply_texture(canvas, background.get('texture') or {}, unit, draft)


def _surface(canvas, source, box, unit, spec):
    from processor.filters import fast_gaussian_blur
    left, top, right, bottom = box
    radius = round(unit * _value(spec, 'radius', 0, 0, 1))
    radius = min(radius, source.width // 2, source.height // 2)
    shadow = spec.get('shadow') or {}
    blur = round(unit * _value(shadow, 'blur', 0, 0, 1))
    spread = round(unit * _value(shadow, 'spread', 0, 0, 1))
    dx = round(unit * _value(shadow, 'offset_x', 0, -1, 1))
    dy = round(unit * _value(shadow, 'offset_y', 0, -1, 1))
    opacity = _value(shadow, 'opacity', .25, 0, 1)
    if opacity and (blur or spread or dx or dy):
        mask = Image.new('L', canvas.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((left + dx - spread, top + dy - spread,
                                                right - 1 + dx + spread, bottom - 1 + dy + spread),
                                               radius=max(0, radius + spread), fill=255)
        if blur:
            mask = fast_gaussian_blur(mask, blur)
        color = _color(shadow.get('color', '#000000'))
        alpha = round(color[3] * opacity)
        mask = mask.point(lambda value: value * alpha // 255)
        layer = Image.new('RGBA', canvas.size, (*color[:3], 0))
        layer.putalpha(mask)
        canvas.alpha_composite(layer)
    stroke = spec.get('stroke') or {}
    stroke_width = round(unit * _value(stroke, 'width', 0, 0, 1))
    stroke_opacity = _value(stroke, 'opacity', 1, 0, 1)
    if stroke_width and stroke_opacity:
        color = _color(stroke.get('color', '#FFFFFF'))
        alpha = round(color[3] * stroke_opacity)
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle((left - stroke_width, top - stroke_width,
                                                right - 1 + stroke_width, bottom - 1 + stroke_width),
                                               radius=radius + stroke_width, outline=(*color[:3], alpha),
                                               width=stroke_width)
        canvas.alpha_composite(layer)
    photo = source.convert('RGBA')
    if radius:
        mask = Image.new('L', source.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, source.width - 1, source.height - 1),radius=radius,fill=255)
        photo.putalpha(ImageChops.multiply(photo.getchannel('A'), mask))
    canvas.alpha_composite(photo, (left, top))


def _legacy_glass_surface(spec):
    """旧毛玻璃未修改表面参数时保留完全一致的阴影"""
    if not spec.get('legacy_glass'):
        return False
    shadow = spec.get('shadow') or {}
    stroke = spec.get('stroke') or {}
    blur = float(shadow.get('blur', 0))
    return (not stroke.get('width') and not shadow.get('offset_x') and not shadow.get('spread')
            and math.isclose(float(shadow.get('offset_y', 0)), blur / 3, abs_tol=1e-9)
            and math.isclose(float(shadow.get('opacity', .25)), 100 / 255, abs_tol=1e-9)
            and _color(shadow.get('color', '#000000')) == (0, 0, 0, 255))


def custom_base(source, ctx, image_id=None, *, palette_source=None):
    """缓存不含装饰和文字的自定义底板"""
    from processor.frame_layers import _cache_identity, _photo_with_shadow
    frame = ctx.get('custom_frame') or {}
    if not isinstance(frame, dict):
        raise ValueError('自定义画框格式无效')
    layout = custom_geometry(source.size, frame, inset=ctx.get('overlay_mode') == 'inset_overlay',
                             legacy_bottom=ctx.get('bottom_margin'))
    width, height = layout['canvas_size']
    available = _available_bytes()
    estimate = width * height * 12
    if available is not None and estimate > max(0, available - 512 * 1024 * 1024) * .8:
        raise ValueError('目标画幅过大，请选择更接近照片的比例')
    background, surface = frame.get('background') or {}, frame.get('photo_surface') or {}
    if not isinstance(background, dict) or not isinstance(surface, dict):
        raise ValueError('画框材质格式无效')
    asset = _asset_version(background)
    draft = bool(ctx.get('_interactive_preview'))
    identity = _cache_identity(ctx, image_id)
    options = json.dumps({'geometry': frame.get('geometry') or {}, 'background': background,
                          'photo_surface': surface, 'legacy_geometry': frame.get('_legacy_geometry')},
                         ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    key = ('custom_frame_base', identity, source.size, source.mode, layout['photo_box'],
           layout['canvas_size'], options, asset, draft) if identity else None
    cached = cached_preview_image(key) if key else None
    if cached is not None and _cache_identity(ctx, image_id) == identity and _asset_version(background) == asset:
        return cached, layout, key
    texture = background.get('texture') or {}
    blank = (layout['canvas_size'] == source.size and layout['photo_box'] == (0, 0, *source.size)
             and background.get('type', 'solid') == 'solid'
             and _color(background.get('color', '#FFFFFF')) == (255, 255, 255, 255)
             and texture.get('type', 'none') == 'none' and not surface.get('radius')
             and not (surface.get('stroke') or {}).get('width')
             and not any((surface.get('shadow') or {}).get(key, 0) for key in ('blur', 'spread', 'offset_x', 'offset_y')))
    if blank:
        canvas = source.copy() if source.mode == 'RGBA' else source.convert('RGBA')
    else:
        canvas = _background(palette_source or source, layout['canvas_size'], layout['unit'], background, image_id, draft)
    if blank:
        pass
    elif _legacy_glass_surface(surface):
        shadow = surface.get('shadow') or {}
        _photo_with_shadow(canvas, source, layout['photo_box'], layout['unit'],
                           float(surface.get('radius', 0)), float(shadow.get('blur', 0)))
    else:
        _surface(canvas, source, layout['photo_box'], layout['unit'], surface)
    if asset is not None and _asset_version(background) != asset:
        raise OSError('背景图片在读取期间发生变化，请重试')
    if key and _cache_identity(ctx, image_id) == identity:
        cache_preview_image(key, canvas)
    return canvas, layout, key
