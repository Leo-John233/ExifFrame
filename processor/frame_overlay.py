"""在安全文字区域内排布文字、品牌标识、分隔线和主色色卡"""

import json
import math
from dataclasses import dataclass, replace

from PIL import Image, ImageDraw, ImageFilter

from core.image_cache import dominant_palette
from processor.core import get_processor
from processor.logo_layer import adaptive_logo, layer_logo
from processor.text_layers import render_text_row, watermark_scale
from processor.render_slots import crop_slots, effective_text, tag_logo, transfer_slots


@dataclass(frozen=True)
class Layer:
    kind: str
    box: tuple[float, float, float, float]
    bitmap: Image.Image | None = None
    text_node: dict | None = None


def _size(box):
    return box[2] - box[0], box[3] - box[1]


def _ink_node(node, ink):
    """先解析段落默认色，再由文字渲染器叠加规则和单字强调色"""
    result = dict(node)
    color = node.get('color', 'auto')
    result['color'] = ink if color == 'auto' else color
    if 'text_segments' in result:
        segments = result['text_segments']
        if isinstance(segments, str):
            segments = json.loads(segments)
        defaults = {key: result[key] for key in ('color', 'font_path', 'font', 'is_bold') if key in result}
        result['text_segments'] = []
        for segment in segments:
            part = {**defaults, **segment}
            if part['color'] == 'auto':
                part['color'] = ink
            result['text_segments'].append(part)
        adaptable = any(segment.get('color', color) == 'auto' for segment in segments)
    else:
        adaptable = color == 'auto'
    return result, adaptable


def _text_bitmap(node, ink):
    prepared, adaptable = _ink_node(node, ink)
    image = render_text_row(prepared)
    bounds = image.getchannel('A').getbbox() or image.info.get('_hidden_text_bounds')
    if not bounds:
        return None, adaptable
    image = crop_slots(image, bounds)
    for item in image.info.get('_render_slots', []):
        item['_font_ratio'] = 1.0
    return image, adaptable


def _text_layer(node, unit, default_height, scale):
    if not node:
        return None
    node = effective_text(node)
    image, adaptable = _text_bitmap(node, '#202124')
    if image is None:
        return None
    height = (float(node['height']) if (node.get('slot_style') or {}).get('height') is not None else
              unit * float(node.get('height_ratio', default_height))) * scale
    if height <= 0:
        return None
    width = height * image.width / image.height
    return Layer('text', (0, 0, width, height), image, node if adaptable else None)


def _logo_layer(path, unit, scale):
    if not path or path == 'None':
        return None
    w, h = unit * .13 * scale, unit * .047 * scale
    badge = layer_logo(path, (max(1, round(w)), max(1, round(h))))
    factor = min(w / badge.width, h / badge.height)
    return Layer('logo', (0, 0, badge.width * factor, badge.height * factor), badge)


def _move(layer, x, y, scale=1):
    a, b, c, d = layer.box
    return replace(layer, box=(x + a * scale, y + b * scale, x + c * scale, y + d * scale))


def _extent(group):
    return max((p.box[2] for p in group), default=0), max((p.box[3] for p in group), default=0)


def _stack(lines, align, gap):
    width = max((p.box[2] for p in lines), default=0)
    y, result = 0, []
    for line in lines:
        x = (width - line.box[2]) * align
        result.append(_move(line, x, y))
        y += line.box[3] + gap
    return result


def _beside(groups, gap):
    sizes = [_extent(group) for group in groups]
    height = max((h for _, h in sizes), default=0)
    x, result = 0, []
    for group, (width, h) in zip(groups, sizes):
        if group:
            result.extend(_move(layer, x, (height - h) / 2) for layer in group)
            x += width + gap
    return result


def _fit(group, box, align):
    width, height = _extent(group)
    room_w, room_h = _size(box)
    if not width or not height or room_w <= 0 or room_h <= 0:
        return []
    scale = min(1, room_w / width, room_h / height)
    x, y = box[0] + (room_w - width * scale) * align, box[1] + (room_h - height * scale) / 2
    return [_move(layer, x, y, scale) for layer in group]


def _caption_area(ctx, layout):
    unit = layout['unit']
    left, top, right, bottom = layout['caption_box']
    inset = layout['inset_overlay']
    anchor = ctx.get('inset_anchor', 'bottom_right') if inset else 'bottom'
    if inset:
        band = min(bottom - top, .16 * unit)
        if anchor.startswith('top'):
            bottom = top + band
        else:
            top = bottom - band
        if anchor.endswith(('_left', '_right')):
            width = min(right - left, max(.68 * (right - left), .86 * unit))
            if anchor.endswith('_right'):
                left = right - width
            else:
                right = left + width

    return (left, top, right, bottom), anchor


def _palette_and_caption(box, unit):
    left, top, right, bottom = box
    bottom -= min(unit * .016, (bottom - top) * .08)
    height = min(unit * .028, (bottom - top) * .23)
    palette = left, bottom - height, right, bottom
    return palette, (left, top, right, bottom - height - min(unit * .014, (bottom - top) * .08))


def palette_box_for(ctx, layout):
    box, _ = _caption_area(ctx, layout)
    return _palette_and_caption(box, layout['unit'])[0]


def plan_overlay(ctx, layout):
    """以浮点坐标规划图层，落到画布时才舍入像素边界"""
    unit = layout['unit']
    inset = layout['inset_overlay']
    box, anchor = _caption_area(ctx, layout)
    anchor_align = 0 if anchor.endswith('_left') else 1 if anchor.endswith('_right') else .5
    layers = []
    if ctx.get('palette_bar'):
        palette, box = _palette_and_caption(box, unit)
        if not ctx.get('_skip_legacy_palette_paint'):
            layers.append(Layer('palette', palette))
    left, top, right, bottom = box
    gap = .021 * unit
    line_gap = max(0, float(ctx.get('middle_spacing', .012 * unit)))
    scale = watermark_scale(ctx)
    lines = {}
    for name in ('left_top', 'left_bottom', 'right_top', 'right_bottom'):
        node = ctx.get(name)
        if node and 'color' not in node and ctx.get('text_color'):
            node = {**node, 'color': ctx['text_color']}
        line = _text_layer(node, unit, .029 if name.endswith('top') else .019, scale)
        if line:
            lines[name] = line
    logos = {}
    for slot in ('left', 'center', 'right'):
        logo = _logo_layer(ctx.get(slot + '_logo'), unit, scale)
        if logo:
            tag_logo(logo.bitmap, ctx, slot + '_logo')
        logos[slot] = [logo] if logo else []
    if ctx.get('caption_layout') == 'centered':
        column = _stack(list(lines.values()), .5, line_gap)
        group = _beside([logos['left'], logos['center'], column, logos['right']], gap)
        return layers + _fit(group, box, anchor_align)

    right_align = 0 if ctx.get('right_alignment') == 'left' else 1
    cols = [_stack([line for name, line in lines.items() if name.startswith(side)], align, line_gap)
            for side, align in (('left', 0), ('right', right_align))]
    group_l = _beside([logos['left'], cols[0]], gap)
    group_r = _beside([cols[1], logos['right']], gap)
    middle = logos['center']
    if not (group_l and group_r):
        grouped = _beside([group_l, middle, group_r], gap)
        align = anchor_align if inset or not (group_l or group_r) else float(bool(group_r))
        return layers + _fit(grouped, box, align)

    if inset and anchor != 'bottom':
        line = [Layer('divider', (0, 0, unit * .0022, unit * .075))] if ctx.get('divider') else []
        block = _beside([group_l, middle, line, group_r], gap)
        return layers + _fit(block, box, anchor_align)

    mid = (left + right) / 2
    center = _fit(middle, (mid - (right-left)*.1, top, mid + (right-left)*.1, bottom), .5)
    left_edge = center[0].box[0] if center else mid
    right_edge = center[0].box[2] if center else mid
    if ctx.get('divider'):
        position = right_edge + gap * .5 if center else mid
        height = min((bottom - top) * .66, unit * .075)
        cy = (top + bottom) / 2
        thickness = unit * .0022
        layers.append(Layer('divider', (position, cy - height / 2,
                                        position + thickness, cy + height / 2)))
        right_edge = position + thickness
    return (layers + _fit(group_l, (left, top, left_edge - gap/2, bottom), 0) + center
            + _fit(group_r, (right_edge + gap/2, top, right, bottom), 1))


def _luma(canvas, box):
    return canvas.resize((1, 1), Image.Resampling.BOX, box=box).convert('L').getpixel((0, 0))


def _divider(canvas, box, color):
    """按像素覆盖率绘制细线，缩小预览时保留不足一像素的笔画"""
    left, top, right, bottom = box
    x, y = max(0, math.floor(left)), max(0, round(top))
    end, base = min(canvas.width, math.ceil(right)), min(canvas.height, round(bottom))
    if end <= x or base <= y:
        return
    ink = color or ('#DADAD6' if _luma(canvas, (x, y, end, base)) < 128 else '#878883')
    strip = Image.new('RGBA', (end-x, base-y), ink)
    alpha = strip.getpixel((0, 0))[3]
    coverage = Image.new('L', (end-x, 1))
    coverage.putdata([round(alpha * (min(i+1, right) - max(i, left))) for i in range(x, end)])
    strip.putalpha(coverage.resize(strip.size, Image.Resampling.NEAREST))
    canvas.alpha_composite(strip, (x, y))


def _stamp(canvas, stamp, box, opacity, shadow, sampling):
    x, y = box[:2]
    if stamp.size != _size(box):
        stamp = stamp.resize(_size(box), sampling)
    if opacity < 1:
        stamp = stamp.copy()
        stamp.putalpha(stamp.getchannel('A').point(lambda a: round(a * opacity)))
        if opacity <= 0:
            stamp.info['_render_slots'] = [{**item, 'bbox': None} for item in stamp.info.get('_render_slots', [])]
    if shadow > 0:
        pad = max(1, round(shadow * 3))
        mask = Image.new('L', (stamp.width + pad*2, stamp.height + pad*2))
        mask.paste(stamp.getchannel('A'), (pad, pad))
        shade = Image.new('RGBA', mask.size)
        shade.putalpha(mask.filter(ImageFilter.GaussianBlur(shadow)).point(lambda a: a * .44))
        canvas.alpha_composite(shade, (x - pad, y - pad + round(shadow)))
    canvas.alpha_composite(stamp, (x, y))
    transfer_slots(stamp, canvas, (x, y))


def draw_overlay(canvas, source, ctx, layout, image_id):
    """在独立底板副本上合成色卡、文字和标识"""
    inset = layout['inset_overlay']
    opacity = min(1, max(0, float(ctx.get('overlay_opacity', .92 if inset else 1))))
    shadow = layout['unit'] * .0018 if inset else 0
    sampling = Image.Resampling.BILINEAR if ctx.get('_interactive_preview') else Image.Resampling.LANCZOS
    for layer in plan_overlay(ctx, layout):
        if layer.kind == 'divider':
            _divider(canvas, layer.box, ctx.get('delimiter_color'))
            continue
        l, t, r, b = (round(value) for value in layer.box)
        box = max(0, l), max(0, t), min(canvas.width, r), min(canvas.height, b)
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        if layer.kind == 'palette':
            colors = dominant_palette(source, image_id)
            draw = ImageDraw.Draw(canvas)
            for index, color in enumerate(colors):
                a = box[0] + round(index * (box[2] - box[0]) / len(colors))
                z = box[0] + round((index + 1) * (box[2] - box[0]) / len(colors))
                if z > a:
                    draw.rectangle((a, box[1], z - 1, box[3] - 1), fill=color)
        elif layer.kind == 'logo':
            stamp = layer.bitmap
            if ctx.get('adaptive_logo_invert'):
                stamp = adaptive_logo(stamp, _luma(canvas, box))
            _stamp(canvas, stamp, box, opacity, shadow, sampling)
        else:
            stamp = layer.bitmap
            if layer.text_node is not None and _luma(canvas, box) < 128:
                stamp, _ = _text_bitmap(layer.text_node, '#FAFAF8')
            if stamp is not None:
                if stamp.info.get('_render_slots'):
                    ink = '#FAFAF8' if _luma(canvas, box) < 128 else '#202124'
                    stamp.info['_render_slots'] = [
                        {**item, 'base_color': item.get('base_color', item.get('color', ink)).replace('auto', ink)}
                        for item in stamp.info['_render_slots']]
                _stamp(canvas, stamp, box, opacity, shadow, sampling)
    return canvas


def draw_timestamp(source, ctx):
    """兼容既有时间戳模板的文字图层和像素锚点"""
    if 'height' not in ctx:
        ctx.set('height', int(source.height * .02))
    renderer = get_processor('multi_rich_text')
    if renderer is None:
        raise RuntimeError('multi_rich_text processor not found')
    renderer().process(ctx)
    text = ctx.get_buffer()[0]
    position = int(source.width * .93) - text.width, int(source.height * .95)
    source.paste(text, position, mask=text)
    transfer_slots(text, source, position)
    return source
