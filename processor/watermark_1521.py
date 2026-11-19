"""沿用 build1521 的整条底栏比例和缩放方式"""

import json
from PIL import Image, ImageOps

from core.image_cache import cached_preview_image, cache_preview_image
from processor.text_layers import _font_at_size, _segment_image, render_text_row as _row_image, watermark_scale
from processor.types import Alignment
from processor.render_slots import tag_logo, transfer_slots
from processor.logo_layer import layer_logo, logo_options, logo_variant_path, fit_logo


_NORMAL_HEIGHT = 1000


def _padding(image, amount, location='tb'):
    left = amount if 'l' in location else 0
    right = amount if 'r' in location else 0
    top = amount if 't' in location else 0
    bottom = amount if 'b' in location else 0
    result = Image.new('RGBA', (image.width + left + right, image.height + top + bottom), (0, 0, 0, 0))
    result.alpha_composite(image.convert('RGBA'), (left, top))
    transfer_slots(image, result, (left, top))
    return result


def _column(top, bottom, background, align_right=False):
    width = max(10, top.width, bottom.width)
    result = Image.new('RGBA', (width, top.height + 100 + bottom.height), (0, 0, 0, 0))
    result.alpha_composite(top, (width - top.width if align_right else 0, 0))
    transfer_slots(top, result, (width - top.width if align_right else 0, 0))
    result.alpha_composite(Image.new('RGBA', (10, 100), background), (0, top.height))
    result.alpha_composite(bottom, (width - bottom.width if align_right else 0, top.height + 100))
    transfer_slots(bottom, result, (width - bottom.width if align_right else 0, top.height + 100))
    return result


def _normalize(image, height=_NORMAL_HEIGHT, sampling=Image.Resampling.LANCZOS):
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), sampling)


def _read_logo(path, padding, background=None, **options):
    path = logo_variant_path(path, background, adaptive=options.get('adaptive', True), variant=options.get('variant', 'auto'))
    info = path.stat()
    key = ('1521_logo_rgba_v4', str(path), info.st_mtime_ns, info.st_size, padding, background, tuple(sorted(options.items())))
    cached = cached_preview_image(key)
    if cached is not None:
        return cached
    image = layer_logo(path, (1000, 1000), background=background, trim=False, **options)
    padded = _padding(image, int(padding * image.height))
    logo = fit_logo(padded, (max(1, round(padded.width * _NORMAL_HEIGHT / padded.height)), _NORMAL_HEIGHT))
    logo.info.update(image.info)
    cache_preview_image(key, logo)
    return logo


def _draft_column(top, bottom, margin, ratio, height, align_right):
    """直接在草图尺寸摆放两行文字，不分配高分辨率虚拟底栏"""
    width = max(1, round(max(top.width, bottom.width, 10) * ratio))
    result = Image.new('RGBA', (width, height))
    for row, y in ((top, margin), (bottom, margin + top.height + 100)):
        size = max(1, round(row.width * ratio)), max(1, round(row.height * ratio))
        stamp = row.resize(size, Image.Resampling.BILINEAR)
        result.alpha_composite(stamp, (width - stamp.width if align_right else 0, round(y * ratio)))
        transfer_slots(stamp, result, (width - stamp.width if align_right else 0, round(y * ratio)))
    return result


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
    footer_height = max(1, round(_NORMAL_HEIGHT * image.width / virtual_width))
    draft = ctx.get('_interactive_preview', False)
    height = footer_height if draft else _NORMAL_HEIGHT
    sampling = Image.Resampling.BILINEAR if draft else Image.Resampling.LANCZOS
    gap = round(200 * height / _NORMAL_HEIGHT)
    background = ctx.get('color', 'white')
    luma = Image.new('RGBA', (1, 1), background).convert('L').getpixel((0, 0))
    options = logo_options(ctx)
    watermark = Image.new('RGBA', (image.width if draft else virtual_width, height), background)
    left_top, left_bottom, right_top, right_bottom = (
        _row_image(ctx.get(key)) for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom'))
    right_alignment = ctx.getenum('right_alignment', Alignment.RIGHT, Alignment)
    left_height = left_top.height + 100 + left_bottom.height
    right_height = right_top.height + 100 + right_bottom.height
    margin = int(max(left_height, right_height) * padding)
    if draft:
        ratio = height / (left_height + margin * 2)
        left = _draft_column(left_top, left_bottom, margin, ratio, height, False)
        right = _draft_column(right_top, right_bottom, margin, ratio, height, right_alignment == Alignment.RIGHT)
    else:
        left = _padding(_column(left_top, left_bottom, background), margin)
        right = _padding(_column(right_top, right_bottom, background, right_alignment == Alignment.RIGHT), margin, 't')
        right = _padding(right, left.height - right.height, 'b')
        left, right = _normalize(left), _normalize(right)

    left_logo = ctx.get('left_logo')
    right_logo = ctx.get('right_logo')
    center_logo = ctx.get('center_logo')
    center = _read_logo(center_logo, padding, luma, **options) if center_logo else None
    if center:
        max_width = watermark.width
        if ctx.get('fit_center_columns', False):
            max_width = max(1, round(watermark.width * .18))
        center = fit_logo(center, (max_width, height))
        center_x = (watermark.width - center.width) // 2
        tag_logo(center, ctx, 'center_logo')
        watermark.alpha_composite(center, (center_x, (height - center.height) // 2))
        transfer_slots(center, watermark, (center_x, (height - center.height) // 2))
    x = 0 if left_logo else gap
    if left_logo:
        x += round(.02 * height) + gap
        logo = _read_logo(left_logo, padding, luma, **options)
        if draft:
            logo = fit_logo(logo, (max(1, round(logo.width * height / logo.height)), height))
        tag_logo(logo, ctx, 'left_logo')
        watermark.alpha_composite(logo, (x, 0))
        transfer_slots(logo, watermark, (x, 0))
        x += logo.width + gap
    if center and ctx.get('fit_center_columns', False):
        available = max(1, center_x - x - gap)
        if left.width > available:
            left = ImageOps.contain(left, (available, height), sampling)
    watermark.alpha_composite(left, (x, (height - left.height) // 2))
    transfer_slots(left, watermark, (x, (height - left.height) // 2))

    x = watermark.width
    right_end = x - gap
    line = logo = None
    if right_logo:
        line = _padding(Image.new('RGBA', (20, _NORMAL_HEIGHT), ctx.get('delimiter_color', 'black')),
                        int(padding * _NORMAL_HEIGHT * .8))
        line, logo = _normalize(line, height, sampling), _read_logo(right_logo, padding, luma, **options)
        if draft:
            logo = fit_logo(logo, (max(1, round(logo.width * height / logo.height)), height))
        tag_logo(logo, ctx, 'right_logo')
    if center and ctx.get('fit_center_columns', False):
        occupied = (line.width + logo.width + 2 * gap) if right_logo else 0
        available = max(1, right_end - occupied - center_x - center.width - gap)
        if right.width > available:
            right = ImageOps.contain(right, (available, height), sampling)
    parts = [right] + ([line, logo] if right_logo else [])
    for part in parts:
        x -= part.width + gap
        watermark.alpha_composite(part, (x, (height - part.height) // 2))
        transfer_slots(part, watermark, (x, (height - part.height) // 2))

    footer = watermark if draft else watermark.resize((image.width, footer_height), Image.Resampling.HAMMING)
    left_margin = ctx.getint('left_margin', 0)
    top_margin = ctx.getint('top_margin', 0)
    canvas = legacy_base(image, ctx, footer_height, ctx.get('_frame_image_id'))
    canvas.alpha_composite(footer, (left_margin, top_margin + image.height))
    transfer_slots(footer, canvas, (left_margin, top_margin + image.height))
    if ctx.get('_logo_slot_keys'):
        canvas.info['_render_line_spacing'] = 100 * footer_height / (left_height + 2 * margin)
    return canvas
