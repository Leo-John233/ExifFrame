"""对已渲染的 Unicode 文本应用单字样式与匹配规则"""

import re


def _check_style(value):
    if not isinstance(value, dict):
        raise ValueError('单字样式必须是对象')
    if 'color' in value and (not isinstance(value['color'], str)
                             or not re.fullmatch(r'#[0-9A-Fa-f]{6}', value['color'])):
        raise ValueError('单字颜色应使用 #RRGGBB')
    if 'font' in value and not isinstance(value['font'], str):
        raise ValueError('单字字体应为字体名称或路径')


def validate_character_styles(char_styles, highlight_rules):
    if not isinstance(char_styles, dict):
        raise ValueError('单字索引应为非负整数')
    for index, style in char_styles.items():
        if not re.fullmatch(r'0|[1-9][0-9]*', str(index)):
            raise ValueError('单字索引应为非负整数')
        _check_style(style)
    if not isinstance(highlight_rules, list):
        raise ValueError('高亮规则必须是列表')
    for rule in highlight_rules:
        _check_style(rule)
        if not isinstance(rule.get('pattern'), str) or not rule['pattern']:
            raise ValueError('请输入匹配表达式')
        try:
            re.compile(rule['pattern'])
        except (re.error, OverflowError, RecursionError) as error:
            raise ValueError('匹配表达式无效') from error


def resolve_character_styles(text, char_styles=None, highlight_rules=None):
    """按规则顺序合并匹配区间，再逐属性应用显式字符索引"""
    indices = {} if char_styles is None else char_styles
    rules = [] if highlight_rules is None else highlight_rules
    validate_character_styles(indices, rules)
    resolved = [{} for _ in text]
    for rule in rules:
        style = {key: rule[key] for key in ('font', 'color') if rule.get(key)}
        if style:
            for match in re.finditer(rule['pattern'], text):
                for index in range(match.start(), match.end()):
                    resolved[index].update(style)
    if indices:
        for index, effective in enumerate(resolved):
            style = indices.get(str(index), indices.get(index))
            if style:
                effective.update({key: style[key] for key in ('font', 'color') if style.get(key)})
    return resolved
