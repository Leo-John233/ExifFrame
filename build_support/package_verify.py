"""在隔离目录中检查单文件发行包的真实运行能力"""

import json
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory


_PRESETS = (
    '背景模糊', '标准水印', '标准水印2', '仅标识居中',
    '尼康专用背景模糊', '文件夹名+右下角参数', '右下角参数', 'logo居中',
)


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_package(report_path: Path) -> int:
    """结果写入指定文件，所有照片和设置均留在报告旁的隔离目录"""
    from core.runtime_paths import initialize_user_config, is_onefile, resource_path, user_data_root

    report = {'ok': False, 'data_root': str(user_data_root()), 'checks': {}}
    checks = report['checks']

    def check(name, action):
        try:
            checks[name] = {'ok': True, 'result': action()}
        except Exception as error:
            checks[name] = {'ok': False, 'error': str(error), 'traceback': traceback.format_exc()}

    try:
        _require(is_onefile(), 'The executable is not a marked single-file build')
        initialize_user_config(migrate_legacy=False)
        from PIL import Image, ImageFont
        import pillow_heif
        from PySide6.QtCore import QCoreApplication
        from core import desktop_service as service, metadata, util
        from core.sample_photo import example_photo_path
        from studio import i18n

        sample = example_photo_path()
        bundle_tool = resource_path('exiftool/exiftool.exe')
        # 即使程序旁有旧工具，也要测试真正内置的副本
        util.EXIFTOOL_PATH = bundle_tool

        def resources():
            for path in (sample, resource_path('static/logo.ico'), resource_path('pyproject.toml')):
                _require(path.is_file(), f'Missing resource: {path}')
            _require((bundle_tool.parent / 'exiftool_files').is_dir(), 'Missing ExifTool runtime directory')
            _require(util.find_exiftool() is not None, 'Missing bundled ExifTool executable')
            with Image.open(sample) as photo:
                photo.verify()
            return {'sample': str(sample), 'exiftool': str(util.find_exiftool())}

        def presets():
            found = {item.name for item in service.list_presets()}
            for name in _PRESETS:
                _require((resource_path('config/templates') / f'{name}.json').is_file(), f'Missing bundled template: {name}')
                _require(name in found, f'Missing user template: {name}')
                service.validate_template(service.read_template(name))
            return list(_PRESETS)

        def fonts():
            paths = [service.config_path('fonts') / name for name in
                     ('AlibabaPuHuiTi-2-45-Light.otf', 'AlibabaPuHuiTi-2-85-Bold.otf')]
            for path in paths:
                _require(path.is_file(), f'Missing font: {path}')
                _require(ImageFont.truetype(str(path), 32).getbbox('ExifFrame 测试') is not None, f'Unable to load font: {path}')
            return [path.name for path in paths]

        def translations():
            i18n.set_language('zh_CN')
            _require(i18n.tr('相机显示文字') == '相机显示文字', 'Chinese application translations failed')
            _require(bool(i18n._qt_translators), 'Chinese Qt translations failed to load')
            translated = QCoreApplication.translate('QPlatformTheme', 'Cancel')
            _require(translated and translated != 'Cancel', 'Chinese Qt text failed')
            i18n.set_language('en_US')
            _require(i18n.tr('相机显示文字') == 'Camera text', 'English application translations failed')
            _require(not i18n._qt_translators, 'English Qt translations were not reset')
            _require(QCoreApplication.translate('QPlatformTheme', 'Cancel') == 'Cancel', 'English Qt text failed')
            return {'chinese_qt_cancel': translated, 'english_qt_cancel': 'Cancel'}

        def persistence():
            name = '单文件验证模板'
            source = service.read_template('标准水印')
            state = user_data_root() / '.verification-state.json'
            previous = state.is_file()
            if previous:
                expected = json.loads(state.read_text(encoding='utf-8'))
                _require(service.read_template(name) == expected['template'], 'Custom template did not persist')
                settings = service.load_settings()
                _require(settings.template_name == name and settings.title == '持久化验证' and settings.quality == 93,
                         'Workspace settings did not persist')
                _require(i18n.language() == 'en_US', 'Language preference did not persist')
            else:
                service.write_template(name, source, create=True)
                settings = service.WatermarkSettings(template_name=name, title='持久化验证', quality=93)
                service.save_workspace_settings(settings)
                i18n.set_language('en_US')
                state.write_text(json.dumps({'template': source}, ensure_ascii=False), encoding='utf-8')
            initialize_user_config(migrate_legacy=False)
            _require(service.read_template(name) == source, 'Custom template changed after initialization')
            return {'previous_run_verified': previous, 'template': name}

        check('resources', resources)
        check('templates', presets)
        check('fonts', fonts)
        # 重启验证必须先检查上次保存的语言，再测试切换
        check('persistence', persistence)
        check('translations', translations)

        with TemporaryDirectory(dir=user_data_root(), prefix='.verification-') as directory:
            temporary = Path(directory)

            def exiftool():
                read = util.get_exif(sample)
                _require(bool(read) and read.get('FileType') == 'JPEG', 'ExifTool did not read the sample JPEG')
                target = temporary / '元数据副本.jpg'
                metadata.save_metadata_copy(sample, target, {'Artist': 'ExifFrame 测试'})
                values = metadata.read_metadata(target)
                _require(values.get('Artist') == 'ExifFrame 测试', 'ExifTool metadata round trip failed')
                return {'file_type': read['FileType'], 'artist': values['Artist']}

            def heif():
                pillow_heif.register_heif_opener()
                photo = temporary / '测试.heic'
                Image.new('RGB', (64, 48), '#6387a2').save(photo, format='HEIF')
                with Image.open(photo) as image:
                    image.load()
                    _require(image.size == (64, 48), 'HEIF decode failed')
                return {'size': [64, 48], 'bytes': photo.stat().st_size}

            def rendering():
                sizes = {}
                for name in _PRESETS:
                    settings = service.WatermarkSettings(template_name=name)
                    result = service.render_photo(sample, settings)
                    _require(result.width > 0 and result.height > 0, f'Template did not render: {name}')
                    sizes[name] = list(result.size)
                output = service.export_photo(sample, service.WatermarkSettings(template_name='标准水印'), temporary / 'output')
                with Image.open(output) as image:
                    image.verify()
                return {'preview_sizes': sizes, 'export_bytes': output.stat().st_size}

            check('exiftool_read_write', exiftool)
            check('heif_round_trip', heif)
            check('render_and_export', rendering)
        report['ok'] = bool(checks) and all(item['ok'] for item in checks.values())
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['ok'] else 1
