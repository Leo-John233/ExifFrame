"""从现有样式和字段组合创建可继续编辑的模板"""

from __future__ import annotations

import json

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QSplitter, QVBoxLayout, QWidget, QGroupBox,
)

from core.desktop_service import list_presets, read_template, validate_template, _template_path
from studio.i18n import bind, tr, register_translations, translator, localize_error
from studio.template_editor import PLACEHOLDERS, TemplateHighlighter
from studio.pixmaps import preview_pixmap


register_translations({
    '新建水印模板': 'Create watermark template', '起始样式': 'Starting point',
    '内置样式': 'Built-in style', '复制当前模板': 'Copy current template',
    '空白边框': 'Blank frame', '新建水印': 'New watermark',
    '自定义水印文字': 'Customize watermark text', '模板摘要': 'Template summary',
    '高级源码…': 'Advanced source…', '重新生成源码': 'Regenerate source',
    '创建模板': 'Create template', '取消': 'Cancel', '模板名称已存在': 'A template with this name already exists',
    '请选择一个样式': 'Select a style', '当前模板不可用': 'Current template is unavailable',
    '从空白边框开始，按需添加文字或在高级源码中设置样式': 'Start with an empty frame; add text or adjust its style in the source editor',
    '保留当前模板的完整样式和处理步骤': 'Preserve all styling and processing steps from the current template',
    '名称：{name}\n样式：{style}\n文字：{fields}\n处理步骤：{count}': 'Name: {name}\nStyle: {style}\nText: {fields}\nProcessing steps: {count}',
    '原样保留': 'Keep original text', '无文字': 'No text', '高级源码已修改': 'Advanced source edited',
    '创建后可在模板编辑器中继续调整所有参数': 'You can refine all settings in the template editor after creation',
    '编辑模板源码': 'Edit template source', '使用此源码': 'Use this source',
    '经典相机边框': 'Classic camera frame', '留白与阴影': 'Border and shadow',
    '沉浸模糊背景': 'Blurred background', '尼康模糊背景': 'Nikon blurred background',
    '极简参数': 'Minimal exposure', '旅途与时间': 'Journey and time', '品牌居中': 'Centered brand',
    '相机、镜头与拍摄参数，适合日常分享': 'Camera, lens and exposure information',
    '圆角照片搭配轻盈阴影和宽边框': 'Rounded photo with subtle shadow and a wide border',
    '延展画面色彩，居中展示拍摄信息': 'Extended photo colors with centered information',
    '突出尼康 Z 标识的专属版式': 'Dedicated layout featuring the Nikon Z logo',
    '小巧文字落在右下角，保留画面重心': 'Compact exposure information at the bottom right',
    '使用照片所在文件夹名称记录这次拍摄': 'Use the photo folder name to label the session',
    '居中品牌标识搭配简洁留白': 'Centered brand logo with a clean border',
})


class TemplateWizard(QDialog):
    """仅返回名称和源码，由调用方执行新建写入"""

    BUILT_INS = ('标准水印', '标准水印2', '背景模糊', '尼康专用背景模糊',
                 '右下角参数', '文件夹名+右下角参数', 'logo居中')

    def __init__(self, parent=None, current_template: str = ''):
        super().__init__(parent)
        self.current_template = current_template
        self.name = ''
        self.source = ''
        self._advanced_source = None
        self._presets = [p for p in list_presets() if p.name in self.BUILT_INS]
        self.setObjectName('templateWizard')
        self.resize(900, 620)
        self.setMinimumSize(700, 490)
        self._build_ui()
        translator.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        name_row = QHBoxLayout()
        name_label = QLabel()
        bind(name_label, '模板名称')
        name_row.addWidget(name_label)
        self.name_input = QLineEdit()
        bind(self.name_input, '新模板名称', 'setPlaceholderText')
        name_row.addWidget(self.name_input, 1)
        name_row.addWidget(QLabel('.json'))
        layout.addLayout(name_row)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        self.mode = QComboBox()
        for key in ('内置样式', '复制当前模板', '空白边框'):
            self.mode.addItem(tr(key), key)
        self.mode.model().item(1).setEnabled(bool(self.current_template))
        left_layout.addWidget(self.mode)
        self.styles = QListWidget()
        self.styles.setObjectName('templateWizardStyles')
        self.styles.setIconSize(QSize(120, 78))
        self.styles.setSpacing(4)
        for preset in self._presets:
            item = QListWidgetItem(self.styles)
            item.setData(Qt.ItemDataRole.UserRole, preset.name)
            if preset.thumbnail:
                item.setIcon(QIcon(preview_pixmap(preset.thumbnail, 120, 78)))
            item.setSizeHint(QSize(280, 86))
        if self.styles.count():
            self.styles.setCurrentRow(0)
        left_layout.addWidget(self.styles, 1)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(140)
        self.preview.setMaximumHeight(220)
        right_layout.addWidget(self.preview)
        self.description = QLabel()
        self.description.setWordWrap(True)
        right_layout.addWidget(self.description)
        self.customize = QCheckBox()
        bind(self.customize, '自定义水印文字')
        right_layout.addWidget(self.customize)
        self.field_box = QWidget()
        fields_layout = QHBoxLayout(self.field_box)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        self.field_checks = []
        for label, expression in PLACEHOLDERS[:6]:
            check = QCheckBox()
            bind(check, label)
            check.setChecked(label != '版权')
            check.toggled.connect(self._content_changed)
            self.field_checks.append((label, expression, check))
            fields_layout.addWidget(check)
        right_layout.addWidget(self.field_box)
        self.summary_group = QGroupBox()
        bind(self.summary_group, '模板摘要', 'setTitle')
        summary_layout = QVBoxLayout(self.summary_group)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_layout.addWidget(self.summary)
        right_layout.addWidget(self.summary_group)
        advanced_row = QHBoxLayout()
        self.advanced_button = QPushButton()
        bind(self.advanced_button, '高级源码…')
        self.advanced_button.setAutoDefault(False)
        self.advanced_button.clicked.connect(self._advanced)
        advanced_row.addWidget(self.advanced_button)
        self.reset_button = QPushButton()
        bind(self.reset_button, '重新生成源码')
        self.reset_button.setAutoDefault(False)
        self.reset_button.clicked.connect(self._content_changed)
        advanced_row.addWidget(self.reset_button)
        right_layout.addLayout(advanced_row)
        right_layout.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([340, 520])
        layout.addWidget(splitter, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bind(self.buttons.button(QDialogButtonBox.StandardButton.Ok), '创建模板')
        bind(self.buttons.button(QDialogButtonBox.StandardButton.Cancel), '取消')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.name_input.textChanged.connect(self._refresh)
        self.mode.currentIndexChanged.connect(self._content_changed)
        self.styles.currentRowChanged.connect(self._content_changed)
        self.customize.toggled.connect(self._content_changed)

    def _content_changed(self, *args):
        self._advanced_source = None
        self._refresh()

    def _style_source(self):
        mode = self.mode.currentData()
        if mode == '复制当前模板':
            if not self.current_template:
                raise ValueError(tr('当前模板不可用'))
            return read_template(self.current_template)
        if mode == '空白边框':
            # 有效空白边框仍能参与预览并继续增加文字
            return json.dumps([{'processor_name': 'watermark', 'color': 'white',
                                **{key: {'processor_name': 'rich_text', 'text': ''}
                                   for key in ('left_top', 'left_bottom', 'right_top', 'right_bottom')}}], indent=2)
        row = self.styles.currentRow()
        if row < 0:
            raise ValueError(tr('请选择一个样式'))
        return read_template(self._presets[row].name)

    def _generate(self):
        if self._advanced_source is not None:
            return self._advanced_source
        source = self._style_source()
        if not self.customize.isChecked():
            return source
        nodes = json.loads(source)
        selected = {name: expression for name, expression, check in self.field_checks if check.isChecked()}
        remaining = list(selected.values())
        footer = next((node for node in nodes if node.get('processor_name') == 'watermark'), None)
        if footer is not None:
            values = (selected.get('相机', ''), selected.get('镜头', ''), selected.get('拍摄参数', ''),
                      '  '.join(selected[name] for name in ('拍摄日期', '版权', '摄影师') if name in selected))
            for key, value in zip(('left_top', 'left_bottom', 'right_top', 'right_bottom'), values):
                previous = footer.get(key, {})
                previous.pop('text_segments', None)
                previous.update(processor_name='rich_text', text=value)
                footer[key] = previous
        else:
            text_nodes = [node for node in nodes if node.get('processor_name') in ('rich_text', 'multi_rich_text')]
            for index, node in enumerate(text_nodes):
                node.pop('text_segments', None)
                value = '  '.join(remaining[index:]) if index == len(text_nodes) - 1 else (remaining[index] if index < len(remaining) else '')
                node.update(processor_name='rich_text', text=value)
        return json.dumps(nodes, ensure_ascii=False, indent=2)

    def _refresh(self, *args):
        mode = self.mode.currentData()
        self.styles.setEnabled(mode == '内置样式')
        self.field_box.setEnabled(self.customize.isChecked())
        self.reset_button.setEnabled(self._advanced_source is not None)
        row = self.styles.currentRow()
        preset = self._presets[row] if row >= 0 else None
        self.preview.clear()
        if mode == '内置样式' and preset:
            if preset.thumbnail:
                self.preview.setPixmap(preview_pixmap(preset.thumbnail, 400, 210))
            style = tr(preset.title)
            self.description.setText(tr(preset.description))
        else:
            style = tr(self.current_template) if mode == '复制当前模板' else tr(mode)
            self.preview.setText(style)
            self.description.setText(tr('保留当前模板的完整样式和处理步骤' if mode == '复制当前模板' else '从空白边框开始，按需添加文字或在高级源码中设置样式'))
        error = ''
        count = '—'
        try:
            self.source = self._generate()
            validate_template(self.source)
            try:
                nodes = json.loads(self.source)
                count = str(len(nodes))
            except ValueError:
                pass
            if count == '0':
                raise ValueError(tr('水印模板需要至少一个处理步骤'))
            name = self.name_input.text().strip()
            path = _template_path(name)
            if path.exists() or any(p.name.casefold() == path.name.casefold() for p in path.parent.glob('*.json')):
                raise ValueError(tr('模板名称已存在'))
        except Exception as exc:
            error = localize_error(exc)
        selected = ' / '.join(tr(name) for name, expression, check in self.field_checks if check.isChecked())
        fields = (selected or tr('无文字')) if self.customize.isChecked() else tr('原样保留')
        if self._advanced_source is not None:
            fields = tr('高级源码已修改')
        self.summary.setText(tr('名称：{name}\n样式：{style}\n文字：{fields}\n处理步骤：{count}',
                                name=self.name_input.text().strip() or tr('未命名模板'), style=style,
                                fields=fields, count=count))
        self.status.setText(error if self.name_input.text().strip() or not self.source else tr('创建后可在模板编辑器中继续调整所有参数'))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not error)

    def _advanced(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('编辑模板源码'))
        dialog.resize(780, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(self.source)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        highlighter = TemplateHighlighter(editor)
        layout.addWidget(editor)
        error = QLabel()
        error.setWordWrap(True)
        layout.addWidget(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('使用此源码'))
        layout.addWidget(buttons)

        def apply():
            try:
                validate_template(editor.toPlainText())
            except Exception as exc:
                error.setText(localize_error(exc))
                return
            self._advanced_source = editor.toPlainText()
            dialog.accept()

        buttons.accepted.connect(apply)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def retranslate_ui(self):
        self.setWindowTitle(tr('新建水印模板'))
        for index in range(self.mode.count()):
            self.mode.setItemText(index, tr(self.mode.itemData(index)))
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
