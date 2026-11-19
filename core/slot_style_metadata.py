"""为动态 Jinja 模板保留可移植的槽位样式，正文保持逐字不变"""

import base64
import json
import re
from copy import deepcopy


_HEADER = re.compile(r'\A\{# ExifFrame-Slot-Styles: ([A-Za-z0-9+/=]+) #\}\r?\n')
_TARGET = re.compile(r'(?:watermark_\d+_)?(?:(?:left|right)_(?:top|bottom)|(?:left|center|right)_logo)|text_\d+')
_PROPERTIES = {'font_path', 'color', 'height', 'height_ratio', 'visible'}


def read_slot_metadata(source: str) -> dict:
    match = _HEADER.match(source or '')
    if not match:
        return {}
    try:
        value = json.loads(base64.b64decode(match[1], validate=True).decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError
        for key, style in value.items():
            if not _TARGET.fullmatch(key) or not isinstance(style, dict) or not set(style).issubset(_PROPERTIES):
                raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError('模板槽位样式无效') from error


def strip_slot_metadata(source: str) -> str:
    match = _HEADER.match(source or '')
    if match:
        read_slot_metadata(source)
        return source[match.end():]
    return source


def write_slot_metadata(source: str, key: str, changes: dict) -> str:
    if not _TARGET.fullmatch(key) or not isinstance(changes, dict) or not set(changes).issubset(_PROPERTIES):
        raise ValueError('模板槽位样式无效')
    styles = read_slot_metadata(source)
    before = deepcopy(styles)
    style = styles.setdefault(key, {})
    for name, value in changes.items():
        if value is None:
            style.pop(name, None)
        else:
            style[name] = value
    if not style:
        styles.pop(key, None)
    if styles == before:
        return source
    body = strip_slot_metadata(source)
    if not styles:
        return body
    encoded = base64.b64encode(json.dumps(styles, ensure_ascii=True, separators=(',', ':')).encode('utf-8')).decode('ascii')
    return '{# ExifFrame-Slot-Styles: ' + encoded + ' #}\n' + body


def apply_slot_metadata(nodes: list, styles: dict) -> list:
    """Jinja 展开后匹配当前照片存在的槽位，未出现的条件分支保留覆写"""
    from core.footer import text_targets
    _, targets = text_targets(nodes)
    for key, _, _, node in targets:
        if key in styles and node:
            node['slot_style'] = {**(node.get('slot_style') or {}), **deepcopy(styles[key])}
    count = 0
    for node in nodes:
        if node.get('processor_name') != 'watermark':
            continue
        count += 1
        prefix = '' if count == 1 else f'watermark_{count}_'
        for name in ('left_logo', 'center_logo', 'right_logo'):
            if prefix + name in styles:
                logos = node.setdefault('logo_styles', {})
                logos[name] = {**logos.get(name, {}), **deepcopy(styles[prefix + name])}
    return nodes
