import functools
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from enum import Enum
from itertools import chain
from typing import Dict, Any, Type, List, MutableMapping, Iterator, Optional

from PIL import Image, ImageColor, ImageOps

from core.brand_glyphs import brand_glyph_policy
from core.configs import load_config
from core.image_cache import cache_preview_image, cached_preview_image, check_cancelled, file_image_id
from core.logger import logger
from core.util import get_exif, log_rt


class PipelineContext(MutableMapping):
    """管道上下文"""

    def __init__(self, config: Dict[str, Any]):
        self._config = config

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key) if key in self._config and self._config.get(key) is not None else default

    def get_exif(self) -> Dict[str, Any]:
        return self.get('exif')

    def getcolor(self, key: str, default: Any = None) -> Any:
        return _parse_color(self._config.get(key, default))

    def getint(self, key: str, default: int = 0) -> int:
        return int(self.get(key, default))

    def getenum(self, key: str, default: Any = None, enum: Type[Enum] = None) -> Any:
        value = self.get(key, default)

        # 未指定枚举类型，直接返回原值
        if enum is None:
            return value

        # 已经是目标枚举类型，直接返回
        if isinstance(value, enum):
            return value

        # 尝试通过 name 查找 (如 "RED" -> Color.RED)
        if isinstance(value, str):
            try:
                return enum[value]
            except KeyError:
                pass
            try:
                return enum[value.upper()]
            except KeyError:
                pass

        # 尝试通过 value 查找 (如 1 -> Color.RED)
        try:
            return enum(value)
        except ValueError:
            pass

        # 都找不到，返回默认值
        return default

    def get_processor_name(self):
        return self.get("processor_name")

    def get_buffer(self) -> List[Image]:
        if not self.get("buffer_loaded", False) and self.get("buffer_path"):
            self.set("buffer", [ImageOps.exif_transpose(Image.open(path)) for path in self.get("buffer_path")])
            self.set("buffer_loaded", True)
        return self.get("buffer", [])

    def set(self, key: str, value: Any):
        self._config[key] = value

    def save_buffer(self, processor_name: str, force_save: bool = False):
        if not (force_save or self.get("save_buffer", False)):
            return self
        directory = self.get("output", "./tmp")
        if not os.path.isdir(directory):
            os.makedirs(directory)
        buffer_path = []
        for img in self.get_buffer():
            if img.mode == "RGB":
                file_ext = "jpg"
            elif img.mode == "RGBA":
                file_ext = "png"
            else:
                raise RuntimeError(f"Unsupported image mode {img.mode}")

            new_filename = f"{processor_name}_{int(time.time())}_{uuid.uuid4().hex}.{file_ext}"
            path = os.path.join(directory, new_filename)
            img.save(path)
            logger.debug(f"Saved image: {path}")
        buffer_path.append(path)
        self.set("buffer_path", buffer_path)
        return self

    def update_buffer(self, buffer: List[Image]):
        self.set("buffer", buffer)
        return self

    def success(self, success: bool = True):
        self.set("success", success)
        return self

    # MutableMapping 要求实现的抽象方法
    def __getitem__(self, key: str) -> Any:
        return self._config[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._config[key] = value

    def __delitem__(self, key: str) -> None:
        del self._config[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._config)

    def __len__(self) -> int:
        return len(self._config)


class ImageProcessor(ABC):
    @abstractmethod
    def process(self, ctx: PipelineContext):
        pass

    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def category(self) -> str:
        pass

    def __init_subclass__(cls, **kwargs):
        """
        这个钩子方法会在子类定义时自动调用。
        在这里我们可以对子类的方法进行拦截（Hook）。
        """
        super().__init_subclass__(**kwargs)

        # 获取子类原本定义的 process 方法
        original_process = cls.process

        # 定义一个包装函数（切面逻辑）
        @functools.wraps(original_process)
        def wrapper(self, ctx: PipelineContext):
            start_time = time.perf_counter()  # 使用高精度计时
            original_ctx = ctx
            text = self.name() in {'rich_text', 'multi_rich_text'}
            if text:
                from processor.render_slots import effective_text, tag_text
                if ctx.get('slot_style'):
                    ctx = PipelineContext(effective_text(ctx))
            try:
                policy = ctx.get('brand_glyph_policy')
                if policy is not None:
                    with brand_glyph_policy(policy):
                        return original_process(self, ctx)
                # 执行原本的业务逻辑
                return original_process(self, ctx)
            finally:
                if text and ctx.get('success'):
                    images = [tag_text(image, ctx) for image in ctx.get_buffer()]
                    original_ctx.update_buffer(images).success()
                end_time = time.perf_counter()
                cost_ms = (end_time - start_time) * 1000
                # 打印日志
                logger.debug(f"[monitor]processor#{self.name()} cost {cost_ms:.2f}ms")


    # 将子类的 process 方法替换为包装后的方法
        cls.process = wrapper

        # 自动注册到注册表
        # 注意：这里我们注册的是类本身，而不是实例
        # 需要创建一个临时实例来获取 name()，或者要求子类实现类方法/属性
        try:
            # 尝试创建实例来获取 name
            # 注意：如果 __init__ 需要参数，这里可能会失败
            instance = cls()
            key = instance.name()
            register_processor(key, cls)
        except Exception as e:
            # 如果无法创建实例，可以要求子类实现类级别的 name 属性
            logger.warning(f"Could not auto-register {cls.__name__}: {e}")
            # 或者可以抛出自定义异常要求子类实现特定接口
            raise TypeError(
                f"{cls.__name__} must be instantiable without arguments "
                f"for auto-registration, or implement a class-level 'name' property."
            ) from e


class Direction(Enum):
    """拼接方向"""
    HORIZONTAL = "horizontal"  # 水平拼接（左到右）
    VERTICAL = "vertical"  # 垂直拼接（上到下）
    DIAGONAL = "diagonal"  # 对角
    RADIAL = "radial"  # 径向


def _parse_color(color) -> tuple:
    """
    解析颜色为 RGBA 元组

    支持格式:
    - 元组: (255, 255, 255) 或 (255, 255, 255, 128)
    - 字符串元组: '(255,255,255,0)' 或 '255,255,255,0'
    - 十六进制: '#FFFFFF' 或 '#FFFFFFFF'
    - 颜色名称: 'red', 'blue' 等
    """
    # 已经是元组或列表
    if isinstance(color, (tuple, list)):
        if len(color) == 3:
            return *color, 255
        return tuple(color)

    # 字符串处理
    if isinstance(color, str):
        color = color.strip()

        # 处理元组格式字符串: '(255,255,255,0)' 或 '255,255,255,0'
        color_clean = color.strip('()')
        if ',' in color_clean:
            try:
                parts = [int(x.strip()) for x in color_clean.split(',')]
                if len(parts) == 3:
                    return *parts, 255
                elif len(parts) == 4:
                    return tuple(parts)
            except ValueError:
                pass

        # 处理十六进制或颜色名称
        try:
            rgba = ImageColor.getrgb(color)
            if len(rgba) == 3:
                return *rgba, 255
            return rgba
        except ValueError:
            pass

    raise ValueError(f"无法解析颜色: {color}")


_processor_registry: Dict[str, Type['ImageProcessor']] = {}


def get_all_processors() -> Dict[str, Type['ImageProcessor']]:
    """获取所有已注册的处理器"""
    return _processor_registry.copy()


def get_processor(key: str) -> Optional[Type['ImageProcessor']]:
    """从注册表获取处理器类

    Args:
        key: 处理器名称

    Returns:
        处理器类，如果未找到则返回 None
    """
    return _processor_registry.get(key)


def register_processor(key: str, processor_cls: Type['ImageProcessor']):
    """注册处理器到全局注册表"""
    if key in _processor_registry:
        return
    _processor_registry[key] = processor_cls
    logger.debug(f"Registered processor: {key} -> {processor_cls.__name__}")


def _preview_filter_key(processor, node, input_keys):
    """只缓存输入身份明确的内置重型滤镜"""
    if (len(input_keys) != 1 or input_keys[0] is None or node.get('save_buffer', False)
            or 'preview_cache_params' not in processor.__dict__):
        return None
    return ('filter', processor, input_keys[0], processor.preview_cache_params(node))


def _source_identity(key):
    """从内部预览身份提取与画质无关的文件版本"""
    if isinstance(key, tuple) and len(key) == 4 and key[0] == 'filter':
        return _source_identity(key[2])
    if isinstance(key, tuple) and len(key) >= 4 and key[0] in ('source', 'file'):
        return ('file', key[1], key[2], key[3])
    return None


def uses_frame_layers(node):
    """仅显式声明画框或启用新前景功能时切换新引擎"""
    return ('custom_frame' in node or 'frame_style' in node or 'overlay_mode' in node or bool(node.get('palette_bar'))
            or bool(node.get('adaptive_logo_invert')))


def _clear_identities(buffers, identities, changed):
    """未知处理器可能原位修改输入，不再复用相同对象的来源身份"""
    affected = {id(image) for image in changed}
    for images, keys in zip(buffers, identities):
        for index, image in enumerate(images):
            if id(image) in affected:
                keys[index] = None


def start_process(data: List[dict], input_path: str = None, output_path: str = None, initial_buffer: List = None,
                  *, preview_source_key=None, cancelled=None, image_id=None, collect_metadata=False):
    """
    执行处理管道

    Args:
        data: 处理器配置列表
        input_path: 输入文件路径
        output_path: 输出文件路径
        initial_buffer: 初始图像缓冲区（可选，用于不从文件加载的情况）
    """
    check_cancelled(cancelled)
    if collect_metadata:
        from processor.render_slots import prepare_slots
        prepare_slots(data)
    nodes = [PipelineContext(datum) for datum in data]

    # 设置初始 buffer
    if initial_buffer is not None:
        nodes[0].set("buffer", initial_buffer)
        nodes[0].set("buffer_loaded", True)
    elif input_path is not None:
        nodes[0].set("buffer_path", [input_path])

    # 填充 exif 信息
    if input_path is not None:
        exif = get_exif(input_path)
        for node in nodes:
            if 'exif' not in node:
                node['exif'] = exif

    # 所有处理器的输出, 0 被看作是头元素的输出
    output = nodes[0].get_buffer()

    all_buffer = [output]
    frame_provenance = any(node.get('processor_name') in {'watermark', 'watermark_with_timestamp'} for node in data)
    source_id = _source_identity(image_id) or _source_identity(preview_source_key)
    if frame_provenance and source_id is None and initial_buffer is None:
        paths = [input_path] if input_path is not None else nodes[0].get('buffer_path', [])
        if isinstance(paths, (tuple, list)) and len(paths) == 1:
            source_id = file_image_id(paths[0])
    source_stage = None
    all_stages = None
    if frame_provenance:
        if source_id is not None and len(output) == 1:
            source_stage = (preview_source_key if _source_identity(preview_source_key) == source_id else
                            ('source', *source_id[1:], output[0].size, output[0].mode, 'input'))
        all_stages = [[source_stage] if len(output) == 1 else [None] * len(output)]
    all_keys = None
    if preview_source_key is not None:
        initial_keys = [preview_source_key] if len(output) == 1 else [None] * len(output)
        all_keys = [initial_keys]
    last_merger_idx = -1

    for idx, node in enumerate(nodes):
        check_cancelled(cancelled)
        input_keys = None
        processor = get_processor(node.get_processor_name())
        if processor is None:
            raise RuntimeError(f"Processor '{node.get_processor_name()}' not found")

        processor_instance: ImageProcessor = processor()
        # 预览节点可指定独立输入，避免重新读取原图的步骤被上一输出覆盖
        if 'input_buffer' in node:
            node.update_buffer(node['input_buffer'])
            node['buffer_loaded'] = True
            if all_keys is not None:
                supplied = node.get('_preview_input_keys')
                if supplied is not None and len(supplied) == len(node['input_buffer']):
                    input_keys = list(supplied)
                else:
                    input_keys = ([preview_source_key] if node.get('_preview_source_input', False)
                                  and len(node['input_buffer']) == 1 else [None] * len(node['input_buffer']))
            if all_stages is not None:
                supplied = node.get('_preview_input_keys')
                if supplied is not None and len(supplied) == len(node['input_buffer']):
                    input_stages = [item if _source_identity(item) is not None else None for item in supplied]
                elif node.get('_preview_source_input', False) and len(node['input_buffer']) == 1:
                    input_stages = [source_stage]
                else:
                    input_stages = [None] * len(node['input_buffer'])
        elif 'select' in node:
            indexes = json.loads(node['select'])
            flattened = list(chain.from_iterable([all_buffer[i] for i in indexes]))
            node.update_buffer(flattened)
            if all_keys is not None:
                input_keys = list(chain.from_iterable([all_keys[i] for i in indexes]))
            if all_stages is not None:
                input_stages = list(chain.from_iterable([all_stages[i] for i in indexes]))
        else:
            # 使用 category() 方法判断是否为 merger，避免导入 Merger 类
            if processor_instance.category() != "merger":
                node.update_buffer(output)
                if all_keys is not None:
                    input_keys = all_keys[-1][:]
                if all_stages is not None:
                    input_stages = all_stages[-1][:]
            else:
                # 收集下标从上一个 merger 之后, 到当前 idx 为止的 buffer
                buffers_to_merge = all_buffer[last_merger_idx + 1:idx + 1]

                # 将数组的数组展平为数组
                flattened = list(chain.from_iterable(buffers_to_merge))
                node.update_buffer(flattened)
                if all_keys is not None:
                    input_keys = list(chain.from_iterable(all_keys[last_merger_idx + 1:idx + 1]))
                if all_stages is not None:
                    input_stages = list(chain.from_iterable(all_stages[last_merger_idx + 1:idx + 1]))
                last_merger_idx = idx

        if all_stages is not None:
            paths = node.get('buffer_path')
            if paths and not node.get('buffer_loaded', False) and isinstance(paths, (tuple, list)):
                input_stages = [file_image_id(path) for path in paths]
            provenance_inputs = node.get('buffer', [])
            if node.get_processor_name() in {'watermark', 'watermark_with_timestamp'}:
                stage = input_stages[0] if len(input_stages) == 1 else None
                node['_frame_image_id'] = _source_identity(stage)
                node['_frame_cache_key'] = stage
            derived_stage = _preview_filter_key(processor, node, input_stages)

        if collect_metadata and node.get_processor_name() in {'watermark', 'watermark_with_timestamp'}:
            inputs = node.get_buffer()
            if inputs:
                node['_render_input_size'] = inputs[0].size

        if all_keys is None:
            processor_instance.process(node)
            check_cancelled(cancelled)
            output = node.get_buffer()
            if all_stages is not None:
                if 'preview_cache_params' not in processor.__dict__:
                    _clear_identities(all_buffer, all_stages, provenance_inputs)
                trusted = derived_stage is not None and len(output) == 1
                all_stages.append([derived_stage] if trusted else [None] * len(output))
            all_buffer.append(output)
            continue
        if input_keys is None:
            input_keys = []
        cacheable = 'preview_cache_params' in processor.__dict__
        if cacheable:
            # 独立文件输入可能替代上一步缓冲区，不能沿用其身份
            reloads_file = bool(node.get('buffer_path')) and not node.get('buffer_loaded', False)
            input_images = node.get_buffer()
            if reloads_file or len(input_keys) != len(input_images):
                input_keys = [None] * len(input_images)
            key = _preview_filter_key(processor, node, input_keys)
        else:
            input_images = node.get('buffer', [])
            key = None
        cached = cached_preview_image(key) if key is not None else None
        if cached is not None:
            node.update_buffer([cached]).success()
        else:
            processor_instance.process(node)
            check_cancelled(cancelled)
            current = node.get_buffer()
            if key is not None and len(current) == 1:
                cache_preview_image(key, current[0])
            else:
                key = None
        if key is None and preview_source_key is not None:
            # 其他处理器可能原位修改输入，清除所有相同对象的缓存身份
            _clear_identities(all_buffer, all_keys, input_images)
            if all_stages is not None:
                _clear_identities(all_buffer, all_stages, input_images)
        output = node.get_buffer()
        if all_stages is not None:
            trusted = derived_stage is not None and len(output) == 1
            all_stages.append([derived_stage] if trusted else [None] * len(output))
        all_buffer.append(output)
        all_keys.append([key] if key is not None and len(output) == 1 else [None] * len(output))

    check_cancelled(cancelled)
    nodes[-1].save_buffer("final").success()
    if output_path is not None:
        nodes[-1].get_buffer()[0].convert("RGB").save(output_path, quality=load_config().getint('DEFAULT', 'quality'), subsampling=load_config().getint('DEFAULT', 'subsampling'))
        logger.success(f"Generated new image: {output_path}")
    return nodes[-1].get_buffer()[0]
