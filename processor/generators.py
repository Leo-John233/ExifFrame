import os.path
import json
import sys
from collections import OrderedDict
from abc import ABC
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List

import numpy as np
from PIL import Image, ImageDraw

from core.configs import fonts_dir
from core.font_fallback import (BASE_FONT_SIZE, TextRun, _font_cache_state, _font_token, _weight,
                                font_at_size, load_font, pooled_fonts, render_styled_runs,
                                render_with_fallback)
from core.geography import location_typography
from processor.core import PipelineContext, ImageProcessor, Direction, _parse_color

def location_text_font(text: str, font_path: str | None, is_bold: bool):
    """仅在轻体字体可用且未指定字体时调整完整地理行"""
    location = location_typography(text)
    if location is None:
        return font_path, text, False
    if font_path is not None or is_bold:
        return font_path, location, False
    target = fonts_dir / 'Roboto-Light.ttf'
    if not target.is_file():
        return font_path, location, False
    try:
        selected = load_font('Roboto-Light.ttf')
        loaded_path = getattr(selected, 'path', None)
        if isinstance(loaded_path, (str, Path)) and Path(loaded_path).resolve() == target.resolve():
            return 'Roboto-Light.ttf', location, True
    except (OSError, RuntimeError, ValueError):
        pass
    return font_path, location, False


def _rendered_segments(node):
    """读取渲染后的片段并保留地理坐标的实际空格"""
    if node.get('processor_name') == 'rich_text':
        segments = [node]
    else:
        segments = node.get('text_segments') or []
        if isinstance(segments, str):
            segments = json.loads(segments)
    result = []
    for segment in segments:
        text = segment.get('text') or ''
        formatted = location_typography(text) if text else None
        result.append((segment, formatted if formatted is not None else text))
    return result


def rendered_text(node):
    """返回可编辑的完整文本，不计内部空片段占位"""
    return ''.join(text for _, text in _rendered_segments(node))


def _style_input(value):
    return json.loads(value) if isinstance(value, str) else value


def _styled_segments(node, segments, whole_rules, whole_chars):
    """保持原有分段缩放及对齐，逐段绘制整行索引对应的样式"""
    from core.character_styles import resolve_character_styles
    from processor.core import start_process

    height = int(node.get('height', 100))
    offset, resolved, changed = 0, [], False
    for segment, displayed in segments:
        segment_rules = resolve_character_styles(displayed, None, _style_input(segment.get('highlight_rules')))
        segment_chars = resolve_character_styles(displayed, _style_input(segment.get('char_styles')), None)
        path = segment.get('font_path') or segment.get('font') or node.get('font_path') or node.get('font')
        color = _parse_color(segment.get('color', node.get('color', 'black')))
        overrides = {}
        for index in range(len(displayed)):
            style = {**segment_rules[index], **whole_rules[offset + index],
                     **segment_chars[index], **whole_chars[offset + index]}
            if style:
                overrides[str(index)] = style
                changed |= (style.get('font', path) != path or
                            _parse_color(style.get('color', color)) != color)
        resolved.append(TextSegment(
            text=segment.get('text'), font_path=path, height=height,
            is_bold=segment.get('is_bold', node.get('is_bold', False)),
            color=segment.get('color', node.get('color', 'black')),
            trim=segment.get('trim', node.get('trim', False)), char_styles=overrides or None))
        offset += len(displayed)
    if not changed:
        return None
    spacing = int(node.get('text_spacing') or 0)
    groups = []
    for segment, (_, displayed) in zip(resolved, segments):
        original = segment.text or ''
        compatible = bool(groups and not spacing and original and displayed == original)
        if compatible:
            previous = groups[-1][-1]
            previous_text = previous.text or ''
            compatible = (previous_text and location_typography(previous_text) is None
                          and previous.font_path == segment.font_path and previous.is_bold == segment.is_bold
                          and previous.trim == segment.trim and _parse_color(previous.color)[3] == 255
                          and _parse_color(segment.color)[3] == 255)
        if compatible:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    images = []
    for group in groups:
        if len(group) == 1 or not any(segment.char_styles for segment in group):
            images.extend(RichTextGenerator.generate(segment) for segment in group)
            continue
        first = group[0]
        first_color = _parse_color(first.color)
        merged, index = {}, 0
        for segment in group:
            segment_color = _parse_color(segment.color)
            for position in range(len(segment.text or '')):
                override = {}
                if segment_color != first_color:
                    override['color'] = '#%02X%02X%02X' % segment_color[:3]
                override.update((segment.char_styles or {}).get(str(position), {}))
                if override:
                    merged[str(index)] = override
                index += 1
        combined = TextSegment(text=''.join(segment.text or '' for segment in group),
                               font_path=first.font_path, height=height, is_bold=first.is_bold,
                               color=first.color, trim=first.trim, char_styles=merged or None)
        images.append(RichTextGenerator.generate(combined))
    result = start_process([{'processor_name': 'concat', 'alignment': node.get('text_alignment'),
                             'spacing': spacing, 'save_buffer': False}],
                           initial_buffer=images)
    return result, 0


@pooled_fonts()
def render_character_node(node, *, watermark=False):
    """把整行和片段的逐字样式合并为共享基线的文字图"""
    if not node.get('char_styles') and not node.get('highlight_rules'):
        raw = node.get('text_segments') or []
        if isinstance(raw, str):
            if 'char_styles' not in raw and 'highlight_rules' not in raw:
                return None
        elif not any(segment.get('char_styles') or segment.get('highlight_rules') for segment in raw):
            return None
    from core.character_styles import resolve_character_styles
    segments = _rendered_segments(node)
    if not (node.get('char_styles') or node.get('highlight_rules') or
            any(segment.get('char_styles') or segment.get('highlight_rules') for segment, _ in segments)):
        return None
    text = ''.join(value for _, value in segments)
    if not text:
        return None
    whole_rules = resolve_character_styles(text, None, _style_input(node.get('highlight_rules')))
    whole_chars = resolve_character_styles(text, _style_input(node.get('char_styles')), None)
    if node.get('processor_name') != 'rich_text' and not watermark:
        has_font = any(style.get('font') for style in (*whole_rules, *whole_chars))
        if not has_font:
            for segment, displayed in segments:
                segment_styles = resolve_character_styles(displayed, _style_input(segment.get('char_styles')),
                                                           _style_input(segment.get('highlight_rules')))
                if any(style.get('font') for style in segment_styles):
                    has_font = True
                    break
        if not has_font:
            return _styled_segments(node, segments, whole_rules, whole_chars)
    offset, runs, changed, fonts, weights = 0, [], False, {}, {}
    height = max(1, int(node.get('height', 100)))
    spacing = max(0, int(node.get('text_spacing') or 0))
    multiple = node.get('processor_name') != 'rich_text'
    any_bold = any(segment.get('is_bold', node.get('is_bold', False)) for segment, _ in segments)
    for segment_index, (segment, displayed) in enumerate(segments):
        if not displayed:
            continue
        original = segment.get('text') or ''
        bold = segment.get('is_bold', node.get('is_bold', False))
        base_path = segment.get('font_path') or segment.get('font') or node.get('font_path') or node.get('font')
        path, _, _ = location_text_font(original, base_path, bold)
        color = _parse_color(segment.get('color', node.get('color', 'black')))
        if multiple:
            segment_rules = resolve_character_styles(displayed, None, _style_input(segment.get('highlight_rules')))
            segment_chars = resolve_character_styles(displayed, _style_input(segment.get('char_styles')), None)
        else:
            segment_rules = segment_chars = [{} for _ in displayed]
        for index, character in enumerate(displayed):
            overlay = {**segment_rules[index], **whole_rules[offset + index],
                       **segment_chars[index], **whole_chars[offset + index]}
            selected_path = overlay.get('font', path)
            selected_color = _parse_color(overlay.get('color', color))
            changed |= selected_path != path or selected_color != color
            if watermark:
                primary_key = (selected_path, BASE_FONT_SIZE)
                if primary_key not in fonts:
                    fonts[primary_key] = load_font(selected_path)
                    weights[primary_key] = _weight(fonts[primary_key])
                size = 260 if bold or weights[primary_key] >= 600 else 240
            else:
                size = round(BASE_FONT_SIZE * 1.13) if bold else BASE_FONT_SIZE
            key = (selected_path, size)
            if key not in fonts:
                fonts[key] = font_at_size(selected_path, size)
            font = fonts[key]
            gap = (spacing * BASE_FONT_SIZE / height if multiple and segment_index and index == 0 else 0)
            if runs and runs[-1].font is font and runs[-1].color == selected_color and not gap:
                old = runs[-1]
                runs[-1] = TextRun(old.text + character, font, selected_color, old.spacing_before)
            else:
                runs.append(TextRun(character, font, selected_color, gap))
        offset += len(displayed)
    if not changed:
        return None
    target = round(height * 1.13) if any_bold else height
    trim = bool(node.get('trim')) or any(segment.get('trim', False) for segment, _ in segments)
    key = ('character_text', watermark, tuple((run.text, _font_token(run.font), run.color, run.spacing_before)
                                              for run in runs), target, trim)
    state = _font_cache_state()
    if not hasattr(state, 'text_images'):
        state.text_images, state.text_bytes = OrderedDict(), 0
    cache = state.text_images
    if key in cache:
        cache.move_to_end(key)
        image = cache[key][0].copy()
        return image, image.info['_text_baseline']
    image, baseline, fallback = render_styled_runs(runs, tight=watermark)
    if not watermark:
        from processor.core import start_process
        image = start_process([
            {'processor_name': 'trim', 'trim_top': trim, 'trim_bottom': trim, 'save_buffer': False},
            {'processor_name': 'resize', 'height': target, 'save_buffer': False},
        ], initial_buffer=[image])
        baseline = 0
    image.info['_text_baseline'] = baseline
    cost = image.width * image.height * 4 + len(text) * 4
    if not fallback and cost <= 16 * 1024 * 1024:
        while cache and (state.text_bytes + cost > 16 * 1024 * 1024 or len(cache) >= 64):
            _, (_, old_cost) = cache.popitem(last=False)
            state.text_bytes -= old_cost
        cache[key] = (image.copy(), cost)
        state.text_bytes += cost
    return image, baseline


@dataclass
class TextSegment:
    text: str
    font_path: Optional[str] = None
    height: int = 100
    is_bold: bool = False
    color: str = "black"
    trim: bool = False
    char_styles: dict | None = None
    highlight_rules: list | None = None

    def get(self, key: str, default=None):
        return getattr(self, key, default)

    @staticmethod
    def from_dict(data: dict):
        return TextSegment(
            text=data.get("text"),
            font_path=data.get("font_path") or data.get("font"),
            height=int(data.get("height", 100)),
            color=data.get("color", "black"),
            is_bold=data.get("is_bold", False),
            trim=data.get("trim", False),
            char_styles=data.get("char_styles"),
            highlight_rules=data.get("highlight_rules"),
        )

    @staticmethod
    def from_dicts(data: List[dict]):
        return [TextSegment.from_dict(datum) for datum in data]


class Generator(ImageProcessor, ABC):

    def category(self) -> str:
        return "generator"


class SolidColorGenerator(Generator):

    def process(self, ctx: PipelineContext):
        width, height = ctx.getint("width"), ctx.getint("height")
        color = ctx.get("color")
        image = Image.new("RGBA", (width, height), color)
        ctx.update_buffer([image]).success()

    def name(self) -> str:
        return "solid_color"


class InterpolateMethod(Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"


# ============ 缓动函数（处理 t 值）============
def _easing_linear(t: np.ndarray) -> np.ndarray:
    """线性"""
    return t


def _easing_ease_in(t: np.ndarray) -> np.ndarray:
    """缓入"""
    return t * t


def _easing_ease_out(t: np.ndarray) -> np.ndarray:
    """缓出"""
    return 1 - (1 - t) ** 2


def _easing_ease_in_out(t: np.ndarray) -> np.ndarray:
    """缓入缓出"""
    return np.where(t < 0.5, 2 * t * t, 1 - (-2 * t + 2) ** 2 / 2)


EASING_FUNCTIONS = {
    InterpolateMethod.LINEAR: _easing_linear,
    InterpolateMethod.EASE_IN: _easing_ease_in,
    InterpolateMethod.EASE_OUT: _easing_ease_out,
    InterpolateMethod.EASE_IN_OUT: _easing_ease_in_out,
}


# ============ NumPy 加速绘制 ============
def _draw_gradient_numpy(
        width: int,
        height: int,
        start_rgba: tuple,
        end_rgba: tuple,
        direction: Direction,
        method: InterpolateMethod = InterpolateMethod.LINEAR
) -> Image.Image:
    """NumPy 加速的渐变绘制"""

    x = np.arange(width)
    y = np.arange(height)
    xx, yy = np.meshgrid(x, y)

    # 计算进度 t
    if direction == Direction.HORIZONTAL:
        t = xx / (width - 1) if width > 1 else np.zeros_like(xx, dtype=float)
    elif direction == Direction.VERTICAL:
        t = yy / (height - 1) if height > 1 else np.zeros_like(yy, dtype=float)
    elif direction == Direction.DIAGONAL:
        t = (xx + yy) / (width + height - 2) if (width + height) > 2 else np.zeros_like(xx, dtype=float)
    elif direction == Direction.RADIAL:
        cx, cy = width / 2, height / 2
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        max_dist = np.sqrt(cx ** 2 + cy ** 2)
        t = np.clip(dist / max_dist, 0, 1)
    else:
        t = np.zeros((height, width), dtype=float)

    # 应用缓动函数
    easing_func = EASING_FUNCTIONS.get(method, _easing_linear)
    t = easing_func(t.astype(float))

    # 向量化颜色插值
    start = np.array(start_rgba, dtype=float)
    end = np.array(end_rgba, dtype=float)

    # 扩展维度 (height, width) -> (height, width, 1)
    t = t[:, :, np.newaxis]

    # 插值计算
    pixels = start + (end - start) * t
    pixels = np.clip(pixels, 0, 255).astype(np.uint8)

    return Image.fromarray(pixels, mode='RGBA')


class GradientColorGenerator(Generator):
    def process(self, ctx: PipelineContext):
        width, height = ctx.get("width"), ctx.get("height")
        start_color = ctx.get("start_color")
        end_color = ctx.get("end_color")
        direction = ctx.getenum("direction", Direction.HORIZONTAL, Direction)  # horizontal, vertical, diagonal
        method = ctx.getenum("interpolate_method", InterpolateMethod.LINEAR, InterpolateMethod)

        start_rgba = _parse_color(start_color)
        end_rgba = _parse_color(end_color)

        image = _draw_gradient_numpy(
            width, height,
            start_rgba, end_rgba,
            direction, method
        )

        ctx.update_buffer([image]).save_buffer(self.name()).success()

    def name(self) -> str:
        return "gradient_color"


class RichTextGenerator(Generator):
    @staticmethod
    @pooled_fonts()
    def generate(segment: TextSegment) -> Image.Image:
        if segment.char_styles or segment.highlight_rules:
            styled = render_character_node({'processor_name': 'rich_text', **asdict(segment)})
            if styled is not None:
                return styled[0]
        text = ' ' if not segment.text or segment.text == '' else segment.text
        path, text, _ = location_text_font(text, segment.font_path, segment.is_bold)
        font = load_font(path)
        color = _parse_color(segment.color)
        key = (_font_token(font), text, segment.height, segment.is_bold, color, segment.trim)
        state = _font_cache_state()
        if not hasattr(state, 'text_images'):
            state.text_images = OrderedDict()
            state.text_bytes = 0
        cache = state.text_images
        if key in cache:
            cache.move_to_end(key)
            return cache[key][0].copy()

        # 普通文字保持原有绘制方式，缺字时继续执行字体回退
        metrics = font.getmetrics()
        image = render_with_fallback(text, font, load_font, color)
        can_cache = image is None
        if can_cache:
            bbox = font.getbbox(text)
            image = Image.new('RGBA', (int(bbox[2] - bbox[0]), metrics[0] + abs(metrics[1])), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.text((0, 0), text, font=font, fill=color)

        pipeline = [
            {
                "processor_name": "trim",
                "trim_top": segment.trim,
                "trim_bottom": segment.trim,
                "save_buffer": False,
            },
            {
                "processor_name": "resize",
                "height": segment.height * 1.13 if segment.is_bold else segment.height,
                "save_buffer": False,
            }
        ]
        from processor.core import start_process
        result = start_process(pipeline, input_path=None, output_path=None, initial_buffer=[image])
        # 限制每个槽位的像素缓存，字体回退结果不缓存以反映系统字体变化
        cost = result.width * result.height * len(result.getbands()) + len(text) * 4
        if can_cache and cost <= 16 * 1024 * 1024:
            while cache and (state.text_bytes + cost > 16 * 1024 * 1024 or len(cache) >= 64):
                _, (_, old_cost) = cache.popitem(last=False)
                state.text_bytes -= old_cost
            cache[key] = (result.copy(), cost)
            state.text_bytes += cost
        return result

    def process(self, ctx: PipelineContext):
        img = RichTextGenerator.generate(TextSegment.from_dict(ctx))
        ctx.update_buffer([img]).save_buffer(self.name()).success()

    def name(self) -> str:
        return "rich_text"


class MultiRichTextGenerator(Generator):
    def process(self, ctx: PipelineContext):
        styled = render_character_node(ctx)
        if styled is not None:
            ctx.update_buffer([styled[0]]).save_buffer(self.name()).success()
            return
        segments = ctx.get("text_segments")
        # 可视化组合可返回动态分段列表，缺失项不会留下多余分隔符
        if isinstance(segments, str):
            segments = json.loads(segments)
        text_segments: List[TextSegment] = TextSegment.from_dicts(segments)
        text_alignment = ctx.get("text_alignment")
        text_spacing = ctx.getint("text_spacing")
        height = ctx.get("height", 100)

        text_images = []
        for segment in text_segments:
            segment.height = height
            context = PipelineContext(asdict(segment))
            context.set("save_buffer", False)
            RichTextGenerator().process(context)
            text_images.extend(context.get_buffer())

        # 使用 start_process 替代直接调用 ConcatMerger，解耦对 Merger 的直接依赖
        from processor.core import start_process
        pipeline = [
            {
                "processor_name": "concat",
                "alignment": text_alignment,
                "spacing": text_spacing,
                "save_buffer": False,
            }
        ]
        result = start_process(pipeline, initial_buffer=text_images)

        ctx.update_buffer([result]).save_buffer(self.name()).success()

    def name(self) -> str:
        return "multi_rich_text"


class ImageLoader(Generator):
    def process(self, ctx: PipelineContext):
        if isinstance(ctx.get('path'), str):
            ctx.update_buffer([Image.open(ctx.get('path'))]).success()
        elif isinstance(ctx.get('path'), list):
            ctx.update_buffer([Image.open(path) for path in ctx.get('path')])

    def name(self) -> str:
        return "image"
