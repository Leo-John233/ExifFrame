"""桌面端的水印预览与导出服务"""

import configparser
import json
import re
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

from jinja2 import Environment, pass_context
from PIL import Image, ImageColor, ImageOps

from core.configs import logos_dir, templates_dir
from core import CONFIG_PATH
from core.jinja2renders import auto_logo, vh, vw
from core.util import EXIFTOOL_PATH, get_exif
from processor.core import start_process

SUPPORTED_SUFFIXES = {'.jpg', '.jpeg', '.png', '.heic', '.heif'}
SETTINGS_PATH = Path('config/desktop.json')
WORKSPACE_CONFIG_PATH = Path(CONFIG_PATH)


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
    background: str = '#FFFFFF'
    text_color: str = '#20252C'
    quality: int = 95
    output_dir: str = ''
    input_dir: str = ''
    overwrite_existing: bool = False
    preserve_structure: bool = True
    use_template_styles: bool = True
    template_source: str = ''


_PRESET_INFO = {
    '标准水印': ('经典相机边框', '相机、镜头与拍摄参数，适合日常分享', 'standard1'),
    '标准水印2': ('留白与阴影', '圆角照片搭配轻盈阴影和宽边框', 'standard2'),
    '背景模糊': ('沉浸模糊背景', '延展画面色彩，居中展示拍摄信息', 'blur'),
    '尼康专用背景模糊': ('尼康模糊背景', '突出尼康 Z 标识的专属版式', 'nikon_blur'),
    '右下角参数': ('极简参数', '小巧文字落在右下角，保留画面重心', 'normal1'),
    '文件夹名+右下角参数': ('旅途与时间', '使用照片所在文件夹名称记录这次拍摄', 'normal2'),
    'logo居中': ('品牌居中', '居中品牌标识搭配简洁留白', 'center_logo'),
}


def list_presets() -> list[Preset]:
    """读取实际模板目录并补充易懂的名称与缩略图"""
    result = []
    for path in sorted(templates_dir.glob('*.json')):
        title, description, image = _PRESET_INFO.get(
            path.stem, (path.stem, '自定义水印模板', '')
        )
        thumbnail = Path('static') / f'{image}.jpeg'
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
    if settings.template_name not in {preset.name for preset in list_presets()}:
        raise ValueError('水印模板不存在，请重新选择')
    if not 0.5 <= settings.font_scale <= 2.0:
        raise ValueError('文字大小需在 50% 到 200% 之间')
    if not 6 <= settings.border_percent <= 30:
        raise ValueError('边框高度需在 6% 到 30% 之间')
    if not 1 <= settings.quality <= 100:
        raise ValueError('导出质量需在 1 到 100 之间')
    for color in (settings.background, settings.text_color):
        ImageColor.getrgb(color)


def load_settings() -> WatermarkSettings:
    """损坏或过期的本机设置自动回退到默认值"""
    defaults = WatermarkSettings()
    # 读取原项目配置，使两种入口使用相同的输入输出目录和模板
    config = configparser.ConfigParser()
    try:
        config.read(WORKSPACE_CONFIG_PATH, encoding='utf-8')
        defaults.input_dir = config.get('DEFAULT', 'input_folder', fallback='')
        defaults.output_dir = config.get('DEFAULT', 'output_folder', fallback='')
        defaults.quality = config.getint('DEFAULT', 'quality', fallback=95)
        defaults.overwrite_existing = config.getboolean('DEFAULT', 'override_existed', fallback=False)
        defaults.template_name = config.get('render', 'template_name', fallback=defaults.template_name)
        _validate(defaults)
    except (OSError, ValueError, configparser.Error):
        defaults = WatermarkSettings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        valid = {field.name for field in fields(WatermarkSettings)}
        values = asdict(defaults)
        values.update({key: value for key, value in data.items() if key in valid and key != 'template_source'})
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
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(SETTINGS_PATH)


def save_workspace_settings(settings: WatermarkSettings) -> None:
    """显式保存时同步原项目配置，保留服务和编码等已有选项"""
    _validate(settings)
    config = configparser.ConfigParser()
    config.read(WORKSPACE_CONFIG_PATH, encoding='utf-8')
    config['DEFAULT'].update(input_folder=settings.input_dir, output_folder=settings.output_dir,
                             quality=str(settings.quality), override_existed=str(settings.overwrite_existing))
    if not config.has_section('render'):
        config.add_section('render')
    config.set('render', 'template_name', settings.template_name)
    WORKSPACE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = WORKSPACE_CONFIG_PATH.with_suffix('.ini.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        config.write(stream)
    temporary.replace(WORKSPACE_CONFIG_PATH)
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
    Environment().parse(source)
    # 条件和循环模板的最终结构由照片预览进一步验证
    if '{%' not in source:
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


@lru_cache(maxsize=64)
def _metadata(source: str, modified: int) -> dict:
    """按文件修改时间缓存信息，没有 ExifTool 时使用照片自带的 EXIF"""
    with Image.open(source) as opened:
        exif = opened.getexif()
        # 部分相机将镜头和拍摄参数放在子目录中
        details = dict(exif)
        try:
            details.update(exif.get_ifd(34665))
        except (KeyError, TypeError, ValueError, OSError):
            pass
        shutter = details.get(33434)
        aperture = details.get(33437)
        focal = details.get(37386)
        result = {
            'Make': str(details.get(271, 'default')),
            'CameraModelName': str(details.get(272, '未记录相机')),
            'LensModel': str(details.get(42036, '未记录镜头')),
            'FNumber': f'{float(aperture):g}' if aperture else '-',
            'FocalLengthIn35mmFormat': str(details.get(41989) or (f'{float(focal):g} mm' if focal else '-')),
            'ShutterSpeed': (f'1/{round(1 / float(shutter))}' if float(shutter) < 1 else f'{float(shutter):g}') if shutter else '-',
            'ISO': str(details.get(34855, '-')),
            'DateTimeOriginal': str(details.get(36867) or details.get(306) or '未记录时间'),
        }
    if Path(EXIFTOOL_PATH).is_file():
        result.update(get_exif(source))
    return result


def _json_fragment(value) -> str:
    """转义模板变量中的引号和换行，保证渲染结果仍是合法 JSON"""
    return json.dumps(str(value) if value is not None else '', ensure_ascii=False)[1:-1]


@pass_context
def _desktop_logo(context, brand=None):
    """没有相机品牌时使用项目自带标识"""
    return auto_logo(context, brand) or (logos_dir / 'default.png').as_posix()


def _configure_nodes(nodes, image, settings, metadata, source):
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
        if node.get('processor_name') == 'watermark_with_timestamp':
            segments = node.get('text_segments', [])
            if title and segments:
                segments[0]['text'] = title
            if subtitle and segments:
                segments[-1]['text'] = subtitle

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        kind = node.get('processor_name')
        if kind:
            node['exif'] = metadata
            node['save_buffer'] = False
        if settings.use_template_styles:
            for value in list(node.values()):
                if isinstance(value, (dict, list)):
                    visit(value)
            paths = node.get('buffer_path')
            if paths and len(paths) == 1 and Path(paths[0]).resolve() == source:
                node.update(buffer=[image.copy()], buffer_loaded=True)
            return
        if kind == 'watermark':
            footer = max(48, round(image.height * settings.border_percent / 100))
            node['bottom_margin'] = footer
            node['color'] = settings.background
            for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom'):
                if isinstance(node.get(key), dict):
                    node[key]['height'] = max(8, round(footer * 0.27))
            # 居中标识模板同样支持自定义署名
            if settings.title and not node.get('left_top', {}).get('text'):
                child = node.get('left_top', {})
                if not child.get('text_segments'):
                    child.update(text=settings.title)
            if settings.subtitle and not node.get('left_bottom', {}).get('text'):
                node.get('left_bottom', {}).update(text=settings.subtitle)
        if kind in {'rich_text', 'multi_rich_text', 'watermark_with_timestamp'}:
            node['height'] = max(8, round(float(node.get('height', image.height * .03)) * settings.font_scale))
            node['color'] = settings.text_color
            for segment in node.get('text_segments', []):
                segment['color'] = settings.text_color
        for key in ('left_logo', 'right_logo', 'center_logo'):
            if key in node and not settings.show_logo:
                node[key] = None
        for value in list(node.values()):
            if isinstance(value, (dict, list)):
                visit(value)
        # 模糊背景等模板重新读取原图时也使用等比缩小后的图像
        paths = node.get('buffer_path')
        if paths and len(paths) == 1 and Path(paths[0]).resolve() == source:
            node.update(buffer=[image.copy()], buffer_loaded=True)

    visit(nodes)


def _scale_nodes(value, scale):
    """同步缩放绝对像素参数，保持预览与原尺寸导出的布局比例"""
    pixels = {'width', 'height', 'border_radius', 'shadow_radius', 'blur_radius',
              'left_margin', 'right_margin', 'top_margin', 'bottom_margin',
              'middle_spacing', 'spacing', 'text_spacing', 'delimiter_width', 'center_logo_height'}
    if isinstance(value, list):
        for child in value:
            _scale_nodes(child, scale)
    elif isinstance(value, dict):
        for key, child in list(value.items()):
            if key in pixels:
                value[key] = round(float(child) * scale)
            elif key in {'offset', 'offsets'}:
                def resize_offsets(offset):
                    return [resize_offsets(item) for item in offset] if isinstance(offset, list) else round(offset * scale)
                value[key] = json.dumps(resize_offsets(json.loads(child)))
            elif isinstance(child, (dict, list)):
                _scale_nodes(child, scale)


def render_photo(path: Path, settings: WatermarkSettings, preview: bool = True) -> Image.Image:
    """让实时预览和原始分辨率导出走相同的水印流水线"""
    _validate(settings)
    source = Path(path).resolve()
    if source.suffix.lower() not in SUPPORTED_SUFFIXES or not source.is_file():
        raise ValueError('请选择存在的 JPG、PNG 或 HEIC 照片')
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGBA' if 'A' in opened.getbands() else 'RGB')
        profile = opened.info.get('icc_profile')
    original_size = image.size
    if preview:
        image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
    metadata = dict(_metadata(str(source), source.stat().st_mtime_ns))
    metadata.update(ImageWidth=str(original_size[0]), ImageHeight=str(original_size[1]))
    if settings.title and not settings.use_template_styles:
        metadata['CameraModelName'] = settings.title
    if settings.subtitle and not settings.use_template_styles:
        metadata['LensModel'] = settings.subtitle
    environment = Environment(finalize=_json_fragment, autoescape=False)
    environment.globals.update(vh=vh, vw=vw, auto_logo=_desktop_logo)
    template = environment.from_string(settings.template_source or read_template(settings.template_name))
    rendered = template.render(exif=metadata, filename=source.stem,
                               file_dir=source.parent.as_posix(), file_path=source.as_posix(), files=[str(source)])
    nodes = json.loads(rendered)
    if not isinstance(nodes, list) or not nodes:
        raise ValueError('水印模板需要至少一个处理步骤')
    if image.size != original_size:
        _scale_nodes(nodes, image.width / original_size[0])
    metadata.update(ImageWidth=str(image.width), ImageHeight=str(image.height))
    _configure_nodes(nodes, image, settings, metadata, source)
    result = start_process(nodes, initial_buffer=[image])
    if profile:
        result.info['icc_profile'] = profile
    if preview:
        result.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return result


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
    target = destination / f'{basename}.jpg'
    if target.resolve() == source or (target.exists() and target.samefile(source)):
        raise ValueError('输出文件与原照片相同，请选择其他输出目录')
    # 同名 PNG 与 JPEG 可能属于两张原片，不允许覆盖输入目录中的其他照片
    if settings.overwrite_existing and target.exists():
        inside_input = input_root is not None and target.resolve().is_relative_to(input_root)
        if inside_input or target.parent == source.parent:
            raise ValueError('不能覆盖输入目录中的照片，请选择独立的输出目录')
    if in_workspace and target.exists() and not settings.overwrite_existing:
        raise FileExistsError(f'已跳过同名输出：{target.name}')
    image = render_photo(source, settings, preview=False)
    # JPEG 不支持透明通道，使用所选边框色铺底
    canvas = Image.new('RGB', image.size, settings.background)
    canvas.paste(image, mask=image.getchannel('A') if image.mode == 'RGBA' else None)
    if settings.overwrite_existing:
        with NamedTemporaryFile(dir=destination, prefix='.export-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            canvas.save(temporary, format='JPEG', quality=settings.quality, subsampling=0,
                        icc_profile=image.info.get('icc_profile'))
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target
    number = 0
    while True:
        suffix = f'_{number}' if number else ''
        target = destination / f'{basename}{suffix}.jpg'
        try:
            stream = target.open('xb')
        except FileExistsError:
            if in_workspace:
                raise
            number += 1
            continue
        try:
            with stream:
                canvas.save(stream, format='JPEG', quality=settings.quality, subsampling=0,
                            icc_profile=image.info.get('icc_profile'))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target
