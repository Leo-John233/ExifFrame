"""从样式和可视化文字组合创建可继续编辑的模板"""

from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.desktop_service import list_presets, read_template, validate_template, _template_path
from studio.footer_editor import FooterPanel, _fit_editor_window
from studio.i18n import bind, tr, register_translations, translator, localize_error
from studio.template_editor import TemplateHighlighter
from studio.pixmaps import preview_pixmap


register_translations({
    '新建水印模板': 'Create watermark template', '起始样式': 'Starting point',
    '内置样式': 'Built-in style', '复制当前模板': 'Copy current template', '空白边框': 'Blank frame',
    '创建模板': 'Create template', '取消': 'Cancel', '请选择一个样式': 'Select a style',
    '模板名称已存在': 'A template with this name already exists', '当前模板不可用': 'Current template is unavailable',
    '从空白边框开始，按需组合每个文字区域': 'Start with an empty frame and compose each text region',
    '保留当前模板的完整样式和处理步骤': 'Preserve all styling and processing steps from the current template',
    '高级源码…': 'Advanced source…', '返回可视化组合': 'Return to visual composer',
    '正在使用高级源码，返回可视化后可继续组合字段': 'Using advanced source. Return to the visual composer to arrange fields',
    '名称：{name} · 样式：{style} · {regions} 个文字区 · {items} 个信息项': 'Name: {name} · Style: {style} · {regions} text regions · {items} items',
    '创建后可继续组合底部信息或编辑高级源码': 'After creation, continue composing the footer or edit the advanced source',
    '使用此源码': 'Use this source', '高级源码编辑器': 'Advanced source editor',
    '无法读取当前组合：{error}': 'Unable to read the current layout: {error}',
    '无法使用可视化组合，源码保持不变：{error}': 'Visual editing is unavailable; source preserved: {error}',
    '经典相机边框': 'Classic camera frame', '留白与阴影': 'Border and shadow',
    '沉浸模糊背景': 'Blurred background', '尼康模糊背景': 'Nikon blurred background',
    '极简参数': 'Minimal exposure', '旅途与时间': 'Journey and time', '品牌居中': 'Centered brand',
    '{regions} 个文字区 · {items} 个信息项': '{regions} text regions · {items} items',
    '输入模板名称后即可创建': 'Enter a template name to create it',
})


class _WizardButtons(QDialogButtonBox):
    """Qt 切换标准按钮语言后恢复明确的创建动作名称"""

    def __init__(self, accept_label):
        self._accept_label = accept_label
        super().__init__(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button(QDialogButtonBox.StandardButton.Ok).setObjectName('primaryButton')
        self._translate()

    def _translate(self):
        self.button(QDialogButtonBox.StandardButton.Ok).setText(tr(self._accept_label))
        self.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        # 英文动作名称更长，切换语言时同步按钮区域的最小宽度
        self.setMinimumWidth(self.sizeHint().width())

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._translate()


class TemplateWizard(QDialog):
    """可视化组合和高级源码共用一份草稿，最终由调用方落盘"""

    BUILT_INS = ('标准水印', '标准水印2', '背景模糊', '尼康专用背景模糊',
                 '右下角参数', '文件夹名+右下角参数', 'logo居中', '仅标识居中')

    def __init__(self, parent=None, current_template: str = '', current_source: str | None = None,
                 metadata=None, filename='', file_dir=''):
        super().__init__(parent)
        self.current_template, self.current_source = current_template, current_source
        self.name, self.source = '', ''
        self._advanced_source = self._visual_source = None
        self._base_source = ''
        self._style_key = None
        self._style_drafts = {}
        self._composition_error = None
        self._loading = True
        self._context = dict(metadata=metadata, filename=filename, file_dir=file_dir)
        self._presets = [preset for preset in list_presets() if preset.name in self.BUILT_INS]
        self.setObjectName('templateWizard')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint |
                            Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(760, 500)
        _fit_editor_window(self, 960, 640)
        self._build_ui()
        self._loading = False
        self._change_style()
        translator.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        names = QHBoxLayout()
        names.setSpacing(8)
        names.addWidget(bind(QLabel(), '模板名称'))
        self.name_input = QLineEdit()
        self.name_input.setObjectName('templateWizardName')
        self.name_input.setClearButtonEnabled(True)
        self.name_input.setMaximumWidth(420)
        bind(self.name_input, '新模板名称', 'setPlaceholderText')
        names.addWidget(self.name_input, 1)
        names.addStretch()
        self.visual_button = bind(QPushButton(), '返回可视化组合')
        self.visual_button.setAutoDefault(False)
        self.visual_button.clicked.connect(self._return_visual)
        names.addWidget(self.visual_button)
        self.advanced_button = bind(QPushButton(), '高级源码…')
        self.advanced_button.setAutoDefault(False)
        self.advanced_button.clicked.connect(self._advanced)
        names.addWidget(self.advanced_button)
        layout.addLayout(names)
        self.splitter = QSplitter()
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        left = QWidget()
        left.setMinimumWidth(205)
        left.setMaximumWidth(270)
        choices = QVBoxLayout(left)
        choices.setContentsMargins(0, 0, 10, 0)
        choices.setSpacing(8)
        choices.addWidget(bind(QLabel(), '起始样式'))
        self.mode = QComboBox()
        for value in ('内置样式', '复制当前模板', '空白边框'):
            self.mode.addItem(tr(value), value)
        self.mode.model().item(1).setEnabled(bool(self.current_template))
        if not self._presets:
            self.mode.setCurrentIndex(1 if self.current_template else 2)
        choices.addWidget(self.mode)
        self.styles = QListWidget()
        self.styles.setObjectName('templateWizardStyles')
        self.styles.setIconSize(QSize(66, 44))
        self.styles.setSpacing(2)
        self.styles.setUniformItemSizes(True)
        self.styles.setWordWrap(True)
        self.styles.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.styles.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.styles.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.styles.setResizeMode(QListWidget.ResizeMode.Adjust)
        for preset in self._presets:
            item = QListWidgetItem(self.styles)
            item.setData(Qt.ItemDataRole.UserRole, preset.name)
            if preset.thumbnail:
                item.setIcon(QIcon(preview_pixmap(preset.thumbnail, 66, 44)))
            # 行宽由视口决定，避免固定宽度挤出横向滚动条
            item.setSizeHint(QSize(0, 58))
        if self.styles.count():
            self.styles.setCurrentRow(0)
        choices.addWidget(self.styles, 1)
        self.splitter.addWidget(left)
        right = QWidget()
        content = QVBoxLayout(right)
        content.setContentsMargins(12, 0, 0, 0)
        content.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(12)
        self.style_title = QLabel()
        title_font = self.style_title.font()
        title_font.setBold(True)
        self.style_title.setFont(title_font)
        self.style_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(self.style_title, 1)
        self.summary = QLabel()
        self.summary.setObjectName('secondaryText')
        heading.addWidget(self.summary)
        content.addLayout(heading)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName('secondaryText')
        content.addWidget(self.description)
        self.mode_hint = QLabel()
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setObjectName('secondaryText')
        content.addWidget(self.mode_hint)
        self.footer_panel = FooterPanel(self._style_source(), parent=self, compact=True, **self._context)
        self.footer_panel.setObjectName('templateWizardFooterPanel')
        self.footer_panel.layout().setContentsMargins(0, 4, 8, 0)
        self.footer_panel.region_group.setMinimumWidth(280)
        self.footer_panel.region_group.setMaximumWidth(360)
        self.footer_panel.layout().setAlignment(self.footer_panel.region_group, Qt.AlignmentFlag.AlignLeft)
        self.footer_panel.item_hint.hide()
        # 列表随内容显示两到五行，不让少量字段撑出大片空白
        model = self.footer_panel.items.model()
        model.rowsInserted.connect(self._fit_content_list)
        model.rowsRemoved.connect(self._fit_content_list)
        model.modelReset.connect(self._fit_content_list)
        self._fit_content_list()
        self.footer_panel.changed.connect(self._content_changed)
        self.panel_scroll = QScrollArea()
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_scroll.setWidget(self.footer_panel)
        content.addWidget(self.panel_scroll, 1)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([245, 690])
        layout.addWidget(self.splitter, 1)
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        bottom.setContentsMargins(0, 8, 0, 0)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName('secondaryText')
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bottom.addWidget(self.status, 1)
        self.buttons = _WizardButtons('创建模板')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        bottom.addWidget(self.buttons)
        layout.addLayout(bottom)
        self.name_input.textChanged.connect(self._refresh)
        self.mode.currentIndexChanged.connect(self._change_style)
        self.styles.currentRowChanged.connect(self._change_style)

    def _fit_content_list(self, *args):
        """区域切换后按信息数量收紧列表，较多内容在列表内滚动"""
        rows = min(5, max(2, self.footer_panel.items.count()))
        self.footer_panel.items.setFixedHeight(rows * 26 + 8)

    def _style_source(self):
        mode = self.mode.currentData()
        if mode == '复制当前模板':
            if not self.current_template:
                raise ValueError(tr('当前模板不可用'))
            return self.current_source if self.current_source is not None else read_template(self.current_template)
        if mode == '空白边框':
            return json.dumps([{'processor_name': 'watermark', 'color': 'white',
                                **{name: {'processor_name': 'rich_text', 'text': ''}
                                   for name in ('left_top', 'left_bottom', 'right_top', 'right_bottom')}}], indent=2)
        row = self.styles.currentRow()
        if row < 0:
            raise ValueError(tr('请选择一个样式'))
        return read_template(self._presets[row].name)

    def _change_style(self, *args):
        """每个起始样式保留独立草稿，切回来时恢复用户组合"""
        if self._loading:
            return
        mode = self.mode.currentData()
        selected = self.styles.currentItem()
        key = (mode, selected.data(Qt.ItemDataRole.UserRole) if mode == '内置样式' and selected else self.current_template if mode == '复制当前模板' else '')
        if key == self._style_key:
            self._refresh()
            return
        if self._composition_error is not None and self._style_key is not None:
            # 无效组合仍留在面板中，先修正再切换，不能用上次有效源码代替
            old_mode, old_name = self._style_key
            self.mode.blockSignals(True)
            self.styles.blockSignals(True)
            self.mode.setCurrentIndex(self.mode.findData(old_mode))
            if old_mode == '内置样式':
                for index, preset in enumerate(self._presets):
                    if preset.name == old_name:
                        self.styles.setCurrentRow(index)
                        break
            self.mode.blockSignals(False)
            self.styles.blockSignals(False)
            self._refresh()
            return
        if self._style_key is not None:
            self._style_drafts[self._style_key] = (self._generate(), self._advanced_source is not None)
        try:
            source, advanced = self._style_drafts.get(key, (None, False))
            if source is None:
                source = self._style_source()
            self._loading = True
            self.footer_panel.set_source(source)
            self._base_source = source
            self._visual_source = None
            self._advanced_source = source if advanced else None
            self._composition_error = None
            self._style_key = key
        except Exception as exc:
            self.status.setText(localize_error(exc))
        finally:
            self._loading = False
        self._refresh()

    def _content_changed(self, *args):
        """真实字段调整才更新草稿，名称和语言变化不重建模型"""
        if self._loading:
            return
        try:
            self._visual_source = self.footer_panel.composed_source()
            self._advanced_source = None
            self._composition_error = None
            self._refresh()
        except Exception as exc:
            self._composition_error = exc
            self.status.setText(tr('无法读取当前组合：{error}', error=localize_error(exc)))
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _generate(self):
        if self._advanced_source is not None:
            return self._advanced_source
        return self._visual_source if self._visual_source is not None else self._base_source

    def _refresh(self, *args):
        if self._loading:
            return
        mode = self.mode.currentData()
        self.styles.setEnabled(mode == '内置样式')
        advanced = self._advanced_source is not None
        self.footer_panel.setEnabled(not advanced)
        self.visual_button.setVisible(advanced)
        self.mode_hint.setVisible(advanced)
        self.mode_hint.setText(tr('正在使用高级源码，返回可视化后可继续组合字段'))
        row = self.styles.currentRow()
        preset = self._presets[row] if row >= 0 else None
        if mode == '内置样式' and preset:
            style = tr(preset.title)
            self.description.setText(tr(preset.description))
        else:
            style = tr(self.current_template) if mode == '复制当前模板' else tr(mode)
            self.description.setText(tr('保留当前模板的完整样式和处理步骤' if mode == '复制当前模板' else '从空白边框开始，按需组合每个文字区域'))
        self.style_title.setText(style)
        self.style_title.setToolTip(style)
        error = ''
        try:
            if self._composition_error is not None:
                raise self._composition_error
            self.source = self._generate()
            validate_template(self.source)
            if self.source.strip() == '[]':
                raise ValueError(tr('水印模板需要至少一个处理步骤'))
            name = self.name_input.text().strip()
            path = _template_path(name)
            if path.exists() or any(item.name.casefold() == path.name.casefold() for item in path.parent.glob('*.json')):
                raise ValueError(tr('模板名称已存在'))
        except Exception as exc:
            error = localize_error(exc)
        model = self.footer_panel.layout_data()
        rows = model.get('rows', {})
        self.summary.setText(tr('{regions} 个文字区 · {items} 个信息项',
                                regions=len(model.get('regions', [])),
                                items=sum(len(row.get('items', [])) for row in rows.values())))
        self.status.setText(error if self._composition_error is not None or self.name_input.text().strip() or not self.source
                            else tr('输入模板名称后即可创建'))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)

    def _advanced(self):
        if self._composition_error is not None:
            self.status.setText(tr('无法读取当前组合：{error}', error=localize_error(self._composition_error)))
            return
        dialog = QDialog(self)
        bind(dialog, '高级源码编辑器', 'setWindowTitle')
        dialog.resize(820, 630)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        editor = QPlainTextEdit(self.source)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        highlighter = TemplateHighlighter(editor)
        layout.addWidget(editor)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = _WizardButtons('使用此源码')
        layout.addWidget(buttons)
        def apply():
            try:
                validate_template(editor.toPlainText())
            except Exception as exc:
                error.setText(localize_error(exc))
                return
            self._advanced_source = editor.toPlainText()
            self._composition_error = None
            # 高级源码先保留原文，返回可视化时再由模型安全解析
            try:
                self.footer_panel.set_source(self._advanced_source)
            except Exception:
                pass
            dialog.accept()
        buttons.accepted.connect(apply)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()
        dialog.deleteLater()

    def _return_visual(self):
        if self._advanced_source is None:
            return
        try:
            self.footer_panel.set_source(self._advanced_source)
            if getattr(self.footer_panel, '_load_error', None) is not None:
                raise self.footer_panel._load_error
        except Exception as exc:
            self.status.setText(tr('无法使用可视化组合，源码保持不变：{error}', error=localize_error(exc)))
            return
        self._base_source = self._advanced_source
        self._visual_source = self._advanced_source = None
        self._composition_error = None
        self._refresh()

    def retranslate_ui(self):
        self.setWindowTitle(tr('新建水印模板'))
        self.mode.blockSignals(True)
        for index in range(self.mode.count()):
            self.mode.setItemText(index, tr(self.mode.itemData(index)))
        self.mode.blockSignals(False)
        for index, preset in enumerate(self._presets):
            item = self.styles.item(index)
            item.setText(tr(preset.title))
            item.setToolTip(tr(preset.description))
        self._refresh()

    def accept(self):
        self._refresh()
        if not self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            return
        self.name = self.name_input.text().strip()
        super().accept()
