"""验证模板预览、导出保护与本机设置恢复"""

import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from core import desktop_service as service


class DesktopServiceTests(unittest.TestCase):
    """使用生成的照片测试真实水印流水线"""

    def setUp(self):
        cache = Path('.serena/cache/tests').resolve()
        cache.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(dir=cache)
        self.folder = Path(self.temporary.name).resolve()
        # 临时目录必须位于项目缓存内，清理时不触及用户照片
        self.assertTrue(self.folder.is_relative_to(cache))
        self.addCleanup(self.temporary.cleanup)
        self.source = self.folder / '旅行照片.jpg'
        Image.new('RGB', (900, 600), '#42769A').save(self.source)
        self.settings = service.WatermarkSettings()

    def test_all_presets_render_and_preserve_source(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        self.assertGreaterEqual(len(service.list_presets()), 7)
        for preset in service.list_presets():
            with self.subTest(template=preset.name):
                settings = replace(self.settings, template_name=preset.name,
                                   title='旅途 "A"', subtitle='第二行\n署名', show_logo=False)
                result = service.render_photo(self.source, settings)
                self.assertGreater(result.width, 0)
                self.assertGreater(result.height, 0)
                self.assertLessEqual(max(result.size), 1600)
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).digest())

    def test_export_never_overwrites_existing_photos(self):
        first = service.export_photo(self.source, self.settings, self.folder)
        existing = first.read_bytes()
        second = service.export_photo(self.source, self.settings, self.folder)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), existing)
        self.assertNotEqual(first, self.source)
        with Image.open(first) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(image.width, 900)
            self.assertGreater(image.height, 600)

    def test_preview_preserves_export_layout_ratio(self):
        Image.new('RGB', (2400, 1600), '#42769A').save(self.source)
        settings = replace(self.settings, template_name='标准水印2')
        preview = service.render_photo(self.source, settings)
        full = service.render_photo(self.source, settings, preview=False)
        self.assertAlmostEqual(preview.width / preview.height, full.width / full.height, delta=0.015)
        self.assertLess(preview.width, full.width)

    def test_missing_exiftool_uses_photo_metadata_and_orientation(self):
        exif = Image.Exif()
        exif[272] = 'Test Camera'
        exif[274] = 6
        Image.new('RGB', (900, 600), '#42769A').save(self.source, exif=exif)
        with patch.object(service, 'EXIFTOOL_PATH', self.folder / 'missing.exe'):
            rendered = service.render_photo(self.source, self.settings)
        self.assertEqual(rendered.width, 600)
        self.assertGreater(rendered.height, 900)

    def test_settings_roundtrip_and_corruption_recovery(self):
        path = self.folder / 'settings.json'
        with patch.object(service, 'SETTINGS_PATH', path):
            settings = replace(self.settings, title='中文署名', quality=86)
            service.save_settings(settings)
            self.assertEqual(service.load_settings(), settings)
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(service.load_settings(), service.WatermarkSettings())
            path.write_text(json.dumps({'font_scale': 'bad'}), encoding='utf-8')
            self.assertEqual(service.load_settings(), service.WatermarkSettings())

    def test_invalid_template_and_ranges_fail_before_render(self):
        for settings in (replace(self.settings, template_name='../outside'),
                         replace(self.settings, quality=101), replace(self.settings, font_scale=0)):
            with self.assertRaises(ValueError):
                service.render_photo(self.source, settings)


if __name__ == '__main__':
    unittest.main()
