"""原子更新配置中指定的键，保留其他设置、注释与原有换行"""

import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from core.runtime_paths import _seed_lock


def _update(text, section, changes):
    values = {key.lower(): str(value) for key, value in changes.items()}
    if any('\n' in value or '\r' in value for value in values.values()):
        raise ValueError('配置值必须在同一行')
    eol = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines(keepends=True)
    start = end = None
    for index, line in enumerate(lines):
        header = re.match(r'^\s*\[([^]]+)\]', line)
        if header:
            if start is not None:
                end = index
                break
            if header[1] == section:
                start = index + 1
    if start is None:
        prefix = '' if not text or text.endswith(('\n', '\r')) else eol
        lines.append(f'{prefix}[{section}]{eol}')
        start = len(lines)
    if end is None:
        end = len(lines)
    for index in range(start, end):
        match = re.match(r'^([ \t]*([^#;:=\s][^:=]*?)[ \t]*[=:][ \t]*)(.*?)([ \t]*)(\r?\n|$)', lines[index])
        if match and (key := match[2].strip().lower()) in values:
            lines[index] = match[1] + values.pop(key) + match[4] + match[5]
    if values:
        if end and not lines[end-1].endswith(('\n', '\r')):
            lines[end-1] += eol
        lines[end:end] = [f'{key} = {value}{eol}' for key, value in values.items()]
    return ''.join(lines)


def update_ini_sections(path, sections):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _seed_lock(path.parent / '.preferences.lock'):
        data = path.read_bytes() if path.exists() else b''
        text = data.decode('utf-8-sig')
        for section, changes in sections.items():
            text = _update(text, section, changes)
        encoded = text.encode('utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8')
        if encoded == data:
            return
        temporary = None
        try:
            with NamedTemporaryFile(dir=path.parent, prefix='.preferences-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def update_ini_values(path, section, changes):
    update_ini_sections(path, {section: changes})
