"""照片信息编辑、迁移与副本保存"""

import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from core.util import find_exiftool
from core.exiftool_process import run_exiftool


@dataclass(frozen=True)
class MetadataField:
    """编辑器共享的字段定义"""

    tag: str
    label: str
    group: str
    kind: str = 'text'
    choices: tuple[tuple[str, str], ...] = ()


FIELDS = (
    *(MetadataField(tag, label, '创作者与版权', kind) for tag, label, kind in (
        ('Artist', '摄影师', 'text'), ('Author', '作者', 'text'), ('Copyright', '版权声明', 'text'),
        ('Software', '处理软件', 'text'), ('ImageDescription', '照片描述', 'text'),
        ('UserComment', '用户备注', 'text'), ('Rating', '星级评分', 'rating'))),
    *(MetadataField(tag, label, '相机与镜头') for tag, label in (
        ('Make', '相机制造商'), ('Model', '相机型号'), ('LensMake', '镜头品牌'), ('LensModel', '镜头型号'))),
    *(MetadataField(tag, label, '曝光参数', 'number') for tag, label in (
        ('FocalLength', '实际焦距'), ('FocalLengthIn35mmFormat', '等效焦距'), ('FNumber', '光圈'),
        ('ExposureTime', '快门速度'), ('ISO', '感光度'), ('ExposureCompensation', '曝光补偿'))),
    MetadataField('Flash', '闪光灯', '曝光参数', 'choice',
                  (('0', '未闪光'), ('1', '已闪光'), ('24', '自动闪光'), ('65', '消除红眼'))),
    MetadataField('WhiteBalance', '白平衡', '曝光参数', 'choice',
                  (('Auto', '自动'), ('Daylight', '日光'), ('Cloudy', '多云'),
                   ('Tungsten', '钨丝灯'), ('Fluorescent', '荧光灯'), ('Manual', '手动'))),
    MetadataField('DateTimeOriginal', '拍摄时间', '时间与位置', 'datetime'),
    MetadataField('CreateDate', '数字化时间', '时间与位置', 'datetime'),
    MetadataField('OffsetTimeOriginal', '时区偏移', '时间与位置'),
    MetadataField('GPSLatitude', '纬度', '时间与位置', 'number'),
    MetadataField('GPSLatitudeRef', '南北纬', '时间与位置', 'choice', (('N', '北纬'), ('S', '南纬'))),
    MetadataField('GPSLongitude', '经度', '时间与位置', 'number'),
    MetadataField('GPSLongitudeRef', '东西经', '时间与位置', 'choice', (('E', '东经'), ('W', '西经'))),
    MetadataField('GPSAltitude', '海拔高度', '时间与位置', 'number'),
)
_FIELDS = {field.tag: field for field in FIELDS}
_LIGHT_SOURCES = {'Daylight': 1, 'Fluorescent': 2, 'Tungsten': 3, 'Cloudy': 10}


class MetadataError(ValueError):
    """携带稳定错误码供界面切换语言"""

    def __init__(self, code: str, field: str = '', detail: str = ''):
        self.code, self.field, self.detail = code, field, detail
        super().__init__(f'{code}: {field or detail}'.rstrip(': '))


def metadata_key(path: Path) -> str:
    """统一同一照片在不同路径写法中的标识"""
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _run_tool(arguments: list[str]) -> subprocess.CompletedProcess:
    """通过 UTF-8 参数流读写，避免中文路径和隐藏控制台问题"""
    tool = find_exiftool()
    if tool is None:
        raise MetadataError('tool_missing')
    if any('\n' in argument or '\r' in argument for argument in arguments):
        raise MetadataError('invalid_value')
    try:
        return run_exiftool(
            [str(tool), '-charset', 'filename=UTF8', '-@', '-'],
            input=('\n'.join(arguments) + '\n').encode('utf-8'), timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, 'stderr', b'') or str(error)
        if isinstance(detail, bytes):
            detail = detail.decode('utf-8', errors='replace')
        raise MetadataError('write_failed', detail=str(detail)) from error


def read_metadata(path: Path) -> dict[str, str]:
    """读取可编辑的标准字段，数值保持便于编辑的原始形式"""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise MetadataError('file_missing')
    arguments = ['-j', '-n', '-lang', 'en', *(f'-{tag}' for tag in _FIELDS),
                 '-LightSource', '-Orientation', '-GPSAltitudeRef', source.as_posix()]
    try:
        records = json.loads(_run_tool(arguments).stdout)
        data = records[0]
    except (ValueError, IndexError, TypeError) as error:
        raise MetadataError('write_failed', detail=str(error)) from error
    values = {key: str(value).replace('\x00', '').strip() for key, value in data.items()
              if key in _FIELDS or key in {'LightSource', 'Orientation', 'GPSAltitudeRef'}}
    if 'WhiteBalance' in values:
        preset = next((name for name, number in _LIGHT_SOURCES.items()
                       if str(number) == values.get('LightSource')), None)
        values['WhiteBalance'] = preset or ('Manual' if values['WhiteBalance'] == '1' else 'Auto')
    if 'ExposureTime' in values:
        seconds = _number(values['ExposureTime'], 'ExposureTime')
        values['ExposureTime'] = str(Fraction(seconds).limit_denominator(1000000)) if 0 < seconds < 1 else f'{seconds:g}'
    if values.get('GPSAltitudeRef') == '1' and 'GPSAltitude' in values:
        values['GPSAltitude'] = f"{-abs(float(values['GPSAltitude'])):g}"
    return values


def _number(value: str, tag: str) -> float:
    """支持整数、小数和分数输入"""
    try:
        result = float(Fraction(value))
        if not math.isfinite(result):
            raise ValueError
        return result
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise MetadataError('invalid_value', tag) from error


def normalize_changes(changes: dict[str, str]) -> dict[str, str]:
    """规范常见单位并校验范围，留空字段保持照片原值"""
    result = {}
    for tag, raw in changes.items():
        if tag not in _FIELDS:
            raise MetadataError('unsupported_tag', tag)
        value = str(raw).strip()
        if not value:
            continue
        if '\x00' in value:
            raise MetadataError('invalid_value', tag)
        if tag in {'DateTimeOriginal', 'CreateDate'}:
            formatted = re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', value)
            try:
                date = datetime.fromisoformat(formatted)
            except ValueError as error:
                raise MetadataError('invalid_date', tag) from error
            result[tag] = date.strftime('%Y:%m:%d %H:%M:%S')
            if tag == 'DateTimeOriginal' and date.utcoffset() is not None and 'OffsetTimeOriginal' not in changes:
                offset = date.strftime('%z')
                result['OffsetTimeOriginal'] = offset[:3] + ':' + offset[3:]
            continue
        if tag == 'OffsetTimeOriginal':
            if not re.fullmatch(r'[+-](?:0\d|1[0-4]):[0-5]\d', value) or (value[1:3] == '14' and value[-2:] != '00'):
                raise MetadataError('invalid_timezone', tag)
        elif tag in {'Flash', 'WhiteBalance', 'GPSLatitudeRef', 'GPSLongitudeRef'}:
            if tag.startswith('GPS'):
                value = value.upper()
            if value not in {choice[0] for choice in _FIELDS[tag].choices}:
                raise MetadataError('invalid_value', tag)
        elif _FIELDS[tag].kind in {'number', 'rating'}:
            value = re.sub(r'(?i)^f/?', '', value) if tag == 'FNumber' else value
            value = re.sub(r'(?i)^iso\s*', '', value) if tag == 'ISO' else value
            value = re.sub(r'(?i)\s*(mm|m|s|秒)$', '', value).strip()
            number_input = value
            number = _number(value, tag)
            if tag in {'ISO', 'Rating'} and number != int(number):
                raise MetadataError('invalid_value', tag)
            limits = {'ISO': (1, 10000000), 'Rating': (0, 5), 'FNumber': (.1, 128),
                      'FocalLength': (.1, 100000), 'FocalLengthIn35mmFormat': (.1, 100000),
                      'ExposureTime': (.00000001, 86400), 'ExposureCompensation': (-30, 30),
                      'GPSLatitude': (-90, 90), 'GPSLongitude': (-180, 180), 'GPSAltitude': (-12000, 100000)}
            lower, upper = limits.get(tag, (-math.inf, math.inf))
            if not lower <= number <= upper:
                raise MetadataError('invalid_gps' if tag.startswith('GPS') else 'invalid_value', tag)
            if tag in {'ISO', 'Rating'}:
                value = str(int(number))
            elif tag.startswith('GPS'):
                value = f'{number:.12g}'
            else:
                value = f'{number:g}'
            if tag == 'ExposureTime' and '/' in number_input:
                value = str(Fraction(number_input))
        result[tag] = value
    for tag, reference, positive, negative in (
            ('GPSLatitude', 'GPSLatitudeRef', 'N', 'S'), ('GPSLongitude', 'GPSLongitudeRef', 'E', 'W')):
        if tag in result:
            number = float(result[tag])
            if number < 0 and result.get(reference, negative) != negative:
                raise MetadataError('invalid_gps', tag)
            result[reference] = result.get(reference, negative if number < 0 else positive)
            # 坐标保留足够精度，避免常规六位格式将秒数舍入到错误的位置
            result[tag] = f'{abs(number):.12g}'
    return result


def merge_overrides(metadata: dict, changes: dict) -> dict:
    """把可编辑字段同步到原水印模板使用的别名"""
    result = dict(metadata)
    values = normalize_changes(changes)
    aliases = {'Model': ('CameraModelName',), 'ExposureTime': ('ShutterSpeed', 'ShutterSpeedValue'),
               'FNumber': ('Aperture', 'ApertureValue', 'AperatureValue'),
               'DateTimeOriginal': ('SubSecDateTimeOriginal',), 'CreateDate': ('SubSecCreateDate',)}
    for tag, value in values.items():
        display = value
        if tag in {'DateTimeOriginal', 'CreateDate'}:
            display = datetime.strptime(value, '%Y:%m:%d %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
        elif tag in {'FocalLength', 'FocalLengthIn35mmFormat'}:
            display = f'{value} mm'
        result[tag] = display
        if tag == 'GPSAltitude':
            result['GPSAltitudeRef'] = '1' if float(value) < 0 else '0'
        for alias in aliases.get(tag, ()):
            result[alias] = display
    return result


def save_metadata_copy(photo: Path, destination: Path, changes: dict, source: Path | None = None,
                       strip_maker_notes: bool = True) -> Path:
    """修改或迁移信息到新副本，图像数据不重新编码且不覆盖原片"""
    original, destination = Path(photo).resolve(), Path(destination).expanduser().resolve()
    if not original.is_file() or (source is not None and not Path(source).is_file()):
        raise MetadataError('file_missing')
    if metadata_key(original) == metadata_key(destination):
        raise MetadataError('source_conflict')
    if destination.exists():
        raise MetadataError('destination_exists')
    values = normalize_changes(changes)
    if not values and source is None:
        raise MetadataError('no_changes')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix='.exif-edit-') as directory:
        temporary_root = Path(directory).resolve()
        if not temporary_root.is_relative_to(destination.parent):
            raise MetadataError('source_conflict')
        target = temporary_root / ('edited' + original.suffix)
        shutil.copy2(original, target)
        # JSON 传递多行和中文字段，避免参数流中的内容被误当作选项
        payload = {'SourceFile': target.as_posix(), **values}
        if 'WhiteBalance' in values:
            value = values['WhiteBalance']
            payload['WhiteBalance'] = '0' if value == 'Auto' else '1'
            payload['LightSource'] = _LIGHT_SOURCES.get(value, 0)
        if 'GPSAltitude' in values:
            altitude = float(values['GPSAltitude'])
            payload['GPSAltitude'] = abs(altitude)
            payload['GPSAltitudeRef'] = 1 if altitude < 0 else 0
        if source is not None:
            payload['EXIF:Orientation'] = read_metadata(original).get('Orientation', '1')
        data_file = temporary_root / 'changes.json'
        data_file.write_text(json.dumps([payload], ensure_ascii=False), encoding='utf-8')
        arguments = ['-overwrite_original', '-n']
        if source is not None:
            arguments.extend(['-tagsFromFile', Path(source).resolve().as_posix(), '-All:All'])
            if strip_maker_notes:
                arguments.append('--MakerNotes')
        arguments.extend([f'-json={data_file.as_posix()}', target.as_posix()])
        _run_tool(arguments)
        # 独占创建最终文件，防止保存期间出现同名文件时被覆盖
        created = False
        try:
            with destination.open('xb') as output, target.open('rb') as incoming:
                created = True
                shutil.copyfileobj(incoming, output)
        except FileExistsError as error:
            raise MetadataError('destination_exists') from error
        except OSError as error:
            if created:
                destination.unlink(missing_ok=True)
            raise MetadataError('write_failed', detail=str(error)) from error
    return destination
