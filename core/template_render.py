"""缓存模板编译结果并正确转义 JSON 字符串中的照片信息"""

import json
from functools import lru_cache

from jinja2 import Environment

from core.jinja2renders import auto_logo, vh, vw


def _json_string(value):
    """只转义字符串内容，不改变模板中独立数组和数值的类型"""
    return json.dumps(str(value) if value is not None else '', ensure_ascii=False)[1:-1]


def _escape_string_variables(source):
    """用 Jinja 词法位置区分字符串插值和 files|tojson 等独立表达式"""
    output, expression = [], []
    quoted = escaped = False
    inside_variable = False
    escape_variable = False
    for _, kind, value in Environment().lex(source):
        if kind == 'variable_begin':
            inside_variable, escape_variable = True, quoted
            output.append(value)
            expression = []
        elif kind == 'variable_end':
            body = ''.join(expression)
            output.append(f'({body}) | json_string' if escape_variable else body)
            output.append(value)
            inside_variable = False
        elif inside_variable:
            expression.append(value)
        else:
            output.append(value)
            if kind == 'data':
                for character in value:
                    if escaped:
                        escaped = False
                    elif quoted and character == '\\':
                        escaped = True
                    elif character == '"':
                        quoted = not quoted
    return ''.join(output)


@lru_cache(maxsize=32)
def compiled_template(source: str, logo=auto_logo):
    """不可变编译结果可由后台任务共享，照片变量仍逐次传入"""
    environment = Environment(autoescape=False)
    environment.filters['json_string'] = _json_string
    environment.globals.update(vh=vh, vw=vw, auto_logo=logo)
    return environment.from_string(_escape_string_variables(source))
