"""界面语言、动态翻译与 Qt 标准控件翻译"""

from __future__ import annotations

import json
import re
import sys
import weakref
from pathlib import Path

from jinja2 import TemplateSyntaxError

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QObject, QTranslator, Signal


PREFERENCES_PATH = Path("config/ui.json")
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
