"""为水印补齐缺失字形并保持原字体风格"""

import math
import os
import struct
import unicodedata
from bisect import bisect_left
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


@lru_cache(maxsize=48)
def _font_table(path, index, modified, size, tag):
    """按需读取字体表，兼容单字体和字体集合"""
    try:
        with Path(path).open('rb') as stream:
            header = stream.read(12)
            offset = 0
            if header[:4] == b'ttcf':
                count = struct.unpack_from('>I', header, 8)[0]
                if index >= count:
                    return b''
                stream.seek(12 + index * 4)
                offset = struct.unpack('>I', stream.read(4))[0]
                stream.seek(offset)
                header = stream.read(12)
            count = struct.unpack_from('>H', header, 4)[0]
            records = stream.read(count * 16)
            for entry in range(count):
                position = entry * 16
                if records[position:position + 4] == tag:
                    start, length = struct.unpack_from('>II', records, position + 8)
                    if start + length > size:
                        return b''
                    stream.seek(start)
                    return stream.read(length)
    except (OSError, ValueError, struct.error):
        pass
    return b''


@lru_cache(maxsize=24)
def _cmaps(path, index, modified, size):
    """只保留 Unicode 字符映射和查询所需的索引"""
    try:
        cmap = _font_table(path, index, modified, size, b'cmap')
        if not cmap:
            return ()
        tables = []
        seen = set()
        for entry in range(struct.unpack_from('>H', cmap, 2)[0]):
            platform, encoding, position = struct.unpack_from('>HHI', cmap, 4 + entry * 8)
            if platform != 0 and not (platform == 3 and encoding in (1, 10)):
                continue
            if position in seen:
                continue
            seen.add(position)
            form = struct.unpack_from('>H', cmap, position)[0]
            if form in (0, 4, 6):
                length = struct.unpack_from('>H', cmap, position + 2)[0]
            elif form in (12, 13):
                length = struct.unpack_from('>I', cmap, position + 4)[0]
            else:
                continue
            table = cmap[position:position + length]
            ends = ()
            if form == 4:
                segments = struct.unpack_from('>H', table, 6)[0] // 2
                ends = struct.unpack_from(f'>{segments}H', table, 14)
            tables.append((form, table, ends))
        return tuple(tables)
    except (OSError, ValueError, struct.error):
        return ()


def _font_key(font):
    """将字体文件版本纳入缓存，替换字体后自动刷新"""
    try:
        path = Path(font.path).resolve()
        info = path.stat()
        return str(path), getattr(font, 'index', 0), info.st_mtime_ns, info.st_size
    except (AttributeError, TypeError, OSError):
        return None


@lru_cache(maxsize=8192)
def _supports(key, codepoint):
    """按真实字形编号判断字符是否可用，避免把方框当成字形"""
    tables = _cmaps(*key) if key else ()
    if not tables:
        return True
    try:
        for form, table, ends in tables:
            if form in (12, 13):
                low, high = 0, struct.unpack_from('>I', table, 12)[0]
                while low < high:
                    middle = (low + high) // 2
                    start, end, glyph = struct.unpack_from('>III', table, 16 + middle * 12)
                    if codepoint < start:
                        high = middle
                    elif codepoint > end:
                        low = middle + 1
                    else:
                        if glyph + (codepoint - start if form == 12 else 0):
                            return True
                        break
            elif form == 4 and codepoint <= 0xFFFF:
                segment = bisect_left(ends, codepoint)
                count = len(ends)
                if segment >= count:
                    continue
                start = struct.unpack_from('>H', table, 16 + count * 2 + segment * 2)[0]
                if codepoint < start:
                    continue
                delta = struct.unpack_from('>H', table, 16 + count * 4 + segment * 2)[0]
                position = 16 + count * 6 + segment * 2
                distance = struct.unpack_from('>H', table, position)[0]
                if distance:
                    glyph = struct.unpack_from('>H', table, position + distance + (codepoint - start) * 2)[0]
                    if glyph and (glyph + delta) & 0xFFFF:
                        return True
                elif (codepoint + delta) & 0xFFFF:
                    return True
            elif form == 0 and codepoint < 256 and table[6 + codepoint]:
                return True
            elif form == 6 and codepoint <= 0xFFFF:
                start, count = struct.unpack_from('>HH', table, 6)
                if start <= codepoint < start + count:
                    if struct.unpack_from('>H', table, 10 + (codepoint - start) * 2)[0]:
                        return True
    except (IndexError, struct.error):
        return True
    return False


def _weight(font):
    """使用字体库内的真实字重，未标注时按常规体处理"""
    key = _font_key(font)
    table = _font_table(*key, b'OS/2') if key else b''
    return struct.unpack_from('>H', table, 4)[0] if len(table) >= 6 else 400


def _invisible(character):
    """空白和连接控制符不单独触发字体切换"""
    codepoint = ord(character)
    return (character.isspace() or unicodedata.category(character) == 'Cf'
            or 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF)


def _native_z(font):
    """字库缺少双线 Z 时，优先沿用本字体的普通 Z 轮廓"""
    key = _font_key(font)
    return key is not None and not _supports(key, 0x2124) and _supports(key, ord('Z'))


def _style_native_z(alpha, text, layout, font, origin):
    """在原 Z 的斜笔画内形成双线，保留字高、字宽和收笔"""
    pixels = np.array(alpha)
    box = font.getbbox('Z')
    advance = font.getlength('Z')
    for index, character in enumerate(text):
        if character != 'ℤ':
            continue
        # 使用整段字距定位，保留前一个字符与 Z 之间的字偶调整
        position = origin[0] + font.getlength(layout[:index + 1]) - advance
        left = max(0, math.floor(position + box[0]))
        right = min(alpha.width, math.ceil(position + box[2]))
        top = max(0, math.floor(origin[1] + box[1]))
        bottom = min(alpha.height, math.ceil(origin[1] + box[3]))
        glyph = pixels[top:bottom, left:right]
        if not glyph.size:
            continue
        columns = np.arange(glyph.shape[1])
        for row in glyph:
            maximum = int(row.max())
            if not maximum:
                continue
            ink = np.flatnonzero(row >= max(1, maximum * .5))
            if not len(ink):
                continue
            width = ink[-1] - ink[0] + 1
            # 顶部和底部横画保持原样，仅分开中间的斜笔画
            if width > glyph.shape[1] * .7:
                continue
            center = (ink[0] + ink[-1]) / 2
            half = max(1.5, width * .15)
            cut = np.clip(half + .5 - np.abs(columns - center), 0, 1)
            row[:] = np.rint(row * (1 - cut)).astype('uint8')
    return Image.fromarray(pixels)


def _render_line(runs, primary, color):
    """按共同基线拼接字体片段，保留字距和左右外伸部分"""
    ascent, descent = primary.getmetrics()
    positions = []
    cursor, left, right = 0.0, 0, 1
    weight = _weight(primary)
    for text, font in runs:
        layout = text.replace('ℤ', 'Z') if 'ℤ' in text and _native_z(font) else text
        font_ascent, font_descent = font.getmetrics()
        ascent, descent = max(ascent, font_ascent), max(descent, font_descent)
        # 缺字字体只有常规体时，按原字重细化或加粗笔画
        difference = weight - _weight(font) if font is not primary else 0
        radius = round(font.size * min(abs(difference), 500) / 20000)
        stroke = radius if difference > 0 else -radius
        positions.append((cursor, text, layout, font, font_ascent, stroke))
        cursor += font.getlength(layout)
    top, bottom = 0, ascent + abs(descent)
    for position, text, layout, font, font_ascent, stroke in positions:
        box = font.getbbox(layout)
        padding = max(0, stroke)
        left = min(left, math.floor(position + box[0]) - padding)
        right = max(right, math.ceil(position + box[2]) + padding)
        top = min(top, ascent - font_ascent + box[1] - padding)
        bottom = max(bottom, ascent - font_ascent + box[3] + padding)
    right = max(right, math.ceil(cursor))
    image = Image.new('RGBA', (right - left, bottom - top), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for position, text, layout, font, font_ascent, stroke in positions:
        origin = position - left, ascent - font_ascent - top
        if stroke < 0 or text != layout:
            layer = Image.new('RGBA', image.size, (0, 0, 0, 0))
            ImageDraw.Draw(layer).text(origin, layout, font=font, fill=color,
                                      stroke_width=max(0, stroke), stroke_fill=color)
            alpha = layer.getchannel('A')
            if stroke < 0:
                alpha = alpha.filter(ImageFilter.MinFilter(1 - stroke * 2))
            if text != layout:
                alpha = _style_native_z(alpha, text, layout, font, origin)
            layer.putalpha(alpha)
            image.alpha_composite(layer)
        else:
            draw.text(origin, layout, font=font, fill=color, stroke_width=stroke, stroke_fill=color)
    return image


def render_with_fallback(text, primary, load_font, color):
    """仅在原字体缺字时绘制混合字体，普通文字沿用原有流程"""
    primary_key = _font_key(primary)
    if all(_invisible(char) or _supports(primary_key, ord(char)) for char in text):
        return None
    fonts = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
    candidates = [fonts / name for name in ('seguisym.ttf', 'cambria.ttc', 'seguiemj.ttf', 'msyh.ttc', 'arial.ttf')]
    loaded, chosen, lines = {}, {}, []
    native_z = 'ℤ' in text and _native_z(primary)
    for line in text.split('\n'):
        runs = []
        for character in line:
            font = primary
            if _invisible(character):
                font = runs[-1][1] if runs else primary
            elif not (character == 'ℤ' and native_z) and not _supports(primary_key, ord(character)):
                if character not in chosen:
                    chosen[character] = primary
                    for path in candidates:
                        if not path.is_file():
                            continue
                        if path not in loaded:
                            candidate = load_font(str(path))
                            loaded[path] = candidate, _font_key(candidate)
                        candidate, key = loaded[path]
                        if _supports(key, ord(character)):
                            chosen[character] = candidate
                            break
                font = chosen[character]
            if runs and runs[-1][1] is font:
                runs[-1] = runs[-1][0] + character, font
            else:
                runs.append((character, font))
        lines.append(_render_line(runs, primary, color))
    image = Image.new('RGBA', (max(line.width for line in lines), sum(line.height for line in lines)), (0, 0, 0, 0))
    top = 0
    for line in lines:
        image.alpha_composite(line, (0, top))
        top += line.height
    return image
