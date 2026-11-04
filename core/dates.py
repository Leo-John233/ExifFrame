"""水印日期的统一显示格式，不改写照片中的 EXIF 时间"""

import re
from datetime import date, datetime


def watermark_date(value, include_time=False):
    """默认仅显示点分日期，需要时显式附加小时与分钟"""
    if value is None:
        return ''
    if isinstance(value, (date, datetime)):
        value = value.isoformat(sep=' ') if isinstance(value, datetime) else value.isoformat()
    match = re.match(r'^\s*(\d{4})[-:./](\d{1,2})[-:./](\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?', str(value))
    if not match:
        return ''
    year, month, day = (int(match.group(index)) for index in (1, 2, 3))
    try:
        date(year, month, day)
    except ValueError:
        return ''
    result = f'{year:04d}.{month:02d}.{day:02d}'
    if include_time and match.group(4) is not None:
        hour, minute = int(match.group(4)), int(match.group(5))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            return ''
        result += f' {hour:02d}:{minute:02d}'
    return result
