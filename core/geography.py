"""将 EXIF 坐标转换为完整的度分秒地理位置"""

import math
import re
from fractions import Fraction


_DIRECTIONS = {'N': 'N', 'NORTH': 'N', '北': 'N', '北纬': 'N',
               'S': 'S', 'SOUTH': 'S', '南': 'S', '南纬': 'S',
               'E': 'E', 'EAST': 'E', '东': 'E', '东经': 'E',
               'W': 'W', 'WEST': 'W', '西': 'W', '西经': 'W'}
_NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:/\d+(?:\.\d*)?)?'
_DIRECTION = r'NORTH|SOUTH|EAST|WEST|北纬|南纬|东经|西经|[NSEW北南东西]'


def _text(value):
    """兼容 EXIF 的字节引用和字符串终止符"""
    if isinstance(value, bytes):
        value = value.decode('ascii', errors='ignore')
    return str(value).replace('\x00', '').strip() if value is not None else ''


def _float(value):
    if isinstance(value, bool):
        raise ValueError
    number = float(Fraction(value)) if isinstance(value, str) and '/' in value else float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def coordinate_degrees(value, reference=None, latitude=True):
    """兼容十进制、度分秒字符串和 EXIF 三元有理数坐标"""
    allowed = {'N', 'S'} if latitude else {'E', 'W'}
    ref_text = _text(reference).upper()
    direction = _DIRECTIONS.get(ref_text) if ref_text else None
    if ref_text and direction not in allowed:
        return None
    try:
        if isinstance(value, (tuple, list)):
            if len(value) != 3:
                return None
            parts = [_float(part) for part in value]
        elif isinstance(value, str) or isinstance(value, bytes):
            text = _text(value).upper()
            if not text:
                return None
            marker = re.search(r'(?<![A-Z])(' + _DIRECTION + r')\s*$', text)
            if marker is None:
                marker = re.search(r'^\s*(' + _DIRECTION + r')(?![A-Z])', text)
            suffix = _DIRECTIONS.get(marker.group(1)) if marker else None
            if suffix and (suffix not in allowed or direction and suffix != direction):
                return None
            direction = suffix or direction
            number_strings = re.findall(_NUMBER, text)
            remainder = re.sub(_NUMBER, '', text)
            remainder = re.sub(r'DEGREES?|DEG|度|分|秒|' + _DIRECTION, '', remainder)
            if remainder.strip(' \t\r\n°\'"′″,，;；()[]'):
                return None
            parts = [_float(part) for part in number_strings]
            if not 1 <= len(parts) <= 3:
                return None
        else:
            parts = [_float(value)]
        degree = parts[0]
        negative = math.copysign(1.0, degree) < 0
        minutes = parts[1] if len(parts) > 1 else 0
        seconds = parts[2] if len(parts) > 2 else 0
        if not 0 <= minutes <= 60 or not 0 <= seconds <= 60:
            return None
        magnitude = abs(degree) + minutes / 60 + seconds / 3600
        if magnitude > (90 if latitude else 180):
            return None
        positive = 'N' if latitude else 'E'
        if negative and direction == positive:
            return None
        negative = negative or direction in {'S', 'W'}
        return -magnitude if negative else magnitude
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None


def _display_coordinate(value, latitude):
    """按整秒四舍五入并正确进位，不给分秒补前导零"""
    total = math.floor(abs(value) * 3600 + .5 + 1e-8)
    degrees, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    negative = math.copysign(1.0, value) < 0
    direction = ('S' if negative else 'N') if latitude else ('W' if negative else 'E')
    return f'{degrees}°{minutes}\'{seconds}"{direction}'


def format_location(metadata: dict) -> str:
    """只在经纬度完整有效时显示一项位置，避免留下半组坐标"""
    latitude = coordinate_degrees(metadata.get('GPSLatitude'), metadata.get('GPSLatitudeRef'), latitude=True)
    longitude = coordinate_degrees(metadata.get('GPSLongitude'), metadata.get('GPSLongitudeRef'), latitude=False)
    if latitude is None or longitude is None:
        return ''
    return _display_coordinate(latitude, True) + ' ' + _display_coordinate(longitude, False)
