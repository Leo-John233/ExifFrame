"""文字与标识槽位选择及独立样式编辑"""

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from core.configs import fonts_dir
from core.footer import FooterError, has_dynamic_structure, set_slot_style, slot_targets
from .controls import CameraRawSlider, CollapsibleSection, ColorProperty
from .i18n import bind, region_title, tr, translator
from .inspector_footer import InlineFooter


class SlotEditor(QWidget):
    source_changed = Signal(str)
    slot_selected = Signal(str)
    advanced_source_requested = Signal()
    logo_visibility_changed = Signal(bool)
    interaction_started = Signal(str)
    interaction_finished = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ''
        self._baseline = ''
        self._targets = {}
        self._defaults = {}
        self._static_targets = {}
        self._static_defaults = {}
        self._rendered = {}
        self._inherited = {}
        self._selected = 'global'
        self._virtual_logo_visible = True
        self._syncing = False
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.buttons = {}
        self._button_keys = None
        self._font_signature = None
        try:
            self._font_paths = sorted(path for path in fonts_dir.iterdir()
                                      if path.is_file() and path.suffix.lower() in {'.ttf', '.otf', '.ttc'})
        except OSError:
            self._font_paths = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.selector = QWidget()
        self.selector.setMinimumWidth(0)
        self.selector.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.selector_layout = QGridLayout(self.selector)
        self.selector_layout.setContentsMargins(0, 0, 0, 0)
        self.selector_layout.setSpacing(4)
        layout.addWidget(self.selector)
        self.visible = bind(QPushButton(), '显示当前槽位')
        self.visible.setCheckable(True)
        self.visible.toggled.connect(self._set_visible)
        layout.addWidget(self.visible)
        self.pages = QStackedWidget()
        self.pages.setMinimumWidth(0)
        self.pages.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.global_page, self.logo_page, self.text_page = QWidget(), QWidget(), QWidget()
        self.global_layout = QVBoxLayout(self.global_page)
        self.logo_layout = QVBoxLayout(self.logo_page)
        text_layout = QVBoxLayout(self.text_page)
        for page_layout in (self.global_layout, self.logo_layout, text_layout):
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(7)
        self.dynamic_page = QWidget()
        dynamic = QVBoxLayout(self.dynamic_page)
        dynamic.setContentsMargins(0, 0, 0, 0)
        dynamic.setSpacing(7)
        note = bind(QLabel(), '此槽位由动态源码生成，请在高级源码中编辑')
        note.setWordWrap(True)
        dynamic.addWidget(note)
        self.dynamic_details = QLabel()
        self.dynamic_details.setWordWrap(True)
        self.dynamic_details.setTextInteractionFlags(self.dynamic_details.textInteractionFlags())
        dynamic.addWidget(self.dynamic_details)
        source_button = bind(QPushButton(), '打开高级源码')
        source_button.clicked.connect(self.advanced_source_requested)
        dynamic.addWidget(source_button)
        dynamic.addStretch()
        self.dynamic_logo = QWidget()
        dynamic_logo_layout = QVBoxLayout(self.dynamic_logo)
        dynamic_logo_layout.setContentsMargins(0, 0, 0, 0)
        dynamic_logo_note = bind(QLabel(), '此槽位由动态源码生成，请在高级源码中编辑')
        dynamic_logo_note.setWordWrap(True)
        dynamic_logo_layout.addWidget(dynamic_logo_note)
        dynamic_logo_button = bind(QPushButton(), '打开高级源码')
        dynamic_logo_button.clicked.connect(self.advanced_source_requested)
        dynamic_logo_layout.addWidget(dynamic_logo_button)
        self.logo_layout.addWidget(self.dynamic_logo)
        for page in (self.global_page, self.logo_page, self.text_page, self.dynamic_page):
            page.setMinimumWidth(0)
            page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            self.pages.addWidget(page)
        layout.addWidget(self.pages)

        self.style_section = CollapsibleSection('槽位样式')
        form = QFormLayout(self.style_section.body)
        form.setContentsMargins(0, 0, 0, 0)
        self.font_combo = QComboBox()
        self.font_combo.setObjectName('slotFontChoice')
        self.font_combo.setMinimumWidth(0)
        self.font_combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.font_combo.currentIndexChanged.connect(self._font_changed)
        form.addRow(bind(QLabel(), '字体'), self.font_combo)
        self.size_slider = CameraRawSlider(1, 2000, 32, suffix=' px')
        self.size_slider.setObjectName('slotFontSize')
        bind(self.size_slider, '字号')
        self.size_slider.valueChanged.connect(self._size_changed)
        self.size_slider.set_reset_action(self._reset_size)
        self.size_slider.interaction_started.connect(lambda: self.interaction_started.emit('slotFontSize'))
        self.size_slider.interaction_finished.connect(lambda: self.interaction_finished.emit('slotFontSize'))
        form.addRow(self.size_slider)
        self.color = ColorProperty('文字颜色')
        self.color.color_changed.connect(lambda value: self._change({'color': value}))
        self.color.reset_requested.connect(lambda: self._reset_property('color'))
        form.addRow(self.color)
        self.style_section.reset_requested.connect(self.reset_style)
        text_layout.addWidget(self.style_section)
        self.footer_section = CollapsibleSection('内容模板')
        footer_layout = QVBoxLayout(self.footer_section.body)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer = InlineFooter()
        self.footer.source_changed.connect(self._footer_changed)
        footer_layout.addWidget(self.footer)
        self.footer_section.reset_requested.connect(self.reset_content)
        text_layout.addWidget(self.footer_section)
        self.dynamic_text = QWidget()
        dynamic_text_layout = QVBoxLayout(self.dynamic_text)
        dynamic_text_layout.setContentsMargins(0, 0, 0, 0)
        dynamic_text_note = bind(QLabel(), '此槽位由动态源码生成，请在高级源码中编辑')
        dynamic_text_note.setWordWrap(True)
        dynamic_text_layout.addWidget(dynamic_text_note)
        self.dynamic_text_value = QLabel()
        self.dynamic_text_value.setWordWrap(True)
        dynamic_text_layout.addWidget(self.dynamic_text_value)
        dynamic_text_button = bind(QPushButton(), '打开高级源码')
        dynamic_text_button.clicked.connect(self.advanced_source_requested)
        dynamic_text_layout.addWidget(dynamic_text_button)
        text_layout.addWidget(self.dynamic_text)
        translator.language_changed.connect(self._retranslate)
        self._rebuild_buttons()
        self._sync()

    def _read_targets(self, source):
        try:
            from core.slot_style_metadata import strip_slot_metadata
            if has_dynamic_structure(source):
                return {}
            return slot_targets(strip_slot_metadata(source))
        except (ValueError, TypeError):
            return {}

    def _merge_rendered_targets(self):
        from core.slot_style_metadata import read_slot_metadata
        self._targets = dict(self._static_targets)
        self._defaults = dict(self._static_defaults)
        try:
            styles = read_slot_metadata(self._source)
            defaults = read_slot_metadata(self._baseline)
        except (ValueError, TypeError):
            styles, defaults = {}, {}
        for key, style in styles.items():
            if key in self._targets:
                self._targets[key] = {**self._targets[key], 'style': {**self._targets[key].get('style', {}), **style}}
        for key, style in defaults.items():
            if key in self._defaults:
                self._defaults[key] = {**self._defaults[key], 'style': {**self._defaults[key].get('style', {}), **style}}
        for key, slot in self._rendered.items():
            if key not in self._targets and isinstance(slot, dict):
                kind = slot.get('kind', 'text')
                self._targets[key] = {'kind': kind, 'node': {}, 'style': styles.get(key, {}), 'dynamic': True}
                self._defaults[key] = {'kind': kind, 'node': {}, 'style': defaults.get(key, {}), 'dynamic': True}
        if not any(target.get('kind') == 'logo' for target in self._targets.values()):
            self._targets['logo'] = {'kind': 'logo', 'node': {}, 'style': {}, 'virtual': True}

    def set_logo_visible(self, visible):
        self._virtual_logo_visible = bool(visible)
        if self._selected == 'logo':
            self._sync()

    def set_source(self, source, *, baseline=None):
        baseline = source if baseline is None else baseline
        baseline_changed = baseline != self._baseline
        self._source, self._baseline = source or '', baseline or ''
        self._static_targets = self._read_targets(self._source)
        self._static_defaults = self._read_targets(self._baseline)
        self._merge_rendered_targets()
        if baseline_changed:
            self._inherited = {}
        self.footer.adopt_style_source(self._source)
        if self._selected != 'global' and self._selected not in self._targets:
            self._selected = 'global'
        self._rebuild_buttons()
        self._sync()

    def set_rendered_slots(self, slots):
        self._rendered = dict(slots or {})
        self._merge_rendered_targets()
        if not self._rendered:
            self._inherited.clear()
        if self._selected != 'global' and self._selected not in self._targets:
            self._selected = 'global'
        for key, slot in self._rendered.items():
            if not isinstance(slot, dict):
                continue
            style = self._targets.get(key, {}).get('style', {})
            defaults = self._defaults.get(key, {}).get('style', {})
            cache = self._inherited.setdefault(key, {})
            for prop, metadata in (('font_path', 'font'), ('color', 'color'), ('height', 'font_size')):
                value = slot.get('base_' + metadata)
                if value is not None:
                    cache[prop] = value
                elif style.get(prop) == defaults.get(prop) and slot.get(metadata) is not None:
                    cache[prop] = slot[metadata]
        self._rebuild_buttons()
        self._sync()

    def select_slot(self, key, *, notify=True):
        key = str(key)
        if key != 'global' and key not in self._targets and key not in self._rendered:
            return False
        self._selected = key
        self._sync()
        if notify:
            self.slot_selected.emit(key)
        return True

    def _label(self, key):
        if key == 'global':
            return tr('全局比例')
        if self._targets.get(key, self._rendered.get(key, {})).get('kind') == 'logo':
            if key.startswith('watermark_'):
                number = key.split('_')[1]
                return tr('水印 {number} · 标识', number=number)
            return tr('标识')
        return region_title(key)

    def _rebuild_buttons(self, *, force=False):
        keys = ['global'] + list(self._targets) + [key for key in self._rendered if key not in self._targets]
        order = {key: index for index, key in enumerate(keys)}
        def kind(key):
            return self._targets.get(key, self._rendered.get(key, {})).get('kind')
        keys.sort(key=lambda key: (0 if key == 'global' else 1 if kind(key) == 'logo' else 2, order[key]))
        signature = tuple((key, kind(key) if key != 'global' else '') for key in keys)
        if not force and signature == self._button_keys:
            return
        self._button_keys = signature
        while self.selector_layout.count():
            item = self.selector_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = {}
        for index, key in enumerate(keys):
            button = QPushButton(self._label(key))
            button.setObjectName('slotCapsule')
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self.select_slot(value))
            self.selector_layout.addWidget(button, index // 3, index % 3)
            self.buttons[key] = button

    def _actual(self, prop, fallback):
        slot = self._rendered.get(self._selected, {})
        metadata = {'font_path': 'font', 'color': 'color', 'height': 'font_size'}[prop]
        return slot.get(metadata) or fallback

    def _base(self, prop):
        cached = self._inherited.get(self._selected, {}).get(prop)
        if cached is not None:
            return cached
        target = self._defaults.get(self._selected, {})
        style, node = target.get('style', {}), target.get('node', {})
        value = style.get(prop, node.get(prop))
        if value is None and isinstance(node.get('text_segments'), list) and node['text_segments']:
            value = node['text_segments'][0].get(prop)
        if isinstance(value, str) and ('{{' in value or '{%' in value):
            return None
        return value

    def _sync(self):
        self._syncing = True
        try:
            for key, button in self.buttons.items():
                button.setChecked(key == self._selected)
            target = self._targets.get(self._selected)
            rendered = self._rendered.get(self._selected)
            self.visible.setVisible(target is not None)
            if target is None and rendered is not None:
                self.pages.setCurrentIndex(3)
                details = []
                for title, key in (('字体', 'font'), ('字号', 'font_size'), ('文字颜色', 'color'),
                                   ('内容', 'text'), ('标识', 'logo')):
                    value = rendered.get(key)
                    if value is not None and value != '':
                        details.append(f"{tr(title)}: {value}{' px' if key == 'font_size' else ''}")
                self.dynamic_details.setText('\n'.join(details))
                return
            if target is None:
                self.pages.setCurrentIndex(0)
                return
            style = target.get('style', {})
            rendered = self._rendered.get(self._selected, {})
            with QSignalBlocker(self.visible):
                visible = self._virtual_logo_visible if target.get('virtual') else style.get('visible', rendered.get('visible', True))
                self.visible.setChecked(visible)
            self.visible.setText(tr('隐藏此槽位' if self.visible.isChecked() else '显示此槽位'))
            dynamic = bool(target.get('dynamic'))
            if target['kind'] == 'logo':
                self.dynamic_logo.setVisible(dynamic)
                self.pages.setCurrentIndex(1)
                return
            self.pages.setCurrentIndex(2)
            self.footer_section.setVisible(not dynamic)
            self.dynamic_text.setVisible(dynamic)
            if dynamic:
                self.dynamic_text_value.setText(str(rendered.get('text', '')))
            else:
                self.footer.select_region(self._selected)
            defaults = self._defaults.get(self._selected, {}).get('style', {})
            inherited = style.get('font_path') == defaults.get('font_path')
            selected = style.get('font_path') if not inherited else ''
            self._populate_fonts(selected or '')
            actual_size = (style.get('height') if style.get('height') != defaults.get('height')
                           else self._actual('height', self._base('height')))
            try:
                actual_size = max(1, min(2000, round(float(actual_size))))
            except (ValueError, TypeError):
                actual_size = None
            with QSignalBlocker(self.size_slider):
                self.size_slider.setSpecialValueText(tr('等待预览') if actual_size is None else '')
                self.size_slider.setValue(actual_size or 1)
                self.size_slider.setEnabled(actual_size is not None)
            color = (style.get('color') if style.get('color') != defaults.get('color')
                     else self._actual('color', self._base('color') or tr('等待预览')))
            self.color.set_color(str(color), inherited=style.get('color') == defaults.get('color'))
        finally:
            self._syncing = False

    def _populate_fonts(self, selected):
        base = self._base('font_path')
        base_text = Path(str(base)).name if base else tr('等待预览')
        signature = (base_text, selected)
        if signature == self._font_signature:
            return
        self._font_signature = signature
        with QSignalBlocker(self.font_combo):
            self.font_combo.clear()
            self.font_combo.addItem(tr('沿用模板 · {value}', value=base_text), '')
            for path in self._font_paths:
                self.font_combo.addItem(path.stem, path.name)
            self.font_combo.addItem(tr('选择字体…'), '__choose__')
            index = self.font_combo.findData(selected)
            if index < 0 and selected:
                self.font_combo.insertItem(self.font_combo.count() - 1, Path(str(selected)).name, selected)
                index = self.font_combo.findData(selected)
            self.font_combo.setCurrentIndex(max(0, index))

    def _font_changed(self, _):
        if self._syncing:
            return
        value = self.font_combo.currentData()
        if value == '__choose__':
            value, _ = QFileDialog.getOpenFileName(self, tr('选择字体'), '', tr('字体文件 (*.ttf *.otf *.ttc)'))
            if not value:
                self._sync()
                return
        if value:
            self._change({'font_path': value})
        else:
            self._reset_property('font_path')

    def _size_changed(self, value):
        if not self._syncing:
            self._change({'height': int(value), 'height_ratio': None}, refresh=False)

    def _set_visible(self, visible):
        if not self._syncing:
            if self._targets.get(self._selected, {}).get('virtual'):
                self._virtual_logo_visible = bool(visible)
                self.logo_visibility_changed.emit(bool(visible))
                self._sync()
            else:
                self._change({'visible': bool(visible)})

    def _reset_property(self, name):
        defaults = self._defaults.get(self._selected, {}).get('style', {})
        self._change({name: defaults.get(name)})

    def _reset_size(self):
        defaults = self._defaults.get(self._selected, {}).get('style', {})
        self._change({'height': defaults.get('height'), 'height_ratio': defaults.get('height_ratio')})

    def reset_style(self):
        defaults = self._defaults.get(self._selected, {}).get('style', {})
        self._change({key: defaults.get(key) for key in ('font_path', 'color', 'height', 'height_ratio')})

    def reset_content(self):
        # 字段内容由逐项编辑维护，不静默覆盖其他槽位或复杂源表达式
        self.footer.reset_region(self._baseline, self._selected)

    def _change(self, changes, *, refresh=True):
        if self._syncing or self._selected == 'global':
            return
        try:
            source = set_slot_style(self._source, self._selected, changes)
        except (FooterError, TypeError, ValueError):
            self._sync()
            return
        if source == self._source:
            return
        self._source = source
        self._static_targets = self._read_targets(source)
        self._merge_rendered_targets()
        self.footer.adopt_style_source(source)
        if refresh:
            self._sync()
        self.source_changed.emit(source)

    def _footer_changed(self, source):
        self._source = source
        self._static_targets = self._read_targets(source)
        self._merge_rendered_targets()
        self.source_changed.emit(source)

    def _retranslate(self):
        self._font_signature = None
        self._rebuild_buttons(force=True)
        self._sync()
