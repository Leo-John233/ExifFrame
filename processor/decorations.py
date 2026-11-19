"""按模板顺序合成画框装饰，距离统一按照片短边折算"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageOps

from core.image_cache import cache_preview_image, cached_preview_image, dominant_palette
from processor.text_layers import render_text_row


def decoration_asset_versions(decorations):
    """只有启用的外部贴图参与底板版本判断"""
    return tuple(_asset_version(item['path']) for item in decorations
                 if item.get('type') == 'png_frame_overlay' and item.get('enabled', True) and item.get('path'))


def _asset_version(path):
    path = Path(path).resolve()
    info = path.stat()
    return str(path), info.st_mtime_ns, info.st_size


def _pixels(item, key, default, unit):
    return round(_length(item, key, default, unit))


def _length(item, key, default, unit):
    try:
        value = float(item.get(key, default))
    except (ValueError, TypeError):
        raise ValueError('装饰尺寸必须是非负数') from None
    if not math.isfinite(value) or value < 0:
        raise ValueError('装饰尺寸必须是非负数')
    return value * unit


def _color(value):
    if isinstance(value, str):
        return ImageColor.getcolor(value, 'RGBA')
    return (*value, 255) if len(value) == 3 else tuple(value)


def _fill(canvas, box, ink, mask=None):
    """使用独立透明度，半透明装饰之间也按顺序混合"""
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return
    if mask is None and ink[3] == 255:
        canvas.paste(ink, box)
        return
    stamp = Image.new('RGBA', (right - left, bottom - top), ink)
    if mask is not None:
        if ink[3] != 255:
            mask = mask.point(lambda a: round(a * ink[3] / 255))
        stamp.putalpha(mask)
    canvas.alpha_composite(stamp, (left, top))


def _round_mask(size, radius, draft):
    # 小图上的圆角也使用面积采样
    scale = 1 if draft or max(size) > 1024 else 3
    width, height = size
    mask = Image.new('L', (width * scale, height * scale))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1),
                                          radius=radius * scale, fill=255)
    return mask.resize(size, Image.Resampling.BOX) if scale > 1 else mask


def _outline(canvas, box, radius, width, color):
    """只生成描边覆盖区域，避免为细线复制整幅照片"""
    x, y, r, b = box
    w, h = r - x, b - y
    width = min(width, (w + 1) // 2, (h + 1) // 2)
    if width <= 0:
        return
    radius = min(radius, w // 2, h // 2)
    cap = max(radius, width)
    for top, bottom in ((y, y + cap), (max(y + cap, b - cap), b)):
        if bottom <= top:
            continue
        mask = Image.new('L', (w, bottom - top))
        ImageDraw.Draw(mask).rounded_rectangle((0, y - top, w - 1, b - top - 1), radius, outline=255, width=width)
        _fill(canvas, (x, top, r, bottom), color, mask)
    _fill(canvas, (x, y + cap, x + width, b - cap), color)
    _fill(canvas, (max(x + width, r - width), y + cap, r, b - cap), color)


def _border(canvas, item, layout):
    unit = layout['unit']
    l, t, r, b = layout['photo_box']
    inset = _pixels(item, 'inset', .01, unit)
    pen = _length(item, 'width', .005, unit)
    if pen == 0:
        return
    width = max(1, round(pen))
    radius = _pixels(item, 'radius', 0, unit)
    distances = [inset]
    if item.get('double', False):
        distances.append(inset + width + _pixels(item, 'gap', .008, unit))
    for index, dist in enumerate(distances):
        box = max(0, l - dist), max(0, t - dist), min(canvas.width, r + dist), min(canvas.height, b + dist)
        color = item.get('color', '#FFFFFF')
        if index:
            color = item.get('outer_color', color)
        ink = _color(color)
        _outline(canvas, box, radius, width, (*ink[:3], round(ink[3] * min(1, pen))))


def _sprocket_strip(span, w, h, gap, edge, text, color, text_color, draft):
    w, h = min(w, span), max(1, h)
    strip = Image.new('RGBA', (span, h))
    hole = Image.new('RGBA', (w, h), color)
    hole.putalpha(_round_mask(hole.size, min(w, h) * .18, draft).point(lambda v: round(v * color[3] / 255)))
    start, end = edge, span - edge
    if text and end > start:
        ink = render_text_row({'processor_name': 'rich_text', 'text': text, 'font_path': 'Roboto-Medium.ttf',
                               'color': text_color})
        bounds = ink.getchannel('A').getbbox()
        if bounds:
            ink = ink.crop(bounds)
            factor = min(h / ink.height, (end - start) * .5 / ink.width)
            dims = max(1, round(ink.width * factor)), max(1, round(ink.height * factor))
            ink = ink.resize(dims, Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS)
            strip.alpha_composite(ink, (start, (h - ink.height) // 2))
            start += ink.width + gap
    count = (end - start + gap) // (w + gap)
    if count > 0:
        start += (end - start - (count * w + (count - 1) * gap)) // 2
        for i in range(count):
            strip.alpha_composite(hole, (start + i * (w + gap), 0))
    return strip


def _sprockets(canvas, item, layout, draft):
    unit = layout['unit']
    w = _pixels(item, 'hole_width', .025, unit)
    h = min(_pixels(item, 'hole_height', .012, unit), canvas.width, canvas.height)
    if not w or not h:
        return
    edge = min(_pixels(item, 'inset', .012, unit), (min(canvas.size) - h) // 2)
    gap = _pixels(item, 'spacing', .015, unit)
    args = (w, h, gap, edge, str(item.get('edge_text', '')), _color(item.get('color', '#E6DEC9')),
            item.get('text_color', '#FF804F'), draft)
    sides = item.get('edges', 'horizontal')
    if sides not in ('horizontal', 'vertical', 'all'):
        raise ValueError('齿孔位置无效')
    if sides in ('horizontal', 'all'):
        strip = _sprocket_strip(canvas.width, *args)
        canvas.alpha_composite(strip, (0, edge))
        canvas.alpha_composite(strip, (0, canvas.height - edge - h))
    if sides in ('vertical', 'all'):
        corner = edge + h if sides == 'all' else 0
        span = canvas.height - 2 * corner
        if span > 0:
            strip = _sprocket_strip(span, *args).transpose(Image.Transpose.ROTATE_90)
            canvas.alpha_composite(strip, (edge, corner))
            canvas.alpha_composite(strip, (canvas.width - edge - h, corner))


def _palette(canvas, source, item, layout, image_id, draft):
    unit = layout['unit']
    count = item.get('count', 5)
    colors = dominant_palette(source, image_id, count=count)
    count = len(colors)
    if item.get('legacy_palette') and 'legacy_palette_box' in layout:
        l, t, r, b = map(round, layout['legacy_palette_box'])
        for i, color in enumerate(colors):
            x = l + round(i * (r - l) / count)
            end = l + round((i + 1) * (r - l) / count)
            _fill(canvas, (x, t, end, b), (*color, 255))
        return
    inset = min(_pixels(item, 'inset', .025, unit), (min(canvas.size) - 1) // 2)
    width = min(_pixels(item, 'width', .24, unit), canvas.width - 2 * inset)
    height = min(_pixels(item, 'height', .025, unit), canvas.height - 2 * inset)
    if not width or not height:
        return
    gap = min(_pixels(item, 'gap', .005, unit), max(0, (width - count) // (count - 1)))
    slot = (width - gap * (count - 1)) / count
    shape = item.get('shape', 'square')
    if shape not in ('square', 'circle', 'capsule'):
        raise ValueError('色块形状无效')
    swatch_width = slot if shape == 'capsule' else min(slot, height)
    swatch_height = min(height, swatch_width)
    run = swatch_width * count + gap * (count - 1)
    vertical, _, horizontal = str(item.get('position', 'bottom_center')).partition('_')
    if vertical not in ('top', 'bottom') or horizontal not in ('left', 'center', 'right'):
        raise ValueError('色卡位置无效')
    y = inset if vertical == 'top' else canvas.height - inset - swatch_height
    x0 = {'left': inset, 'center': (canvas.width - run) / 2, 'right': canvas.width - inset - run}[horizontal]
    for index, color in enumerate(colors):
        x = x0 + index * (swatch_width + gap)
        box = round(x), round(y), round(x + swatch_width), round(y + swatch_height)
        size = box[2] - box[0], box[3] - box[1]
        if min(size) <= 0:
            continue
        mask = _round_mask(size, min(size) / 2, draft) if shape in ('circle', 'capsule') else None
        _fill(canvas, box, (*color, 255), mask)


def _marks(canvas, item, layout):
    unit = layout['unit']
    l, t, r, b = layout['photo_box']
    pad = _pixels(item, 'inset', .035, unit)
    length = min(_pixels(item, 'length', .03, unit), (r - l) // 2, (b - t) // 2)
    pen = _length(item, 'width', .003, unit)
    width = min(max(1, round(pen)), length)
    if not width or not pen or 2 * pad >= min(r - l, b - t):
        return
    ink = _color(item.get('color', '#FAFAF8'))
    ink = (*ink[:3], round(ink[3] * min(1, pen)))
    cross = item.get('style') == 'crosshair'
    for x, dx in ((l + pad, 1), (r - 1 - pad, -1)):
        for y, dy in ((t + pad, 1), (b - 1 - pad, -1)):
            hx = x - dx * (length // 2) if cross else x
            vy = y - dy * (length // 2) if cross else y
            xr = sorted((hx, hx + dx * (length - 1)))
            yr = sorted((vy, vy + dy * (length - 1)))
            line_top, line_left = y - width // 2, x - width // 2
            _fill(canvas, (max(l, xr[0]), max(t, line_top), min(r, xr[1] + 1), min(b, line_top + width)), ink)
            _fill(canvas, (max(l, line_left), max(t, yr[0]), min(r, line_left + width), min(b, yr[1] + 1)), ink)


def _axis_cuts(length, first, last):
    if not all(math.isfinite(n) and 0 <= n <= .5 for n in (first, last)):
        raise ValueError('九宫格切边须在 0 到 50 之间')
    a, b = round(length * first), round(length * last)
    return (0, a, max(a, length - b), length)


def nine_slice(image, size, slices, unit, sampling):
    """四角共用一个等比缩放因子，只沿各边的长轴延展"""
    sw, sh = image.size
    tw, th = size
    x = _axis_cuts(sw, float(slices.get('left', .15)), float(slices.get('right', .15)))
    y = _axis_cuts(sh, float(slices.get('top', .15)), float(slices.get('bottom', .15)))
    scale = min(unit / min(sw, sh), tw / max(1, x[1] + sw - x[2]), th / max(1, y[1] + sh - y[2]))

    def target(cuts, dest):
        start = min(dest, round(cuts[1] * scale))
        end = max(start, dest - round((cuts[3] - cuts[2]) * scale))
        return 0, start, end, dest

    dst_x, dst_y = target(x, tw), target(y, th)
    output = Image.new('RGBA', size)
    for row in range(3):
        for col in range(3):
            left, top, right, bottom = x[col], y[row], x[col + 1], y[row + 1]
            dst = dst_x[col], dst_y[row], dst_x[col + 1], dst_y[row + 1]
            dims = dst[2] - dst[0], dst[3] - dst[1]
            if min(dims) <= 0:
                continue
            # 两边各占一半时沿接缝取样，不挤占四角
            if left == right:
                left = min(left, sw - 1)
                right = left + 1
            if top == bottom:
                top = min(top, sh - 1)
                bottom = top + 1
            tile = image.crop((left, top, right, bottom))
            if tile.size != dims:
                tile = tile.resize(dims, sampling)
            output.paste(tile, dst[:2])
    return output


def _png(canvas, item, layout, draft):
    path = item.get('path')
    if not path:
        return
    version = _asset_version(path)
    fit = item.get('fit', 'stretch')
    slices = item.get('slices') or {}
    key = ('png_frame_overlay', version, canvas.size, fit, tuple(sorted(slices.items())), layout['unit'], draft)
    stamp = cached_preview_image(key)
    if stamp is None:
        sampling = Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS
        with Image.open(version[0]) as opened:
            if opened.format != 'PNG':
                raise ValueError('相框贴图须为 PNG 图片')
            art = opened.convert('RGBA')
        if fit == 'nine_slice':
            stamp = nine_slice(art, canvas.size, slices, layout['unit'], sampling)
        elif fit == 'cover':
            stamp = ImageOps.fit(art, canvas.size, method=sampling)
        elif fit == 'stretch':
            stamp = art.resize(canvas.size, sampling)
        else:
            raise ValueError('相框贴图适配方式无效')
        if _asset_version(path) != version:
            raise OSError('相框贴图在读取期间发生变化，请重试')
        cache_preview_image(key, stamp)
    opacity = float(item.get('opacity', 1))
    if not math.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError('相框贴图透明度须在 0 到 100 之间')
    if opacity < 1:
        stamp.putalpha(stamp.getchannel('A').point(lambda a: round(a * opacity)))
    canvas.alpha_composite(stamp)


def draw_decorations(canvas, source, decorations, layout, image_id, draft=False):
    """依序绘制相框装饰，保留关闭的图层配置"""
    for item in decorations:
        if not item.get('enabled', True):
            continue
        kind = item.get('type')
        legacy = item.get('legacy_style')
        if (kind, legacy) in (('border_line', 'gallery_mat'), ('film_sprockets', 'film_strip')):
            from processor.frame_layers import _film_holes, _gallery
            box = layout['photo_box']
            photo = canvas.crop(box)
            if kind == 'border_line':
                _gallery(canvas, box, layout['unit'])
            else:
                _film_holes(canvas, layout)
            canvas.paste(photo, box[:2])
        elif kind == 'border_line':
            _border(canvas, item, layout)
        elif kind == 'film_sprockets':
            _sprockets(canvas, item, layout, draft)
        elif kind == 'palette_bar':
            _palette(canvas, source, item, layout, image_id, draft)
        elif kind == 'viewfinder_marks':
            _marks(canvas, item, layout)
        elif kind == 'png_frame_overlay':
            _png(canvas, item, layout, draft)
        else:
            raise ValueError('未知装饰图层')
    return canvas
