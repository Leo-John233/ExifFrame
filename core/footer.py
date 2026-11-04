"""水印文字区域的字段组合和模板往返"""

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache

from jinja2 import Environment, nodes, pass_context
from core.geography import format_location


@dataclass(frozen=True)
class FooterField:
    """面向界面的独立信息项"""

    key: str
    label: str
    group: str
    example: str
    expression: str
    prefix: str = ''
    suffix: str = ''


_DATE = "((exif.DateTimeOriginal or exif.CreateDate)|default(''))"
FIELD_CATALOG = (
    FooterField('camera_model', '相机型号', '相机与镜头', 'NIKON Z f', "exif.CameraModelName|default(exif.Model|default(''))"),
    FooterField('camera_make', '相机品牌', '相机与镜头', 'NIKON', "exif.Make|default('')"),
    FooterField('lens_model', '镜头型号', '相机与镜头', 'NIKKOR Z 24-200mm', "exif.LensModel|default('')"),
    FooterField('lens_make', '镜头品牌', '相机与镜头', 'Nikon', "exif.LensMake|default('')"),
    FooterField('focal_length', '实际焦距', '相机与镜头', '24 mm', "exif.FocalLength|default('')"),
    FooterField('focal_35', '等效焦距', '相机与镜头', '24 mm', "exif.FocalLengthIn35mmFormat|default('')"),
    FooterField('aperture', '光圈', '拍摄参数', '5.0', "(exif.FNumber or exif.AperatureValue or exif.ApertureValue)|default('')", 'f/'),
    FooterField('shutter', '快门', '拍摄参数', '1/250', "(exif.ShutterSpeed or exif.ExposureTime or exif.ShutterSpeedValue)|default('')", '', 's'),
    FooterField('iso', '感光度', '拍摄参数', '160', "exif.ISO|default('')", 'ISO'),
    FooterField('exposure_bias', '曝光补偿', '拍摄参数', '+0.3', "exif.ExposureCompensation|default('')", '', ' EV'),
    FooterField('flash', '闪光灯', '拍摄参数', 'Off', "exif.Flash|default('')"),
    FooterField('white_balance', '白平衡', '拍摄参数', 'Auto', "exif.WhiteBalance|default('')"),
    FooterField('date', '拍摄日期', '时间与位置', '2026-10-05', _DATE + '[:10]'),
    FooterField('time', '拍摄时间', '时间与位置', '11:11:39', _DATE + '[11:19]'),
    FooterField('datetime', '日期与时间', '时间与位置', '2026-10-05 11:11', _DATE + '[:16]'),
    FooterField('timezone', '时区偏移', '时间与位置', '+08:00', "exif.OffsetTimeOriginal|default('')"),
    FooterField('location', '地理位置', '时间与位置', '26°9\'12"N 119°17\'8"E', 'geo_location(exif)'),
    FooterField('gps_altitude', '海拔', '时间与位置', '100', "exif.GPSAltitude|default('')", '', ' m'),
    FooterField('photographer', '摄影师', '作者与文字', 'Alice', "exif.Artist|default('')"),
    FooterField('author', '作者', '作者与文字', 'Alice', "exif.Author|default('')"),
    FooterField('copyright', '版权', '作者与文字', 'All rights reserved', "exif.Copyright|default('')"),
    FooterField('description', '照片描述', '作者与文字', 'Travel', "exif.ImageDescription|default('')"),
    FooterField('comment', '备注', '作者与文字', 'Travel notes', "exif.UserComment|default('')"),
    FooterField('software', '处理软件', '作者与文字', 'ExifFrame', "exif.Software|default('')"),
    FooterField('rating', '评分', '作者与文字', '5', "exif.Rating|default('')"),
    FooterField('filename', '文件名称', '文件', 'DSC_7575', "filename|default('')"),
    FooterField('folder', '文件夹名称', '文件', 'Travel', "file_dir.replace('\\\\', '/').split('/')[-1]"),
)
_FIELDS = {item.key: item for item in FIELD_CATALOG}
_FIELDS.update({
    'gps_latitude': FooterField('gps_latitude', '纬度（旧字段）', '时间与位置', '30.5', "exif.GPSLatitude|default('')"),
    'gps_longitude': FooterField('gps_longitude', '经度（旧字段）', '时间与位置', '104.2', "exif.GPSLongitude|default('')"),
})
REGION_LABELS = {'left_top': '左上', 'left_bottom': '左下', 'right_top': '右上', 'right_bottom': '右下'}
_TEXT_TYPES = {'rich_text', 'multi_rich_text', 'watermark_with_timestamp'}
_STYLE_KEYS = {'font_path', 'color', 'is_bold', 'trim'}
_EMPTY = {'', '-', '—', 'None', '未记录相机', '未记录镜头', '未记录时间'}
_ALIASES = {
    'CameraModelName': 'camera_model', 'Model': 'camera_model', 'Make': 'camera_make',
    'LensModel': 'lens_model', 'LensID': 'lens_model', 'LensMake': 'lens_make',
    'FocalLength': 'focal_length', 'FocalLengthIn35mmFormat': 'focal_35',
    'FNumber': 'aperture', 'AperatureValue': 'aperture', 'ApertureValue': 'aperture',
    'ShutterSpeed': 'shutter', 'ExposureTime': 'shutter', 'ShutterSpeedValue': 'shutter',
    'ISO': 'iso', 'ExposureCompensation': 'exposure_bias', 'Artist': 'photographer',
    'Author': 'author', 'Copyright': 'copyright', 'ImageDescription': 'description',
    'UserComment': 'comment', 'Software': 'software', 'Rating': 'rating', 'Flash': 'flash',
    'WhiteBalance': 'white_balance', 'GPSLatitude': 'gps_latitude', 'GPSLongitude': 'gps_longitude',
    'GPSAltitude': 'gps_altitude', 'OffsetTimeOriginal': 'timezone',
}


class FooterError(ValueError):
    """可由界面统一翻译的组合错误"""


def get_footer_field(key):
    """已保存的旧坐标项仍可读取，新字段库只提供合并位置"""
    return _FIELDS.get(key)


def _load(source):
    try:
        data = json.loads(source)
    except (ValueError, TypeError) as error:
        raise FooterError('当前模板需要使用高级源码编辑') from error
    if not isinstance(data, list) or any(not isinstance(node, dict) for node in data):
        raise FooterError('当前模板需要使用高级源码编辑')
    return data


def _targets(data):
    for index, node in enumerate(data):
        if node.get('processor_name') == 'watermark':
            return 'footer', [(key, index, key, node.get(key, {})) for key in REGION_LABELS]
    return 'overlay', [(f'text_{number}', index, None, node)
                       for number, (index, node) in enumerate((i, n) for i, n in enumerate(data)
                                                             if n.get('processor_name') in _TEXT_TYPES)]


def _generated_row(text):
    """直接读取组合函数的常量参数，不执行模板代码"""
    if not isinstance(text, str) or 'footer_' not in text:
        return None
    try:
        parsed = Environment().parse(text)
        if len(parsed.body) != 1 or not isinstance(parsed.body[0], nodes.Output) or len(parsed.body[0].nodes) != 1:
            return None
        call = parsed.body[0].nodes[0]
        encoded_segments = False
        if isinstance(call, nodes.Filter) and call.name == 'tojson':
            call = call.node
            encoded_segments = True
        if isinstance(call, nodes.Call) and isinstance(call.node, nodes.Name) and call.node.name in {'footer_row', 'footer_segments'}:
            if encoded_segments != (call.node.name == 'footer_segments'):
                return None
            return {'items': call.args[1].as_const(), 'separator': call.args[2].as_const()}, call.args[3].as_const()
    except Exception:
        pass
    return None


def _field_key(expression):
    if 'geo_location(exif)' in expression and not re.search(r'exif\.', expression):
        return 'location'
    if 'footer_row' in expression or 'footer_segments' in expression:
        return None
    if re.search(r'file_dir|file_path.*parent', expression):
        return 'folder'
    if re.search(r'\bfilename\b', expression):
        return 'filename'
    names = re.findall(r'exif\.([A-Za-z0-9_]+)', expression)
    if names and all(name in {'DateTimeOriginal', 'CreateDate', 'DigitalCreationDate', 'DateCreated',
                             'DateTimeCreated', 'DigitalCreationDateTime', 'FileInodeChangeDateTime',
                             'FileAccessDateTime'} for name in names):
        return 'time' if '[11:' in expression else 'date' if '[:10]' in expression else 'datetime'
    choices = {_ALIASES[name] for name in names if name in _ALIASES}
    return next(iter(choices)) if len(choices) == 1 and len(names) == sum(name in _ALIASES for name in names) else None


def _read_text(text):
    """将原模板中的拍摄参数拆成独立字段，同时保留原表达式"""
    text = str(text or '')
    matches = list(re.finditer(r'\{\{(.*?)\}\}', text, re.S))
    if '{%' in text or '{#' in text:
        return {'items': [{'raw': text, 'label': '原有自定义内容'}], 'separator': ' '}
    if not matches:
        return {'items': [{'text': text}] if text.strip() else [], 'separator': ' '}
    items, separator, previous_end = [], ' ', 0
    for match in matches:
        expression = match.group(1).strip()
        # 旧模板先经过 JSON 解码，独立执行表达式前恢复代码中的转义层
        if 'footer_row' not in expression and 'footer_segments' not in expression:
            expression = expression.replace('\\', '\\\\')
        key = _field_key(expression)
        item = {'field': key, 'expression': expression, 'prefix': '', 'suffix': ''} if key else {'raw': '{{ ' + expression + ' }}', 'label': '原有自定义内容'}
        literal = text[previous_end:match.start()]
        if items and 'field' in items[-1]:
            suffix = _FIELDS[items[-1]['field']].suffix
            if suffix and literal.startswith(suffix):
                items[-1]['suffix'] = suffix
                literal = literal[len(suffix):]
        prefix = _FIELDS[key].prefix if key else ''
        if prefix:
            prefix_match = re.search(re.escape(prefix) + r'\s*$', literal)
            if prefix_match:
                item['prefix'] = prefix_match.group()
                literal = literal[:prefix_match.start()]
        if literal and not literal.strip(' \t·|,，;；/'):
            separator = literal
        elif literal.strip():
            items.append({'text': literal.strip()})
        items.append(item)
        previous_end = match.end()
    tail = text[previous_end:]
    if items and 'field' in items[-1]:
        suffix = _FIELDS[items[-1]['field']].suffix
        if suffix and tail.startswith(suffix):
            items[-1]['suffix'] = suffix
            tail = tail[len(suffix):]
    if tail.strip():
        items.append({'text': tail.strip()})
    return {'items': items, 'separator': separator}


def _read_row(node):
    if not isinstance(node, dict):
        raise FooterError('当前模板需要使用高级源码编辑')
    text = node.get('text', '')
    generated = _generated_row(text if 'text_segments' not in node else node['text_segments'])
    if generated:
        return generated
    segments = node.get('text_segments')
    if segments is not None and not isinstance(segments, list):
        raise FooterError('当前模板需要使用高级源码编辑')
    if not isinstance(segments, list):
        return _read_text(text), 'hide'
    if any(not isinstance(segment, dict) for segment in segments):
        raise FooterError('当前模板需要使用高级源码编辑')
    parsed = [_read_text(segment.get('text', '')) for segment in segments]
    field_keys = {item['field'] for row in parsed for item in row['items'] if 'field' in item}
    if len(segments) > 1 and (len(field_keys) <= 1):
        # 保留红色 Z 等分段样式，增加别的字段时不破坏原有文字
        return {'items': [{'raw': ''.join(str(part.get('text', '')) for part in segments),
                            'segments': deepcopy(segments), 'label': '原有文字样式'}], 'separator': ' '}, 'hide'
    items, separator = [], ' '
    for segment, row in zip(segments, parsed):
        style = {key: deepcopy(value) for key, value in segment.items() if key in _STYLE_KEYS}
        for item in row['items']:
            item['style'] = style
            items.append(item)
        if str(segment.get('text', '')).isspace():
            separator = str(segment['text'])
        elif row['separator'] != ' ':
            separator = row['separator']
    return {'items': items, 'separator': separator}, 'hide'


def read_layout(source: str) -> dict:
    """读取所有可编辑文字区，无法识别的内容仍原样保留"""
    data = _load(source)
    kind, targets = _targets(data)
    if not targets:
        raise FooterError('模板中没有可组合的文字区域')
    rows, missing = {}, 'hide'
    for key, index, child, node in targets:
        rows[key], mode = _read_row(node)
        if mode == 'dash':
            missing = mode
    logo = 'keep'
    if kind == 'footer':
        footer = data[targets[0][1]]
        positions = [name for name in ('left', 'center', 'right') if footer.get(f'{name}_logo')]
        logo = positions[0] if len(positions) == 1 else 'none' if not positions else 'keep'
    return normalize_layout({'version': 1, 'kind': kind, 'regions': [item[0] for item in targets],
                             'rows': rows, 'logo': logo, 'missing': missing})


def normalize_layout(layout: dict) -> dict:
    """限制可视化模型的形状，不改动字段内部保留的高级样式"""
    result = deepcopy(layout)
    if result.get('kind') not in ('footer', 'overlay') or not isinstance(result.get('regions'), list):
        raise FooterError('底部信息区域无效')
    if result.get('logo', 'keep') not in ('keep', 'none', 'left', 'center', 'right'):
        raise FooterError('标识位置无效')
    if result.get('missing', 'hide') not in ('hide', 'dash'):
        raise FooterError('缺失值处理方式无效')
    for region in result['regions']:
        if not isinstance(region, str) or not re.fullmatch(r'(?:left|right)_(?:top|bottom)|text_\d+', region):
            raise FooterError('底部信息区域无效')
        row = result.get('rows', {}).get(region)
        if not isinstance(row, dict) or not isinstance(row.get('items'), list):
            raise FooterError('底部信息区域无效')
        if not isinstance(row.get('separator', ' '), str) or len(row.get('separator', ' ')) > 32:
            raise FooterError('分隔符过长')
        if len(row['items']) > 32:
            raise FooterError('每个区域最多放置 32 项信息')
        for item in row['items']:
            if not isinstance(item, dict):
                raise FooterError('底部信息字段无效')
            if 'field' in item and item['field'] not in _FIELDS:
                raise FooterError('底部信息字段无效')
            if not any(name in item for name in ('field', 'text', 'raw')):
                raise FooterError('底部信息字段无效')
            for name in ('text', 'raw', 'prefix', 'suffix', 'expression'):
                if name in item and not isinstance(item[name], str):
                    raise FooterError('底部信息字段无效')
            if len(item.get('text', '')) > 2000:
                raise FooterError('自定义文字过长')
    result.setdefault('version', 1)
    result.setdefault('missing', 'hide')
    result.setdefault('logo', 'keep')
    return result


def _row_call(function, row, missing, style=None):
    arguments = [row['items'], row.get('separator', ' '), missing]
    if style is not None:
        arguments.append(style)
    # Jinja 识别 Python 的 None/True/False，避免 JSON 的 null 被当作未定义变量
    encoded = ', '.join(repr(item) for item in arguments)
    suffix = ' | tojson' if function == 'footer_segments' else ''
    return '{{ ' + function + '(exif, ' + encoded + ')' + suffix + ' }}'


def write_layout(source: str, layout: dict) -> str:
    """只重建发生修改的文字区，保留其他滤镜、字体、颜色和自定义步骤"""
    layout = normalize_layout(layout)
    original = read_layout(source)
    if layout['kind'] != original['kind'] or layout['regions'] != original['regions']:
        raise FooterError('文字区必须保留在原有版式内')
    if layout == original:
        return source
    data = _load(source)
    kind, targets = _targets(data)
    for key, index, child, node in targets:
        if layout['rows'][key] == original['rows'][key] and layout['missing'] == original['missing']:
            continue
        edited = deepcopy(node)
        if not edited:
            edited = {'processor_name': 'rich_text'}
        if edited.get('processor_name') in {'multi_rich_text', 'watermark_with_timestamp'}:
            style = {name: edited[name] for name in _STYLE_KEYS if name in edited}
            if isinstance(edited.get('text_segments'), list) and edited['text_segments']:
                style.update({name: value for name, value in edited['text_segments'][0].items() if name in _STYLE_KEYS})
            edited['text_segments'] = _row_call('footer_segments', layout['rows'][key], layout['missing'], style)
            edited.pop('text', None)
        else:
            edited['text'] = _row_call('footer_row', layout['rows'][key], layout['missing'])
            edited.pop('text_segments', None)
        if child:
            data[index][child] = edited
        else:
            data[index] = edited
    if kind == 'footer' and layout['logo'] != original['logo'] and layout['logo'] != 'keep':
        footer = data[targets[0][1]]
        path = next((footer.get(f'{place}_logo') for place in ('center', 'right', 'left') if footer.get(f'{place}_logo')), '{{ auto_logo() }}')
        for place in ('left', 'center', 'right'):
            footer[f'{place}_logo'] = path if layout['logo'] == place else None
        if layout['logo'] == 'center':
            footer['fit_center_columns'] = True
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


@lru_cache(maxsize=128)
def _expression(environment, source):
    return environment.compile_expression(source)


@lru_cache(maxsize=64)
def _raw_template(environment, source):
    return environment.from_string(source)


def _resolved_style(style, context, values):
    """保留原分段中按照片变量设置的颜色和字体"""
    return {key: _raw_template(context.environment, value).render(values)
            if isinstance(value, str) and ('{{' in value or '{%' in value) else value
            for key, value in style.items()}


def _item_parts(context, metadata, item, missing, base_style):
    values = dict(context.get_all())
    values['exif'] = metadata
    if 'segments' in item:
        parts = []
        for segment in item['segments']:
            text = _raw_template(context.environment, str(segment.get('text', ''))).render(values)
            if text:
                style = _resolved_style({key: value for key, value in segment.items() if key in _STYLE_KEYS}, context, values)
                parts.append({**base_style, **style, 'text': text})
        if parts:
            parts[0]['text'] = item.get('prefix', '') + parts[0]['text']
            parts[-1]['text'] += item.get('suffix', '')
        return parts
    style = {**base_style, **_resolved_style(item.get('style', {}), context, values)}
    if 'field' in item:
        field = _FIELDS[item['field']]
        value = _expression(context.environment, item.get('expression') or field.expression)(**values)
        value = str(value).strip() if value is not None else ''
        if value in _EMPTY:
            return [{**style, 'text': '—'}] if missing == 'dash' else []
        return [{**style, 'text': item.get('prefix', field.prefix) + value + item.get('suffix', field.suffix)}]
    if 'text' in item:
        return [{**style, 'text': item['text']}] if item['text'] else []
    text = _raw_template(context.environment, item.get('raw', '')).render(values)
    return [{**style, 'text': item.get('prefix', '') + text + item.get('suffix', '')}] if text else []


@pass_context
def footer_segments(context, metadata, items, separator=' ', missing='hide', style=None):
    """按有值字段插入分隔符，避免缺项留下单位或孤立符号"""
    output = []
    values = {**context.get_all(), 'exif': metadata}
    base = _resolved_style(style or {}, context, values)
    for item in items:
        parts = _item_parts(context, metadata, item, missing, base)
        if not parts:
            continue
        if output and separator:
            output.append({**base, 'text': separator})
        output.extend(parts)
    return output or [{**base, 'text': ''}]


@pass_context
def footer_row(context, metadata, items, separator=' ', missing='hide'):
    """同一组合模型同时用于实际渲染和界面示例"""
    return ''.join(part['text'] for part in footer_segments(context, metadata, items, separator, missing))


def preview_rows(layout: dict, metadata=None, filename='', file_dir='') -> dict[str, str]:
    """生成文字示例，不读取照片或执行图像处理"""
    layout = normalize_layout(layout)
    if metadata is None:
        metadata = {'CameraModelName': 'NIKON Z f', 'Make': 'NIKON', 'LensModel': 'NIKKOR Z 24-200mm',
                    'FocalLength': '24 mm', 'FocalLengthIn35mmFormat': '24 mm', 'FNumber': '5.0',
                    'ShutterSpeed': '1/250', 'ISO': '160', 'Artist': 'Alice', 'Copyright': 'All rights reserved',
                    'DateTimeOriginal': '2026-10-05 11:11:39',
                    'GPSLatitude': '26.1533333333333', 'GPSLatitudeRef': 'N',
                    'GPSLongitude': '119.285555555556', 'GPSLongitudeRef': 'E'}
        for field in FIELD_CATALOG:
            match = re.search(r'exif\.([A-Za-z0-9_]+)', field.expression)
            if match:
                metadata.setdefault(match.group(1), field.example)
    environment = Environment(autoescape=False)
    environment.globals.update(footer_row=footer_row, footer_segments=footer_segments, geo_location=format_location)
    output = {}
    for region, row in layout['rows'].items():
        try:
            output[region] = environment.from_string(_row_call('footer_row', row, layout['missing'])).render(
                exif=metadata, filename=filename or 'DSC_7575', file_dir=file_dir or 'Travel')
        except Exception:
            output[region] = '…'
    return output
