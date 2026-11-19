"""声明式画框底板及与前景共享的几何"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from core.image_cache import cache_preview_image, cached_preview_image, valid_file_image_id
from processor.filters import blur_sample_factor, fast_gaussian_blur
from processor.render_slots import transfer_slots


_DEFAULTS = {
    'solid_border': (.045, .17, '#FFFFFF'),
    'polaroid_bottom': (.055, .34, '#FFFFFF'),
    'blurred_glass': (.08, .24, '#FFFFFF'),
    'gallery_mat': (.12, .23, '#F3EFE8'),
    'film_strip': (.075, .24, '#171513'),
}


def _number(ctx, key, default, low, high):
    value = float(ctx.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{key} 参数超出范围')
    return value


def _rgba(value):
    if isinstance(value, (tuple, list)):
        if len(value) == 3:
            return (*value, 255)
        if len(value) == 4:
            return tuple(value)
    return ImageColor.getcolor(str(value), 'RGBA')


def _parameters(ctx, style):
    margin, bottom, color = _DEFAULTS[style]
    fixed_bottom = ctx.get('bottom_margin')
    if fixed_bottom is not None:
        fixed_bottom = int(fixed_bottom)
        if fixed_bottom < 0:
            raise ValueError('bottom_margin 参数超出范围')
    return {
        'margin': _number(ctx, 'frame_margin', margin, 0, 1),
        'bottom': _number(ctx, 'frame_bottom', bottom, 0, 1),
        'radius': _number(ctx, 'frame_radius', .025, 0, 1),
        'shadow': _number(ctx, 'frame_shadow', .025, 0, 1),
        'blur': _number(ctx, 'frame_blur', .08, 0, 1),
        'brightness': _number(ctx, 'frame_brightness', .72, 0, 2),
        'vignette': _number(ctx, 'frame_vignette', .25, 0, 1),
        'color': _rgba(ctx.get('frame_color', ctx.get('color', color))),
        'fixed_bottom': fixed_bottom,
    }


def _layout(size, style, parameters, inset=False):
    width, height = size
    unit = min(width, height)
    if inset:
        padding = min(max(1, round(unit * .035)), max(0, (unit - 1) // 2))
        return {'photo_box': (0, 0, width, height),
                'caption_box': (padding, padding, width - padding, height - padding),
                'canvas_size': (width, height), 'unit': unit, 'inset_overlay': True,
                'frame_style': style}
    margin = max(0, round(unit * parameters['margin']))
    bottom = (parameters['fixed_bottom'] if parameters['fixed_bottom'] is not None
              else max(1, round(unit * parameters['bottom'])))
    if style == 'film_strip':
        margin = max(margin, max(3, round(unit * .055)))
        if parameters['fixed_bottom'] is None:
            bottom = max(bottom, max(4, round(unit * .11)))
    canvas_size = (width + margin * 2, height + margin + bottom)
    photo_box = (margin, margin, margin + width, margin + height)
    caption_bottom = canvas_size[1]
    if style == 'film_strip':
        caption_bottom -= max(2, round(unit * .055))
    caption_box = (margin, photo_box[3], margin + width, max(photo_box[3], caption_bottom))
    return {'photo_box': photo_box, 'caption_box': caption_box, 'canvas_size': canvas_size,
            'unit': unit, 'inset_overlay': False, 'frame_style': style}


def frame_geometry(source_size, ctx):
    """不读取图像，仅计算指定源尺寸对应的画框几何"""
    if 'custom_frame' in ctx:
        from processor.custom_frame import custom_geometry, legacy_composite_size
        frame = ctx.get('custom_frame') or {}
        if not isinstance(frame, dict):
            raise ValueError('自定义画框格式无效')
        size = legacy_composite_size(source_size, ctx) if frame.get('legacy_composite') else source_size
        return custom_geometry(size, frame, inset=ctx.get('overlay_mode') == 'inset_overlay',
                               legacy_bottom=ctx.get('bottom_margin'))
    style = ctx.get('frame_style') or 'solid_border'
    if style not in _DEFAULTS:
        raise ValueError(f'未知画框样式：{style}')
    if len(source_size) != 2 or min(source_size) <= 0:
        raise ValueError('照片尺寸无效')
    return _layout(tuple(source_size), style, _parameters(ctx, style),
                   ctx.get('overlay_mode') == 'inset_overlay')


def _blurred_background(source, size, unit, parameters):
    # 在受限尺寸生成模糊底板，再放大以控制高清内存和耗时
    scale = min(1.0, 1600 / max(size))
    factor = blur_sample_factor(unit * parameters['blur'] * scale)
    scale /= factor
    small_size = (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
    sampling = Image.Resampling.BILINEAR if factor > 1 else Image.Resampling.LANCZOS
    background = ImageOps.fit(source, small_size, method=sampling)
    if 'A' in background.getbands():
        base = Image.new('RGBA', small_size, 'white')
        base.alpha_composite(background.convert('RGBA'))
        background = base.convert('RGB')
    else:
        background = background.convert('RGB')
    radius = unit * parameters['blur'] * scale
    if radius > 0:
        background = background.filter(ImageFilter.GaussianBlur(radius))
    if parameters['brightness'] != 1:
        background = ImageEnhance.Brightness(background).enhance(parameters['brightness'])
    if parameters['vignette']:
        pixels = np.asarray(background, dtype=np.float32)
        x = np.linspace(-1, 1, small_size[0], dtype=np.float32)
        y = np.linspace(-1, 1, small_size[1], dtype=np.float32)
        distance = np.minimum(1, (x[None, :] ** 2 + y[:, None] ** 2) / 2)
        factor = 1 - parameters['vignette'] * distance
        background = Image.fromarray(np.clip(pixels * factor[:, :, None], 0, 255).astype('uint8'), 'RGB')
    if small_size != size:
        background = background.resize(size, sampling)
    return background.convert('RGBA')


def _photo_with_shadow(canvas, source, box, unit, radius_ratio, shadow_ratio):
    left, top, right, bottom = box
    radius = max(0, min(round(unit * radius_ratio), source.width // 2, source.height // 2))
    shadow = max(0, round(unit * shadow_ratio))
    if shadow:
        mask = Image.new('L', canvas.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((left, top + max(1, shadow // 3), right - 1, bottom - 1 + max(1, shadow // 3)),
                               radius=radius, fill=100)
        mask = fast_gaussian_blur(mask, shadow)
        layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        layer.putalpha(mask)
        canvas.alpha_composite(layer)
    photo = source.convert('RGBA')
    if radius:
        mask = Image.new('L', source.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, source.width - 1, source.height - 1), radius=radius, fill=255)
        photo.putalpha(ImageChops.multiply(photo.getchannel('A'), mask))
    canvas.alpha_composite(photo, (left, top))


def _gallery(canvas, box, unit):
    left, top, right, bottom = box
    line = max(1, round(unit * .001))
    outer, inner = max(2, round(unit * .026)), max(1, round(unit * .013))
    shadow_width = max(1, round(unit * .008))
    mask = Image.new('L', canvas.size, 0)
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=58)
    mask = fast_gaussian_blur(mask, shadow_width)
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shadow.putalpha(mask)
    canvas.alpha_composite(shadow)
    draw = ImageDraw.Draw(canvas)
    for gap, color in ((outer, (165, 157, 145, 255)), (inner, (210, 203, 193, 255))):
        draw.rectangle((left - gap, top - gap, right - 1 + gap, bottom - 1 + gap), outline=color, width=line)


def _film_holes(canvas, layout):
    unit = layout['unit']
    width, height = layout['canvas_size']
    hole_w = max(1, min(width, round(unit * .04)))
    hole_h = max(1, min(height, round(unit * .025)))
    gap, edge = max(1, round(unit * .035)), max(0, min(round(unit * .015), (width - hole_w) // 2))
    count = max(1, (width - 2 * edge + gap) // (hole_w + gap))
    span = count * hole_w + (count - 1) * gap
    start = max(0, (width - span) // 2)
    draw = ImageDraw.Draw(canvas)
    for index in range(count):
        x = start + index * (hole_w + gap)
        for y in (edge, max(edge, height - edge - hole_h)):
            draw.rounded_rectangle((x, y, min(width - 1, x + hole_w - 1), min(height - 1, y + hole_h - 1)),
                                   radius=max(1, hole_h // 5), fill=(225, 219, 205, 255))


def _valid_stage(key):
    """只接受可追溯到真实文件版本的内部管线身份"""
    if not isinstance(key, tuple) or not key:
        return False
    if key[0] == 'filter' and len(key) == 4:
        return _valid_stage(key[2])
    if key[0] in ('file', 'source') and len(key) >= 4:
        return valid_file_image_id(('file', key[1], key[2], key[3]))
    return False


def _cache_identity(ctx, image_id):
    if '_frame_cache_key' in ctx:
        stage = ctx.get('_frame_cache_key')
        return ('pipeline', stage) if _valid_stage(stage) else None
    return ('file', image_id) if valid_file_image_id(image_id) else None


def legacy_base(source, ctx, footer_height, image_id=None):
    """复用旧版底板的精确像素和来源版本"""
    left = int(ctx.get('left_margin', 0))
    right = int(ctx.get('right_margin', 0))
    top = int(ctx.get('top_margin', 0))
    color = ctx.get('color', 'white')
    size = (source.width + left + right, source.height + top + footer_height)
    identity = _cache_identity(ctx, image_id)
    key = ('legacy_frame_base', identity, source.size, source.mode, size, left, top, _rgba(color)) if identity else None
    cached = cached_preview_image(key) if key is not None else None
    if cached is not None and _cache_identity(ctx, image_id) == identity:
        return transfer_slots(source, cached, (left, top), replace=True)
    canvas = Image.new('RGBA', size, color)
    canvas.alpha_composite(source.convert('RGBA'), (left, top))
    if key is not None and _cache_identity(ctx, image_id) == identity:
        cache_preview_image(key, canvas)
    return transfer_slots(source, canvas, (left, top), replace=True)


def frame_base(source, ctx, image_id=None):
    """生成不包含文字的画框底板，缓存只使用可信源图身份"""
    inset = ctx.get('overlay_mode') == 'inset_overlay'
    style = ctx.get('frame_style') or 'solid_border'
    if style not in _DEFAULTS:
        raise ValueError(f'未知画框样式：{style}')
    if source.width <= 0 or source.height <= 0:
        raise ValueError('照片尺寸无效')
    params = _parameters(ctx, style)
    layout = frame_geometry(source.size, ctx)
    identity = _cache_identity(ctx, image_id)
    key = ('frame_base', identity, source.size, source.mode, style, inset,
           tuple(sorted(params.items()))) if identity else None
    cached = cached_preview_image(key) if key is not None else None
    if cached is not None and _cache_identity(ctx, image_id) == identity:
        return cached, layout
    if inset:
        canvas = source.copy() if source.mode == 'RGBA' else source.convert('RGBA')
    else:
        box, unit = layout['photo_box'], layout['unit']
        if style == 'blurred_glass':
            canvas = _blurred_background(source, layout['canvas_size'], unit, params)
            _photo_with_shadow(canvas, source, box, unit, params['radius'], params['shadow'])
        else:
            canvas = Image.new('RGBA', layout['canvas_size'], params['color'])
            if style == 'gallery_mat':
                _gallery(canvas, box, unit)
            elif style == 'film_strip':
                _film_holes(canvas, layout)
            canvas.alpha_composite(source.convert('RGBA'), (box[0], box[1]))
    if key is not None and _cache_identity(ctx, image_id) == identity:
        cache_preview_image(key, canvas)
    return canvas, layout


def render_frame(source, ctx, image_id=None):
    """统一调度声明式和旧版画框，并共享底板缓存"""
    from processor.core import uses_frame_layers
    from processor.core import PipelineContext
    from processor.render_slots import effective_text
    prepared = dict(ctx)
    for name in ('left_top', 'left_bottom', 'right_top', 'right_bottom'):
        if isinstance(ctx.get(name), dict):
            prepared[name] = effective_text(ctx[name])
    for name, style in (ctx.get('logo_styles') or {}).items():
        if name in {'left_logo', 'center_logo', 'right_logo'} and isinstance(style, dict):
            if style.get('visible') is False:
                prepared[name] = None
    ctx = PipelineContext(prepared)
    if 'custom_frame' in ctx:
        return _render_custom_frame(source, ctx, image_id)
    if not uses_frame_layers(ctx):
        if ctx.get('processor_name') == 'watermark_with_timestamp':
            from processor.frame_overlay import draw_timestamp
            return draw_timestamp(source, ctx)
        from processor.watermark_1521 import render_watermark, uses_default_layout, watermark_scale
        scale = watermark_scale(ctx)
        if uses_default_layout(ctx):
            return render_watermark(ctx, source, scale)
        from processor.filters import draw_pixel_footer
        return draw_pixel_footer(ctx, source, scale)
    from processor.frame_overlay import draw_overlay
    canvas, layout = frame_base(source, ctx, image_id)
    box = layout['photo_box']
    transfer_slots(source, canvas, box[:2], (box[2] - box[0], box[3] - box[1]), replace=True)
    if ctx.get('processor_name') == 'watermark_with_timestamp':
        context = dict(ctx)
        row = {name: ctx[name] for name in ('text_segments', 'text', 'font_path', 'font', 'color',
                                            'is_bold', 'trim', 'text_spacing', 'text_alignment',
                                            'char_styles', 'highlight_rules', '_slot_key', 'slot_style', 'visible') if name in ctx}
        row['processor_name'] = 'multi_rich_text' if 'text_segments' in row else 'rich_text'
        if ctx.get('height_ratio') is not None:
            row['height_ratio'] = ctx['height_ratio']
        elif ctx.get('height') is not None:
            row['height_ratio'] = float(ctx['height']) / layout['unit']
        context.setdefault('right_top', row)
        ctx = context
    return draw_overlay(canvas, source, ctx, layout, image_id)


def _render_custom_frame(source, ctx, image_id):
    """依次组合可缓存底板、装饰和独立文字前景"""
    import json
    from copy import deepcopy
    from processor.core import PipelineContext
    from processor.custom_frame import custom_base, plan_custom_base
    from processor.decorations import decoration_asset_versions, draw_decorations
    from processor.frame_overlay import draw_overlay, palette_box_for

    frame = ctx.get('custom_frame') or {}
    if not isinstance(frame, dict):
        raise ValueError('自定义画框格式无效')
    working, cache_ctx, cache_id = source, ctx, image_id
    legacy = bool(frame.get('legacy_composite'))
    if legacy:
        previous = {key: deepcopy(value) if isinstance(value, (dict, list))
                    and key not in {'buffer', 'input_buffer'} else value
                    for key, value in ctx.items() if key != 'custom_frame'}
        working = source.copy()
        previous.update(buffer=[working], buffer_loaded=True)
        working = render_frame(working, PipelineContext(previous), image_id)
        cache_ctx = dict(ctx)
        cache_ctx['_frame_cache_key'] = None
        cache_id = None
    plan = plan_custom_base(working, cache_ctx, cache_id)
    layout, base_key = plan.layout, plan.key
    decorations = frame.get('decorations') or []
    if not isinstance(decorations, list) or not all(isinstance(item, dict) for item in decorations):
        raise ValueError('装饰图层格式无效')
    overlay = dict(ctx)
    if frame.get('legacy_palette_migrated'):
        enabled = any(item.get('type') == 'palette_bar' and item.get('legacy_palette')
                      and item.get('enabled', True) for item in decorations)
        overlay['palette_bar'] = enabled
        if enabled:
            layout['legacy_palette_box'] = palette_box_for(overlay, layout)
            overlay['_skip_legacy_palette_paint'] = True
    versions = decoration_asset_versions(decorations)
    draft = bool(ctx.get('_interactive_preview'))
    options = json.dumps(decorations, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    geometry_key = (layout['photo_box'], layout['caption_box'], layout['canvas_size'], layout['unit'],
                    layout['inset_overlay'], layout.get('legacy_palette_box'))
    decorated_key = ('custom_decorated', base_key, geometry_key, options, versions, draft) if base_key and decorations else None
    cached = cached_preview_image(decorated_key) if decorated_key else None
    if (cached is not None and plan.current(cache_ctx, cache_id)
            and decoration_asset_versions(decorations) == versions):
        canvas = cached
    else:
        canvas, _, _ = custom_base(working, cache_ctx, cache_id, palette_source=source,
                                   palette_image_id=image_id, plan=plan)
        if decorations:
            canvas = draw_decorations(canvas, source, decorations, layout, image_id, draft=draft)
            if (decorated_key and plan.current(cache_ctx, cache_id)
                    and decoration_asset_versions(decorations) == versions):
                cache_preview_image(decorated_key, canvas)
    box = layout['photo_box']
    transfer_slots(working, canvas, box[:2], (box[2] - box[0], box[3] - box[1]), replace=True)
    if legacy:
        return canvas
    if ctx.get('processor_name') == 'watermark_with_timestamp':
        row = {name: ctx[name] for name in ('text_segments', 'text', 'font_path', 'font', 'color',
                                            'is_bold', 'trim', 'text_spacing', 'text_alignment',
                                            'char_styles', 'highlight_rules', '_slot_key', 'slot_style', 'visible') if name in ctx}
        row['processor_name'] = 'multi_rich_text' if 'text_segments' in row else 'rich_text'
        if ctx.get('height_ratio') is not None:
            row['height_ratio'] = ctx['height_ratio']
        elif ctx.get('height') is not None:
            row['height_ratio'] = float(ctx['height']) / layout['unit']
        overlay.setdefault('right_top', row)
    return draw_overlay(canvas, source, overlay, layout, image_id)
