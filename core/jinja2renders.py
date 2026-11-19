from jinja2 import pass_context

from core.configs import logos_dir


@pass_context
def vw(context, percent):
    exif = context.get('exif', {})
    return int(int(exif.get('ImageWidth', 0)) * percent / 100)


@pass_context
def vh(context, percent):
    exif = context.get('exif', {})
    return int(int(exif.get('ImageHeight', 0)) * percent / 100)


@pass_context
def auto_logo(context, brand: str = None):
    exif = context.get('exif', {})
    brand = str(brand or exif.get('Make') or 'default').strip().casefold()
    variants = []
    for path in sorted(logos_dir.iterdir()):
        if path.suffix.lower() not in {'.png', '.jpg', '.jpeg'}:
            continue
        name = path.stem.casefold()
        if name in brand:
            return path.absolute().as_posix()
        # Leica、Olympus 等品牌文件名还带版本或配色后缀
        manufacturer = name.replace('-', '_').split('_', 1)[0]
        if manufacturer != name and manufacturer in brand:
            variants.append(path)
    if variants:
        return variants[0].absolute().as_posix()
    return None
