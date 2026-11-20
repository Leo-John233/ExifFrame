"""桌面端的水印预览与导出服务"""

import configparser
import json
import math
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, field
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from types import SimpleNamespace

from jinja2 import Environment, pass_context
from PIL import Image, ImageColor, ImageOps

from core.brand_glyphs import validate_policy
from core.configs import logos_dir, templates_dir
from core import CONFIG_PATH
from core.image_cache import check_cancelled, photo_dimensions, photo_draft, photo_proxy
from core.runtime_paths import config_path, resource_path
from core.jinja2renders import auto_logo, vh, vw
from core.util import find_exiftool, get_exif
from core.metadata import merge_overrides, metadata_key
from core.geography import coordinate_degrees
from core.template_render import compiled_template, _prepare_footer_calls
from processor.core import start_process, uses_frame_layers

SUPPORTED_SUFFIXES = {'.jpg', '.jpeg', '.png', '.heic', '.heif'}
SETTINGS_PATH = config_path('desktop.json')
WORKSPACE_CONFIG_PATH = Path(CONFIG_PATH)
_protected_snapshot_lock = Lock()


@dataclass(frozen=True)
class Preset:
    """水印浏览列表中的模板信息"""

    name: str
    title: str
    description: str
    thumbnail: Path | None
    supports_footer: bool


@dataclass
class WatermarkSettings:
    """预览与导出共用一份参数快照"""

    template_name: str = '标准水印'
    title: str = ''
    subtitle: str = ''
    show_logo: bool = True
    font_scale: float = 1.0
    border_percent: int = 12
    border_override: bool = False
    background: str = '#FFFFFF'
    text_color: str = '#20252C'
    background_override: bool = False
    text_color_override: bool = False
    logo_choice: str = ''
    font_path: str = ''
    text_alignment: str = ''
    text_spacing: int | None = None
    line_spacing: int | None = None
    quality: int = 95
    subsampling: int = 2
    output_dir: str = ''
    input_dir: str = ''
    overwrite_existing: bool = False
    preserve_structure: bool = True
    use_template_styles: bool = True
    template_source: str = ''
    input_files: tuple[str, ...] = ()
    protected_sources: tuple[str, ...] = ()
    metadata_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    brand_glyph_policy: str = ''


_PRESET_INFO = {
    '极简无框角标': ('极简无框角标', '原图边缘的轻量参数角标', 'preset_inset_corner'),
    '拍立得经典宽底': ('拍立得经典宽底', '暖白宽底，突出照片和拍摄信息', 'preset_polaroid'),
    '毛玻璃悬浮卡片': ('毛玻璃悬浮卡片', '模糊背景衬托圆角照片', 'preset_glass'),
    '美术馆装裱画框': ('美术馆装裱画框', '米白留白营造装裱感', 'preset_gallery'),
    '35mm胶片暗房印记': ('35mm胶片暗房印记', '深色胶片边框与拍摄参数', 'preset_film'),
    '主色提取色卡栏': ('主色提取色卡栏', '从照片提取色彩并排展示', 'preset_palette'),
    '红标铭牌强调风': ('红标铭牌强调风', '深色底栏与红色品牌强调', 'preset_red_label'),
    '极简双行分割线': ('极简双行分割线', '双列信息与克制分隔线', 'preset_divider'),
    '标准水印': ('经典相机边框', '相机、镜头与拍摄参数，适合日常分享', 'standard1'),
    '标准水印2': ('留白与阴影', '圆角照片搭配轻盈阴影和宽边框', 'standard2'),
    '背景模糊': ('沉浸模糊背景', '延展画面色彩，居中展示拍摄信息', 'blur'),
    '尼康专用背景模糊': ('尼康模糊背景', '突出尼康 Z 标识的专属版式', 'nikon_blur'),
    '右下角参数': ('极简参数', '小巧文字落在右下角，保留画面重心', 'normal1'),
    '文件夹名+右下角参数': ('旅途与时间', '使用照片所在文件夹名称记录这次拍摄', 'normal2'),
    'logo居中': ('品牌居中', '品牌标识居中，两侧显示相机、镜头与拍摄参数', 'center_logo'),
    '仅标识居中': ('仅品牌标识', '底部仅显示品牌标识，适合简洁展示', 'center_logo_only'),
}


def list_presets() -> list[Preset]:
    """读取实际模板目录并补充易懂的名称与缩略图"""
    result = []
    for path in sorted(templates_dir.glob('*.json')):
        title, description, image = _PRESET_INFO.get(
            path.stem, (path.stem, '自定义水印模板', '')
        )
        thumbnail = resource_path('static') / f'{image}.jpeg'
        source = path.read_text(encoding='utf-8')
        result.append(Preset(
            path.stem, title, description,
            thumbnail if image and thumbnail.is_file() else None,
            '"watermark"' in source,
        ))
    # 常用边框排在前面，保留自定义模板的稳定顺序
    order = list(_PRESET_INFO)
    return sorted(result, key=lambda item: order.index(item.name) if item.name in order else len(order))


def _validate(settings: WatermarkSettings) -> None:
    """在进入图像处理前校验模板和可视参数"""
    for name in ('template_name', 'title', 'subtitle', 'input_dir', 'output_dir', 'template_source',
                 'logo_choice', 'font_path', 'text_alignment'):
        if not isinstance(getattr(settings, name), str):
            raise ValueError('文本设置格式无效，请重新加载配置')
    for name in ('show_logo', 'overwrite_existing', 'preserve_structure', 'use_template_styles', 'border_override',
                 'background_override', 'text_color_override'):
        if not isinstance(getattr(settings, name), bool):
            raise ValueError('开关设置格式无效，请重新加载配置')
    if not _template_path(settings.template_name).is_file():
        raise ValueError('水印模板不存在，请重新选择')
    if settings.brand_glyph_policy != '':
        validate_policy(settings.brand_glyph_policy)
    if not 0.5 <= settings.font_scale <= 2.0:
        raise ValueError('文字大小需在 50% 到 200% 之间')
    if not 6 <= settings.border_percent <= 30:
        raise ValueError('边框高度需在 6% 到 30% 之间')
    if not 1 <= settings.quality <= 100:
        raise ValueError('导出质量需在 1 到 100 之间')
    if settings.subsampling not in (0, 1, 2):
        raise ValueError('JPEG 色度采样需为 0、1 或 2')
    if settings.text_alignment not in ('', 'left', 'right'):
        raise ValueError('文字对齐方式无效')
    for value in (settings.text_spacing, settings.line_spacing):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 5000):
            raise ValueError('文字间距需为非负整数')
    for color in (settings.background, settings.text_color):
        ImageColor.getrgb(color)


def load_settings() -> WatermarkSettings:
    """损坏或过期的本机设置自动回退到默认值"""
    defaults = WatermarkSettings()
    # 读取原项目配置，使两种入口使用相同的输入输出目录和模板
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read(WORKSPACE_CONFIG_PATH, encoding='utf-8-sig')
        defaults.input_dir = config.get('DEFAULT', 'input_folder', fallback='')
        defaults.output_dir = config.get('DEFAULT', 'output_folder', fallback='')
        defaults.quality = config.getint('DEFAULT', 'quality', fallback=95)
        defaults.subsampling = config.getint('DEFAULT', 'subsampling', fallback=2)
        defaults.overwrite_existing = config.getboolean('DEFAULT', 'override_existed', fallback=False)
        defaults.template_name = config.get('render', 'template_name', fallback=defaults.template_name)
        _validate(defaults)
    except (OSError, ValueError, configparser.Error):
        defaults = WatermarkSettings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        valid = {field.name for field in fields(WatermarkSettings)}
        values = asdict(defaults)
        values.update({key: value for key, value in data.items() if key in valid and key not in {'template_source', 'input_files', 'protected_sources', 'metadata_overrides'}})
        if 'border_override' not in data:
            # 旧版默认 12 为自动，其他已保存数值保留为手动
            values['border_override'] = values['border_percent'] != 12
        for color, enabled in (('background', 'background_override'), ('text_color', 'text_color_override')):
            if enabled not in data:
                values[enabled] = ImageColor.getrgb(values[color]) != ImageColor.getrgb(getattr(defaults, color))
        # 共用字段始终以原项目配置为准，旧桌面缓存不再覆盖模板和导出参数
        if WORKSPACE_CONFIG_PATH.is_file():
            for key in ('template_name', 'input_dir', 'output_dir', 'quality', 'subsampling', 'overwrite_existing'):
                values[key] = getattr(defaults, key)
        settings = WatermarkSettings(**values)
        _validate(settings)
        if not isinstance(settings.title, str) or not isinstance(settings.subtitle, str):
            return defaults
        if not isinstance(settings.output_dir, str) or not isinstance(settings.show_logo, bool):
            return defaults
        return settings
    except (OSError, ValueError, TypeError, AttributeError):
        return defaults


def save_settings(settings: WatermarkSettings) -> None:
    """使用临时文件替换设置，避免中断留下半份内容"""
    _validate(settings)
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_suffix('.json.tmp')
    values = asdict(settings)
    # 未保存的模板草稿不写入个人配置
    values.pop('template_source', None)
    values.pop('input_files', None)
    values.pop('protected_sources', None)
    values.pop('metadata_overrides', None)
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(SETTINGS_PATH)


def save_workspace_settings(settings: WatermarkSettings) -> None:
    """显式保存时同步原项目配置，保留服务和编码等已有选项"""
    _validate(settings)
    from core.ini_preferences import update_ini_sections
    update_ini_sections(WORKSPACE_CONFIG_PATH, {
        'DEFAULT': {'input_folder': settings.input_dir, 'output_folder': settings.output_dir,
                    'quality': settings.quality, 'subsampling': settings.subsampling,
                    'override_existed': settings.overwrite_existing},
        'render': {'template_name': settings.template_name},
    })
    save_settings(settings)


def _template_path(name: str) -> Path:
    """限制模板名称为单个安全的 Windows 文件名"""
    if (not name or name != name.strip() or len(name) > 80 or name.endswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                                            *(f'COM{i}' for i in range(1, 10)),
                                            *(f'LPT{i}' for i in range(1, 10))}):
        raise ValueError('模板名称不能包含路径、特殊字符或 Windows 保留名称')
    target = templates_dir / f'{name}.json'
    if not target.resolve().is_relative_to(templates_dir.resolve()):
        raise ValueError('模板路径必须位于模板目录内')
    return target


def read_template(name: str) -> str:
    """读取完整模板源码以支持高级编辑"""
    return _template_path(name).read_text(encoding='utf-8')


def validate_template(source: str) -> None:
    """检查 Jinja 语法及普通模板的 JSON 结构"""
    from core.slot_style_metadata import strip_slot_metadata
    source = strip_slot_metadata(source)
    Environment().parse(_prepare_footer_calls(source))
    # 条件和循环模板的最终结构由照片预览进一步验证
    if '{%' not in source:
        try:
            nodes = json.loads(source)
        except ValueError:
            simplified = re.sub(r'\{\{.*?\}\}|\{#.*?#\}', '0', source, flags=re.S)
            nodes = json.loads(simplified)
        if not isinstance(nodes, list) or any(not isinstance(node, dict) for node in nodes):
            raise ValueError('模板必须是由处理步骤对象组成的 JSON 数组')


def write_template(name: str, source: str, create: bool = False) -> None:
    """新建模板采用独占写入，已有模板以临时文件原子替换"""
    target = _template_path(name)
    validate_template(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    if create:
        with target.open('x', encoding='utf-8') as stream:
            stream.write(source)
        return
    if not target.is_file():
        raise FileNotFoundError('模板不存在，请先新建模板')
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                            prefix='.template-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(source)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _metadata(source: str, modified: int) -> dict:
    """工具新增或更换后自动刷新缓存，避免继续使用缺失的回退信息"""
    tool = find_exiftool()
    signature = (str(tool), tool.stat().st_mtime_ns, tool.stat().st_size) if tool else None
    return dict(_cached_metadata(source, modified, Path(source).stat().st_size, signature))


@lru_cache(maxsize=64)
def _cached_metadata(source: str, modified: int, size: int, tool_signature) -> dict:
    """优先使用完整 ExifTool 数据，仅读取失败时回退照片自带信息"""
    if tool_signature:
        extracted = get_exif(source)
        if extracted:
            return extracted
    with Image.open(source) as opened:
        exif = opened.getexif()
        # 部分相机将镜头和拍摄参数放在子目录中
        details = dict(exif)
        try:
            details.update(exif.get_ifd(34665))
        except (KeyError, TypeError, ValueError, OSError):
            pass
        try:
            gps = exif.get_ifd(34853)
        except (KeyError, TypeError, ValueError, OSError):
            gps = {}
        shutter = details.get(33434)
        aperture = details.get(33437)
        focal = details.get(37386)
        equivalent = details.get(41989) or focal
        result = {
            'Make': str(details.get(271, 'default')),
            'CameraModelName': str(details.get(272, '未记录相机')),
            'LensModel': str(details.get(42036, '未记录镜头')),
            'FNumber': f'{float(aperture):g}' if aperture else '-',
            'FocalLength': f'{float(focal):g} mm' if focal else '-',
            'FocalLengthIn35mmFormat': f'{float(equivalent):g} mm' if equivalent else '-',
            'ShutterSpeed': (f'1/{round(1 / float(shutter))}' if float(shutter) < 1 else f'{float(shutter):g}') if shutter else '-',
            'ISO': str(details.get(34855, '-')),
            'DateTimeOriginal': str(details.get(36867) or details.get(306) or '未记录时间'),
        }
        # 没有外部工具时仍读取 GPS 子目录，保持位置字段可用
        for tag, reference, value_tag, ref_tag, latitude in (
                ('GPSLatitude', 'GPSLatitudeRef', 2, 1, True),
                ('GPSLongitude', 'GPSLongitudeRef', 4, 3, False)):
            coordinate = coordinate_degrees(gps.get(value_tag), gps.get(ref_tag), latitude=latitude)
            if coordinate is not None:
                result[tag] = f'{abs(coordinate):.12g}'
                positive, negative = ('N', 'S') if latitude else ('E', 'W')
                result[reference] = negative if math.copysign(1, coordinate) < 0 else positive
        altitude, reference = gps.get(6), gps.get(5)
        if altitude is not None:
            if isinstance(altitude, (tuple, list)) and len(altitude) == 2:
                altitude = f'{altitude[0]}/{altitude[1]}'
            elif hasattr(altitude, 'numerator') and hasattr(altitude, 'denominator'):
                altitude = f'{altitude.numerator}/{altitude.denominator}'
            result['GPSAltitude'] = altitude
        if reference is not None:
            if isinstance(reference, (bytes, bytearray)):
                reference = reference[0] if reference and reference[0] in (0, 1) else bytes(reference).decode('ascii', errors='ignore').strip('\x00')
            result['GPSAltitudeRef'] = reference
    # 清理相机写入的字符串终止符并统一回退时间格式
    result = {key: str(value).replace('\x00', '').strip() for key, value in result.items()}
    result['DateTimeOriginal'] = re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', result['DateTimeOriginal'])
    return result


def _selected_logo(choice, metadata):
    """将品牌或自定义图片解析为当前照片的标识"""
    path = Path(choice).expanduser()
    if path.is_absolute() or path.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
        from processor.logo_layer import resolve_logo_path
        path = resolve_logo_path(path)
        if not path.is_file():
            raise ValueError('所选标识图片不存在')
        return str(path.resolve()).replace('\\', '/')
    selected = auto_logo({'exif': metadata}, choice)
    if selected:
        return selected
    brand = choice.casefold().strip()
    for candidate in sorted(logos_dir.iterdir(), key=lambda item: item.name.casefold()):
        if (candidate.suffix.lower() in {'.png', '.jpg', '.jpeg'}
                and candidate.stem.casefold().startswith((brand + '_', brand + '-'))):
            return str(candidate.absolute()).replace('\\', '/')
    return None


@pass_context
def _configured_logo(context, brand=None):
    """在不修改模板的情况下应用照片自己的标识选择"""
    choice = context.get('_logo_choice', '')
    metadata = context.get('exif', {})
    if choice:
        return _selected_logo(choice, metadata)
    selected = auto_logo(context, brand)
    if selected:
        return selected
    name = brand or metadata.get('Make', '')
    first = re.split(r'[\s_-]+', str(name).strip(), maxsplit=1)[0]
    return _selected_logo(first, metadata) if first else None


def _uses_logo(nodes, logo):
    """识别模板已接入所选标识的路径，避免重复叠加"""
    from processor.logo_layer import resolve_logo_path
    needle = resolve_logo_path(logo).as_posix().casefold()
    if isinstance(nodes, list):
        return any(_uses_logo(item, logo) for item in nodes)
    if not isinstance(nodes, dict):
        return False
    for key, value in nodes.items():
        if key in {'exif', 'metadata', 'metadata_overrides'}:
            continue
        if key in {'left_logo', 'right_logo', 'center_logo', 'path', 'buffer_path'}:
            paths = value if isinstance(value, list) else [value]
            if any(isinstance(path, str) and path and resolve_logo_path(path).as_posix().casefold() == needle for path in paths):
                return True
        if isinstance(value, (dict, list)) and _uses_logo(value, logo):
            return True
    return False


def _overlay_logo(image, logo, *, collect_metadata=False):
    """为无标识槽位的版式添加右上角小标识"""
    bounds = (max(1, round(image.width * .08)), max(1, round(image.height * .08)))
    from processor.logo_layer import layer_logo, background_luma
    badge = layer_logo(logo, bounds)
    margin = max(1, round(min(image.size) * .02))
    x = max(0, image.width - badge.width - margin)
    lightness = background_luma(image, (x, margin, x + badge.width, margin + badge.height))
    badge = layer_logo(logo, bounds, background=lightness)
    canvas = image.convert('RGBA')
    canvas.alpha_composite(badge, (max(0, image.width - badge.width - margin), margin))
    canvas.info.update(image.info)
    if collect_metadata:
        from processor.render_slots import tag_logo, transfer_slots
        tag_logo(badge, {'_logo_slot_keys': {'right_logo': 'right_logo'}, 'right_logo': logo}, 'right_logo')
        transfer_slots(badge, canvas, (max(0, image.width - badge.width - margin), margin))
    return canvas


def _legacy_auto_colors(node, background=None):
    """旧底栏遇到自动文字色时使用对比色，不改动模板文件"""
    from processor.core import _parse_color

    try:
        red, green, blue, *_ = _parse_color(background if background is not None else node.get('color', 'white'))
        dark = red * .2126 + green * .7152 + blue * .0722 < 145
    except (TypeError, ValueError):
        dark = False
    color = '#FAFAF8' if dark else '#202124'
    for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom'):
        child = node.get(key)
        if not isinstance(child, dict):
            continue
        inherited_auto = child.get('color') == 'auto'
        if inherited_auto:
            child['color'] = color
        segments = child.get('text_segments')
        if isinstance(segments, str):
            if not inherited_auto and not re.search(r'"color"\s*:\s*"auto"', segments):
                continue
            try:
                segments = json.loads(segments)
            except ValueError:
                continue
            child['text_segments'] = segments
        if isinstance(segments, list):
            for segment in segments:
                if isinstance(segment, dict) and (segment.get('color') == 'auto'
                                                  or (inherited_auto and 'color' not in segment)):
                    segment['color'] = color


def _configure_nodes(nodes, image, settings, metadata, source, preview=False, source_scale=1.0,
                     preview_inputs=None, interactive=False):
    """为现有处理器注入尺寸与样式，同时复用内存中的预览图"""
    title = '' if settings.use_template_styles else settings.title
    subtitle = '' if settings.use_template_styles else settings.subtitle
    # 无边框模板把署名放进已有文字区，不额外遮挡照片
    text_nodes = [node for node in nodes if node.get('processor_name') in {'rich_text', 'multi_rich_text'}]
    for index, text in enumerate((title, subtitle)):
        if text and index < len(text_nodes):
            node = text_nodes[index]
            if node['processor_name'] == 'multi_rich_text':
                node['text_segments'] = [{'text': text}]
            else:
                node['text'] = text
        elif text and len(text_nodes) == 1 and index == 1:
            node = text_nodes[0]
            node['text'] = f"{node.get('text', '')}  {text}"
    for node in nodes:
        if node.get('processor_name') == 'watermark_with_timestamp' and (title or subtitle):
            segments = node.get('text_segments', [])
            if isinstance(segments, str):
                segments = json.loads(segments)
                node['text_segments'] = segments
            if title and isinstance(segments, list) and segments:
                segments[0]['text'] = title
            if subtitle and isinstance(segments, list) and segments:
                segments[-1]['text'] = subtitle

    def use_preview_inputs(node):
        paths = node.get('buffer_path')
        if not preview or not isinstance(paths, (list, tuple)) or not paths:
            return
        from processor.logo_layer import resolve_logo_path
        resolved = [resolve_logo_path(path) for path in paths]
        if preview_inputs and all(path in preview_inputs for path in resolved):
            entries = [preview_inputs[path] for path in resolved]
            node.update(input_buffer=[item[0].copy() for item in entries], buffer_loaded=True,
                        _preview_input_keys=[item[1] for item in entries])
        elif len(resolved) == 1 and resolved[0] == source:
            node.update(input_buffer=[image.copy()], buffer_loaded=True, _preview_source_input=True)

    def visit(node, in_watermark=False):
        if isinstance(node, list):
            for child in node:
                visit(child, in_watermark)
            return
        if not isinstance(node, dict):
            return
        kind = node.get('processor_name')
        if settings.brand_glyph_policy and not settings.use_template_styles and kind in {
                'watermark', 'watermark_with_timestamp', 'rich_text', 'multi_rich_text'}:
            node['brand_glyph_policy'] = settings.brand_glyph_policy
            segments = node.get('text_segments') or []
            if isinstance(segments, str):
                node['text_segments'] = segments = json.loads(segments)
            for segment in segments:
                if isinstance(segment, dict) and 'brand_glyph_policy' in segment:
                    segment['brand_glyph_policy'] = settings.brand_glyph_policy
        if kind == 'watermark':
            frame_requested = uses_frame_layers(node)
            if not frame_requested:
                background = settings.background if not settings.use_template_styles and settings.background_override else None
                _legacy_auto_colors(node, background)
            for key in ('left_logo', 'right_logo', 'center_logo'):
                if key in node and node[key] in (None, '', 'None'):
                    node[key] = None
        if kind:
            node.setdefault('exif', metadata)
            if preview:
                node['save_buffer'] = False
                if interactive:
                    node['_interactive_preview'] = True
                if kind in {'rich_text', 'multi_rich_text'} and not in_watermark and 'height' not in node:
                    node['height'] = max(1, round(100 * source_scale))
        if settings.use_template_styles:
            for key, value in list(node.items()):
                if key in {'exif', 'metadata', 'metadata_overrides'}:
                    continue
                if isinstance(value, (dict, list)):
                    visit(value, in_watermark or kind == 'watermark')
            if kind:
                use_preview_inputs(node)
            return
        if kind == 'watermark':
            if not settings.show_logo:
                for key in ('left_logo', 'right_logo', 'center_logo'):
                    if key in node:
                        node[key] = None
            elif settings.logo_choice:
                logo = _selected_logo(settings.logo_choice, metadata)
                keys = [key for key in ('left_logo', 'right_logo', 'center_logo') if node.get(key)]
                if not keys:
                    keys = [next((key for key in ('center_logo', 'right_logo', 'left_logo') if key in node), 'right_logo')]
                for key in keys:
                    node[key] = logo
            if settings.text_alignment:
                node['right_alignment'] = settings.text_alignment
            if settings.line_spacing is not None:
                node['middle_spacing'] = round(settings.line_spacing * source_scale)
            if settings.border_override:
                node['bottom_margin'] = max(1, round(image.height * settings.border_percent / 100))
            if settings.font_scale != 1:
                node['watermark_scale'] = float(node.get('watermark_scale', 1)) * settings.font_scale
            if settings.background_override:
                node['color'] = settings.background
                if frame_requested:
                    node['frame_color'] = settings.background
            if settings.text_color_override and frame_requested:
                node['text_color'] = settings.text_color
            # 居中标识模板同样支持自定义署名
            if settings.title and not node.get('left_top', {}).get('text'):
                child = node.get('left_top', {})
                if not child.get('text_segments'):
                    child.update(text=settings.title)
            if settings.subtitle and not node.get('left_bottom', {}).get('text'):
                node.get('left_bottom', {}).update(text=settings.subtitle)
        if kind == 'watermark_with_timestamp' and uses_frame_layers(node):
            if settings.border_override:
                node['bottom_margin'] = max(1, round(image.height * settings.border_percent / 100))
            if settings.background_override:
                node['frame_color'] = settings.background
            if settings.text_color_override:
                node['text_color'] = settings.text_color
        if kind in {'rich_text', 'multi_rich_text', 'watermark_with_timestamp'}:
            if settings.font_path:
                node['font_path'] = settings.font_path
                segments = node.get('text_segments', [])
                if isinstance(segments, str):
                    segments = json.loads(segments)
                    node['text_segments'] = segments
                if isinstance(segments, list):
                    for segment in segments:
                        if isinstance(segment, dict):
                            segment['font_path'] = settings.font_path
            if kind == 'multi_rich_text' and settings.text_spacing is not None:
                node['text_spacing'] = round(settings.text_spacing * source_scale)
            if not in_watermark:
                if 'height' in node and settings.font_scale != 1:
                    node['height'] = max(1, round(float(node['height']) * settings.font_scale))
                elif 'height' not in node and kind in {'rich_text', 'multi_rich_text'} and (source_scale != 1 or settings.font_scale != 1):
                    node['height'] = max(1, round(100 * source_scale * settings.font_scale))
                elif 'height' not in node and kind == 'watermark_with_timestamp' and settings.font_scale != 1:
                    node['height'] = max(1, round(int(image.height * .02) * settings.font_scale))
            if settings.text_color_override:
                node['color'] = settings.text_color
                segments = node.get('text_segments', [])
                if isinstance(segments, str):
                    segments = json.loads(segments)
                    node['text_segments'] = segments
                if isinstance(segments, list):
                    for segment in segments:
                        if isinstance(segment, dict):
                            segment['color'] = settings.text_color
        for key in ('left_logo', 'right_logo', 'center_logo'):
            if key in node and not settings.show_logo:
                node[key] = None
        for key, value in list(node.items()):
            if key in {'exif', 'metadata', 'metadata_overrides'}:
                continue
            if isinstance(value, (dict, list)):
                visit(value, in_watermark or kind == 'watermark')
        # 模糊背景等模板重新读取原图时也使用等比缩小后的图像
        if kind:
            use_preview_inputs(node)

    visit(nodes)


def _scale_nodes(value, scale):
    """同步缩放绝对像素参数，保持预览与原尺寸导出的布局比例"""
    pixels = {'width', 'height', 'border_radius', 'shadow_radius', 'blur_radius',
              'left_margin', 'right_margin', 'top_margin', 'bottom_margin',
              'middle_spacing', 'spacing', 'text_spacing', 'delimiter_width', 'center_logo_height',
              'center_logo_padding', 'center_height'}
    if isinstance(value, list):
        for child in value:
            _scale_nodes(child, scale)
    elif isinstance(value, dict):
        defaults = {'blur': ('blur_radius', 5), 'rounded_corner': ('border_radius', 10),
                    'shadow': ('shadow_radius', 30), 'concat': ('spacing', 10)}
        kind = value.get('processor_name')
        default = defaults.get(kind) if isinstance(kind, str) else None
        if default is not None and value.get(default[0]) is None:
            value[default[0]] = default[1]
        for key, child in list(value.items()):
            if key in {'exif', 'metadata', 'metadata_overrides', 'custom_frame'}:
                continue
            if key in pixels:
                value[key] = round(float(child) * scale)
            elif key in {'offset', 'offsets'}:
                def resize_offsets(offset):
                    return [resize_offsets(item) for item in offset] if isinstance(offset, list) else round(offset * scale)
                value[key] = json.dumps(resize_offsets(json.loads(child)))
            elif isinstance(child, (dict, list)):
                _scale_nodes(child, scale)


def _preview_input_paths(nodes):
    """收集处理器显式引用的照片，不读取元数据字典"""
    result = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            paths = value.get('buffer_path') if value.get('processor_name') else None
            if isinstance(paths, (list, tuple)):
                from processor.logo_layer import resolve_logo_path
                result.extend(resolve_logo_path(path) for path in paths)
            for key, child in value.items():
                if key not in {'exif', 'metadata', 'metadata_overrides'} and isinstance(child, (dict, list)):
                    visit(child)

    visit(nodes)
    return result


def _preview_inputs(nodes, source, image, original_size, info, cancelled, *, interactive=False):
    """所有输入使用共同缩放比例，避免多照片布局失配"""
    paths = list(dict.fromkeys(_preview_input_paths(nodes)))
    sizes = {source: original_size}
    for path in paths:
        if path not in sizes:
            sizes[path] = photo_dimensions(path, cancelled=cancelled)[0]
    max_edge = max(max(size) for size in sizes.values())
    max_side = 900 if interactive else 1800
    load_proxy = photo_draft if interactive else photo_proxy
    quality = 'draft' if interactive else 'proxy'
    scale = min(1.0, max_side / max_edge)
    source_limit = max(1, round(max(original_size) * scale))
    if source_limit < max(image.size):
        image, _, _ = load_proxy(source, max_side=source_limit, cancelled=cancelled)
    # 像素取整可能让极小主图的实际比例偏大，始终遵循共同上限
    source_scale = min(scale, image.width / original_size[0], image.height / original_size[1])
    source_key = ('source', str(source), info.st_mtime_ns, info.st_size, image.size, image.mode, quality, source_limit)
    inputs = {source: (image, source_key)}
    for path in paths:
        if path in inputs:
            continue
        check_cancelled(cancelled)
        before = path.stat()
        limit = min(max_side, max(1, round(max(sizes[path]) * source_scale)))
        other, actual_size, _ = load_proxy(path, max_side=limit, cancelled=cancelled)
        after = path.stat()
        if (actual_size != sizes[path] or
                (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size)):
            raise OSError('照片在预览期间发生变化，请重试')
        key = ('source', str(path), before.st_mtime_ns, before.st_size, other.size, other.mode, quality, limit)
        inputs[path] = (other, key)
    return image, source_key, inputs, source_scale


def _preview_file_signature(template_source, files):
    """引用批次照片的模板需要随相关文件变化更新预览"""
    if not re.search(r'\bfiles\b', template_source):
        return ()
    result = []
    for path in files:
        try:
            info = Path(path).stat()
            result.append((str(path), info.st_mtime_ns, info.st_size))
        except OSError:
            result.append((str(path), None, None))
    return tuple(result)


def _output_rgb(image, settings):
    """预览和导出共享透明度转换"""
    if settings.use_template_styles or not settings.background_override:
        return image.convert('RGB')
    canvas = Image.new('RGB', image.size, settings.background)
    canvas.paste(image, mask=image.getchannel('A') if image.mode == 'RGBA' else None)
    return canvas


def _terminal_frame_input_size(nodes, original_size, settings, metadata, source):
    """计算常见内置多步模板进入末尾画框前的原尺寸"""
    prefix = nodes[:-1]
    if not prefix:
        return original_size
    last = prefix[-1]
    if last.get('processor_name') == 'crop':
        width, height = int(last.get('width') or 0), int(last.get('height') or 0)
        if width > 0 and height > 0:
            return width, height
    if any(node.get('select') is not None or node.get('buffer_path') or node.get('input_buffer')
           for node in prefix):
        return None
    # 内置角标由原图和一行文字对齐合成，只需实际生成小尺寸字图
    if (len(prefix) == 2 and prefix[0].get('processor_name') in {'rich_text', 'multi_rich_text'}
            and prefix[1].get('processor_name') == 'alignment'):
        from processor.core import PipelineContext, get_processor

        configured = deepcopy(prefix)
        _configure_nodes(configured, SimpleNamespace(height=original_size[1]), settings, metadata, source)
        configured[0]['save_buffer'] = False
        context = PipelineContext(configured[0])
        get_processor(configured[0]['processor_name'])().process(context)
        images = context.get_buffer()
        if len(images) == 1:
            return max(original_size[0], images[0].width), max(original_size[1], images[0].height)
        return None
    known = {'rounded_corner', 'blur', 'shadow', 'watermark', 'watermark_with_timestamp', 'margin', 'resize', 'crop'}
    if any(node.get('processor_name') not in known for node in prefix):
        return None
    configured = deepcopy(prefix)
    _configure_nodes(configured, SimpleNamespace(height=original_size[1]), settings, metadata, source)
    width, height = original_size
    for node in configured:
        kind = node['processor_name']
        if kind == 'shadow':
            radius = int(node.get('shadow_radius') or 0) if node.get('shadow_radius') is not None else 30
            if radius > 0:
                width, height = width + radius * 4, height + radius * 4
        elif kind in {'watermark', 'watermark_with_timestamp'}:
            if uses_frame_layers(node):
                from processor.frame_layers import frame_geometry
                width, height = frame_geometry((width, height), node)['canvas_size']
            else:
                from processor.custom_frame import legacy_composite_size
                width, height = legacy_composite_size((width, height), node)
        elif kind == 'margin':
            width += int(node.get('left_margin') or 0) + int(node.get('right_margin') or 0)
            height += int(node.get('top_margin') or 0) + int(node.get('bottom_margin') or 0)
        elif kind == 'resize':
            w, h, scale = node.get('width'), node.get('height'), node.get('scale')
            if w and h:
                width, height = int(w), int(h)
            elif w or h or scale:
                factor = float(w) / width if w else float(h) / height if h else float(scale)
                width, height = int(width * factor), int(height * factor)
            else:
                return None
        elif kind == 'crop':
            w, h = int(node.get('width') or 0), int(node.get('height') or 0)
            width, height = w if w > 0 else width, h if h > 0 else height
    return width, height


def _nearest_frame_ratio(size, node):
    """未知管线保留近似尺寸，同时对齐声明的固定画幅"""
    if node.get('processor_name') not in {'watermark', 'watermark_with_timestamp'}:
        return size
    frame = node.get('custom_frame')
    geometry = frame.get('geometry') if isinstance(frame, dict) else None
    if not isinstance(geometry, dict) or geometry.get('canvas_mode') != 'aspect_ratio':
        return size
    value = geometry.get('ratio', '4:5')
    try:
        if isinstance(value, str) and ':' in value:
            left, right = value.split(':', 1)
            ratio = Fraction(left.strip()) / Fraction(right.strip())
            if not (left.strip().isdigit() and right.strip().isdigit()):
                ratio = ratio.limit_denominator(1000)
        else:
            ratio = Fraction(str(value)).limit_denominator(1000)
        if ratio <= 0:
            return size
        width_unit, height_unit = ratio.numerator, ratio.denominator
        divisor = width_unit * width_unit + height_unit * height_unit
        multiple = max(1, (size[0] * width_unit + size[1] * height_unit + divisor // 2) // divisor)
        return width_unit * multiple, height_unit * multiple
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return size


def _rendered_rows(nodes):
    """提取模板渲染及快捷样式应用后的区域文字"""
    from core.footer import text_targets
    from processor.generators import rendered_text

    _, targets = text_targets(nodes)
    return {key: rendered_text(node or {}) for key, _, _, node in targets}


def render_photo(path: Path, settings: WatermarkSettings, preview: bool = True, *,
                 full_resolution: bool = False, cancelled=None, interactive: bool = False) -> Image.Image:
    """代理预览与原尺寸导出共用水印流水线"""
    check_cancelled(cancelled)
    _validate(settings)
    source = Path(path).resolve()
    if source.suffix.lower() not in SUPPORTED_SUFFIXES or not source.is_file():
        raise ValueError('请选择存在的 JPG、PNG 或 HEIC 照片')
    info = source.stat()
    if preview and not full_resolution:
        load_proxy = photo_draft if interactive else photo_proxy
        image, original_size, encoded_size = load_proxy(source, cancelled=cancelled)
    else:
        with Image.open(source) as opened:
            encoded_size = opened.size
            image = ImageOps.exif_transpose(opened).copy()
        original_size = image.size
    check_cancelled(cancelled)
    if preview:
        current = source.stat()
        if (current.st_mtime_ns, current.st_size) != (info.st_mtime_ns, info.st_size):
            raise OSError('照片在预览期间发生变化，请重试')
    profile = image.info.get('icc_profile')
    metadata = dict(_metadata(str(source), info.st_mtime_ns))
    check_cancelled(cancelled)
    changes = settings.metadata_overrides.get(metadata_key(source), {})
    if changes:
        metadata = merge_overrides(metadata, changes)
    # 模板按编码尺寸计算 vh/vw，快捷样式保留相同的方向语义
    metadata.setdefault('ImageWidth', str(encoded_size[0]))
    metadata.setdefault('ImageHeight', str(encoded_size[1]))
    if settings.title and not settings.use_template_styles:
        metadata['CameraModelName'] = settings.title
    if settings.subtitle and not settings.use_template_styles:
        metadata['LensModel'] = settings.subtitle
    template = compiled_template(settings.template_source or read_template(settings.template_name), _configured_logo)
    rendered = template.render(exif=metadata, filename=source.stem,
                               file_dir=source.parent.as_posix(), file_path=source.as_posix(),
                               files=list(settings.input_files) or [str(source)],
                               _logo_choice='' if settings.use_template_styles else settings.logo_choice)
    check_cancelled(cancelled)
    nodes = json.loads(rendered)
    if not isinstance(nodes, list) or not nodes:
        raise ValueError('水印模板需要至少一个处理步骤')
    preview_inputs = None
    source_key = None
    source_scale = 1.0
    if preview and not full_resolution:
        image, source_key, preview_inputs, source_scale = _preview_inputs(
            nodes, source, image, original_size, info, cancelled, interactive=interactive)
        current = source.stat()
        if (current.st_mtime_ns, current.st_size) != (info.st_mtime_ns, info.st_size):
            raise OSError('照片在预览期间发生变化，请重试')
    elif preview:
        source_key = ('source', str(source), info.st_mtime_ns, info.st_size, image.size, image.mode, 'full')
        preview_inputs = {source: (image, source_key)}
    full_size = None
    if preview and not full_resolution and source_scale != 1 and nodes[-1].get('processor_name') == 'crop':
        width, height = int(nodes[-1].get('width') or 0), int(nodes[-1].get('height') or 0)
        if width > 0 and height > 0:
            full_size = (width, height)
    frame_geometry_node = None
    frame_input_size = original_size
    if preview and not full_resolution and source_scale != 1:
        node = nodes[-1]
        paths = node.get('buffer_path')
        if paths:
            direct = (isinstance(paths, (list, tuple)) and len(paths) == 1
                      and Path(paths[0]).resolve() == source)
        else:
            direct = len(nodes) == 1
            if not direct and isinstance(node.get('select'), str):
                try:
                    direct = json.loads(node['select']) == [0]
                except (TypeError, ValueError):
                    pass
            if not direct and node.get('select') is None and 'custom_frame' in node:
                frame_input_size = _terminal_frame_input_size(nodes, original_size, settings, metadata, source)
                direct = frame_input_size is not None
        if node.get('processor_name') in {'watermark', 'watermark_with_timestamp'} and direct and uses_frame_layers(node):
            keys = ('frame_style', 'overlay_mode', 'frame_margin', 'frame_bottom', 'frame_radius',
                    'frame_shadow', 'frame_blur', 'frame_brightness', 'frame_vignette',
                    'frame_color', 'color', 'bottom_margin', 'custom_frame')
            frame_geometry_node = (deepcopy(node) if 'custom_frame' in node else
                                   {key: node[key] for key in keys if key in node})
    if image.size != original_size:
        _scale_nodes(nodes, source_scale)
    _configure_nodes(nodes, image, settings, metadata, source, preview=preview, source_scale=source_scale,
                     preview_inputs=preview_inputs, interactive=interactive and preview and not full_resolution)
    if frame_geometry_node is not None:
        from processor.frame_layers import frame_geometry
        if 'custom_frame' in frame_geometry_node:
            # 旧版组合的画布依赖完整节点和快捷样式，按原图尺寸注入一次
            original = SimpleNamespace(height=original_size[1])
            _configure_nodes([frame_geometry_node], original, settings, metadata, source)
        elif not settings.use_template_styles and settings.border_override:
            frame_geometry_node['bottom_margin'] = max(1, round(original_size[1] * settings.border_percent / 100))
        full_size = frame_geometry(frame_input_size, frame_geometry_node)['canvas_size']
    check_cancelled(cancelled)
    rendered_rows = _rendered_rows(nodes) if preview else None
    image_id = ('file', str(source), info.st_mtime_ns, info.st_size)
    result = start_process(nodes, initial_buffer=[image], preview_source_key=source_key,
                           cancelled=cancelled, image_id=image_id, collect_metadata=preview)
    check_cancelled(cancelled)
    if not settings.use_template_styles and settings.show_logo and settings.logo_choice:
        logo = _selected_logo(settings.logo_choice, metadata)
        if logo and not _uses_logo(nodes, logo):
            result = _overlay_logo(result, logo, collect_metadata=preview)
            check_cancelled(cancelled)
    if preview:
        if not full_resolution and source_scale != 1:
            if full_size is None:
                full_size = (max(1, round(result.width / source_scale)),
                             max(1, round(result.height / source_scale)))
                full_size = _nearest_frame_ratio(full_size, nodes[-1])
        else:
            full_size = result.size
        from processor.render_slots import complete_slots, finish_slots, resolved_style
        complete_slots(nodes, result)
        rendered_slots = finish_slots(result, full_size)
        rendered_style = resolved_style(nodes, source_scale)
        rendered_style['logo'] = next((item.get('logo') for item in rendered_slots
                                      if item.get('logo') and item.get('visible') and item.get('bbox')),
                                     rendered_style.get('logo'))
        result = _output_rgb(result, settings)
        if not full_resolution:
            max_side = 900 if interactive else 1800
            sampling = Image.Resampling.BILINEAR if interactive else Image.Resampling.LANCZOS
            result.thumbnail((max_side, max_side), sampling)
        result.info['preview_full_size'] = full_size
        result.info['preview_source_size'] = original_size
        result.info['preview_rendered_rows'] = rendered_rows
        result.info['preview_rendered_slots'] = rendered_slots
        result.info['preview_rendered_style'] = rendered_style
    if profile:
        result.info['icc_profile'] = profile
    return result


def _protected_source_index(settings: WatermarkSettings):
    """每份导出快照仅解析一次源路径和文件标识"""
    key = (settings.input_files, settings.protected_sources)
    cached = getattr(settings, '_protected_source_index', None)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]
    with _protected_snapshot_lock:
        cached = getattr(settings, '_protected_source_index', None)
        if cached is None or cached[0] != key:
            paths = set()
            identities = set()
            for item in (*settings.input_files, *settings.protected_sources):
                protected = Path(item).expanduser().resolve()
                paths.add(protected)
                try:
                    info = protected.stat()
                    identities.add((info.st_dev, info.st_ino))
                except OSError:
                    pass
            cached = (key, frozenset(paths), frozenset(identities))
            settings._protected_source_index = cached
    return cached[1], cached[2]


def export_photo(path: Path, settings: WatermarkSettings, output_dir: Path) -> Path:
    """保留输入目录结构，按覆盖开关处理已有输出并始终保护原照片"""
    source = Path(path).resolve()
    destination = Path(output_dir).expanduser().resolve()
    input_root = Path(settings.input_dir).expanduser().resolve() if settings.input_dir else None
    in_workspace = input_root is not None and source.is_relative_to(input_root)
    relative = source.relative_to(input_root) if in_workspace else Path(source.name)
    if in_workspace and settings.preserve_structure:
        destination /= relative.parent
    destination.mkdir(parents=True, exist_ok=True)
    basename = source.stem if in_workspace else f'{source.stem}_watermarked'
    extension = '.png' if source.suffix.lower() == '.png' else '.jpg'
    image_format = 'PNG' if extension == '.png' else 'JPEG'
    target = destination / f'{basename}{extension}'
    if target.resolve() == source or (target.exists() and target.samefile(source)):
        raise ValueError('输出文件与原照片相同，请选择其他输出目录')
    # 同名 PNG 与 JPEG 可能属于两张原片，不允许覆盖输入目录中的其他照片
    if settings.overwrite_existing and target.exists():
        inside_input = input_root is not None and target.resolve().is_relative_to(input_root)
        if inside_input or target.parent == source.parent:
            raise ValueError('不能覆盖输入目录中的照片，请选择独立的输出目录')
        # 保护整个导入队列，包括未勾选照片和同一文件的其他路径
        paths, identities = _protected_source_index(settings)
        info = target.stat()
        if target.resolve() in paths or (info.st_dev, info.st_ino) in identities:
            raise ValueError('不能覆盖已导入的原照片，请选择独立的输出目录')
    if in_workspace and target.exists() and not settings.overwrite_existing:
        raise FileExistsError(f'已跳过同名输出：{target.name}')
    image = render_photo(source, settings, preview=False)
    canvas = _output_rgb(image, settings)
    save_options = {'quality': settings.quality, 'subsampling': settings.subsampling}
    if not settings.use_template_styles:
        save_options['icc_profile'] = image.info.get('icc_profile')
    if settings.overwrite_existing:
        with NamedTemporaryFile(dir=destination, prefix='.export-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            canvas.save(temporary, format=image_format, **save_options)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
    number = 0
    while True:
        suffix = f'_{number}' if number else ''
        target = destination / f'{basename}{suffix}{extension}'
        try:
            stream = target.open('xb')
        except FileExistsError:
            if in_workspace:
                raise
            number += 1
            continue
        try:
            with stream:
                canvas.save(stream, format=image_format, **save_options)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
