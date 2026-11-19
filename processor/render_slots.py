"""随实际像素合成传递槽位边界和有效样式，坐标始终相对于所在图像"""

import json
from pathlib import Path

SLOTS_KEY = '_render_slots'
TEXT_KINDS = {'rich_text', 'multi_rich_text', 'watermark_with_timestamp'}


def effective_text(node):
    """槽位覆写高于全局样式，单字规则仍由文字渲染器最后叠加"""
    result = dict(node or {})
    if result.get('_slot_style_applied'):
        return result
    style = result.get('slot_style') or {}
    if not isinstance(style, dict):
        style = {}
    if style and '_slot_base' not in result:
        result['_slot_base'] = {key: value for key, value in result.items()
                                if key in {'processor_name', 'text', 'text_segments', 'font_path', 'font',
                                           'color', 'height', 'height_ratio', 'is_bold', '_slot_key'}}
    if style:
        result['_slot_style_applied'] = True
    result.update({key: value for key, value in style.items()
                   if key in {'font_path', 'color', 'height', 'height_ratio', 'visible'} and value is not None})
    if 'text_segments' in result:
        segments = result['text_segments']
        if isinstance(segments, str):
            segments = json.loads(segments)
        if isinstance(segments, list) and style:
            overrides = {key: style[key] for key in ('font_path', 'color') if style.get(key) is not None}
            result['text_segments'] = [{**segment, **overrides} for segment in segments]
    return result


def prepare_slots(nodes):
    """复用编辑器的稳定区域标识，嵌套子管线不重新编号"""
    from core.footer import text_targets
    _, targets = text_targets(nodes)
    for key, _, _, node in targets:
        if node:
            node.setdefault('_slot_key', key)
    number = 0
    for node in nodes:
        if node.get('processor_name') == 'watermark':
            number += 1
            prefix = '' if number == 1 else f'watermark_{number}_'
            node.setdefault('_logo_slot_keys', {name: prefix + name for name in
                                               ('left_logo', 'center_logo', 'right_logo')})


def _color(value):
    try:
        from processor.core import _parse_color
        rgba = _parse_color(value)
        return '#' + ''.join(f'{v:02X}' for v in (rgba[:3] if rgba[3] == 255 else rgba))
    except (ValueError, TypeError):
        return str(value)


def text_record(node, image):
    from core.brand_glyphs import current_policy
    from processor.generators import _rendered_segments, rendered_text, location_text_font
    segments = _rendered_segments(node)
    fonts, colors = [], []
    for segment, _ in segments or [(node, '')]:
        font, _, _ = location_text_font(segment.get('text', ''),
                                       segment.get('font_path') or segment.get('font'), segment.get('is_bold', False))
        from core.font_fallback import load_font, pooled_fonts
        with pooled_fonts():
            actual = load_font(font)
            font = getattr(actual, 'path', '')
            if not isinstance(font, (str, bytes, Path)):
                font = 'Pillow default'
        fonts.append(Path(str(font)).name)
        colors.append(_color(segment.get('color', node.get('color', 'black'))))
    visible = node.get('visible', True) is not False
    bounds = image.getchannel('A').getbbox() if 'A' in image.getbands() and visible else None
    height = float(node.get('height', image.height))
    result = {'key': node['_slot_key'], 'kind': 'text', 'text': rendered_text(node),
            'font': fonts[0] if len(set(fonts)) == 1 else ' / '.join(dict.fromkeys(fonts)),
            'color': colors[0] if len(set(colors)) == 1 else ' / '.join(dict.fromkeys(colors)),
            'visible': visible, 'brand_glyph_policy': node.get('brand_glyph_policy') or current_policy(),
            '_font_ratio': height / image.height,
            'bbox': ([bounds[0] / image.width, bounds[1] / image.height,
                      bounds[2] / image.width, bounds[3] / image.height] if bounds else None)}
    base = node.get('_slot_base')
    if base and base.get('_slot_key'):
        details = text_record(base, image)
        result.update(base_font=details['font'], base_color=details['color'])
    return result


def tag_text(image, node):
    """在缓存返回副本上附加信息，隐藏文字保留排版占位"""
    if node.get('_slot_key'):
        image.info[SLOTS_KEY] = [text_record(node, image)]
    if node.get('visible', True) is False:
        image.putalpha(0)
    return image


def tag_logo(image, ctx, slot):
    key = (ctx.get('_logo_slot_keys') or {}).get(slot)
    if key:
        bounds = image.getchannel('A').getbbox() if 'A' in image.getbands() else (0, 0, *image.size)
        image.info[SLOTS_KEY] = [{'key': key, 'kind': 'logo', 'visible': True, 'logo': ctx.get(slot),
                                 'bbox': ([bounds[0] / image.width, bounds[1] / image.height,
                                           bounds[2] / image.width, bounds[3] / image.height] if bounds else None)}]
    return image


def transfer_slots(source, target, offset=(0, 0), size=None, *, replace=False):
    """使用同一次合成的偏移和缩放矩阵传播边界，裁去画布外部分"""
    records = source.info.get(SLOTS_KEY)
    if not records:
        if replace:
            target.info.pop(SLOTS_KEY, None)
        return target
    width, height = size or source.size
    dx, dy = offset
    transformed = []
    for record in records:
        item = dict(record)
        if item.get('bbox'):
            l, t, r, b = item['bbox']
            l, t, r, b = ((l * width + dx) / target.width, (t * height + dy) / target.height,
                          (r * width + dx) / target.width, (b * height + dy) / target.height)
            item['bbox'] = [max(0, l), max(0, t), min(1, r), min(1, b)] if r > 0 and b > 0 and l < 1 and t < 1 else None
        if '_font_ratio' in item:
            item['_font_ratio'] *= height / target.height
        transformed.append(item)
    target.info[SLOTS_KEY] = ([] if replace else list(target.info.get(SLOTS_KEY, []))) + transformed
    return target


def crop_slots(image, box):
    result = image.crop(box)
    return transfer_slots(image, result, (-box[0], -box[1]), replace=True)


def finish_slots(image, full_size):
    """对外只发布原图逻辑字号和归一化边界，避免 LOD 改变检查器数值"""
    result = []
    for record in image.info.get(SLOTS_KEY, []):
        item = dict(record)
        ratio = item.pop('_font_ratio', None)
        if ratio is not None:
            item['font_size'] = round(ratio * full_size[1], 2)
        result.append(item)
    return result


def complete_slots(nodes, image):
    """保留隐藏或空白槽位的属性，使检查器仍能恢复显示"""
    from PIL import Image
    from core.footer import text_targets
    present = {item['key'] for item in image.info.get(SLOTS_KEY, [])}
    extra = []
    _, targets = text_targets(nodes)
    for key, _, _, node in targets:
        if key not in present and node and node.get('_slot_key'):
            details = text_record(effective_text(node), Image.new('RGBA', (1, 1)))
            details.pop('_font_ratio', None)
            extra.append(details)
    for node in nodes:
        for name, key in (node.get('_logo_slot_keys') or {}).items():
            if key not in present:
                style = (node.get('logo_styles') or {}).get(name) or {}
                extra.append({'key': key, 'kind': 'logo', 'logo': node.get(name), 'bbox': None,
                              'visible': bool(node.get(name)) and style.get('visible') is not False})
    image.info[SLOTS_KEY] = list(image.info.get(SLOTS_KEY, [])) + extra
