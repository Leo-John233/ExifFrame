"""沿用 build1521 的整条底栏比例和缩放方式"""

import json
import math
from collections import OrderedDict
from threading import local

from PIL import Image, ImageDraw, ImageOps

from core.font_fallback import _font_key, _native_z, _supports, _weight, render_with_fallback
from processor.core import _parse_color
from processor.generators import _font_state, load_font, location_text_font
from processor.types import Alignment


_NORMAL_HEIGHT = 1000
_FONT_CACHE = local()
_TEXT_LIMIT = 16 * 1024 * 1024


def _font_at_size(path, size):
    """按字体文件版本和工作线程复用对应字号"""
    primary = load_font(path)
    key = (primary, size)
    if not hasattr(_FONT_CACHE, 'variants'):
        _FONT_CACHE.variants = OrderedDict()
    cache = _FONT_CACHE.variants
    if key not in cache:
        cache[key] = primary.font_variant(size=size) if hasattr(primary, 'font_variant') else primary
        if len(cache) > 32:
            cache.popitem(last=False)
    cache.move_to_end(key)
    return cache[key]


def _segment_image(segment):
    """按旧版字形边界生成单个文字片段"""
    original = segment.get('text') or '   '
    path, text, location = location_text_font(original, segment.get('font_path'), segment.get('is_bold', False))
    primary = load_font(path)
    size = 260 if segment.get('is_bold', False) or _weight(primary) >= 600 else 240
    font = _font_at_size(path, size)
    original_font = _font_at_size(None, size) if location else None
    baseline = original_font.getmetrics()[0] if original_font is not None else font.getmetrics()[0]
    color = _parse_color(segment.get('color', 'black'))
    key = ('watermark_1521', font, text, color, original_font, original if original_font is not None else None)
    if not hasattr(_font_state, 'text_images'):
        _font_state.text_images = OrderedDict()
        _font_state.text_bytes = 0
    cache = _font_state.text_images
    if key in cache:
        cache.move_to_end(key)
        return cache[key][0].copy(), baseline

    image = render_with_fallback(text, font, lambda fallback: _font_at_size(fallback, size), color)
    can_cache = image is None
    layout = text
    if 'ℤ' in text and _native_z(font) and not _supports(_font_key(font), ord('ℤ')):
        layout = text.replace('ℤ', 'Z')
    if '\n' in layout:
        probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        bounds = probe.multiline_textbbox((0, 0), layout, font=font)
    else:
        bounds = font.getbbox(layout)
    if can_cache:
        width = max(1, bounds[2] - bounds[0])
        height = max(1, bounds[3])
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(image).text((0, 0), text, font=font, fill=color)
    else:
        ink = image.getchannel('A').getbbox()
        height = max(1, bounds[3], ink[3] if ink else 0)
        if height < image.height:
            image = image.crop((0, 0, image.width, height))
    if original_font is not None:
        # 使用原字体的行框和基线，避免带动同列其他字段缩放
        height = max(1, original_font.getbbox(original)[3])
        frame = Image.new('RGBA', (image.width, height), (0, 0, 0, 0))
        frame.alpha_composite(image, (0, baseline - font.getmetrics()[0]))
        image = frame
    cost = image.width * image.height * 4 + len(text) * 4
    if can_cache and cost <= _TEXT_LIMIT:
        while cache and (_font_state.text_bytes + cost > _TEXT_LIMIT or len(cache) >= 64):
            _, (_, old_cost) = cache.popitem(last=False)
            _font_state.text_bytes -= old_cost
        cache[key] = (image.copy(), cost)
        _font_state.text_bytes += cost
    return image, baseline


def _row_image(node):
    if node.get('processor_name') == 'rich_text':
        return _segment_image(node)[0]
    segments = node.get('text_segments') or []
    if isinstance(segments, str):
        segments = json.loads(segments)
    if not segments:
        return _segment_image({'text': ''})[0]
    rendered = [_segment_image(segment) for segment in segments]
    if len(rendered) == 1:
        return rendered[0][0]
    baseline = max(ascent for _, ascent in rendered)
    height = max(baseline - ascent + image.height for image, ascent in rendered)
    width = sum(image.width for image, _ in rendered)
    result = Image.new('RGBA', (max(1, width), max(1, height)), (0, 0, 0, 0))
    x = 0
    for image, ascent in rendered:
        result.alpha_composite(image, (x, baseline - ascent))
        x += image.width
    return result


def _padding(image, amount, location='tb'):
    left = amount if 'l' in location else 0
    right = amount if 'r' in location else 0
    top = amount if 't' in location else 0
    bottom = amount if 'b' in location else 0
    result = Image.new('RGBA', (image.width + left + right, image.height + top + bottom), (0, 0, 0, 0))
    result.paste(image, (left, top))
    return result


def _column(top, bottom, background, align_right=False):
    width = max(10, top.width, bottom.width)
    result = Image.new('RGBA', (width, top.height + 100 + bottom.height), (0, 0, 0, 0))
    result.paste(top, (width - top.width if align_right else 0, 0))
    result.paste(Image.new('RGBA', (10, 100), background), (0, top.height))
    result.paste(bottom, (width - bottom.width if align_right else 0, top.height + 100))
    return result


def _normalize(image):
    width = max(1, round(image.width * _NORMAL_HEIGHT / image.height))
    return image.resize((width, _NORMAL_HEIGHT), Image.Resampling.LANCZOS)


def _read_logo(path, padding):
    with Image.open(path) as opened:
        image = opened.convert('RGBA')
    return _normalize(_padding(image, int(padding * image.height)))


def uses_default_layout(ctx):
    """明确的像素参数继续使用模板原有布局"""
    explicit = ('bottom_margin', 'middle_spacing', 'delimiter_width',
                'center_logo_height', 'center_height', 'center_logo_padding')
    if any(key in ctx for key in explicit):
        return False
    for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom'):
        node = ctx.get(key)
        if not isinstance(node, dict) or node.get('processor_name') not in {'rich_text', 'multi_rich_text'}:
            return False
        if ('height' in node or node.get('trim') or node.get('text_spacing') or
                node.get('text_alignment') or any(key in node for key in ('buffer_path', 'input_buffer', 'select'))):
            return False
        segments = node.get('text_segments') or []
        if isinstance(segments, str):
            segments = json.loads(segments)
        if any(segment.get('trim') for segment in segments):
            return False
    return True


def watermark_scale(ctx):
    scale = float(ctx.get('watermark_scale', 1.0))
    if not math.isfinite(scale) or not .5 <= scale <= 2:
        raise ValueError('水印整体大小需在 50% 到 200% 之间')
    return scale


def render_watermark(ctx, image, scale):
    """按旧版虚拟底栏拼接后整体映射到照片宽度"""
    landscape = image.width >= image.height
    ratio = .08 if landscape else .13
    padding = .44 if landscape else .62
    base_width = int(_NORMAL_HEIGHT / ratio)
    virtual_width = max(1, int(base_width / scale))
    background = ctx.get('color', 'white')
    watermark = Image.new('RGBA', (virtual_width, _NORMAL_HEIGHT), background)
    left_top, left_bottom, right_top, right_bottom = (
        _row_image(ctx.get(key)) for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom'))
    right_alignment = ctx.getenum('right_alignment', Alignment.RIGHT, Alignment)
    left = _column(left_top, left_bottom, background)
    right = _column(right_top, right_bottom, background, align_right=right_alignment == Alignment.RIGHT)
    max_height = max(left.height, right.height)
    margin = int(max_height * padding)
    left = _padding(left, margin)
    right = _padding(right, margin, 't')
    right = _padding(right, left.height - right.height, 'b')
    left, right = _normalize(left), _normalize(right)

    left_logo = ctx.get('left_logo')
    right_logo = ctx.get('right_logo')
    center_logo = ctx.get('center_logo')
    center = _read_logo(center_logo, padding) if center_logo else None
    if center:
        max_width = watermark.width
        if ctx.get('fit_center_columns', False):
            max_width = max(1, round(watermark.width * .18))
        center = ImageOps.contain(center, (max_width, _NORMAL_HEIGHT), Image.Resampling.LANCZOS)
        center_x = (watermark.width - center.width) // 2
        watermark.paste(center, (center_x, (_NORMAL_HEIGHT - center.height) // 2))
    x = 0 if left_logo else 200
    if left_logo:
        x += 20 + 200
        logo = _read_logo(left_logo, padding)
        watermark.paste(logo, (x, 0))
        x += logo.width + 200
    if center and ctx.get('fit_center_columns', False):
        available = max(1, center_x - x - 200)
        if left.width > available:
            left = ImageOps.contain(left, (available, _NORMAL_HEIGHT), Image.Resampling.LANCZOS)
    watermark.paste(left, (x, (_NORMAL_HEIGHT - left.height) // 2))

    x = watermark.width
    right_end = x - 200
    line = logo = None
    if right_logo:
        line = _padding(Image.new('RGBA', (20, _NORMAL_HEIGHT), ctx.get('delimiter_color', 'black')),
                        int(padding * _NORMAL_HEIGHT * .8))
        line, logo = _normalize(line), _read_logo(right_logo, padding)
    if center and ctx.get('fit_center_columns', False):
        occupied = (line.width + logo.width + 400) if right_logo else 0
        available = max(1, right_end - occupied - center_x - center.width - 200)
        if right.width > available:
            right = ImageOps.contain(right, (available, _NORMAL_HEIGHT), Image.Resampling.LANCZOS)
    parts = [right] + ([line, logo] if right_logo else [])
    for part in parts:
        x -= part.width + 200
        watermark.paste(part, (x, (_NORMAL_HEIGHT - part.height) // 2))

    footer_height = max(1, round(_NORMAL_HEIGHT * image.width / watermark.width))
    footer = watermark.resize((image.width, footer_height), Image.Resampling.LANCZOS)
    left_margin = ctx.getint('left_margin', 0)
    right_margin = ctx.getint('right_margin', 0)
    top_margin = ctx.getint('top_margin', 0)
    canvas = Image.new('RGBA', (image.width + left_margin + right_margin,
                                image.height + top_margin + footer_height), background)
    canvas.paste(image, (left_margin, top_margin), mask=image if image.mode == 'RGBA' else None)
    canvas.alpha_composite(footer, (left_margin, top_margin + image.height))
    return canvas
