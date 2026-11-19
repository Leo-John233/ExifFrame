"""供画框、底栏和内嵌标注共用的文字图层"""

import json
import math
from collections import OrderedDict

from PIL import Image, ImageDraw

from core.brand_glyphs import current_policy, node_glyph_policy
from core.font_fallback import (_font_cache_state, _font_token, _weight, font_at_size, load_font,
                                pooled_fonts, render_with_fallback)
from processor.core import _parse_color
from processor.generators import location_text_font, render_character_node


_TEXT_LIMIT = 16 * 1024 * 1024


def watermark_scale(ctx):
    scale = float(ctx.get('watermark_scale', 1.0))
    if not math.isfinite(scale) or not .5 <= scale <= 2:
        raise ValueError('水印整体大小需在 50% 到 200% 之间')
    return scale


def _font_at_size(path, size):
    """在独占槽位内复用对应字号"""
    return font_at_size(path, size)


@node_glyph_policy
@pooled_fonts()
def _segment_image(segment):
    """按旧版字形边界生成单个文字片段"""
    original = segment.get('text') or '   '
    path, text, location = location_text_font(original, segment.get('font_path') or segment.get('font'),
                                              segment.get('is_bold', False))
    primary = load_font(path)
    size = 260 if segment.get('is_bold', False) or _weight(primary) >= 600 else 240
    font = _font_at_size(path, size)
    original_font = _font_at_size(None, size) if location else None
    baseline = original_font.getmetrics()[0] if original_font is not None else font.getmetrics()[0]
    color = _parse_color(segment.get('color', 'black'))
    key = ('watermark_1521', _font_token(font), text, color, current_policy(),
           _font_token(original_font) if original_font is not None else None,
           original if original_font is not None else None)
    state = _font_cache_state()
    if not hasattr(state, 'text_images'):
        state.text_images = OrderedDict()
        state.text_bytes = 0
    cache = state.text_images
    if key in cache:
        cache.move_to_end(key)
        return cache[key][0].copy(), baseline

    drawing = text.replace('ℤ', 'Z') if current_policy() == 'plain_z' else text
    image = render_with_fallback(drawing, font, lambda fallback: _font_at_size(fallback, size), color)
    primary_font = image is None
    can_cache = primary_font or image.info.get('_font_fallback_used') is False
    if image is not None and original_font is None and current_policy() == 'system' and 'ℤ' in text:
        baseline = image.info.get('_fallback_baseline', baseline)
    layout = text
    if 'ℤ' in text and current_policy() != 'system':
        layout = text.replace('ℤ', 'Z')
    if '\n' in layout:
        probe = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
        bounds = probe.multiline_textbbox((0, 0), layout, font=font)
    else:
        bounds = font.getbbox(layout)
    if primary_font:
        width = max(1, bounds[2] - bounds[0])
        height = max(1, bounds[3])
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(image).text((0, 0), drawing, font=font, fill=color)
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
        while cache and (state.text_bytes + cost > _TEXT_LIMIT or len(cache) >= 64):
            _, (_, old_cost) = cache.popitem(last=False)
            state.text_bytes -= old_cost
        cache[key] = (image.copy(), cost)
        state.text_bytes += cost
    return image, baseline


@node_glyph_policy
def render_text_row(node):
    """按连续字形和共同基线生成一行透明文字"""
    styled = render_character_node(node, watermark=True)
    if styled is not None:
        return styled[0]
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
