"""界面语言、动态翻译与 Qt 标准控件翻译"""

from __future__ import annotations

import json
import re
import sys
import weakref
from pathlib import Path

from jinja2 import TemplateSyntaxError

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QObject, QTranslator, Signal
from core.runtime_paths import config_path


PREFERENCES_PATH = config_path('ui.json')
_messages = {}
_messages.update({'相机显示文字': 'Camera text', '镜头显示文字': 'Lens text'})
_messages.update({
    '仅标识居中': 'Centered logo only', '仅品牌标识': 'Logo only',
    '品牌标识居中，两侧显示相机、镜头与拍摄参数': 'Centered logo with camera, lens and exposure details on both sides',
    '底部仅显示品牌标识，适合简洁展示': 'A compact footer containing only the brand logo',
})
_language = "zh_CN"
try:
    _stored = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    if _stored.get("language") in ("zh_CN", "en_US"):
        _language = _stored["language"]
except (OSError, ValueError, TypeError, AttributeError):
    pass


class Translator(QObject):
    """通过同一个信号更新主窗口和已经打开的对话框"""

    language_changed = Signal()


translator = Translator()
_qt_translators = []


def register_translations(mapping: dict[str, str]) -> None:
    """允许各功能模块注册自己的文案而不依赖主窗口"""
    _messages.update(mapping)


register_translations({
    '尼康 ℤ 符号': 'Nikon ℤ symbol',
    '定制几何符号': 'Geometric symbol',
    '标准 Z': 'Standard Z',
    '系统字体': 'System font',
    '保留原有设置': 'Keep original settings',
    '品牌符号策略无效': 'Invalid brand symbol policy',
})

register_translations({
    '沿用模板 · {color}': 'Template · {color}',
    '重置为模板默认': 'Reset to template default',
    '重置此分组': 'Reset this section',
})


def language() -> str:
    return _language


def tr(source_zh: str, **kwargs) -> str:
    """先选语言再插入变量以保留文件名和用户内容"""
    text = _messages.get(source_zh, source_zh) if _language == "en_US" else source_zh
    return text.format(**kwargs) if kwargs else text


def install_qt_translations() -> None:
    """为标准按钮和非原生文件对话框加载 Qt 官方翻译"""
    app = QCoreApplication.instance()
    if app is None:
        return
    for item in _qt_translators:
        app.removeTranslator(item)
        item.deleteLater()
    _qt_translators.clear()
    QLocale.setDefault(QLocale(_language))
    if _language == "zh_CN":
        locations = (Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
                     Path(getattr(sys, '_MEIPASS', '.')) / 'translations', Path('translations'))
        for name in ("qtbase_zh_CN.qm", "qt_zh_CN.qm"):
            for directory in locations:
                item = QTranslator(app)
                if item.load(str(directory / name)):
                    app.installTranslator(item)
                    _qt_translators.append(item)
                    break


def set_language(code: str) -> None:
    """保存独立语言偏好且不触发照片处理参数变更"""
    global _language
    if code not in ("zh_CN", "en_US"):
        raise ValueError("Unsupported interface language")
    changed = code != _language
    _language = code
    try:
        PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = PREFERENCES_PATH.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"language": code}), encoding="utf-8")
        temporary.replace(PREFERENCES_PATH)
    except OSError:
        # 只读安装目录仍允许本次会话切换语言
        pass
    install_qt_translations()
    if changed:
        translator.language_changed.emit()


def bind(widget, source: str, setter="setText", **kwargs):
    """绑定固定文案并避免翻译器延长窗口的生命周期"""
    registered = getattr(widget, "_translation_bindings", set())
    if (source, setter) in registered:
        return widget
    registered.add((source, setter))
    widget._translation_bindings = registered
    target = weakref.ref(widget)
    def update():
        item = target()
        if item is not None:
            try:
                getattr(item, setter)(tr(source, **kwargs))
            except RuntimeError:
                pass
    update()
    translator.language_changed.connect(update)
    def detach(*args):
        try:
            translator.language_changed.disconnect(update)
        except (RuntimeError, TypeError):
            pass
    widget.destroyed.connect(detach)
    return widget


def bind_static_texts(root, exclude=()):
    """仅绑定已登记的固定文案，不修改输入值和用户文件名"""
    excluded = set(exclude)
    for item in [root, *root.findChildren(QObject)]:
        if item in excluded:
            continue
        for getter, setter in (("text", "setText"), ("title", "setTitle"),
                               ("windowTitle", "setWindowTitle"), ("toolTip", "setToolTip"),
                               ("placeholderText", "setPlaceholderText")):
            if not hasattr(item, getter) or not hasattr(item, setter):
                continue
            try:
                source = getattr(item, getter)()
            except TypeError:
                continue
            if isinstance(source, str) and source in _messages:
                bind(item, source, setter)


register_translations({
    'EXIF 副本工具': 'EXIF copy tools', '将所选字段写入新副本': 'Write selected fields to a new copy',
    '已选 {selected} / 共 {total} 张': '{selected} selected / {total} photos',
    '展开或收起胶片带': 'Show or hide filmstrip',
    '显示胶片带': 'Show filmstrip',
    '新建空白预设': 'New blank preset', '模板槽位样式无效': 'Invalid template slot style',
    '按住空格对比原图': 'Hold Space for original',
    '深色': 'Dark', '浅色': 'Light', '主题': 'Theme', '另存为预设': 'Save as preset',
    '模板已保存：{name}': 'Preset saved: {name}',
    '从胶片带选择一张照片\n\n勾选的输入照片会一并导出': 'Choose a photo from the filmstrip\n\nChecked photos are exported together',
})


def region_title(region, number=None) -> str:
    """统一显示普通区域、独立文字与多水印区域"""
    from core.footer import REGION_LABELS

    if region in REGION_LABELS:
        return tr(REGION_LABELS[region] + '区域')
    match = re.fullmatch(r'watermark_([0-9]+)_(left_top|left_bottom|right_top|right_bottom)', str(region))
    if match:
        return tr('水印 {number} · {region}', number=int(match.group(1)),
                  region=tr(REGION_LABELS[match.group(2)] + '区域'))
    match = re.fullmatch(r'text_([0-9]+)', str(region))
    if match:
        return tr('文字区域 {number}', number=int(match.group(1)) + 1)
    return tr('文字区域 {number}', number=number) if number is not None else str(region)


def localize_error(error) -> str:
    """翻译应用错误片段并保留路径和模板源码中的用户文本"""
    if isinstance(error, json.JSONDecodeError):
        return tr('JSON 格式有误，第 {line} 行、第 {column} 列', line=error.lineno, column=error.colno)
    if isinstance(error, TemplateSyntaxError):
        return tr('模板语法有误，第 {line} 行', line=error.lineno)
    if isinstance(error, FileNotFoundError):
        return tr('文件不存在：{path}', path=error.filename or '')
    if isinstance(error, PermissionError):
        return tr('无法访问文件，请检查权限：{path}', path=error.filename or '')
    text = str(error)
    if text.startswith('所选样式引用的素材不存在：'):
        return tr('所选样式引用的素材不存在：{path}', path=text.removeprefix('所选样式引用的素材不存在：'))
    if text.startswith('未知画框样式：'):
        return tr('未知画框样式：{style}', style=text.removeprefix('未知画框样式：'))
    match = re.fullmatch(r'([a-z][a-z0-9_]*) 参数超出范围', text)
    if match:
        return tr('画框参数超出范围：{name}', name=match.group(1))
    # 文件名属于用户内容，只拆分处理器附加的错误说明
    if "：" in text and not text.startswith("已跳过同名输出："):
        name, detail = text.split("：", 1)
        return f"{name}: {localize_error(detail)}" if _language == "en_US" else f"{name}：{localize_error(detail)}"
    if text.startswith("已跳过同名输出："):
        return tr("已跳过同名输出：") + text.removeprefix("已跳过同名输出：")
    if text in _ERROR_SOURCES:
        return tr(text)
    # 会话元数据校验可能通过工作线程以稳定错误码返回
    code, _, detail = text.partition(":")
    if code in _METADATA_ERRORS:
        message = tr(_METADATA_ERRORS[code])
        from core.metadata import FIELDS
        detail = next((tr(field.label) for field in FIELDS if field.tag == detail.strip()), detail.strip())
        return f"{message}: {detail.strip()}" if detail.strip() else message
    return text


register_translations({
    '取消全选': 'Uncheck all',
    '反选': 'Invert selection',
    '已勾选 {selected} / 共 {total} 张': 'Checked {selected} / Total {total}',
    '滚轮缩放 拖动平移 双击切换适应和100% 按住空格查看原图':
        'Scroll to zoom, drag to pan, double-click for fit or 100%, hold Space for the original',
    '适应': 'Fit',
    '原图读取失败，保留水印预览': 'Could not load the original; watermark preview retained',
    '{mode} · {width} × {height}': '{mode} · {width} × {height}',
    '正在读取照片…': 'Loading photo…',
    '导出当前照片': 'Export current photo',
    '导出已选 ({count})': 'Export selected ({count})',
    '导出当前照片，原文件保持不变（Ctrl+R）': 'Export the current photo without changing the original (Ctrl+R)',
    '选择一张输入照片或勾选要导出的照片': 'Select an input photo or check photos to export',
    '逐字样式': 'Character styling',
    '选择字符': 'Select characters',
    '选择照片后显示文字': 'Select a photo to display text',
    '已选 {count} 个字符': '{count} characters selected',
    '自定义颜色…': 'Custom color…',
    '字符字体': 'Character font',
    '跟随整段': 'Use segment font',
    '应用字体': 'Apply font',
    '清除选中样式': 'Clear selected styles',
    '清除本行样式': 'Clear row styles',
    '清除本行全部样式': 'Clear all row styles',
    '徕卡红': 'Leica red',
    '哈苏橙': 'Hasselblad orange',
    '尼康黄': 'Nikon yellow',
    '富士绿': 'Fujifilm green',
    '灰色': 'Gray',
    '白色': 'White',
    '黑色': 'Black',
    '规则高亮': 'Highlight rules',
    '正则表达式': 'Regular expression',
    '按选中文字添加': 'Add selected text',
    '添加规则': 'Add rule',
    '删除规则': 'Remove rule',
    '无高亮规则': 'No highlight rules',
    '规则高亮需单独删除': 'Remove highlight rules separately',
    '请选择连续文字': 'Select contiguous text',
    '正则表达式无效': 'Invalid regular expression',
    '单字样式必须是对象': 'Character styles must be an object',
    '单字颜色应使用 #RRGGBB': 'Character colors must use #RRGGBB',
    '单字字体应为字体名称或路径': 'Character fonts must be a font name or path',
    '单字索引应为非负整数': 'Character indexes must be non-negative integers',
    '高亮规则必须是列表': 'Highlight rules must be a list',
    '请输入匹配表达式': 'Enter a matching expression',
    '匹配表达式无效': 'Invalid matching expression',
    '样式已应用到当前照片': 'Style applied to the current photo',
    '样式已同步到 {count} 张照片': 'Style synced to {count} photos',
    '已向 {count} 张照片应用 {fields} 个字段': 'Applied {fields} fields to {count} photos',
    '请检查字段格式：{field}': 'Check the value for {field}',
    '关于': 'About',
    '关闭': 'Close',
    '选择照片': 'Choose photo',
    '选择预览照片': 'Choose a preview photo',
    '水印细节': 'Watermark detail',
    '选择一张照片查看实际水印效果': 'Choose a photo to see the actual watermark',
    '模板有效后显示照片预览': 'The photo preview appears when the template is valid',
    '等待有效模板': 'Waiting for a valid template',
    '正在更新照片预览…': 'Updating photo preview…',
    '照片预览已更新': 'Photo preview updated',
    '模板有误，保留上次预览：{error}': 'Template error; previous preview retained: {error}',
    '预览失败，保留上次结果：{error}': 'Preview failed; previous result retained: {error}',
    '预览已停止': 'Preview stopped',
    '预览照片：{name}': 'Preview photo: {name}',
    '示例照片': 'Example photo',
    '创作者与版权': 'Creator and copyright',
    '相机与镜头': 'Camera and lens',
    '曝光参数': 'Exposure',
    '时间与位置': 'Time and location',
    '摄影师': 'Photographer',
    '作者': 'Author',
    '版权声明': 'Copyright',
    '处理软件': 'Software',
    '照片描述': 'Image description',
    '用户备注': 'User comment',
    '星级评分': 'Rating',
    '相机制造商': 'Camera manufacturer',
    '相机型号': 'Camera model',
    '镜头品牌': 'Lens manufacturer',
    '镜头型号': 'Lens model',
    '实际焦距': 'Focal length',
    '等效焦距': '35mm-equivalent focal length',
    '光圈': 'Aperture',
    '快门速度': 'Shutter speed',
    '感光度': 'ISO',
    '曝光补偿': 'Exposure compensation',
    '闪光灯': 'Flash',
    '白平衡': 'White balance',
    '拍摄时间': 'Capture time',
    '数字化时间': 'Digitized time',
    '时区偏移': 'Time zone offset',
    '纬度': 'Latitude',
    '南北纬': 'Latitude hemisphere',
    '经度': 'Longitude',
    '东西经': 'Longitude hemisphere',
    '海拔高度': 'Altitude',
    '未闪光': 'Did not fire',
    '已闪光': 'Fired',
    '自动闪光': 'Auto flash',
    '消除红眼': 'Red-eye reduction',
    '日光': 'Daylight',
    '多云': 'Cloudy',
    '钨丝灯': 'Tungsten',
    '荧光灯': 'Fluorescent',
    '手动': 'Manual',
    '北纬': 'North',
    '南纬': 'South',
    '东经': 'East',
    '西经': 'West',
    '未记录': 'Not recorded',
    '留空保留原值': 'Leave blank to preserve the original',
    '地点名': 'Place name',
    '自定义文字': 'Custom text',
    '选择要编辑的区域': 'Choose a region to edit',
    '可添加字段': 'Available fields',
    '添加字段': 'Add field',
    '上移': 'Move up',
    '下移': 'Move down',
    '删除': 'Remove',
    '区域内分隔符': 'Separator in this region',
    '文字区域 {number}': 'Text region {number}',
    '水印 {number} · {region}': 'Watermark {number} · {region}',
    '左上': 'Top left',
    '左下': 'Bottom left',
    '右上': 'Top right',
    '右下': 'Bottom right',
    '左上区域': 'Top left',
    '左下区域': 'Bottom left',
    '右上区域': 'Top right',
    '右下区域': 'Bottom right',
    '相机品牌': 'Camera brand',
    '快门': 'Shutter speed',
    '拍摄日期': 'Capture date',
    '日期与时间': 'Date and time',
    '海拔': 'Altitude',
    '版权': 'Copyright',
    '备注': 'Comment',
    '评分': 'Rating',
    '文件名称': 'File name',
    '文件夹名称': 'Folder name',
    '纬度（旧字段）': 'Latitude (legacy)',
    '经度（旧字段）': 'Longitude (legacy)',
    '拍摄参数': 'Exposure',
    '作者与文字': 'Creator and text',
    '文件': 'File',
    '模板': 'Template',
    '样式': 'Style',
    '选择模板': 'Choose template',
    '编辑页脚信息': 'Edit footer information',
    '仅应用': 'Apply only',
    '边框与背景': 'Border and background',
    '标识': 'Logo',
    '自动识别': 'Auto-detect',
    '自定义图片…': 'Custom image…',
    '隐藏标识': 'Hide logo',
    '字体与颜色': 'Font and colors',
    '沿用模板': 'Use template setting',
    '沿用模板（{value}）': 'Use template ({value})',
    '选择字体…': 'Choose font…',
    '文本排版': 'Text layout',
    '左对齐': 'Align left',
    '居中': 'Center',
    '右对齐': 'Align right',
    '字距': 'Letter spacing',
    '行距': 'Line spacing',
    '照片信息': 'Photo information',
    '选择照片后编辑 EXIF': 'Select a photo to edit EXIF',
    '批量时仅应用已勾选字段': 'Only checked fields apply to multiple photos',
    '应用当前照片': 'Apply to current photo',
    '勾选照片': 'Checked photos',
    '全部照片': 'All photos',
    '输出设置': 'Output settings',
    '模板预设': 'Presets',
    '样式与文本': 'Style & text',
    'EXIF 信息': 'EXIF info',
    '仅应用到当前照片': 'Apply to current photo',
    '同步样式到全部已勾选': 'Sync style to checked photos',
    '批量覆写已勾选 EXIF': 'Batch overwrite checked EXIF',
    '设为默认模板': 'Set as default template',
    '默认模板已设为 {name}': 'Default template set to {name}',
    '经典相机边框': 'Classic camera frame',
    '留白与阴影': 'Border and shadow',
    '沉浸模糊背景': 'Blurred background',
    '尼康模糊背景': 'Nikon blurred background',
    '极简参数': 'Minimal exposure',
    '旅途与时间': 'Journey and time',
    '品牌居中': 'Centered brand',
    '极简无框角标': 'Minimal corner overlay',
    '原图边缘的轻量参数角标': 'A compact information overlay at the photo edge',
    '拍立得经典宽底': 'Classic instant photo',
    '暖白宽底，突出照片和拍摄信息': 'A warm white border with a wide caption area',
    '毛玻璃悬浮卡片': 'Frosted glass card',
    '模糊背景衬托圆角照片': 'A rounded photo over a blurred background',
    '美术馆装裱画框': 'Gallery mat',
    '米白留白营造装裱感': 'A warm off-white gallery-style mat',
    '35mm胶片暗房印记': '35mm film imprint',
    '深色胶片边框与拍摄参数': 'A dark film border with exposure details',
    '主色提取色卡栏': 'Photo palette strip',
    '从照片提取色彩并排展示': 'Show a strip of colors extracted from the photo',
    '红标铭牌强调风': 'Red badge',
    '深色底栏与红色品牌强调': 'A dark footer with a red brand accent',
    '极简双行分割线': 'Minimal two-line divider',
    '双列信息与克制分隔线': 'Two columns of information with a subtle divider',
    '边框样式': 'Frame style',
    '未指定': 'Not specified',
    '纯色边框': 'Solid border',
    '拍立得宽底': 'Instant-photo border',
    '毛玻璃卡片': 'Frosted glass card',
    '画廊装裱': 'Gallery mat',
    '胶片暗房': 'Film strip',
    '文字覆盖方式': 'Text placement',
    '默认位置': 'Default position',
    '内嵌覆盖': 'Inset overlay',
    '色卡栏': 'Palette strip',
    '自适应反转标识': 'Adaptively invert logo',
    '开启': 'On',
    '停用': 'Off',
    '默认': 'Default',
    '内嵌覆盖优先于边框样式': 'Inset overlay takes precedence over the frame style',
    '未知画框样式：{style}': 'Unknown frame style: {style}',
    '画框参数超出范围：{name}': 'Frame parameter out of range: {name}',
    '照片尺寸无效': 'Invalid photo dimensions',
    '背景亮度': 'Background brightness',
    '暗角强度': 'Vignette strength',
    '模糊强度': 'Blur strength',
    '角标位置': 'Overlay position',
    '覆盖不透明度': 'Overlay opacity',
    '底部': 'Bottom',
    '仅应用当前': 'Apply to current',
    '同步样式': 'Sync style',
    '同步勾选字段到照片': 'Sync checked fields',
    '品牌标识': 'Brand logo',
    '标识来源': 'Logo source',
    '字体': 'Font',
    '文字与间距': 'Text and spacing',
    '右侧文字对齐': 'Right text alignment',
    '片段间距': 'Segment spacing',
    '行间距': 'Line spacing',
    '页脚字段': 'Footer fields',
    '完整字段排版…': 'Full field layout…',
    '勾选字段仅用于批量同步': 'Checked fields are used only for batch sync',
    '全选字段': 'Select all fields',
    '清除字段选择': 'Clear field selection',
    '更多 EXIF…': 'More EXIF…',
    '选择标识图片': 'Choose logo image',
    '图片 (*.png *.jpg *.jpeg)': 'Images (*.png *.jpg *.jpeg)',
    '选择字体': 'Choose font',
    '字体文件 (*.ttf *.otf *.ttc)': 'Font files (*.ttf *.otf *.ttc)',
    '请先解锁设置': 'Unlock settings first',
    '请选择输入照片': 'Select an input photo',
    '请先勾选照片': 'Check photos first',
    '请先勾选要同步的字段': 'Check the fields to sync first',
    "地理位置": "Location",
    "导出 1 张照片": "Export 1 photo",
    "导出这张勾选照片，原文件保持不变（Ctrl+R）": "Export this checked photo and keep the source file unchanged (Ctrl+R)",
    "导出已取消，已保存 1 张照片": "Export cancelled; 1 photo saved",
    "导出完成，已保存 1 张照片": "Export complete; 1 photo saved",
    "导出照片": "Export photos", "导出 {count} 张照片": "Export {count} photos", "正在导出…": "Exporting…",
    "取消导出": "Cancel export", "保存设置": "Save settings", "重置设置": "Reset settings",
    "锁定设置": "Lock settings", "编辑设置": "Edit settings", "设置已载入": "Settings loaded",
    "设置有修改，尚未保存": "Settings have unsaved changes", "设置已保存": "Settings saved", "保存设置失败": "Unable to save settings",
    "保存输入输出目录、模板选择和导出选项，不改写模板内容": "Save folders, template selection and export options without changing the template content",
    "对照原图": "Compare original", "仅切换预览，不改变导出内容（Ctrl+Tab）": "Switch the preview only; exported photos remain unchanged (Ctrl+Tab)",
    "编辑当前照片的水印信息，原片保持不变（Ctrl+I）": "Edit the current photo's watermark information; keep the source photo unchanged (Ctrl+I)",
    "自由组合水印字段、顺序和分隔符（Ctrl+Shift+E）": "Arrange watermark fields, order and separators (Ctrl+Shift+E)",
    "编辑完整 JSON / Jinja 模板（Ctrl+E）": "Edit the complete JSON / Jinja template (Ctrl+E)",
    "正在读取照片，完成后可以导出": "Photos are loading; export will be available when loading finishes",
    "导出 {count} 张勾选照片，原文件保持不变（Ctrl+R）": "Export {count} checked photos and keep the source files unchanged (Ctrl+R)",
    "在输入列表勾选需要导出的照片": "Check the photos you want to export in the input list",
    "先添加照片，再勾选需要导出的照片": "Add photos, then check the ones you want to export",
    "正在导出 {current}/{total} · {name}": "Exporting {current}/{total} · {name}",
    "导出已取消，已保存 {count} 张照片": "Export cancelled; {count} photos saved",
    "导出完成，已保存 {count} 张照片": "Export complete; {count} photos saved", "导出失败": "Export failed",
    "当前照片完成后取消导出": "Finishing the current photo, then cancelling export",
    "等待预览完成后开始导出…": "Waiting for previews to finish before exporting…",
    "正在处理的照片完成后取消导出": "Finishing photos in progress, then cancelling export",
    "添加照片后开始编辑水印\n\n拖入 JPG、PNG、HEIC 文件或文件夹，或点击上方“添加照片”": "Add photos to start editing watermarks\n\nDrop JPG, PNG, HEIC files or folders here, or use Add photos above",
    "从左侧列表选择一张照片\n\n勾选的输入照片会一并导出": "Select a photo in the list to preview it\n\nChecked input photos will be exported together",
    "此目录暂无导出照片\n\n导出后可在“输出”标签查看成品": "No exported photos in this folder\n\nExport your photos to review the results in the Output tab",
    "组合底部信息…": "Compose footer information…", "高级源码": "Advanced source", "高级源码…": "Advanced source…",
    "切换编辑方式": "Switch editor", "将未保存的修改带到{editor}继续编辑？": "Continue editing the unsaved changes in {editor}?",
    "可视化组合": "the visual composer", "高级源码编辑器": "the source editor",
    "无法打开组合编辑器": "Unable to open the footer composer", "无法切换编辑器": "Unable to switch editors",
    "无法读取当前组合": "Unable to read the current composition",
    'JSON 格式有误，第 {line} 行、第 {column} 列': 'Invalid JSON at line {line}, column {column}',
    '模板语法有误，第 {line} 行': 'Invalid template syntax at line {line}',
    '文件不存在：{path}': 'File not found: {path}',
    '无法访问文件，请检查权限：{path}': 'Cannot access the file; check permissions: {path}',
})


_ERROR_SOURCES = {
    '样式包格式无效', '样式包版本不受支持', '样式包素材过大', '样式包素材无效或已损坏',
    '素材图片无效或已损坏', '素材图片大小无效', '素材需要 PNG 或 JPEG 图片',
    '素材文件已存在且内容不同', '模板已存在，请换一个名称',
    '品牌符号策略无效',
    '照片尺寸无效',
    '单字样式必须是对象', '单字颜色应使用 #RRGGBB', '单字字体应为字体名称或路径',
    '单字索引应为非负整数', '高亮规则必须是列表', '请输入匹配表达式', '匹配表达式无效',
    "当前模板需要使用高级源码编辑", "模板中没有可组合的文字区域", "底部信息区域无效", "标识位置无效",
    "缺失值处理方式无效", "分隔符过长", "每个区域最多放置 32 项信息", "底部信息字段无效", "自定义文字过长",
    "文字区必须保留在原有版式内", "底部空间不足以容纳水印内容",
    "文本设置格式无效，请重新加载配置", "开关设置格式无效，请重新加载配置", "水印模板不存在，请重新选择",
    "文字大小需在 50% 到 200% 之间", "边框高度需在 6% 到 30% 之间", "导出质量需在 1 到 100 之间",
    "水印整体大小需在 50% 到 200% 之间",
    "JPEG 色度采样需为 0、1 或 2", "模板名称不能包含路径、特殊字符或 Windows 保留名称",
    "模板路径必须位于模板目录内", "模板必须是由处理步骤对象组成的 JSON 数组", "模板不存在，请先新建模板",
    "请选择存在的 JPG、PNG 或 HEIC 照片", "水印模板需要至少一个处理步骤",
    "输出文件与原照片相同，请选择其他输出目录", "不能覆盖输入目录中的照片，请选择独立的输出目录",
    "不能覆盖已导入的原照片，请选择独立的输出目录",
}
_METADATA_ERRORS = {
    "tool_missing": "未找到 ExifTool", "file_missing": "照片文件不存在", "invalid_value": "照片信息的数值无效",
    "invalid_date": "日期格式无效", "invalid_timezone": "时区偏移格式无效", "invalid_gps": "位置坐标无效",
    "unsupported_tag": "不支持此照片信息字段", "write_failed": "照片信息处理失败",
    "source_conflict": "不能覆盖原照片", "destination_exists": "目标文件已存在", "no_changes": "没有需要保存的修改",
}


register_translations({
    "当前模板需要使用高级源码编辑": "Use Advanced source to edit this template",
    "模板中没有可组合的文字区域": "This template has no text regions to compose",
    "底部信息区域无效": "Invalid footer region", "标识位置无效": "Invalid logo position",
    "缺失值处理方式无效": "Invalid missing-value setting", "分隔符过长": "The separator is too long",
    "每个区域最多放置 32 项信息": "Each region can contain up to 32 items",
    "底部信息字段无效": "Invalid footer field", "自定义文字过长": "Custom text is too long",
    "文字区必须保留在原有版式内": "Text regions must stay within the original layout",
    "底部空间不足以容纳水印内容": "Not enough footer space for the watermark content",
    "未找到 ExifTool": "ExifTool was not found", "照片文件不存在": "Photo file not found",
    "照片信息的数值无效": "Invalid photo information value", "日期格式无效": "Invalid date format",
    "时区偏移格式无效": "Invalid time zone offset", "位置坐标无效": "Invalid location coordinates",
    "不支持此照片信息字段": "Unsupported metadata field", "照片信息处理失败": "Unable to process photo information",
    "不能覆盖原照片": "The source photo cannot be overwritten", "目标文件已存在": "The destination already exists",
    "没有需要保存的修改": "There are no changes to save",
    "文件(&F)": "&File", "模板(&T)": "&Template", "查看(&V)": "&View", "语言": "Language",
    "中文": "Chinese", "英文": "English", "添加照片": "Add photos", "输入目录": "Input folder",
    "输出目录": "Output folder", "刷新目录": "Refresh", "处理选中照片": "Process selected",
    "停止": "Stop", "保存配置": "Save settings", "重置配置": "Reset settings",
    "新建模板…": "New template…", "模板另存为…": "Save template as…", "编辑模板源码…": "Edit template source…",
    "编辑照片信息…": "Edit photo information…", "编辑当前照片信息…": "Edit current photo information…",
    "编辑选中照片信息…": "Edit checked photos information…", "显示原图": "Show original", "锁定配置": "Lock settings",
    "退出": "Exit", "错误详情…": "Error details…", "常用操作": "Tools", "预览": "Preview", "原图": "Original",
    "未选择照片": "No photo selected", "详情": "Details", "打开输出目录": "Open output folder", "就绪": "Ready",
    "水印模板": "Watermark template", "新建": "New", "另存为": "Save as", "源码": "Source",
    "按模板原样处理": "Use original template styles",
    "保留模板中的文字、颜色、字号和布局；调整下方参数后切换为自定义": "Keep the template's text, colors, sizes and layout. Editing the controls below switches to custom styles.",
    "快捷调整": "Style adjustments", "留空使用照片信息": "Leave blank to use photo information",
    "主标题": "Title", "副标题": "Subtitle", "显示品牌标识": "Show brand logo", "文字大小": "Text size",
    "水印缩放": "Watermark scale", "自动": "Auto",
    "最左侧为模板自动留白，拖动可按照片高度设置基准比例": "At the far left, use the template's automatic footer; drag to set a base percentage of photo height",
    "留白固定为照片高度的 {percent}%，缩放过大可能超出固定底栏": "Footer height is fixed at {percent}% of the photo; large watermark scales may exceed it",
    "底部留白": "Footer height", "颜色": "Colors", "底色": "Background", "背景颜色": "Background color", "文字颜色": "Text color",
    "点击选择{label}，当前颜色 {color}": "Choose {label}; current color: {color}",
    "模板颜色保持不变；点击选择{label}，候选颜色 {color}": "Template color is unchanged; choose {label} to apply {color}",
    "输出选项": "Output options", "JPEG 质量": "JPEG quality", "覆盖同名输出文件": "Overwrite existing output",
    "只替换输出文件，始终保护输入原片": "Replace output files only; source photos are always protected",
    "保留输入目录结构": "Keep input folder structure", "保存": "Save", "重置": "Reset", "配置已载入": "Settings loaded",
    "自定义模板": "Custom template", "使用模板定义的样式": "Using the template's styles",
    "自定义模式 · 快捷参数覆盖模板样式": "Custom styles override the template settings",
    "配置有修改，尚未保存": "Settings have unsaved changes", "配置已保存": "Settings saved", "编辑配置": "Edit settings",
    "选择颜色": "Choose color", "保存配置失败": "Unable to save settings", "选择输入目录": "Choose input folder",
    "选择输出目录": "Choose output folder", "目录无法读取": "Unable to read folder", "输入队列已清空": "Input list cleared",
    "输入文件": "Input photo", "输出文件": "Output photo", "水印预览": "Watermark preview", "适应窗口": "Fit to window",
    "正在生成预览…": "Rendering preview…", "目录读取完成": "Folder loaded", "部分照片无法读取": "Some photos could not be read",
    "处理已取消": "Processing cancelled", "处理完成": "Processing complete", "预览失败，详情见状态栏": "Preview failed; see the status bar",
    "预览失败": "Preview failed", "处理失败": "Processing failed", "处理 {current}/{total} · {name}": "Processing {current}/{total} · {name}",
    "读取目录 · {name}": "Reading folder · {name}", "成功 {completed} / 失败 {errors} / 跳过 {skipped}": "Done {completed} / Failed {errors} / Skipped {skipped}",
    "处理详情": "Processing details", "暂无错误": "No errors", "当前照片完成后停止": "Stopping after the current photo",
    "读取模板失败": "Unable to read template", "模板草稿已应用，尚未保存到模板文件": "Template draft applied; the template file has not been saved",
    "等待当前照片处理结束…": "Waiting for the current photo…", "已跳过同名文件：{path}": "Skipped existing output: {path}",
    "等待照片信息处理结束…": "Waiting for photo information processing…",
    "选择照片以预览\n\n可拖入 JPG、PNG、HEIC 文件或文件夹": "Select a photo to preview\n\nDrop JPG, PNG, HEIC files or folders here",
    "输入": "Input", "输出": "Output", "文件名": "Name", "尺寸": "Dimensions", "全选": "Select all", "取消选择": "Uncheck all",
    "移除": "Remove", "清空": "Clear", "选择目录": "Choose folder", "手动添加": "Added manually",
    "输入 {total} 张 / 已选 {selected} 张 / 输出 {output} 张": "Input {total} / Checked {selected} / Output {output}",
    "照片 (*.jpg *.jpeg *.png *.heic *.heif)": "Photos (*.jpg *.jpeg *.png *.heic *.heif)",
    "照片信息已更新，仅用于水印": "Photo information updated for watermarking only",
    "{width} × {height} · {mode}": "{width} × {height} · {mode}",
    "{mode} · {width} × {height} · 适应窗口": "{mode} · {width} × {height} · Fit to window",
    "{title}：{error}": "{title}: {error}",
    "尚未选择可编辑的照片": "Select a photo to edit its information", "模板已创建：{name}": "Template created: {name}",
    "创建模板失败": "Unable to create template", "_副本": "_copy",
    "标准水印": "Classic camera frame", "标准水印2": "Shadow frame", "背景模糊": "Blurred background",
    "尼康专用背景模糊": "Nikon blurred background", "右下角参数": "Corner settings",
    "文件夹名+右下角参数": "Folder and shooting date", "logo居中": "Centered brand mark",
    "品牌标识居中": "Centered brand mark",
    "相机、镜头与拍摄参数，适合日常分享": "Camera, lens and exposure information",
    "圆角照片搭配轻盈阴影和宽边框": "Rounded photo with a shadow and wide border",
    "延展画面色彩，居中展示拍摄信息": "Extended photo colors with centered details",
    "突出尼康 Z 标识的专属版式": "A layout featuring the Nikon Z mark",
    "小巧文字落在右下角，保留画面重心": "Compact information in the lower-right corner",
    "使用照片所在文件夹名称记录这次拍摄": "Show the containing folder and shooting date",
    "居中品牌标识搭配简洁留白": "Centered brand logo with a simple border", "自定义水印模板": "Custom watermark template",
    "窗口启动失败": "Unable to start ExifFrame", "请检查 config 和 static 资源目录": "Check the config and static resource folders",
    "缺少桌面依赖，请先使用当前 Python 环境安装 requirements.txt": "Desktop dependencies are missing. Install requirements.txt in the current Python environment.",
    "ExifFrame 桌面版仅支持 Windows": "ExifFrame desktop is available on Windows only",
    "文本设置格式无效，请重新加载配置": "Invalid text settings; reload the configuration",
    "开关设置格式无效，请重新加载配置": "Invalid option settings; reload the configuration",
    "水印模板不存在，请重新选择": "Watermark template not found; choose another template",
    "文字大小需在 50% 到 200% 之间": "Text size must be between 50% and 200%",
    "水印整体大小需在 50% 到 200% 之间": "Watermark scale must be between 50% and 200%",
    "边框高度需在 6% 到 30% 之间": "Footer height must be between 6% and 30%",
    "导出质量需在 1 到 100 之间": "Export quality must be between 1 and 100",
    "JPEG 色度采样需为 0、1 或 2": "JPEG subsampling must be 0, 1 or 2",
    "模板名称不能包含路径、特殊字符或 Windows 保留名称": "Template names cannot contain paths, special characters or Windows reserved names",
    "模板路径必须位于模板目录内": "Templates must stay inside the template folder",
    "模板必须是由处理步骤对象组成的 JSON 数组": "A template must be a JSON array of processing objects",
    "模板不存在，请先新建模板": "Template not found; create it first",
    "请选择存在的 JPG、PNG 或 HEIC 照片": "Choose an existing JPG, PNG or HEIC photo",
    "水印模板需要至少一个处理步骤": "The template needs at least one processing step",
    "输出文件与原照片相同，请选择其他输出目录": "The output would replace the source photo; choose another output folder",
    "不能覆盖输入目录中的照片，请选择独立的输出目录": "Source photos cannot be overwritten; choose a separate output folder",
    "不能覆盖已导入的原照片，请选择独立的输出目录": "Imported source photos cannot be overwritten; choose a separate output folder",
    "已跳过同名输出：": "Skipped existing output: ",
})

register_translations({
    '内置模板': 'Built-in templates',
    '我的模板': 'My templates',
    '另存我的模板': 'Save template',
    '导入样式包': 'Import style pack',
    '导出样式包': 'Export style pack',
    '样式包 (*.efstyle)': 'Style packs (*.efstyle)',
    '模板名称': 'Template name',
    '请输入模板名称': 'Enter a template name',
    '模板已保存到我的模板：{name}': 'Saved to my templates: {name}',
    '样式包已导入：{name}': 'Style pack imported: {name}',
    '样式包已导出：{path}': 'Style pack exported: {path}',
    '无法保存模板': 'Unable to save template',
    '无法导入样式包': 'Unable to import style pack',
    '无法导出样式包': 'Unable to export style pack',
    '样式包格式无效': 'Invalid style pack',
    '样式包版本不受支持': 'Unsupported style pack version',
    '样式包素材无效或已损坏': 'Style pack asset is invalid or damaged',
    '样式包素材过大': 'Style pack assets are too large',
    '素材图片无效或已损坏': 'Asset image is invalid or damaged',
    '素材图片大小无效': 'Invalid asset image size',
    '素材需要 PNG 或 JPEG 图片': 'An asset must be a PNG or JPEG image',
    '素材文件已存在且内容不同': 'An existing asset has different contents',
    '模板已存在，请换一个名称': 'A template with this name already exists',
    '所选样式引用的素材不存在：{path}': 'A referenced asset is missing: {path}',
})

register_translations({
    '添加': 'Add',
    '当前模板无法在此编辑画框，请使用高级源码': 'This template cannot be edited here; use advanced source',
    '画框定制': 'Frame design', '当前画框请在画框定制中调整': 'Adjust this frame under Frame design',
    '调整后生成当前照片的画框草稿': 'Edits create a frame draft for this photo',
    '画框距离和尺寸按照片短边的百分比计算': 'Frame distances and sizes use the photo’s short edge',
    '恢复模板画框': 'Restore template frame', '画幅与边距': 'Canvas and margins',
    '画幅模式': 'Canvas mode', '扩展边距': 'Expand margins', '固定比例': 'Fixed aspect ratio',
    '画幅比例': 'Aspect ratio', '水平偏移': 'Horizontal offset', '垂直偏移': 'Vertical offset',
    '锁定四边比例': 'Lock margin proportions', '上边距': 'Top margin', '下边距': 'Bottom margin',
    '左边距': 'Left margin', '右边距': 'Right margin',
    '画框背景与材质': 'Frame background and texture', '背景类型': 'Background type',
    '纯色': 'Solid color', '渐变色': 'Gradient', '自动主色': 'Dominant color',
    '照片模糊': 'Blurred photo', '自定义背景图': 'Custom background', '画框颜色': 'Frame color',
    '渐变起始色': 'Gradient start', '渐变结束色': 'Gradient end', '渐变方式': 'Gradient type',
    '线性': 'Linear', '径向': 'Radial', '渐变角度': 'Gradient angle', '模糊半径': 'Blur radius',
    '背景饱和度': 'Background saturation', '背景图片': 'Background image', '背景图片适配': 'Image fit',
    '铺满裁切': 'Fill and crop', '拉伸': 'Stretch', '完整包含': 'Fit inside',
    '表面纹理': 'Texture', '无纹理': 'None', '纸张': 'Paper', '颗粒': 'Grain',
    '纹理强度': 'Texture strength', '纹理缩放': 'Texture scale', '纹理种子': 'Texture seed',
    '照片外观': 'Photo appearance', '照片圆角': 'Photo corner radius', '照片描边宽度': 'Photo outline width',
    '照片描边颜色': 'Photo outline color', '照片描边不透明度': 'Photo outline opacity',
    '阴影模糊': 'Shadow blur', '阴影水平偏移': 'Shadow horizontal offset', '阴影垂直偏移': 'Shadow vertical offset',
    '阴影扩散': 'Shadow spread', '阴影不透明度': 'Shadow opacity', '阴影颜色': 'Shadow color',
    '画框装饰': 'Frame decorations', '边框线条': 'Border line', '胶片齿孔': 'Film sprockets',
    '主色色卡': 'Color palette', '取景框': 'Viewfinder marks', 'PNG 画框': 'PNG frame',
    '启用当前装饰': 'Enable selected decoration', '双线边框': 'Double border', '线条内缩': 'Line inset',
    '线条宽度': 'Line width', '双线间距': 'Line spacing', '线条圆角': 'Line radius', '线条颜色': 'Line color',
    '齿孔位置': 'Sprocket edges', '上下边': 'Top and bottom', '左右边': 'Left and right', '四边': 'All edges',
    '齿孔宽度': 'Sprocket width', '齿孔高度': 'Sprocket height', '齿孔间隔': 'Sprocket spacing',
    '齿孔内缩': 'Sprocket inset', '齿孔颜色': 'Sprocket color', '胶片边缘文字': 'Film edge text',
    '边缘文字颜色': 'Edge text color', '色块数量': 'Number of colors', '色块形状': 'Swatch shape',
    '方形': 'Square', '圆形': 'Circle', '胶囊': 'Capsule', '色卡位置': 'Palette position',
    '底部居中': 'Bottom center', '顶部居中': 'Top center', '色卡宽度': 'Palette width',
    '色卡高度': 'Palette height', '色卡内缩': 'Palette inset', '色块间距': 'Swatch gap',
    '取景标记': 'Viewfinder style', '四角': 'Corners', '十字': 'Crosshair', '标记内缩': 'Mark inset',
    '标记长度': 'Mark length', '标记宽度': 'Mark width', '标记颜色': 'Mark color',
    'PNG 图片': 'PNG image', '图片适配': 'Image fit', '九宫格': 'Nine-slice',
    '图片不透明度': 'Image opacity', '九宫格上边': 'Top slice', '九宫格下边': 'Bottom slice',
    '九宫格左边': 'Left slice', '九宫格右边': 'Right slice', '选择图片': 'Choose image',
    'PNG 图片 (*.png)': 'PNG images (*.png)', '背景图片 (*.png *.jpg *.jpeg)': 'Background images (*.png *.jpg *.jpeg)',
    '图片导入失败': 'Unable to import image', '全部模板': 'All templates',
    '读取模板样式失败': 'Unable to read template style',
})

_CUSTOM_FRAME_ERRORS = {
    '齿孔位置无效': 'Invalid sprocket placement',
    '色块形状无效': 'Invalid swatch shape',
    '色卡位置无效': 'Invalid palette position',
    '自定义画框格式无效': 'Invalid custom frame',
    '画框几何格式无效': 'Invalid frame geometry',
    '目标画幅比例无效': 'Invalid canvas aspect ratio',
    '画布模式无效': 'Invalid canvas mode',
    '画框底部留白无效': 'Invalid bottom margin',
    '目标画幅过大，请选择更接近照片的比例': 'Insufficient memory for this canvas. Choose a ratio closer to the photo.',
    '画框材质格式无效': 'Invalid frame material',
    '背景材质类型无效': 'Invalid background material',
    '背景图片不存在或不可读取': 'The background image is missing or unreadable',
    '背景图片在读取期间发生变化，请重试': 'The background image changed while loading. Try again.',
    '背景图片适配方式无效': 'Invalid background image fit',
    '渐变类型无效': 'Invalid gradient type',
    '纹理类型无效': 'Invalid texture type',
    '装饰图层格式无效': 'Invalid decoration stack',
    '装饰尺寸必须是非负数': 'Decoration dimensions must be nonnegative',
    '色卡颜色数应为 3 到 8': 'Choose between 3 and 8 palette colors',
    '九宫格切边须在 0 到 50 之间': 'Nine-slice margins must be between 0 and 50 percent',
    '相框贴图须为 PNG 图片': 'Choose a PNG frame image',
    '相框贴图适配方式无效': 'Invalid PNG frame fit',
    '相框贴图在读取期间发生变化，请重试': 'The PNG frame changed while loading. Try again.',
    '相框贴图透明度须在 0 到 100 之间': 'PNG frame opacity must be between 0 and 100 percent',
    '未知装饰图层': 'Unknown decoration type',
}
register_translations(_CUSTOM_FRAME_ERRORS)
_ERROR_SOURCES.update(_CUSTOM_FRAME_ERRORS)

# 检查器导航、槽位编辑与预设分类
register_translations({
    '预设库': 'Presets', '文字与 Logo': 'Text & logo',
    '留白': 'White border', '毛玻璃': 'Frosted glass', '胶片': 'Film', '无框': 'Frameless',
    '全局比例': 'Global scale', '全局比例与布局': 'Global scale & layout',
    '水印整体缩放': 'Overall watermark scale', '排版高级选项': 'Advanced typography',
    '槽位样式': 'Slot style', '内容模板': 'Content template', '单字染色': 'Character color',
    '显示当前槽位': 'Show selected slot', '字号': 'Font size', '等待预览': 'Waiting for preview',
    '沿用模板 · {value}': 'Template · {value}', '自动识别 · {value}': 'Auto · {value}',
    '水印 {number} · 标识': 'Watermark {number} · Logo',
    '输入自定义文字': 'Enter custom text', '添加文字': 'Add text',
    '无损副本与高级文件操作…': 'Lossless copy & advanced file operations…',
    '同步样式到已选 ({count})': 'Sync style to selected ({count})',
})
register_translations({'更多字段': 'More fields'})
register_translations({'正在生成缩略图…': 'Generating preview…', '缩略图不可用': 'Preview unavailable'})
register_translations({'隐藏此槽位': 'Hide this slot', '显示此槽位': 'Show this slot'})
register_translations({
    '另存为预设': 'Save preset', '设为默认': 'Set as default',
    '导入预设包': 'Import pack', '导出预设包': 'Export pack', '我的': 'Mine',
    '同步样式到已选 ({count})': 'Sync selected ({count})',
    '仅应用到当前照片': 'Apply to current',
})
register_translations({'全部': 'All', '留白': 'White', '毛玻璃': 'Glass'})
register_translations({
    '此槽位由动态源码生成，请在高级源码中编辑': 'This slot is generated by dynamic source; edit it in Advanced source',
    '打开高级源码': 'Open advanced source', '内容': 'Content',
})
register_translations({
    '照片背景': 'Photo background', '模糊照片背景': 'Blurred photo background',
    '渐变背景': 'Gradient background', '照片主色背景': 'Photo palette background',
    '自定义图片背景': 'Custom image background',
})
register_translations({
    '更多格式选项': 'More formatting', '字段前缀': 'Field prefix', '字段后缀': 'Field suffix',
    '所有区域缺失值': 'Missing values in all slots',
    '隐藏该字段': 'Hide the field', '显示破折号': 'Show a dash',
})
register_translations({'保留原位置': 'Keep original position', '左侧': 'Left', '右侧': 'Right'})
register_translations({'我的模板': 'My presets', '缺失值': 'Missing', '缺失值策略影响所有区域': 'The missing-value policy affects all slots'})
