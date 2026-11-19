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
    from processor.logo_layer import resolve_logo_path
    exif = context.get('exif', {})
    brand = str(brand or exif.get('Make') or 'default').strip().casefold()
    candidates = [path for path in sorted(logos_dir.iterdir()) if path.suffix.lower() in {'.png', '.jpg', '.jpeg'}]
    exact = next((path for path in candidates if path.stem.casefold() == brand), None)
    if exact:
        return resolve_logo_path(exact).as_posix()
    variants = []
    for path in candidates:
        name = path.stem.casefold()
        if name in brand:
            return resolve_logo_path(path).as_posix()
        # Leica、Olympus 等品牌文件名还带版本或配色后缀
        manufacturer = name.replace('-', '_').split('_', 1)[0]
        if manufacturer != name and manufacturer in brand:
            variants.append(path)
    if variants:
        return resolve_logo_path(variants[0]).as_posix()
    return None
