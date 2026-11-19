"""沿用 build1521 的整条底栏比例和缩放方式"""

import json

from PIL import Image, ImageOps

from processor.text_layers import _font_at_size, _segment_image, render_text_row as _row_image, watermark_scale
from processor.types import Alignment


_NORMAL_HEIGHT = 1000


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


def render_watermark(ctx, image, scale):
    """按旧版虚拟底栏拼接后整体映射到照片宽度"""
    from processor.frame_layers import legacy_base

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
    top_margin = ctx.getint('top_margin', 0)
    canvas = legacy_base(image, ctx, footer_height, ctx.get('_frame_image_id'))
    canvas.alpha_composite(footer, (left_margin, top_margin + image.height))
    return canvas
