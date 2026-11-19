"""按当前字体度量绘制可切换的尼康品牌字形"""

from __future__ import annotations

import math
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from threading import RLock

from PIL import Image, ImageChops, ImageDraw, ImageFont


POLICIES = ('geometric', 'plain_z', 'system')
_policy = ContextVar('brand_glyph_policy', default='geometric')
_glyph_cache = OrderedDict()
_glyph_lock = RLock()
_GLYPH_LIMIT = 64
_GLYPH_BYTES = 16 * 1024 * 1024
_glyph_bytes = 0


def current_policy():
    return _policy.get()


def validate_policy(value):
    if value not in POLICIES:
        raise ValueError('品牌符号策略无效')
    return value


@contextmanager
def brand_glyph_policy(value):
    """按任务隔离策略并在退出或异常时恢复"""
    token = _policy.set(validate_policy(value))
    try:
        yield
    finally:
        _policy.reset(token)


def node_glyph_policy(function):
    """让独立文字节点可覆盖外层任务的符号策略"""
    @wraps(function)
    def wrapper(node, *args, **kwargs):
        value = node.get('brand_glyph_policy')
        if value is None:
            return function(node, *args, **kwargs)
        with brand_glyph_policy(value):
            return function(node, *args, **kwargs)
    return wrapper


@dataclass(frozen=True)
class FontMetrics:
    cap_top: float
    cap_height: float
    z_width: float
    stem_v: float
    bar_h: float
    lsb: float
    rsb: float


def _measure_run_length(pixels: list[int], reverse: bool = False) -> int:
    seq = reversed(pixels) if reverse else pixels
    started = False
    count = 0
    for v in seq:
        if v >= 128:
            started = True
            count += 1
        elif started:
            break
    return count


def measure_font_metrics(font: ImageFont.FreeTypeFont) -> FontMetrics:
    """从真实 H 和 Z 测量字高、笔画与左右留白"""
    target_size = getattr(font, "size", 64)
    ref_size = max(target_size, 180)
    scale = target_size / float(ref_size)
    try:
        ref_font = font.font_variant(size=ref_size)
    except Exception:
        ref_font = font
        scale = 1.0

    def rasterize(ch: str) -> tuple[Image.Image, tuple[int, int, int, int]]:
        bbox = ref_font.getbbox(ch)
        if not bbox:
            return Image.new("L", (1, 1), 0), (0, 0, 1, 1)
        x0, y0, x1, y1 = bbox
        w, h = max(1, x1 - x0), max(1, y1 - y0)
        img = Image.new("L", (w, h), 0)
        ImageDraw.Draw(img).text((-x0, -y0), ch, font=ref_font, fill=255)
        return img, bbox

    h_img, h_bbox = rasterize("H")
    z_img, z_bbox = rasterize("Z")

    cap_top_ref = z_bbox[1]
    cap_h_ref = max(1, z_bbox[3] - z_bbox[1])
    z_w_ref = max(1, z_bbox[2] - z_bbox[0])

    # 1. 从 'H' 上半部（避开中间横杠）测竖杠粗细 stem_v
    hy = int(h_img.height * 0.25)
    h_row = [h_img.getpixel((x, hy)) for x in range(h_img.width)]
    stem_v_ref = max(2, _measure_run_length(h_row))

    # 2. 从 'Z' 上下横杠测横杠粗细 bar_h
    zx_top = int(z_img.width * 0.28)
    zx_bot = int(z_img.width * 0.72)
    top_col = [z_img.getpixel((zx_top, y)) for y in range(z_img.height)]
    bot_col = [z_img.getpixel((zx_bot, y)) for y in range(z_img.height)]
    bar_h_ref = 0.5 * (
        max(2, _measure_run_length(top_col, reverse=False))
        + max(2, _measure_run_length(bot_col, reverse=True))
    )

    z_adv_ref = float(ref_font.getlength("Z"))
    lsb_ref = max(0.0, float(z_bbox[0]))
    rsb_ref = max(0.0, z_adv_ref - float(z_bbox[2]))

    return FontMetrics(
        cap_top=cap_top_ref * scale,
        cap_height=cap_h_ref * scale,
        z_width=z_w_ref * scale,
        stem_v=stem_v_ref * scale,
        bar_h=bar_h_ref * scale,
        lsb=lsb_ref * scale,
        rsb=rsb_ref * scale,
    )


def _measure_ink(font):
    """按真实墨迹测量大写字高、Z 字宽和左右留白"""
    sampled, scale = font, 1.0

    def bounds(character):
        box = sampled.getbbox(character)
        raw = sampled.getmask(character, mode='L')
        image = Image.frombytes('L', raw.size, bytes(raw))
        ink = image.point(lambda value: 255 if value >= 128 else 0).getbbox()
        if not ink:
            return box
        return box[0] + ink[0], box[1] + ink[1], box[0] + ink[2], box[1] + ink[3]

    z, h = bounds('Z'), bounds('H')
    left, right = max(0.0, z[0] * scale), max(0.0, (sampled.getlength('Z') - z[2]) * scale)
    return ((z[2] - z[0]) * scale, min(z[1], h[1]) * scale,
            (max(z[3], h[3]) - min(z[1], h[1])) * scale, left, right)


def render_nikon_z_mask(
    font: ImageFont.FreeTypeFont,
    supersample: int = 8,
    *,
    profile: str = 'reference',
) -> tuple[Image.Image, float, float, float]:
    """
    生成高精度抗锯齿尼康 ℤ 字形灰度掩码。
    返回: (alpha_mask, draw_offset_x, draw_offset_y, advance_width)
    """
    if profile not in ('reference', 'screenshot'):
        raise ValueError('品牌字形配置无效')
    m = measure_font_metrics(font)
    ink = _measure_ink(font) if profile == 'screenshot' else None
    H = max(4.0, ink[2] if ink else m.cap_height)
    r = m.stem_v / H  # 真实字重比（Light ~0.045, Regular ~0.09, Bold ~0.17+）

    # 1. 字宽随字重适度放宽，保证双斜杠与中缝呼吸感（Bold 下接近正方形）
    W = max(m.z_width * 1.12, H * (0.86 + 0.75 * r))
    if ink:
        W = max(1.0, ink[0] * (1.075 + .15 * r))

    # 2. 横杠厚度严格跟随当前字体 'Z' 的 bar_h，极粗字重仅做微弱光学收敛
    th = m.bar_h * (1.0 - 0.35 * max(0.0, r - 0.13))
    th = max(1.0, min(th, 0.165 * H))
    if ink:
        boost = max(0.0, min(1.0, (r - .085) / .12))
        th = max(1.0, min(m.bar_h * (1 + .30 * boost) * (1 - .35 * max(0.0, r - .13)), .19 * H))

    # 3. 光学黑度守恒：字越粗，单条斜杠相对主竖杠比例越收敛，避免双斜杠发闷
    t_weight = max(0.0, min(1.0, (r - 0.045) / (0.185 - 0.045)))
    diag_ratio = 0.86 - 0.29 * t_weight          # Light: ~0.86x, Bold: ~0.57x
    d_perp = max(1.0, m.stem_v * diag_ratio)     # 单条斜杠真实法向宽度
    g_perp = max(0.088 * H, 0.54 * m.stem_v)     # 中缝真实法向宽度，绝不塌缩成细缝
    if ink:
        d_perp = max(1.0, m.stem_v * (.72 - .20 * t_weight))
        g_perp = max(.060 * H, .30 * m.stem_v)

    # 4. 不动点迭代：将法向宽度 (d_perp, g_perp) 精确投影为 y=th / y=H-th 上的水平切宽
    dy = max(1.0, H - 2.0 * th)
    d_total_perp = 2.0 * d_perp + g_perp
    cos_theta = 0.78
    for _ in range(5):
        D_h = min(W * 0.68, d_total_perp / max(0.35, cos_theta))
        dx = max(1.0, W - D_h)
        cos_theta = dy / math.hypot(dx, dy)

    D_h = min(W * 0.68, d_total_perp / max(0.35, cos_theta))
    ratio_d = d_perp / d_total_perp
    d_h = D_h * ratio_d
    g_h = D_h - 2.0 * d_h

    # 5. 8x 超采样绘制：平齐无衬线拐角 + 严格平行双斜杠
    ss = supersample
    pad = 2
    out_w = max(1, math.ceil(W) + pad * 2)
    out_h = max(1, math.ceil(H) + pad * 2)
    hi = Image.new("L", (out_w * ss, out_h * ss), 0)
    draw = ImageDraw.Draw(hi)

    ox, oy = pad * ss, pad * ss
    W_s, H_s, th_s = W * ss, H * ss, th * ss
    D_s, d_s, g_s = D_h * ss, d_h * ss, g_h * ss

    # 上下横杠（左右端垂直平齐，匹配无衬线 Z）
    draw.rectangle([ox, oy, ox + W_s, oy + th_s], fill=255)
    draw.rectangle([ox, oy + H_s - th_s, ox + W_s, oy + H_s], fill=255)

    # 沿精确斜率向横杠内微延 1px 消除接缝，同时保持中缝在 [th, H-th] 内绝对锐利
    slope = (W_s - D_s) / max(1.0, H_s - 2.0 * th_s)
    eps = 1.0
    dx_eps = slope * eps

    # 左斜杠
    left_diag = [
        (ox + W_s - D_s + dx_eps, oy + th_s - eps),
        (ox + W_s - D_s + d_s + dx_eps, oy + th_s - eps),
        (ox + d_s - dx_eps, oy + H_s - th_s + eps),
        (ox - dx_eps, oy + H_s - th_s + eps),
    ]
    # 右斜杠（外边缘平齐接入右上角 (W, th)）
    right_diag = [
        (ox + W_s - d_s + dx_eps, oy + th_s - eps),
        (ox + W_s + dx_eps, oy + th_s - eps),
        (ox + D_s - dx_eps, oy + H_s - th_s + eps),
        (ox + d_s + g_s - dx_eps, oy + H_s - th_s + eps),
    ]
    draw.polygon(left_diag, fill=255)
    draw.polygon(right_diag, fill=255)

    # 精确裁剪回 [0, W] x [0, H] 防止微延超出外轮廓
    mask_hi = Image.new("L", hi.size, 0)
    ImageDraw.Draw(mask_hi).rectangle([ox, oy, ox + W_s, oy + H_s], fill=255)
    hi = Image.composite(hi, Image.new("L", hi.size, 0), mask_hi)

    # BOX 面积积分下采样：边缘丝滑抗锯齿且无 LANCZOS 振铃光晕
    mask = hi.resize((out_w, out_h), Image.Resampling.BOX)

    lsb = max(m.lsb, 0.04 * H)
    rsb = max(m.rsb, 0.04 * H)
    cap_top = m.cap_top
    if ink:
        lsb = max(0.0, .015 * H - .15 * ink[3])
        rsb = max(0.0, .015 * H - .25 * ink[4])
        cap_top = ink[1]
    advance = lsb + W + rsb
    return mask, lsb - pad, cap_top - pad, advance


def brand_glyph(font, supersample=8, *, profile='screenshot'):
    """复用字形遮罩、绘制偏移与独立步进"""
    global _glyph_bytes
    token = getattr(font, '_exifframe_token', None)
    key = (token, getattr(font, 'size', None), supersample, profile) if token is not None else None
    if key is not None:
        with _glyph_lock:
            cached = _glyph_cache.get(key)
            if cached is not None:
                _glyph_cache.move_to_end(key)
                return cached[0].copy(), *cached[1:4]
    mask, offset_x, offset_y, advance = render_nikon_z_mask(font, supersample, profile=profile)
    cost = mask.width * mask.height
    if key is not None and cost <= _GLYPH_BYTES:
        with _glyph_lock:
            old = _glyph_cache.pop(key, None)
            if old:
                _glyph_bytes -= old[4]
            while _glyph_cache and (_glyph_bytes + cost > _GLYPH_BYTES or len(_glyph_cache) >= _GLYPH_LIMIT):
                _, entry = _glyph_cache.popitem(last=False)
                _glyph_bytes -= entry[4]
            _glyph_cache[key] = (mask.copy(), offset_x, offset_y, advance, cost)
            _glyph_bytes += cost
    return mask, offset_x, offset_y, advance


def draw_brand_glyph(canvas, font, origin, color):
    """按 Z 的左右留白和字高合成独立颜色的几何字形"""
    mask, offset_x, offset_y, _ = brand_glyph(font)
    rgba = tuple(color) if isinstance(color, (tuple, list)) else color
    layer = Image.new('RGBA', mask.size, rgba)
    if layer.getpixel((0, 0))[3] != 255:
        mask = ImageChops.multiply(mask, layer.getchannel('A'))
    layer.putalpha(mask)
    canvas.alpha_composite(layer, (round(origin[0] + offset_x), round(origin[1] + offset_y)))
