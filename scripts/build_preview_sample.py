"""从项目原有展示图的照片区域重建无水印交互示例"""

from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image
from PIL.TiffImagePlugin import IFDRational


SOURCE_SHA256 = 'a640cde0b05978c5c99f4115fc82c43f838cb01cf23b35939beb6c8e7147a612'
PHOTO_BOX = (0, 0, 8256, 5504)
OUTPUT_SIZE = (1920, 1280)


def build_preview_sample() -> Path:
    """按已核验边界裁掉底栏，参数只依据原图底栏的可见内容"""
    root = Path(__file__).resolve().parents[1]
    source = root / 'static' / 'standard1.jpeg'
    destination = root / 'static' / 'preview.jpg'
    if sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('来源样图已变化，请重新核对照片边界和可见拍摄参数')
    with Image.open(source) as image:
        if image.size != (8256, 6164):
            raise ValueError('来源样图尺寸与已核验记录不一致')
        # 白色底栏从第 5504 行开始，660 像素等于照片高度的 12% 向下取整
        photo = image.crop(PHOTO_BOX).resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
        profile = image.info.get('icc_profile')

    exif = Image.Exif()
    exif[271] = 'NIKON'
    # 保留可见字面型号，不猜测已被移除的原始型号标签
    exif[272] = 'NIKON Z 72'
    exif[274] = 1
    exif[305] = 'ExifFrame bundled sample preparation'
    # 原展示图不含拍摄 EXIF，下列示例字段由现有底栏抄录
    # 时间只显示到分钟，秒数补 00 仅满足 EXIF 格式，不代表实测秒数
    note = (
        'ExifFrame bundled preview sample derived from static/standard1.jpeg; '
        'crop [0,0,8256,5504], resized to 1920x1280. '
        'Shooting fields were transcribed from the existing visible footer, '
        'not recovered from original EXIF. The visible time is 2026-01-10 15:56; '
        'seconds are padded with 00 and the time zone is unknown.'
    )
    exif[34665] = {
        33434: IFDRational(1, 1600),
        33437: IFDRational(18, 10),
        34855: 64,
        36867: '2026:01:10 15:56:00',
        37386: IFDRational(50, 1),
        37510: b'ASCII\x00\x00\x00' + note.encode('ascii'),
        40961: 1,
        40962: OUTPUT_SIZE[0],
        40963: OUTPUT_SIZE[1],
        41989: 50,
        42036: 'NIKKOR Z 50mm f/1.8 S',
    }
    with NamedTemporaryFile(dir=destination.parent, prefix='.preview-', suffix='.jpg', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            photo.save(stream, format='JPEG', quality=94, subsampling=0, optimize=True,
                       exif=exif, icc_profile=profile)
        except Exception:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    print(build_preview_sample())
