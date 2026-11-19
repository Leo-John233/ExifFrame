"""自定义画框的可视化参数和装饰编辑"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .controls import CameraRawSlider, CollapsibleSection, ColorProperty
from .i18n import bind, localize_error, tr, translator


_FRAME_DEFAULTS = {
    'geometry': {'canvas_mode': 'expand', 'top': 0, 'bottom': 0, 'left': 0, 'right': 0,
                 'locked': False, 'ratio': '4:5', 'offset_x': 0, 'offset_y': 0},
    'background': {'type': 'solid', 'color': '#FFFFFF', 'start_color': '#FFFFFF', 'end_color': '#E5E5E5',
                   'gradient_type': 'linear', 'angle': 0, 'path': '', 'fit': 'cover', 'blur': 0.08,
                   'brightness': 1, 'saturation': 1, 'vignette': 0.2,
                   'texture': {'type': 'none', 'opacity': 0.12, 'scale': 1, 'seed': 0}},
    'photo_surface': {'radius': 0, 'stroke': {'width': 0, 'color': '#FFFFFF', 'opacity': 1},
                      'shadow': {'blur': 0, 'offset_x': 0, 'offset_y': 0, 'spread': 0,
                                 'opacity': 0.25, 'color': '#000000'}},
    'decorations': [],
}
_DECORATIONS = (
    ('边框线条', 'border_line'), ('胶片齿孔', 'film_sprockets'), ('主色色卡', 'palette_bar'),
    ('取景框', 'viewfinder_marks'), ('PNG 画框', 'png_frame_overlay'),
)
_DECOR_DEFAULTS = {
    'border_line': {'enabled': True, 'double': False, 'inset': 0.01, 'width': 0.005, 'gap': 0.008,
                    'radius': 0, 'color': '#FFFFFF'},
    'film_sprockets': {'enabled': True, 'edges': 'horizontal', 'hole_width': 0.025, 'hole_height': 0.012,
                       'spacing': 0.015, 'inset': 0.012, 'color': '#E6DEC9', 'edge_text': '',
                       'text_color': '#FF804F'},
    'palette_bar': {'enabled': True, 'count': 5, 'shape': 'square', 'position': 'bottom_center',
                    'width': 0.24, 'height': 0.025, 'inset': 0.025, 'gap': 0.005},
    'viewfinder_marks': {'enabled': True, 'style': 'corners', 'inset': 0.035, 'length': 0.03,
                         'width': 0.003, 'color': '#FAFAF8'},
    'png_frame_overlay': {'enabled': True, 'path': '', 'fit': 'stretch', 'opacity': 1,
                          'slices': {'top': 0.15, 'bottom': 0.15, 'left': 0.15, 'right': 0.15}},
}


def _merge(defaults, values):
    """补足界面默认项，同时保留未知字段"""
    result = deepcopy(defaults)
    if not isinstance(values, dict):
        return result
    for key, value in values.items():
        if isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _get(data, path, fallback=None):
    for part in path.split('.'):
        if not isinstance(data, dict) or part not in data:
            return fallback
        data = data[part]
    return data


def _set(data, path, value):
    parts = path.split('.')
    for part in parts[:-1]:
        if not isinstance(data.get(part), dict):
            data[part] = {}
        data = data[part]
    data[parts[-1]] = value


def _node(source):
    try:
        document = json.loads(source)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(document, list):
        return None, None
    for index, node in enumerate(document):
        if isinstance(node, dict) and isinstance(node.get('custom_frame'), dict):
            return document, index
    # 外框作用于最后的成品，避免后面的裁切或加边再次改变固定画幅
    if (document and isinstance(document[-1], dict)
            and document[-1].get('processor_name') in ('watermark', 'watermark_with_timestamp')):
        return document, len(document) - 1
    return document, None


def _frame_values(node):
    """解析当前或模板基准的同一套有效画框参数"""
    from processor.custom_frame import default_custom_frame, legacy_custom_frame
    custom = isinstance(node.get('custom_frame'), dict)
    try:
        legacy = {} if custom else legacy_custom_frame(node)
    except (ValueError, TypeError):
        # 含 Jinja 的旧参数在读取照片前无法确定
        legacy = default_custom_frame()
        legacy['legacy_composite'] = True
    custom_values = node.get('custom_frame') if custom else {}
    frame = _merge(_FRAME_DEFAULTS, _merge(legacy, custom_values))
    if not isinstance(frame.get('decorations'), list):
        frame['decorations'] = []
    if (frame['background'].get('type') == 'blurred_photo'
            and 'brightness' not in (legacy.get('background') or {})
            and 'brightness' not in (custom_values.get('background') or {})):
        frame['background']['brightness'] = .72
    return frame


class CustomFramePanel(QWidget):
    """基于模板源码编辑画框，未操作时不改动模板"""

    source_changed = Signal(str)
    interaction_started = Signal(str)
    interaction_finished = Signal(str)
    custom_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = ''
        self._baseline = ''
        self._document = None
        self._index = None
        self._frame = deepcopy(_FRAME_DEFAULTS)
        self._baseline_frame = deepcopy(_FRAME_DEFAULTS)
        self._syncing = False
        self._custom = False
        self._ratios = None
        self._active_text = None
        self._controls = {}
        self._decor_controls = {}
        self._combos = []
        self._deco_pages = {}
        self._sections = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(7)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName('secondaryText')
        outer.addWidget(self.message)
        units = QLabel()
        units.setWordWrap(True)
        units.setObjectName('secondaryText')
        bind(units, '画框距离和尺寸按照片短边的百分比计算')
        outer.addWidget(units)
        self.revert_button = QPushButton()
        bind(self.revert_button, '恢复模板画框')
        self.revert_button.clicked.connect(self._revert)
        outer.addWidget(self.revert_button)
        self._build_geometry(outer)
        self._build_background(outer)
        self._build_photo(outer)
        self._build_decorations(outer)
        outer.addStretch(1)
        translator.language_changed.connect(self._retranslate)
        self._retranslate()
        self._sync()

    @property
    def is_custom(self):
        return self._custom

    @staticmethod
    def _form(section):
        form = QFormLayout(section.body)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(6)
        return form

    @staticmethod
    def _label(text):
        label = QLabel()
        label.setWordWrap(True)
        bind(label, text)
        return label

    def _record(self, path, widget, *, decoration=None, default=None, scale=1):
        entry = (widget, default, scale)
        if decoration is None:
            self._controls[path] = entry
        else:
            self._decor_controls.setdefault(decoration, {})[path] = entry

    def _section(self, title, group, *, expanded=False):
        section = CollapsibleSection(title, expanded=expanded)
        section.reset_requested.connect(lambda: self._reset_section(group))
        self._sections[group] = section
        return section

    def _baseline_color(self, path, default, decoration):
        if decoration is None:
            return _get(self._baseline_frame, path, default)
        item = self._decoration()
        if not item:
            return default
        kind = item.get('type')
        base_items = self._baseline_frame.get('decorations', [])
        row = self.decor_list.currentRow()
        baseline = base_items[row] if 0 <= row < len(base_items) else None
        if not isinstance(baseline, dict) or baseline.get('type') != kind:
            matches = [value for value in base_items if isinstance(value, dict) and value.get('type') == kind]
            baseline = matches[0] if len(matches) == 1 else {}
        return _get(baseline, path, _get(_DECOR_DEFAULTS.get(kind, {}), path, default))

    def _reset_color(self, path, default, decoration):
        self._change(path, self._baseline_color(path, default, decoration), decoration=decoration)

    def _reset_section(self, group):
        if self._document is None or group not in self._sections:
            return
        baseline = deepcopy(self._baseline_frame.get(group))
        extras = {'geometry': ('_legacy_geometry',), 'decorations': ('legacy_palette_migrated',)}.get(group, ())
        if (self._frame.get(group) == baseline
                and all(self._frame.get(key) == self._baseline_frame.get(key) for key in extras)):
            return
        self._frame[group] = baseline
        for key in extras:
            if key in self._baseline_frame:
                self._frame[key] = deepcopy(self._baseline_frame[key])
            else:
                self._frame.pop(key, None)
        self._publish()
        self._sync()
        self._refresh_decorations()

    def _update_group_resets(self):
        for group, section in self._sections.items():
            extras = {'geometry': ('_legacy_geometry',), 'decorations': ('legacy_palette_migrated',)}.get(group, ())
            changed = (self._frame.get(group) != self._baseline_frame.get(group)
                       or any(self._frame.get(key) != self._baseline_frame.get(key) for key in extras))
            section.reset_button.setEnabled(self._document is not None and changed)

    def _number(self, form, label, path, low, high, default, *, scale=100, step=0.1, decoration=None):
        suffix = '°' if path == 'background.angle' else '%' if scale == 100 else ''
        slider = CameraRawSlider(low * scale, high * scale, default * scale,
                                 step=step, decimals=1 if step < 1 else 0,
                                 suffix=suffix)
        slider.setObjectName('customFrame_' + (decoration + '_' if decoration else '') + path.replace('.', '_'))
        bind(slider, label)
        self._record(path, slider, decoration=decoration, default=default, scale=scale)
        slider.valueChanged.connect(lambda value: self._change(path, value / scale if scale != 1 else value,
                                                               decoration=decoration))
        name = slider.objectName()
        slider.interaction_started.connect(lambda: self._begin_number(path, name, decoration))
        slider.interaction_finished.connect(lambda: self._end_number(name))
        form.addRow(slider)
        return slider

    def _combo(self, form, label, path, choices, default, *, decoration=None, editable=False):
        combo = QComboBox()
        combo.setMinimumWidth(0)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(3)
        combo.setEditable(editable)
        combo.setObjectName('customFrame_' + (decoration + '_' if decoration else '') + path.replace('.', '_'))
        self._combos.append((combo, choices))
        self._record(path, combo, decoration=decoration, default=default)
        combo.currentIndexChanged.connect(lambda _: self._combo_changed(combo, path, decoration))
        if editable:
            combo.lineEdit().editingFinished.connect(lambda: self._ratio_edited(combo, path))
        form.addRow(self._label(label), combo)
        return combo

    def _check(self, form, label, path, default=False, *, decoration=None):
        check = QCheckBox()
        check.setObjectName('customFrame_' + (decoration + '_' if decoration else '') + path.replace('.', '_'))
        bind(check, label)
        self._record(path, check, decoration=decoration, default=default)
        check.toggled.connect(lambda value: self._change(path, value, decoration=decoration))
        form.addRow(check)
        return check

    def _color(self, form, label, path, default, *, decoration=None):
        color = ColorProperty(label)
        color.setObjectName('customFrame_' + (decoration + '_' if decoration else '') + path.replace('.', '_'))
        self._record(path, color, decoration=decoration, default=default)
        color.color_changed.connect(lambda value: self._change(path, value, decoration=decoration))
        color.reset_requested.connect(lambda: self._reset_color(path, default, decoration))
        form.addRow(color)
        return color

    def _asset(self, form, label, path, *, decoration=None, png_only=False):
        field = QLineEdit()
        field.setReadOnly(True)
        field.setMinimumWidth(0)
        field.setObjectName('customFrame_' + (decoration + '_' if decoration else '') + path.replace('.', '_'))
        self._record(path, field, decoration=decoration, default='')
        choose = QPushButton('…')
        choose.setObjectName(field.objectName() + '_choose')
        bind(choose, '选择图片', 'setToolTip')
        choose.clicked.connect(lambda: self._choose_asset(path, decoration, png_only))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(field, 1)
        row.addWidget(choose)
        form.addRow(self._label(label), row)
        return field

    def _build_geometry(self, outer):
        section = self._section('画幅与边距', 'geometry', expanded=True)
        form = self._form(section)
        self.canvas_mode = self._combo(form, '画幅模式', 'geometry.canvas_mode',
                                       [('扩展边距', 'expand'), ('固定比例', 'aspect_ratio')], 'expand')
        self.ratio_group = QWidget()
        ratio_form = QFormLayout(self.ratio_group)
        ratio_form.setContentsMargins(0, 0, 0, 0)
        self.ratio = self._combo(ratio_form, '画幅比例', 'geometry.ratio',
                                 [(x, x) for x in ('1:1', '4:5', '5:4', '3:4', '4:3', '3:2', '2:3', '16:9', '9:16')],
                                 '4:5', editable=True)
        self._number(ratio_form, '水平偏移', 'geometry.offset_x', -1, 1, 0, step=1)
        self._number(ratio_form, '垂直偏移', 'geometry.offset_y', -1, 1, 0, step=1)
        form.addRow(self.ratio_group)
        self._check(form, '锁定四边比例', 'geometry.locked')
        for label, key, default in (('上边距', 'top', 0), ('下边距', 'bottom', 0),
                                    ('左边距', 'left', 0), ('右边距', 'right', 0)):
            self._number(form, label, 'geometry.' + key, 0, 8, default)
        outer.addWidget(section)

    def _build_background(self, outer):
        section = self._section('画框背景与材质', 'background')
        form = self._form(section)
        self.background_type = self._combo(form, '背景类型', 'background.type',
            [('纯色', 'solid'), ('渐变色', 'gradient'), ('自动主色', 'auto_dominant'),
             ('照片模糊', 'blurred_photo'), ('自定义背景图', 'custom_image')], 'solid')
        self.background_pages = QWidget()
        background_layout = QVBoxLayout(self.background_pages)
        background_layout.setContentsMargins(0, 0, 0, 0)
        background_layout.setSpacing(0)
        self._background_pages = {}
        for kind in ('solid', 'gradient', 'auto_dominant', 'blurred_photo', 'custom_image'):
            page = QWidget()
            inner = QFormLayout(page)
            inner.setContentsMargins(0, 0, 0, 0)
            if kind == 'solid':
                self._color(inner, '画框颜色', 'background.color', '#FFFFFF')
            elif kind == 'gradient':
                self._color(inner, '渐变起始色', 'background.start_color', '#FFFFFF')
                self._color(inner, '渐变结束色', 'background.end_color', '#E5E5E5')
                self._combo(inner, '渐变方式', 'background.gradient_type', [('线性', 'linear'), ('径向', 'radial')], 'linear')
                self.gradient_angle = self._number(inner, '渐变角度', 'background.angle',
                                                   -3600, 3600, 0, scale=1, step=1)
            elif kind == 'blurred_photo':
                for label, key, low, high, default in (
                        ('模糊半径', 'blur', 0, 1, .08), ('暗角强度', 'vignette', 0, 1, .2)):
                    self._number(inner, label, 'background.' + key, low, high, default)
            elif kind == 'custom_image':
                self._asset(inner, '背景图片', 'background.path')
                self._combo(inner, '背景图片适配', 'background.fit',
                            [('铺满裁切', 'cover'), ('拉伸', 'stretch'), ('完整包含', 'contain')], 'cover')
            self._background_pages[kind] = page
            background_layout.addWidget(page)
        form.addRow(self.background_pages)
        self._number(form, '背景亮度', 'background.brightness', 0, 2, 1)
        self._number(form, '背景饱和度', 'background.saturation', 0, 4, 1)
        self.texture_type = self._combo(form, '表面纹理', 'background.texture.type',
                                        [('无纹理', 'none'), ('纸张', 'paper'), ('颗粒', 'grain')], 'none')
        self.texture_controls = QWidget()
        texture = QFormLayout(self.texture_controls)
        texture.setContentsMargins(0, 0, 0, 0)
        self._number(texture, '纹理强度', 'background.texture.opacity', 0, 1, .12)
        self._number(texture, '纹理缩放', 'background.texture.scale', .05, 8, 1, step=1)
        self._number(texture, '纹理种子', 'background.texture.seed', 0, 9999, 0, scale=1, step=1)
        form.addRow(self.texture_controls)
        outer.addWidget(section)

    def _build_photo(self, outer):
        section = self._section('照片外观', 'photo_surface')
        form = self._form(section)
        self._number(form, '照片圆角', 'photo_surface.radius', 0, 1, 0)
        self._number(form, '照片描边宽度', 'photo_surface.stroke.width', 0, 1, 0)
        self._color(form, '照片描边颜色', 'photo_surface.stroke.color', '#FFFFFF')
        self._number(form, '照片描边不透明度', 'photo_surface.stroke.opacity', 0, 1, 1)
        self._number(form, '阴影模糊', 'photo_surface.shadow.blur', 0, 1, 0)
        self._number(form, '阴影水平偏移', 'photo_surface.shadow.offset_x', -1, 1, 0)
        self._number(form, '阴影垂直偏移', 'photo_surface.shadow.offset_y', -1, 1, 0)
        self._number(form, '阴影扩散', 'photo_surface.shadow.spread', 0, 1, 0)
        self._number(form, '阴影不透明度', 'photo_surface.shadow.opacity', 0, 1, .25)
        self._color(form, '阴影颜色', 'photo_surface.shadow.color', '#000000')
        outer.addWidget(section)

    def _build_decorations(self, outer):
        section = self._section('画框装饰', 'decorations')
        layout = QVBoxLayout(section.body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.decor_list = QListWidget()
        self.decor_list.setObjectName('customFrameDecorations')
        self.decor_list.setMaximumHeight(125)
        self.decor_list.currentRowChanged.connect(self._decor_selected)
        layout.addWidget(self.decor_list)
        row = QHBoxLayout()
        self.decor_add_combo = QComboBox()
        self.decor_add_combo.setMinimumWidth(0)
        self._combos.append((self.decor_add_combo, _DECORATIONS))
        row.addWidget(self.decor_add_combo, 1)
        self.add_decoration_button = QPushButton()
        bind(self.add_decoration_button, '添加')
        self.add_decoration_button.clicked.connect(self._add_decoration)
        row.addWidget(self.add_decoration_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        for label, name, handler in (('上移', 'up', lambda: self._move_decoration(-1)),
                                     ('下移', 'down', lambda: self._move_decoration(1)),
                                     ('移除', 'remove', self._remove_decoration)):
            button = QPushButton()
            button.setObjectName('customFrameDecoration_' + name)
            bind(button, label)
            button.clicked.connect(handler)
            row.addWidget(button)
        layout.addLayout(row)
        self.decor_enabled = QCheckBox()
        bind(self.decor_enabled, '启用当前装饰')
        self.decor_enabled.toggled.connect(lambda value: self._change('enabled', value, decoration='current'))
        layout.addWidget(self.decor_enabled)
        self.decor_pages = QWidget()
        pages_layout = QVBoxLayout(self.decor_pages)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        pages_layout.setSpacing(0)
        for _, kind in _DECORATIONS:
            page = QWidget()
            form = QFormLayout(page)
            form.setContentsMargins(0, 0, 0, 0)
            if kind == 'border_line':
                self._check(form, '双线边框', 'double', decoration=kind)
                self._deco_numbers(form, kind, [('线条内缩', 'inset', 0, .5, .01),
                    ('线条宽度', 'width', 0, .1, .005), ('双线间距', 'gap', 0, .2, .008),
                    ('线条圆角', 'radius', 0, .5, 0)])
                self._color(form, '线条颜色', 'color', '#FFFFFF', decoration=kind)
            elif kind == 'film_sprockets':
                self._combo(form, '齿孔位置', 'edges', [('上下边', 'horizontal'), ('左右边', 'vertical'),
                            ('四边', 'all')], 'horizontal', decoration=kind)
                self._deco_numbers(form, kind, [('齿孔宽度', 'hole_width', .001, .2, .025),
                    ('齿孔高度', 'hole_height', .001, .2, .012), ('齿孔间隔', 'spacing', 0, .2, .015),
                    ('齿孔内缩', 'inset', 0, .5, .012)])
                self._color(form, '齿孔颜色', 'color', '#E6DEC9', decoration=kind)
                editor = QLineEdit()
                editor.setMinimumWidth(0)
                self._record('edge_text', editor, decoration=kind, default='')
                editor.textEdited.connect(lambda text, widget=editor: self._text_edited(widget, 'edge_text', text))
                editor.editingFinished.connect(lambda widget=editor: self._text_finished(widget))
                form.addRow(self._label('胶片边缘文字'), editor)
                self._color(form, '边缘文字颜色', 'text_color', '#FF804F', decoration=kind)
            elif kind == 'palette_bar':
                self._number(form, '色块数量', 'count', 3, 8, 5, scale=1, step=1, decoration=kind)
                self._combo(form, '色块形状', 'shape', [('方形', 'square'), ('圆形', 'circle'),
                            ('胶囊', 'capsule')], 'square', decoration=kind)
                self._combo(form, '色卡位置', 'position', [('左下', 'bottom_left'), ('底部居中', 'bottom_center'),
                            ('右下', 'bottom_right'), ('左上', 'top_left'), ('顶部居中', 'top_center'),
                            ('右上', 'top_right')], 'bottom_center', decoration=kind)
                self._deco_numbers(form, kind, [('色卡宽度', 'width', .01, 1, .24),
                    ('色卡高度', 'height', .001, .2, .025), ('色卡内缩', 'inset', 0, .5, .025),
                    ('色块间距', 'gap', 0, .1, .005)])
            elif kind == 'viewfinder_marks':
                self._combo(form, '取景标记', 'style', [('四角', 'corners'), ('十字', 'crosshair')],
                            'corners', decoration=kind)
                self._deco_numbers(form, kind, [('标记内缩', 'inset', 0, .5, .035),
                    ('标记长度', 'length', .001, .5, .03), ('标记宽度', 'width', .001, .1, .003)])
                self._color(form, '标记颜色', 'color', '#FAFAF8', decoration=kind)
            else:
                self._asset(form, 'PNG 图片', 'path', decoration=kind, png_only=True)
                self.png_fit = self._combo(form, '图片适配', 'fit',
                    [('拉伸', 'stretch'), ('九宫格', 'nine_slice'), ('铺满裁切', 'cover')],
                    'stretch', decoration=kind)
                self._number(form, '图片不透明度', 'opacity', 0, 1, 1, decoration=kind)
                self.slice_controls = QWidget()
                slices = QFormLayout(self.slice_controls)
                slices.setContentsMargins(0, 0, 0, 0)
                for label, side in (('九宫格上边', 'top'), ('九宫格下边', 'bottom'),
                                    ('九宫格左边', 'left'), ('九宫格右边', 'right')):
                    self._number(slices, label, 'slices.' + side, 0, .5, .15, step=1, decoration=kind)
                form.addRow(self.slice_controls)
            self._deco_pages[kind] = page
            pages_layout.addWidget(page)
        layout.addWidget(self.decor_pages)
        outer.addWidget(section)

    def _deco_numbers(self, form, kind, definitions):
        for label, key, low, high, default in definitions:
            self._number(form, label, key, low, high, default, decoration=kind)

    def _begin_number(self, path, name, decoration):
        if decoration is None and path.startswith('geometry.') and path.split('.')[-1] in {'top', 'bottom', 'left', 'right'}:
            self._ratios = deepcopy(self._frame.get('geometry', {}))
        self.interaction_started.emit(name)

    def _end_number(self, name):
        self._ratios = None
        self.interaction_finished.emit(name)

    def _combo_changed(self, combo, path, decoration):
        if not self._syncing and combo.currentIndex() >= 0:
            self._change(path, combo.currentData(), decoration=decoration)

    def _ratio_edited(self, combo, path):
        if self._syncing:
            return
        value = combo.currentText().strip().replace('：', ':')
        try:
            width, height = value.split(':')
            width, height = float(width), float(height)
            if (not math.isfinite(width) or not math.isfinite(height)
                    or width <= 0 or height <= 0 or not .001 <= width / height <= 1000):
                raise ValueError
        except ValueError:
            self._sync_control(path)
            return
        self._change(path, value)

    def _text_edited(self, widget, path, value):
        if self._active_text is not widget:
            self._active_text = widget
            self.interaction_started.emit('customFrame_' + path)
        self._change(path, value, decoration='current')

    def _text_finished(self, widget):
        if self._active_text is widget:
            self._active_text = None
            self.interaction_finished.emit('customFrame_edge_text')

    def _choose_asset(self, path, decoration, png_only):
        filters = tr('PNG 图片 (*.png)') if png_only else tr('背景图片 (*.png *.jpg *.jpeg)')
        filename, _ = QFileDialog.getOpenFileName(self, tr('选择图片'), '', filters)
        if not filename:
            return
        try:
            from core.style_pack import copy_asset
            value = copy_asset(Path(filename), png_only=png_only)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr('图片导入失败'), localize_error(error))
            return
        self._change(path, value, decoration=decoration)

    def _decoration(self):
        items = self._frame.get('decorations', [])
        row = self.decor_list.currentRow()
        return items[row] if isinstance(items, list) and 0 <= row < len(items) and isinstance(items[row], dict) else None

    def _change(self, path, value, *, decoration=None):
        if self._syncing or self._document is None:
            return
        target = self._decoration() if decoration is not None else self._frame
        if target is None or (decoration not in (None, 'current') and target.get('type') != decoration):
            return
        old = _get(target, path)
        if old == value:
            return
        _set(target, path, value)
        if decoration is None and path.startswith('geometry.') and path != 'geometry.locked':
            self._frame.pop('_legacy_geometry', None)
        if decoration is not None and path != 'enabled':
            target.pop('legacy_style', None)
            if path != 'count':
                target.pop('legacy_palette', None)
            if path == 'color':
                target.pop('outer_color', None)
        if decoration is None and path.startswith('geometry.') and path.split('.')[-1] in {'top', 'bottom', 'left', 'right'}:
            self._link_edges(path, value, old)
        self._publish()
        if decoration is None:
            self._sync_control(path)
        else:
            self._sync_decoration_control(path)
        self._visibility()

    def _link_edges(self, path, value, old):
        geometry = self._frame.get('geometry', {})
        if not geometry.get('locked'):
            return
        key = path.split('.')[-1]
        origin = self._ratios or {**geometry, key: old}
        base = origin.get(key, 0)
        for side in ('top', 'bottom', 'left', 'right'):
            if side == key:
                continue
            source = origin.get(side, 0)
            linked = source * value / base if base else value
            geometry[side] = round(max(0, min(8, linked)), 5)
            self._sync_control('geometry.' + side)

    def _add_decoration(self):
        kind = self.decor_add_combo.currentData()
        if kind not in _DECOR_DEFAULTS or self._document is None:
            return
        items = self._frame.setdefault('decorations', [])
        items.append({'type': kind, **deepcopy(_DECOR_DEFAULTS[kind])})
        self._publish()
        self._refresh_decorations(len(items) - 1)

    def _remove_decoration(self):
        items = self._frame.get('decorations', [])
        row = self.decor_list.currentRow()
        if not 0 <= row < len(items):
            return
        del items[row]
        self._publish()
        self._refresh_decorations(min(row, len(items) - 1))

    def _move_decoration(self, direction):
        items = self._frame.get('decorations', [])
        row = self.decor_list.currentRow()
        other = row + direction
        if not (0 <= row < len(items) and 0 <= other < len(items)):
            return
        items[row], items[other] = items[other], items[row]
        self._publish()
        self._refresh_decorations(other)

    def _publish(self):
        if self._document is None:
            return
        if self._index is None:
            self._document.append({'processor_name': 'watermark'})
            self._index = len(self._document) - 1
        self._document[self._index]['custom_frame'] = deepcopy(self._frame)
        self._source = json.dumps(self._document, ensure_ascii=False, indent=2) + '\n'
        if not self._custom:
            self._custom = True
            self.custom_changed.emit(True)
        self._update_revert()
        self._update_group_resets()
        self.source_changed.emit(self._source)

    def _revert(self):
        if self._document is None or self._index is None:
            return
        base_doc, base_index = _node(self._baseline)
        baseline = base_doc[base_index] if base_doc is not None and base_index is not None else {}
        node = self._document[self._index]
        if 'custom_frame' in baseline:
            node['custom_frame'] = deepcopy(baseline['custom_frame'])
        else:
            node.pop('custom_frame', None)
            if base_index is None and set(node) == {'processor_name'}:
                del self._document[self._index]
        source = json.dumps(self._document, ensure_ascii=False, indent=2) + '\n'
        self.set_source(source, baseline=self._baseline)
        self.source_changed.emit(source)

    def set_source(self, source, *, baseline=None):
        baseline = source if baseline is None else baseline
        if source == self._source and baseline == self._baseline:
            return
        self._source, self._baseline = source, baseline
        self._document, self._index = _node(source)
        node = self._document[self._index] if self._document is not None and self._index is not None else {}
        custom = isinstance(node.get('custom_frame'), dict)
        self._frame = _frame_values(node)
        base_doc, base_index = _node(baseline)
        base_node = base_doc[base_index] if base_doc is not None and base_index is not None else {}
        self._baseline_frame = _frame_values(base_node)
        previous = self._custom
        self._custom = custom
        self.setEnabled(self._document is not None)
        self._update_message()
        self._sync()
        self._refresh_decorations()
        self._update_revert()
        self._update_group_resets()
        if previous != custom:
            self.custom_changed.emit(custom)

    def _update_message(self):
        self.message.setText(tr('当前模板无法在此编辑画框，请使用高级源码'))
        self.message.setVisible(self._document is None)

    def _update_revert(self):
        base_doc, base_index = _node(self._baseline)
        base_node = base_doc[base_index] if base_doc is not None and base_index is not None else {}
        node = self._document[self._index] if self._document is not None and self._index is not None else {}
        self.revert_button.setEnabled(node.get('custom_frame') != base_node.get('custom_frame'))

    def _sync_control(self, path, *, decoration=None):
        entries = self._controls if decoration is None else self._decor_controls.get(decoration, {})
        if path not in entries:
            return
        widget, default, scale = entries[path]
        target = self._frame if decoration is None else self._decoration()
        value = _get(target, path, default)
        blocker = QSignalBlocker(widget)
        if isinstance(widget, CameraRawSlider):
            try:
                widget.setValue(float(value) * scale)
            except (TypeError, ValueError):
                widget.setValue(default * scale)
        elif isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index < 0 and widget.isEditable():
                widget.setEditText(str(value))
            else:
                widget.setCurrentIndex(max(0, index))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QLineEdit):
            if not widget.hasFocus():
                widget.setText(str(value or ''))
                widget.setToolTip(str(value or ''))
        elif isinstance(widget, ColorProperty):
            baseline = self._baseline_color(path, default, decoration)
            widget.set_color(value or default, inherited=str(value).upper() == str(baseline).upper())
        del blocker

    def _sync(self):
        self._syncing = True
        try:
            for path in self._controls:
                self._sync_control(path)
            self._visibility()
        finally:
            self._syncing = False

    def _sync_decoration_control(self, path):
        item = self._decoration()
        if item is not None:
            self._sync_control(path, decoration=item.get('type'))

    def _decor_selected(self, row):
        item = self._decoration()
        self.decor_enabled.setEnabled(item is not None)
        blocker = QSignalBlocker(self.decor_enabled)
        self.decor_enabled.setChecked(bool(item and item.get('enabled', True)))
        del blocker
        kind = item.get('type') if item else None
        for key, page in self._deco_pages.items():
            page.setVisible(key == kind)
        for path in self._decor_controls.get(kind, {}):
            self._sync_control(path, decoration=kind)
        self._visibility()

    def _refresh_decorations(self, row=None):
        current = self.decor_list.currentRow() if row is None else row
        items = self._frame.get('decorations', [])
        if not isinstance(items, list):
            items = []
        labels = dict((value, label) for label, value in _DECORATIONS)
        blocker = QSignalBlocker(self.decor_list)
        self.decor_list.clear()
        for item in items:
            kind = item.get('type', '') if isinstance(item, dict) else ''
            label = tr(labels[kind]) if kind in labels else str(kind)
            self.decor_list.addItem(label)
        self.decor_list.setCurrentRow(min(max(0, current), len(items) - 1) if items else -1)
        del blocker
        self._decor_selected(self.decor_list.currentRow())

    def _visibility(self):
        geometry = self._frame.get('geometry', {})
        background = self._frame.get('background', {})
        self.ratio_group.setVisible(geometry.get('canvas_mode') == 'aspect_ratio')
        for key, page in self._background_pages.items():
            page.setVisible(key == background.get('type', 'solid'))
        self.gradient_angle.setVisible(background.get('gradient_type', 'linear') == 'linear')
        self.texture_controls.setVisible(_get(background, 'texture.type', 'none') != 'none')
        item = self._decoration()
        self.slice_controls.setVisible(bool(item and item.get('type') == 'png_frame_overlay' and item.get('fit') == 'nine_slice'))

    def _retranslate(self):
        for combo, choices in self._combos:
            value = combo.currentData()
            if combo.isEditable() and value is None:
                value = combo.currentText()
            blocker = QSignalBlocker(combo)
            combo.clear()
            for label, data in choices:
                combo.addItem(tr(label), data)
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
            elif combo.isEditable() and value:
                combo.setEditText(str(value))
            del blocker
        self._refresh_decorations()
        self._update_message()
