"""从原始品牌素材恢复透明边缘；尺寸和原有排版留白保持不变"""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image


WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
# 已核对的原图底色和印刷色；这些规则只用于本仓库的出厂素材
INKS = {
    'canon': (WHITE, [(255, 0, 0)]),
    'dji': (WHITE, [(21, 21, 21)]),
    'fujifilm': (WHITE, [BLACK, (237, 26, 58)]),
    'hasselblad': (WHITE, [(35, 24, 21)]),
    'leica_logo': (WHITE, [(237, 28, 36)]),
    'olympus_blue_gold': (WHITE, [(8, 16, 123), (233, 178, 38)]),
    'olympus_white_gold': ((19, 14, 117), [WHITE, (233, 178, 38)]),
    'panasonic': (WHITE, [BLACK]),
    'panasonic2': (WHITE, [(0, 86, 168)]),
    'pentax': (WHITE, [(255, 0, 23), (255, 0, 0)]),
    'ricoh': (WHITE, [(215, 6, 59)]),
    'sony': (WHITE, [(55, 52, 53)]),
    'sony_dark': (BLACK, [WHITE]),
    'xmage': ((192, 0, 1), [WHITE]),
}


def unmatte(rgb, paper, inks):
    """对每种品牌色求解 C = aF + (1-a)B，选回合成误差最小的解"""
    delta = rgb.astype(np.float32) - paper
    best = np.full(rgb.shape[:2], np.inf, dtype=np.float32)
    result = np.zeros((*rgb.shape[:2], 4), np.uint8)
    for ink in inks:
        vector = np.asarray(ink, dtype=np.float32) - paper
        coverage = np.clip(np.sum(delta * vector, axis=2) / np.dot(vector, vector), 0, 1)
        error = np.sum((delta - coverage[:, :, None] * vector) ** 2, axis=2)
        match = error < best
        best[match] = error[match]
        result[match, :3] = ink
        alpha = coverage[match] * 255
        # 清除原素材压缩留下的近底色噪点，保留真正的半透明过渡
        result[match, 3] = np.where(alpha < 4, 0, np.where(alpha > 252, 255, np.rint(alpha)))
    return result


def clean(path):
    name = path.stem.lower()
    with Image.open(path) as original:
        rgba = original.convert('RGBA')
    if name == 'nikon':
        # 黄色方章与白色光带均属于标识本体
        return rgba
    if name == 'default':
        # 缺少厂商时的空占位，没有字标；沿用原始布局尺寸
        return Image.new('RGBA', rgba.size)
    if name == 'apple':
        ink = Image.new('RGBA', rgba.size, (153, 153, 153))
        ink.putalpha(rgba.getchannel('A'))
        return ink
    if rgba.getchannel('A').getextrema()[0] == 0:
        return rgba
    paper, inks = INKS[name]
    paper = np.asarray(paper, dtype=np.float32)
    # 分条处理大尺寸徽标，避免为整幅图片分配多份浮点缓冲
    for top in range(0, rgba.height, 128):
        box = (0, top, rgba.width, min(rgba.height, top + 128))
        source = np.asarray(rgba.crop(box))
        pixels = unmatte(source[:, :, :3], paper, inks)
        if name == 'leica_logo':
            # 原图是红色实心圆章；同一扫描线两侧红色轮廓之间保留白色签名
            for y, row in enumerate(pixels):
                red = np.flatnonzero(row[:, 3] >= 248)
                if red.size:
                    interior = slice(red[0], red[-1] + 1)
                    row[interior] = source[y, interior]
        pixels[:, :, 3] = ((pixels[:, :, 3].astype(np.uint16) * source[:, :, 3] + 127) // 255)
        rgba.paste(Image.fromarray(pixels), box[:2])
    return rgba


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='原始 17 个 Logo 所在目录')
    parser.add_argument('destination', type=Path, help='输出 PNG 的目录')
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    for name in sorted((*INKS, 'apple', 'default', 'nikon')):
        filename = 'DJI' if name == 'dji' else name
        src = args.source / (filename + '.png')
        if name == 'dji' and not src.is_file():
            src = src.with_suffix('.jpg')
        image = clean(src)
        image.save(args.destination / (filename + '.png'))
        print(f'{filename:20} {image.width}x{image.height}  alpha={image.getchannel("A").getextrema()}')


if __name__ == '__main__':
    main()
