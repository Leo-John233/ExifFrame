"""右侧模板、样式和照片信息面板"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy,
    QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from core.configs import fonts_dir
from .controls import CameraRawSlider
from .custom_frame_panel import CustomFramePanel
from .i18n import bind, tr, translator
from .inspector_footer import InlineFooter
from .pixmaps import TemplateThumbnail


_COMMON_FIELDS = (
    ('Make', '相机制造商'), ('Model', '相机型号'), ('LensModel', '镜头型号'),
    ('FocalLength', '实际焦距'), ('FNumber', '光圈'), ('ExposureTime', '快门速度'),
    ('ISO', '感光度'), ('DateTimeOriginal', '拍摄时间'), ('Location', '地点名'),
    ('UserComment', '自定义文字'),
)
_ALIASES = {'Model': ('Model', 'CameraModelName'), 'ExposureTime': ('ExposureTime', 'ShutterSpeed')}
_BRANDS = ('Canon', 'Nikon', 'Sony', 'Fujifilm', 'Panasonic', 'Olympus',
           'Pentax', 'Leica', 'Hasselblad', 'Ricoh', 'DJI', 'Apple')
_FRAME_OPTIONS = (
    ('未指定', ''), ('纯色边框', 'solid_border'), ('拍立得宽底', 'polaroid_bottom'),
    ('毛玻璃卡片', 'blurred_glass'), ('画廊装裱', 'gallery_mat'), ('胶片暗房', 'film_strip'),
)
_OVERLAY_OPTIONS = (('默认位置', ''), ('内嵌覆盖', 'inset_overlay'))
_SWITCH_OPTIONS = (('开启', True), ('停用', False))
_ANCHOR_OPTIONS = (('左上', 'top_left'), ('右上', 'top_right'), ('左下', 'bottom_left'),
                   ('右下', 'bottom_right'), ('底部', 'bottom'))
_FRAME_DEFAULT = '__template_default__'


class CollapsibleSection(QWidget):
    """紧凑的可折叠设置分组"""

    def __init__(self, title, *, expanded=True, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = QToolButton()
        self.toggle.setObjectName('inspectorSection')
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bind(self.toggle, title)
        self.body = QWidget()
        self.body.setVisible(expanded)
        self.toggle.toggled.connect(self.body.setVisible)
        self.toggle.toggled.connect(lambda value: self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow))
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)


class TemplateCard(QFrame):
    """保持图片比例的可点击模板卡片"""

    selected = Signal(str)

    def __init__(self, preset, parent=None):
        super().__init__(parent)
        self.preset = preset
        self.setObjectName('inspectorTemplateCard')
        self.setProperty('selected', False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet('''
            QFrame#inspectorTemplateCard { background: #202123; border: 1px solid #454648; border-radius: 5px; }
            QFrame#inspectorTemplateCard:hover { border-color: #808080; }
            QFrame#inspectorTemplateCard[selected="true"] { background: #303133; border: 2px solid #A4A4A4; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 6)
        layout.setSpacing(5)
        self.thumbnail = TemplateThumbnail()
        self.thumbnail.setObjectName('templatePreview')
        self.thumbnail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.thumbnail.set_source(preset.thumbnail)
        self.title = QLabel()
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.thumbnail)
        layout.addWidget(self.title)
        self.retranslate()

    def retranslate(self):
        title = self.preset.title if self.preset.description == '自定义水印模板' else tr(self.preset.title)
        self.title.setText(title)
        self.setToolTip(tr(self.preset.description))
        self.setAccessibleName(title)
        if not self.preset.thumbnail:
            self.thumbnail.setText(tr('自定义模板'))

    def set_selected(self, selected):
        if self.property('selected') == selected:
            return
        self.setProperty('selected', selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.selected.emit(self.preset.name)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.selected.emit(self.preset.name)
            event.accept()
            return
        super().keyPressEvent(event)


class Inspector(QWidget):
    """集中管理当前照片的模板、样式和 EXIF 操作"""

    template_selected = Signal(str)
    style_changed = Signal(str, object)
    interaction_started = Signal(str)
    interaction_finished = Signal(str)
    metadata_changed = Signal(str, object)
    metadata_apply_requested = Signal(str, object)
    metadata_requested = Signal()
    apply_current_requested = Signal()
    sync_style_requested = Signal()
    new_template_requested = Signal()
    use_as_default_requested = Signal()
    copy_template_requested = Signal()
    import_style_requested = Signal()
    export_style_requested = Signal()
    advanced_source_requested = Signal()
    footer_editor_requested = Signal()
    metadata_editor_requested = Signal()
    export_changed = Signal(str, object)
    output_directory_requested = Signal()
    save_settings_requested = Signal()
    reset_settings_requested = Signal()
    lock_settings_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('inspectorPanel')
        self.setMinimumWidth(290)
        self.setMaximumWidth(440)
        self._syncing = False
        self._locked = False
        self._busy = False
        self._dirty = False
        self._photo_path = None
        self._photo_read_only = False
        self._edited_fields = set()
        self._checked_count = 0
        self._total_count = 0
        self._selected_template = ''
        self._cards = {}
        self._presets = []
        self._style_values = {}
        self._active_text = None
        self._frame_source = ''
        self._frame_baseline_source = None
        self._frame_document = None
        self._frame_index = None
        self._frame_defaults = {}
        self.metadata_fields = {}
        self.metadata_checks = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(7)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('inspectorTabs')
        self.tabs.setStyleSheet('QTabBar::tab { padding: 6px 9px; }')
        self.tabs.tabBar().setExpanding(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.template_page = self._build_templates()
        self.style_page = self._build_style()
        self.metadata_page = self._build_metadata()
        self.tabs.addTab(self.template_page, tr('模板预设'))
        self.tabs.addTab(self.style_page, tr('样式与文本').replace('&', '&&'))
        self.tabs.addTab(self.metadata_page, tr('EXIF 信息'))
        outer.addWidget(self.tabs, 1)

        self.apply_current_button = self._button('仅应用到当前照片', self.apply_current_requested.emit)
        self.sync_style_button = self._button('同步样式到全部已勾选', self.sync_style_requested.emit)
        outer.addWidget(self.apply_current_button)
        outer.addWidget(self.sync_style_button)
        self.sync_metadata_button = self._button('批量覆写已勾选 EXIF', self._apply_checked_metadata)
        self.sync_metadata_button.setVisible(False)
        outer.addWidget(self.sync_metadata_button)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.lock_button = QPushButton()
        self.lock_button.setCheckable(True)
        self.lock_button.toggled.connect(self._lock_changed)
        self.save_button = self._button('保存设置', self.save_settings_requested.emit)
        self.reset_button = self._button('重置设置', self.reset_settings_requested.emit)
        for button in (self.lock_button, self.save_button, self.reset_button):
            button.setStyleSheet('padding-left: 2px; padding-right: 2px;')
        controls.addWidget(self.lock_button)
        controls.addWidget(self.save_button)
        controls.addWidget(self.reset_button)
        outer.addLayout(controls)
        self.saved_label = QLabel()
        self.saved_label.setObjectName('secondaryText')
        self.saved_label.setWordWrap(True)
        outer.addWidget(self.saved_label)
        translator.language_changed.connect(self._retranslate)
        self._retranslate()
        self._update_actions()

    @staticmethod
    def _button(text, callback):
        button = QPushButton()
        button.setAutoDefault(False)
        button.setMinimumWidth(0)
        bind(button, text)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _scroll():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(3, 8, 7, 8)
        layout.setSpacing(9)
        scroll.setWidget(body)
        return scroll, body, layout

    def _build_templates(self):
        scroll, body, layout = self._scroll()
        self._template_body = body
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self._button('新建', self.new_template_requested.emit))
        row.addWidget(self._button('高级源码', self.advanced_source_requested.emit))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self._button('另存我的模板', self.copy_template_requested.emit))
        row.addWidget(self._button('设为默认模板', self.use_as_default_requested.emit))
        layout.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(5)
        row.addWidget(self._button('导入样式包', self.import_style_requested.emit))
        row.addWidget(self._button('导出样式包', self.export_style_requested.emit))
        layout.addLayout(row)
        self._preset_category = self._combo('templateCategory')
        for label, value in (('全部模板', 'all'), ('内置模板', 'built_in'), ('我的模板', 'mine')):
            self._preset_category.addItem(tr(label), value)
        self._preset_category.currentIndexChanged.connect(self._rebuild_template_cards)
        layout.addWidget(self._preset_category)
        cards = QWidget()
        self._card_layout = QGridLayout(cards)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setHorizontalSpacing(7)
        self._card_layout.setVerticalSpacing(7)
        self._card_layout.setColumnStretch(0, 1)
        self._card_layout.setColumnStretch(1, 1)
        layout.addWidget(cards)
        layout.addStretch()
        return scroll

    def _build_style(self):
        scroll, body, layout = self._scroll()
        self._style_scroll = scroll
        self._style_body = body
        self.template_styles_check = QCheckBox()
        self.template_styles_check.setObjectName('useTemplateStylesCheck')
        bind(self.template_styles_check, '按模板原样处理')
        self.template_styles_check.toggled.connect(lambda value: self._emit_style('use_template_styles', value))
        layout.addWidget(self.template_styles_check)

        border = CollapsibleSection('边框与背景')
        form = QFormLayout(border.body)
        self._legacy_frame_notice = QLabel()
        self._legacy_frame_notice.setWordWrap(True)
        self._legacy_frame_notice.setObjectName('secondaryText')
        bind(self._legacy_frame_notice, '当前画框请在画框定制中调整')
        self._legacy_frame_notice.hide()
        form.addRow(self._legacy_frame_notice)
        self.frame_combo = self._combo('frameStyle')
        self.overlay_combo = self._combo('overlayMode')
        self.palette_combo = self._combo('paletteBar')
        self.frame_combo.currentIndexChanged.connect(lambda _: self._frame_changed('frame_style', self.frame_combo))
        self.overlay_combo.currentIndexChanged.connect(lambda _: self._frame_changed('overlay_mode', self.overlay_combo))
        self.palette_combo.currentIndexChanged.connect(lambda _: self._frame_changed('palette_bar', self.palette_combo))
        bind(self.overlay_combo, '内嵌覆盖优先于边框样式', 'setToolTip')
        form.addRow(self._label('边框样式'), self.frame_combo)
        form.addRow(self._label('文字覆盖方式'), self.overlay_combo)
        form.addRow(self._label('色卡栏'), self.palette_combo)
        self.glass_controls = QWidget()
        glass = QFormLayout(self.glass_controls)
        glass.setContentsMargins(0, 0, 0, 0)
        self.frame_brightness = self._number('背景亮度', -1, 200, -1, 'frameBrightness')
        self.frame_vignette = self._number('暗角强度', -1, 100, -1, 'frameVignette')
        self.frame_blur = self._number('模糊强度', -1, 100, -1, 'frameBlur')
        for key, spin in (
                ('frame_brightness', self.frame_brightness),
                ('frame_vignette', self.frame_vignette),
                ('frame_blur', self.frame_blur)):
            spin.valueChanged.connect(lambda value, name=key: self._frame_number_changed(name, value))
            glass.addRow(spin)
        form.addRow(self.glass_controls)
        self.inset_controls = QWidget()
        inset = QFormLayout(self.inset_controls)
        inset.setContentsMargins(0, 0, 0, 0)
        self.inset_anchor = self._combo('insetAnchor')
        self.inset_anchor.currentIndexChanged.connect(lambda _: self._frame_changed('inset_anchor', self.inset_anchor))
        self.overlay_opacity = self._number('覆盖不透明度', -1, 100, -1, 'overlayOpacity')
        self.overlay_opacity.valueChanged.connect(lambda value: self._frame_number_changed('overlay_opacity', value))
        inset.addRow(self._label('角标位置'), self.inset_anchor)
        inset.addRow(self.overlay_opacity)
        form.addRow(self.inset_controls)
        self.border_slider = self._number('底部留白', 5, 30, 5, 'borderSlider')
        form.addRow(self.border_slider)
        self.border_slider.valueChanged.connect(self._border_changed)
        self.background_button = self._button('底色', lambda: self._choose_color('background'))
        self.background_button.setObjectName('backgroundColorButton')
        form.addRow(self.background_button)
        layout.addWidget(border)

        custom = CollapsibleSection('画框定制', expanded=False)
        custom_layout = QVBoxLayout(custom.body)
        custom_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_frame = CustomFramePanel()
        self.custom_frame.source_changed.connect(self._custom_frame_source_changed)
        self.custom_frame.custom_changed.connect(self._set_custom_active)
        self.custom_frame.interaction_started.connect(self.interaction_started)
        self.custom_frame.interaction_finished.connect(self.interaction_finished)
        custom_layout.addWidget(self.custom_frame)
        layout.addWidget(custom)

        logo = CollapsibleSection('品牌标识')
        form = QFormLayout(logo.body)
        self.logo_check = QCheckBox()
        self.logo_check.setObjectName('showLogoCheck')
        bind(self.logo_check, '显示品牌标识')
        self.logo_check.toggled.connect(self._logo_enabled)
        self.logo_combo = self._combo('logoChoice')
        self.logo_combo.currentIndexChanged.connect(self._logo_changed)
        self.logo_invert_combo = self._combo('adaptiveLogoInvert')
        self.logo_invert_combo.currentIndexChanged.connect(
            lambda _: self._frame_changed('adaptive_logo_invert', self.logo_invert_combo))
        form.addRow(self.logo_check)
        form.addRow(self._label('标识来源'), self.logo_combo)
        form.addRow(self._label('自适应反转标识'), self.logo_invert_combo)
        layout.addWidget(logo)

        typography = CollapsibleSection('字体与颜色')
        form = QFormLayout(typography.body)
        self.font_combo = self._combo('fontChoice')
        self.font_combo.currentIndexChanged.connect(self._font_changed)
        form.addRow(self._label('字体'), self.font_combo)
        self.glyph_combo = self._combo('brandGlyphPolicy')
        self.glyph_combo.currentIndexChanged.connect(
            lambda _: self._emit_style('brand_glyph_policy', self.glyph_combo.currentData()))
        form.addRow(self._label('尼康 ℤ 符号'), self.glyph_combo)
        self.font_slider = self._number('水印缩放', 50, 200, 100, 'fontScaleSlider')
        form.addRow(self.font_slider)
        self.font_slider.valueChanged.connect(self._font_scale_changed)
        self.text_button = self._button('文字颜色', lambda: self._choose_color('text_color'))
        self.text_button.setObjectName('textColorButton')
        form.addRow(self.text_button)
        layout.addWidget(typography)

        text = CollapsibleSection('文字与间距', expanded=False)
        form = QFormLayout(text.body)
        self.title_input = QLineEdit()
        self.subtitle_input = QLineEdit()
        self.title_input.setObjectName('titleInput')
        self.subtitle_input.setObjectName('subtitleInput')
        for item in (self.title_input, self.subtitle_input):
            item.setMinimumWidth(0)
            bind(item, '留空使用照片信息', 'setPlaceholderText')
        self.title_input.textEdited.connect(lambda value: self._text_edited(self.title_input, 'title', value))
        self.subtitle_input.textEdited.connect(lambda value: self._text_edited(self.subtitle_input, 'subtitle', value))
        self.title_input.editingFinished.connect(lambda: self._finish_text(self.title_input))
        self.subtitle_input.editingFinished.connect(lambda: self._finish_text(self.subtitle_input))
        form.addRow(self._label('相机显示文字'), self.title_input)
        form.addRow(self._label('镜头显示文字'), self.subtitle_input)
        self.alignment_combo = self._combo('textAlignment')
        self.alignment_combo.currentIndexChanged.connect(
            lambda index: self._emit_style('text_alignment', self.alignment_combo.currentData()))
        form.addRow(self._label('右侧文字对齐'), self.alignment_combo)
        self.text_spacing_spin = self._number('片段间距', -1, 5000, -1, 'textSpacing', ' px')
        self.line_spacing_spin = self._number('行间距', -1, 5000, -1, 'lineSpacing', ' px')
        self.text_spacing_spin.valueChanged.connect(lambda value: self._emit_style('text_spacing', None if value < 0 else value))
        self.line_spacing_spin.valueChanged.connect(lambda value: self._emit_style('line_spacing', None if value < 0 else value))
        form.addRow(self.text_spacing_spin)
        form.addRow(self.line_spacing_spin)
        layout.addWidget(text)

        footer = CollapsibleSection('页脚字段', expanded=False)
        self.footer_section = footer
        footer_layout = QVBoxLayout(footer.body)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self.inline_footer = InlineFooter()
        self.inline_footer.source_changed.connect(lambda source: self._emit_style('template_source', source))
        footer_layout.addWidget(self.inline_footer)
        footer_layout.addWidget(self._button('完整字段排版…', self.footer_editor_requested.emit))
        layout.addWidget(footer)

        export = CollapsibleSection('输出设置', expanded=False)
        form = QFormLayout(export.body)
        self.quality_spin = self._number('JPEG 质量', 1, 100, 95, 'qualitySpin')
        self.quality_spin.valueChanged.connect(lambda value: self._emit_export('quality', value))
        form.addRow(self.quality_spin)
        self.output_input = QLineEdit()
        self.output_input.setMinimumWidth(0)
        self.output_input.textEdited.connect(lambda value: self._emit_export('output_dir', value.strip()))
        row = QHBoxLayout()
        row.addWidget(self.output_input, 1)
        browse = QPushButton('…')
        browse.clicked.connect(self.output_directory_requested.emit)
        row.addWidget(browse)
        form.addRow(self._label('输出目录'), row)
        self.overwrite_check = QCheckBox()
        bind(self.overwrite_check, '覆盖同名输出文件')
        self.overwrite_check.toggled.connect(lambda value: self._emit_export('overwrite_existing', value))
        self.structure_check = QCheckBox()
        bind(self.structure_check, '保留输入目录结构')
        self.structure_check.toggled.connect(lambda value: self._emit_export('preserve_structure', value))
        form.addRow(self.overwrite_check)
        form.addRow(self.structure_check)
        layout.addWidget(export)
        layout.addStretch()
        return scroll

    def _build_metadata(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(5, 8, 5, 5)
        layout.setSpacing(7)
        self.photo_label = QLabel()
        self.photo_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.photo_label.setObjectName('secondaryText')
        layout.addWidget(self.photo_label)
        self.metadata_stack = QStackedWidget()
        empty = QLabel()
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        bind(empty, '选择照片后编辑 EXIF')
        self.metadata_stack.addWidget(empty)
        scroll, body, form_layout = self._scroll()
        note = QLabel()
        note.setWordWrap(True)
        note.setObjectName('secondaryText')
        bind(note, '勾选字段仅用于批量同步')
        form_layout.addWidget(note)
        fields = QWidget()
        grid = QGridLayout(fields)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(2, 1)
        for row, (tag, caption) in enumerate(_COMMON_FIELDS):
            check = QCheckBox()
            check.setObjectName('metadataCheck_' + tag)
            check.toggled.connect(self._update_actions)
            label = self._label(caption)
            label.setWordWrap(True)
            editor = QLineEdit()
            editor.setObjectName('metadata_' + tag)
            editor.setMinimumWidth(0)
            editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            bind(editor, '未记录', 'setPlaceholderText')
            editor.textEdited.connect(lambda value, field=tag: self._metadata_edited(field, value))
            grid.addWidget(check, row, 0)
            grid.addWidget(label, row, 1)
            grid.addWidget(editor, row, 2)
            self.metadata_checks[tag] = check
            self.metadata_fields[tag] = editor
        form_layout.addWidget(fields)
        row = QHBoxLayout()
        row.addWidget(self._button('全选字段', lambda: self._select_fields(True)))
        row.addWidget(self._button('清除字段选择', lambda: self._select_fields(False)))
        form_layout.addLayout(row)
        form_layout.addWidget(self._button('更多 EXIF…', self.metadata_editor_requested.emit))
        form_layout.addStretch()
        self.metadata_stack.addWidget(scroll)
        layout.addWidget(self.metadata_stack, 1)
        return page

    @staticmethod
    def _label(text):
        label = QLabel()
        bind(label, text)
        return label

    def _number(self, label, low, high, default, name, suffix=''):
        slider = CameraRawSlider(low, high, default, suffix=suffix)
        slider.setObjectName(name)
        slider.setMinimumWidth(0)
        bind(slider, label)
        slider.interaction_started.connect(lambda: self.interaction_started.emit(name))
        slider.interaction_finished.connect(lambda: self.interaction_finished.emit(name))
        return slider

    @staticmethod
    def _combo(name):
        combo = QComboBox()
        combo.setObjectName(name)
        combo.setMinimumWidth(0)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(4)
        return combo

    def _text_edited(self, widget, key, value):
        if self._active_text is None or self._active_text[0] is not widget:
            self._active_text = (widget, key)
            self.interaction_started.emit(key)
        self._emit_style(key, value)

    def _finish_text(self, widget):
        if self._active_text is not None and self._active_text[0] is widget:
            key = self._active_text[1]
            self._active_text = None
            self.interaction_finished.emit(key)

    def _emit_style(self, key, value):
        if not self._syncing:
            self._style_values[key] = value
            self.style_changed.emit(key, value)

    def _emit_export(self, key, value):
        if not self._syncing:
            self.export_changed.emit(key, value)

    def _border_changed(self, value):
        self._emit_style('border_percent', None if value == 5 else value)

    def _font_scale_changed(self, value):
        self._emit_style('font_scale', value / 100)

    def _logo_enabled(self, checked):
        self.logo_combo.setEnabled(checked)
        self._emit_style('show_logo', checked)

    def _choose_color(self, key):
        color = QColorDialog.getColor(QColor(self._style_values.get(key, '#FFFFFF')), self)
        if color.isValid():
            value = color.name()
            self._set_swatch(self.background_button if key == 'background' else self.text_button, value)
            self._emit_style(key, value)

    @staticmethod
    def _set_swatch(button, color):
        swatch = QPixmap(24, 16)
        swatch.fill(Qt.GlobalColor.transparent)
        painter = QPainter(swatch)
        painter.fillRect(8, 1, 14, 14, QColor(color))
        painter.setPen(QColor('#949494'))
        painter.drawRect(8, 1, 13, 13)
        painter.end()
        button.setIcon(QIcon(swatch))
        button.setIconSize(QSize(24, 16))

    def _logo_changed(self, index):
        if self._syncing:
            return
        value = self.logo_combo.currentData()
        if value == '__choose__':
            path, _ = QFileDialog.getOpenFileName(self, tr('选择标识图片'), '', tr('图片 (*.png *.jpg *.jpeg)'))
            if not path:
                self._set_combo_value(self.logo_combo, self._style_values.get('logo_choice', ''))
                return
            value = str(Path(path).resolve())
            self._set_combo_value(self.logo_combo, value)
        self._emit_style('logo_choice', value or '')

    def _font_changed(self, index):
        if self._syncing:
            return
        value = self.font_combo.currentData()
        if value == '__choose__':
            path, _ = QFileDialog.getOpenFileName(self, tr('选择字体'), '', tr('字体文件 (*.ttf *.otf *.ttc)'))
            if not path:
                self._set_combo_value(self.font_combo, self._style_values.get('font_path', ''))
                return
            value = str(Path(path).resolve())
            self._set_combo_value(self.font_combo, value)
        self._emit_style('font_path', value or '')

    @staticmethod
    def _set_combo_value(combo, value):
        blocker = QSignalBlocker(combo)
        index = combo.findData(value)
        if index < 0 and value:
            index = max(0, combo.count() - 1)
            combo.insertItem(index, Path(value).name if ('/' in value or '\\' in value) else value, value)
        combo.setCurrentIndex(max(0, index))
        del blocker

    def _metadata_edited(self, tag, value):
        if not self._syncing and self._photo_path is not None:
            self._edited_fields.add(tag)
            self.metadata_changed.emit(tag, value)

    def _select_fields(self, checked):
        for check in self.metadata_checks.values():
            check.setChecked(checked)
        self._update_actions()

    def selected_metadata(self):
        """批量操作只读取明确勾选的字段"""
        return {tag: self.metadata_fields[tag].text() for tag, check in self.metadata_checks.items() if check.isChecked()}

    def _apply_checked_metadata(self):
        self.metadata_apply_requested.emit('checked', self.selected_metadata())

    def _lock_changed(self, checked):
        if not self._syncing:
            self.lock_settings_toggled.emit(checked)

    def _tab_changed(self, index):
        if hasattr(self, 'sync_style_button'):
            self.sync_style_button.setVisible(index != 2)
            self.sync_metadata_button.setVisible(index == 2)
        if index == 2:
            self.metadata_requested.emit()

    @property
    def metadata_visible(self):
        return self.tabs.currentIndex() == 2

    def show_style_tab(self):
        self.tabs.setCurrentIndex(1)
        self.footer_section.toggle.setChecked(True)
        QTimer.singleShot(0, self, lambda: self._style_scroll.ensureWidgetVisible(self.footer_section))

    def show_metadata_tab(self):
        if self.metadata_visible:
            self.metadata_requested.emit()
        else:
            self.tabs.setCurrentIndex(2)

    def set_presets(self, presets, selected=None):
        """更新模板卡片并保持当前选择"""
        self._presets = list(presets)
        self._selected_template = selected or self._selected_template
        self._rebuild_template_cards()

    def _rebuild_template_cards(self):
        while self._card_layout.count():
            item = self._card_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cards.clear()
        category = self._preset_category.currentData()
        presets = [preset for preset in self._presets
                   if category == 'all' or (preset.description == '自定义水印模板') == (category == 'mine')]
        for index, preset in enumerate(presets):
            card = TemplateCard(preset)
            card.selected.connect(self.template_selected.emit)
            self._cards[preset.name] = card
            self._card_layout.addWidget(card, index // 2, index % 2)
        self.set_selected_template(self._selected_template)

    def show_my_templates(self):
        self._preset_category.setCurrentIndex(self._preset_category.findData('mine'))
        self.tabs.setCurrentIndex(0)

    def set_selected_template(self, name):
        self._selected_template = name or ''
        for key, card in self._cards.items():
            card.set_selected(key == self._selected_template)

    def set_settings(self, settings):
        """同步状态时不触发用户编辑信号"""
        self._syncing = True
        widgets = (self.template_styles_check, self.logo_check, self.logo_combo, self.font_combo, self.glyph_combo,
                   self.font_slider, self.border_slider, self.title_input, self.subtitle_input,
                   self.alignment_combo, self.text_spacing_spin, self.line_spacing_spin,
                   self.quality_spin, self.output_input, self.overwrite_check, self.structure_check)
        blockers = [QSignalBlocker(widget) for widget in widgets]
        try:
            self.set_selected_template(getattr(settings, 'template_name', ''))
            self.template_styles_check.setChecked(getattr(settings, 'use_template_styles', True))
            self.logo_check.setChecked(getattr(settings, 'show_logo', True))
            self.logo_combo.setEnabled(self.logo_check.isChecked())
            self._style_values = {key: getattr(settings, key, default) for key, default in (
                ('logo_choice', ''), ('font_path', ''), ('background', '#FFFFFF'), ('text_color', '#20252C'))}
            self._set_combo_value(self.logo_combo, self._style_values['logo_choice'])
            self._set_combo_value(self.font_combo, self._style_values['font_path'])
            policy = '' if self.template_styles_check.isChecked() else getattr(settings, 'brand_glyph_policy', '')
            self._set_combo_value(self.glyph_combo, policy)
            self.font_slider.setValue(round(getattr(settings, 'font_scale', 1.0) * 100))
            border = getattr(settings, 'border_percent', 12) if getattr(settings, 'border_override', False) else 5
            self.border_slider.setValue(border)
            for widget, value in ((self.title_input, getattr(settings, 'title', '')),
                                  (self.subtitle_input, getattr(settings, 'subtitle', '')),
                                  (self.output_input, getattr(settings, 'output_dir', ''))):
                if widget.text() != value and not widget.hasFocus():
                    widget.setText(value)
            self._set_combo_value(self.alignment_combo, getattr(settings, 'text_alignment', ''))
            for spin, value in ((self.text_spacing_spin, getattr(settings, 'text_spacing', None)),
                                (self.line_spacing_spin, getattr(settings, 'line_spacing', None))):
                spin.setValue(-1 if value is None else int(value))
            self.quality_spin.setValue(getattr(settings, 'quality', 95))
            self.overwrite_check.setChecked(getattr(settings, 'overwrite_existing', False))
            self.structure_check.setChecked(getattr(settings, 'preserve_structure', True))
            self._set_swatch(self.background_button, self._style_values['background'])
            self._set_swatch(self.text_button, self._style_values['text_color'])
            self._update_values()
        finally:
            blockers.clear()
            self._syncing = False

    @staticmethod
    def _frame_node(source):
        try:
            document = json.loads(source)
            if isinstance(document, list):
                for index, node in enumerate(document):
                    if isinstance(node, dict) and node.get('processor_name') in {'watermark', 'watermark_with_timestamp'}:
                        return document, index
        except (TypeError, ValueError):
            pass
        return None, None

    def set_frame_source(self, source, *, baseline=None):
        """读取模板中的边框选项，不改写未经编辑的源码"""
        baseline = source if baseline is None else baseline
        if source == self._frame_source and baseline == self._frame_baseline_source:
            return
        base_document, base_index = self._frame_node(baseline)
        base = base_document[base_index] if base_index is not None else {}
        defaults = {key: base[key] for key in (
            'frame_style', 'overlay_mode', 'palette_bar', 'adaptive_logo_invert',
            'frame_brightness', 'frame_vignette', 'frame_blur', 'inset_anchor', 'overlay_opacity')
                    if key in base}
        self._frame_source = source
        self._frame_baseline_source = baseline
        self._frame_defaults = defaults
        self._frame_document, self._frame_index = self._frame_node(source)
        self._update_frame_options()
        self.custom_frame.set_source(source, baseline=baseline)
        self._set_custom_active(self.custom_frame.is_custom)

    def _update_frame_options(self):
        node = self._frame_document[self._frame_index] if self._frame_index is not None else {}
        for key, combo, options in (
                ('frame_style', self.frame_combo, _FRAME_OPTIONS),
                ('overlay_mode', self.overlay_combo, _OVERLAY_OPTIONS),
                ('palette_bar', self.palette_combo, _SWITCH_OPTIONS),
                ('adaptive_logo_invert', self.logo_invert_combo, _SWITCH_OPTIONS),
                ('inset_anchor', self.inset_anchor, _ANCHOR_OPTIONS)):
            value = node.get(key)
            base_value = self._frame_defaults.get(key)
            blocker = QSignalBlocker(combo)
            combo.clear()
            base_label = next((label for label, option in options if option == base_value), None)
            if base_label is None and base_value is None:
                base_label = ('未指定' if key == 'frame_style' else '默认位置' if key == 'overlay_mode'
                              else '右下' if key == 'inset_anchor' else '默认')
            default_text = (tr('沿用模板（{value}）', value=tr(base_label)) if base_label
                            else tr('沿用模板'))
            combo.addItem(default_text, _FRAME_DEFAULT)
            for label, option in options:
                combo.addItem(tr(label), option)
            same_as_default = (key in node) == (key in self._frame_defaults) and value == base_value
            index = 0 if same_as_default else combo.findData(value)
            if index < 0 and value is None:
                fallback = '' if key in ('frame_style', 'overlay_mode') else 'bottom_right' if key == 'inset_anchor' else False
                index = combo.findData(fallback)
            if index < 0:
                combo.addItem(str(value), value)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
            combo.setEnabled(self._frame_index is not None)
            del blocker
        for key, spin in (('frame_brightness', self.frame_brightness), ('frame_vignette', self.frame_vignette),
                          ('frame_blur', self.frame_blur), ('overlay_opacity', self.overlay_opacity)):
            value = node.get(key)
            blocker = QSignalBlocker(spin)
            spin.setSpecialValueText(tr('沿用模板'))
            valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            spin.setValue(round(value * 100) if valid else -1)
            spin.setEnabled(self._frame_index is not None)
            del blocker
        self._update_effect_visibility()
        self._set_custom_active(self.custom_frame.is_custom)

    def _set_custom_active(self, active):
        self._legacy_frame_notice.setVisible(active)
        for widget in (self.frame_combo, self.palette_combo, self.glass_controls,
                       self.border_slider, self.background_button):
            widget.setEnabled(not active)
        # 文字覆盖位置和透明度仍用于定制画框的前景
        self.overlay_combo.setEnabled(self._frame_index is not None)
        self.inset_controls.setEnabled(True)
        if not active:
            for widget in (self.frame_combo, self.overlay_combo, self.palette_combo):
                widget.setEnabled(self._frame_index is not None)

    def _custom_frame_source_changed(self, source):
        previous_index = self._frame_index
        self._frame_source = source
        self._frame_document, self._frame_index = self._frame_node(source)
        self.inline_footer.adopt_style_source(source)
        if self._frame_index != previous_index:
            self._update_frame_options()
        self._emit_style('template_source', source)

    def _update_effect_visibility(self):
        node = self._frame_document[self._frame_index] if self._frame_index is not None else {}
        inset = node.get('overlay_mode') == 'inset_overlay'
        self.glass_controls.setVisible(not inset and node.get('frame_style') == 'blurred_glass')
        self.inset_controls.setVisible(inset)

    def _frame_changed(self, key, combo):
        self._set_frame_value(key, combo.currentData())

    def _frame_number_changed(self, key, value):
        self._set_frame_value(key, _FRAME_DEFAULT if value < 0 else value / 100)

    def _set_frame_value(self, key, value):
        if self._syncing or self._frame_index is None:
            return
        node = self._frame_document[self._frame_index]
        if value == _FRAME_DEFAULT:
            if key in self._frame_defaults:
                value = self._frame_defaults[key]
            else:
                value = None
        elif key in ('frame_style', 'overlay_mode') and value == '':
            value = None
        if value == node.get(key) and (value is not None or key not in node):
            return
        if value is None:
            node.pop(key, None)
        else:
            node[key] = value
        source = json.dumps(self._frame_document, ensure_ascii=False, indent=2) + '\n'
        self._frame_source = source
        if key in ('frame_style', 'overlay_mode'):
            self._update_frame_options()
        self.inline_footer.adopt_style_source(source)
        self.custom_frame.set_source(source, baseline=self._frame_baseline_source)
        self._emit_style('template_source', source)

    def set_photo(self, path, values, *, force=False, read_only=False):
        """只更新未编辑的 EXIF 项，保留正在输入的文本"""
        path = str(path) if path is not None else None
        changed = path != self._photo_path
        self._photo_path = path
        self._photo_read_only = bool(read_only)
        if changed:
            self._edited_fields.clear()
        self.photo_label.setText(Path(path).name if path else '')
        self.photo_label.setToolTip(path or '')
        self.metadata_stack.setCurrentIndex(1 if path else 0)
        self.metadata_stack.setEnabled(not self._locked and not self._photo_read_only)
        self._template_body.setEnabled(not self._locked and not self._photo_read_only)
        self._style_body.setEnabled(not self._locked and not self._photo_read_only)
        values = values or {}
        self._syncing = True
        try:
            for tag, editor in self.metadata_fields.items():
                if not force and not changed and (tag in self._edited_fields or editor.hasFocus()):
                    continue
                value = next((values[key] for key in _ALIASES.get(tag, (tag,)) if values.get(key) is not None), '')
                text = str(value)
                if editor.text() != text:
                    blocker = QSignalBlocker(editor)
                    editor.setText(text)
                    del blocker
        finally:
            self._syncing = False
        self._update_actions()

    def set_counts(self, checked, total):
        self._checked_count, self._total_count = int(checked), int(total)
        self._update_actions()

    def set_locked(self, locked):
        self._locked = bool(locked)
        self._syncing = True
        blocker = QSignalBlocker(self.lock_button)
        self.lock_button.setChecked(self._locked)
        del blocker
        self._syncing = False
        self._template_body.setEnabled(not self._locked and not self._photo_read_only)
        self._style_body.setEnabled(not self._locked and not self._photo_read_only)
        self.metadata_stack.setEnabled(not self._locked and not self._photo_read_only)
        self._update_actions()
        self._retranslate()

    def set_dirty(self, dirty):
        self._dirty = bool(dirty)
        self._update_values()

    def set_busy(self, busy):
        self._busy = bool(busy)
        self._update_actions()

    def _update_actions(self, *args):
        current = self._photo_path is not None and not self._photo_read_only and not self._busy and not self._locked
        self.apply_current_button.setEnabled(current)
        self.sync_style_button.setEnabled(current and self._checked_count > 0)
        self.sync_metadata_button.setEnabled(current and self._checked_count > 0 and
                                             any(check.isChecked() for check in self.metadata_checks.values()))
        if self._locked:
            reason = tr('请先解锁设置')
        elif self._photo_path is None or self._photo_read_only:
            reason = tr('请选择输入照片')
        elif self._checked_count <= 0:
            reason = tr('请先勾选照片')
        else:
            reason = ''
        self.sync_style_button.setToolTip(reason)
        self.sync_metadata_button.setToolTip(reason or (tr('请先勾选要同步的字段')
                                                        if not any(check.isChecked() for check in self.metadata_checks.values()) else ''))

    def _update_values(self):
        self.saved_label.setText(tr('设置有修改，尚未保存' if self._dirty else '设置已保存'))

    def _retranslate(self):
        self.tabs.setTabText(0, tr('模板预设'))
        self.tabs.setTabText(1, tr('样式与文本').replace('&', '&&'))
        self.tabs.setTabText(2, tr('EXIF 信息'))
        self.lock_button.setText(tr('编辑设置' if self._locked else '锁定设置'))
        for index, label in enumerate(('全部模板', '内置模板', '我的模板')):
            self._preset_category.setItemText(index, tr(label))
        for card in self._cards.values():
            card.retranslate()
        for combo, first, choices, last in (
                (self.logo_combo, '自动识别', [(brand, brand) for brand in _BRANDS], '自定义图片…'),
                (self.font_combo, '沿用模板', self._font_choices(), '选择字体…'),
                (self.alignment_combo, '沿用模板', [('左对齐', 'left'), ('右对齐', 'right')], None)):
            value = combo.currentData()
            if value is None:
                value = ''
            blocker = QSignalBlocker(combo)
            combo.clear()
            combo.addItem(tr(first), '')
            for label, data in choices:
                combo.addItem(tr(label) if combo is self.alignment_combo else label, data)
            if last:
                combo.addItem(tr(last), '__choose__')
            self._set_combo_value(combo, value)
            del blocker
        self.text_spacing_spin.setSpecialValueText(tr('沿用模板'))
        self.line_spacing_spin.setSpecialValueText(tr('沿用模板'))
        self.border_slider.setSpecialValueText(tr('自动'))
        glyph = self.glyph_combo.currentData() or ''
        blocker = QSignalBlocker(self.glyph_combo)
        self.glyph_combo.clear()
        for label, value in (('沿用模板', ''), ('定制几何符号', 'geometric'),
                             ('标准 Z', 'plain_z'), ('系统字体', 'system')):
            self.glyph_combo.addItem(tr(label), value)
        self._set_combo_value(self.glyph_combo, glyph)
        del blocker
        self._update_frame_options()
        self._update_values()
        self._update_actions()

    @staticmethod
    def _font_choices():
        try:
            return [(path.stem, path.name) for path in sorted(fonts_dir.iterdir())
                    if path.suffix.lower() in {'.ttf', '.otf', '.ttc'} and path.is_file()]
        except OSError:
            return []
