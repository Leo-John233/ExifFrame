"""使用显式字段选择编辑水印信息并安全保存照片副本"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateTimeEdit, QDialog, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from core.metadata import FIELDS, metadata_key, normalize_changes, read_metadata, save_metadata_copy
from studio.i18n import bind, tr, register_translations, translator, localize_error, language


register_translations({
    '编辑照片信息': 'Edit photo information', '当前照片': 'Current photo',
    '仅影响水印，原片保持不变': 'Changes apply to the watermark; original photos stay unchanged',
    '应用范围': 'Apply to', '全选': 'Select all', '清空选择': 'Deselect all',
    '字段': 'Field', '原始值': 'Original value', '待应用值': 'New value',
    '未记录': 'Not recorded', '留空保留原值': 'Leave blank to preserve the original',
    '加载参考照片…': 'Load reference photo…', '清除水印修改': 'Clear watermark changes',
    '保存修改副本…': 'Save edited copy…', '将 EXIF 迁移到其他照片副本…': 'Transfer EXIF to another photo copy…',
    '应用到勾选照片的水印': 'Apply to checked photos', '关闭': 'Close',
    '排除厂商私有数据': 'Exclude manufacturer data',
    '避免将特定相机的私有结构复制到其他照片': 'Avoid copying camera-specific private structures to other photos',
    '勾选需要修改的字段；未勾选和留空字段保留照片自身信息': 'Check fields to change; unchecked and empty fields keep each photo’s own values',
    '正在读取 {name}…': 'Reading {name}…', '已读取 {name}': 'Loaded {name}',
    '正在读取参考照片 {name}…': 'Reading reference photo {name}…',
    '已从 {name} 加载 {count} 个字段，请检查后应用': 'Loaded {count} fields from {name}; review before applying',
    '参考照片：{name}': 'Reference photo: {name}', '参考照片：未选择': 'Reference photo: none',
    '已向 {count} 张照片应用 {fields} 个字段': 'Applied {fields} fields to {count} photos',
    '已清除 {count} 张照片的水印修改': 'Cleared watermark changes for {count} photos',
    '请至少勾选一张照片': 'Check at least one photo', '请勾选并填写需要修改的字段': 'Check and fill in the fields you want to change',
    '正在保存副本…': 'Saving copy…', '副本已保存：{path}': 'Copy saved: {path}',
    '正在迁移 EXIF 到副本…': 'Transferring EXIF to copy…',
    '任务完成后将关闭此窗口': 'This window will close when the operation finishes',
    '信息尚未应用': 'Unapplied information', '放弃尚未应用的字段修改？': 'Discard field changes that have not been applied?',
    '选择参考照片': 'Choose reference photo', '选择接收 EXIF 的照片': 'Choose the photo to receive EXIF',
    '保存照片副本': 'Save photo copy', '照片与 RAW 文件 ({extensions});;所有文件 (*)': 'Photos and RAW files ({extensions});;All files (*)',
    '照片文件 (*{suffix});;所有文件 (*)': 'Photo files (*{suffix});;All files (*)',
    '副本必须保留原照片的扩展名': 'The copy must keep the original photo extension',
    '创作者与版权': 'Creator and copyright', '相机与镜头': 'Camera and lens',
    '曝光参数': 'Exposure', '时间与位置': 'Time and location',
    '摄影师': 'Photographer', '作者': 'Author', '版权声明': 'Copyright', '处理软件': 'Software',
    '照片描述': 'Image description', '用户备注': 'User comment', '星级评分': 'Rating',
    '相机制造商': 'Camera manufacturer', '相机型号': 'Camera model', '镜头品牌': 'Lens manufacturer',
    '镜头型号': 'Lens model', '实际焦距': 'Focal length', '等效焦距': '35mm-equivalent focal length',
    '光圈': 'Aperture', '快门速度': 'Shutter speed', '感光度': 'ISO', '曝光补偿': 'Exposure compensation',
    '闪光灯': 'Flash', '白平衡': 'White balance', '拍摄时间': 'Capture time', '数字化时间': 'Digitized time',
    '时区偏移': 'Time zone offset', '纬度': 'Latitude', '南北纬': 'Latitude hemisphere',
    '经度': 'Longitude', '东西经': 'Longitude hemisphere', '海拔高度': 'Altitude',
    '未闪光': 'Did not fire', '已闪光': 'Fired', '自动闪光': 'Auto flash', '消除红眼': 'Red-eye reduction',
    '自动': 'Auto', '日光': 'Daylight', '多云': 'Cloudy', '钨丝灯': 'Tungsten', '荧光灯': 'Fluorescent',
    '手动': 'Manual', '北纬': 'North', '南纬': 'South', '东经': 'East', '西经': 'West',
    '未找到 ExifTool，请将程序和运行文件放入 exiftool 文件夹': 'ExifTool was not found; place the executable and runtime files in the exiftool folder',
    '照片文件不存在': 'Photo file does not exist', '不支持此字段：{field}': 'Unsupported field: {field}',
    '请检查字段格式：{field}': 'Check the value for {field}', '请填写有效日期：{field}': 'Enter a valid date for {field}',
    '时区格式应为 +08:00 或 -05:00': 'Use a time zone offset such as +08:00 or -05:00',
    '请检查经纬度范围及半球方向': 'Check the coordinate range and hemisphere',
    '目标文件已存在，请使用新文件名': 'Destination already exists; choose a new file name',
    '副本不能与原照片或参考照片相同': 'The copy cannot be the original or reference photo',
    '照片副本写入失败': 'Could not write the photo copy',
    '操作失败：{error}': 'Operation failed: {error}',
    '字段：{field}': 'Field: {field}',
    '修改坐标时同时选择对应的半球方向': 'Editing a coordinate also selects its hemisphere',
    '地理位置': 'Location',
    '纬度与经度合为地理位置，在水印中以度分秒显示': 'Latitude and longitude form one Location field, shown in degrees, minutes and seconds in the watermark',
})

PHOTO_EXTENSIONS = '*.jpg *.jpeg *.png *.heic *.heif *.tif *.tiff *.dng *.nef *.nrw *.cr2 *.cr3 *.crw *.arw *.sr2 *.raf *.rw2 *.orf *.pef *.srw *.3fr *.iiq'


class _MetadataTask(QThread):
    """持有调用结果，在线程完成后统一返回主线程"""

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.operation()
        except Exception as exc:
            self.error = exc


class MetadataEditor(QDialog):
    """后台读取原始信息，字段变更只通过应用信号提交"""

    applied = Signal(dict)

    def __init__(self, parent=None, paths: list[Path] | None = None,
                 current: Path | None = None, overrides: dict | None = None):
        super().__init__(parent)
        self.paths = list(dict.fromkeys(Path(path) for path in (paths or [])))
        self.current = Path(current) if current else (self.paths[0] if self.paths else None)
        if self.current and self.current not in self.paths:
            self.paths.insert(0, self.current)
        self.overrides = {key: dict(value) for key, value in (overrides or {}).items()}
        self.original = {}
        self.reference = None
        self._job = None
        self._callback = None
        self._close_when_done = False
        self._loaded = False
        self._baseline = ()
        self._status = ('勾选需要修改的字段；未勾选和留空字段保留照片自身信息', {})
        self._last_error = None
        self._field_rows = {}
        self._tabs = []
        self.setObjectName('metadataEditor')
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1040, 760)
        self.setMinimumSize(790, 530)
        self._build_ui()
        translator.language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()
        if self.current:
            self._load_current()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        top = QHBoxLayout()
        label = QLabel()
        bind(label, '当前照片')
        top.addWidget(label)
        self.current_combo = QComboBox()
        for path in self.paths:
            self.current_combo.addItem(path.name, path)
            self.current_combo.setItemData(self.current_combo.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole)
        if self.current:
            self.current_combo.setCurrentIndex(self.paths.index(self.current))
        top.addWidget(self.current_combo, 1)
        self.reference_button = QPushButton()
        bind(self.reference_button, '加载参考照片…')
        self.reference_button.clicked.connect(self._load_reference)
        top.addWidget(self.reference_button)
        layout.addLayout(top)
        note = QLabel()
        bind(note, '仅影响水印，原片保持不变')
        layout.addWidget(note)
        splitter = QSplitter()
        selection = QWidget()
        select_layout = QVBoxLayout(selection)
        select_layout.setContentsMargins(0, 0, 6, 0)
        select_label = QLabel()
        bind(select_label, '应用范围')
        select_layout.addWidget(select_label)
        self.photos = QListWidget()
        self.photos.setObjectName('metadataTargets')
        for path in self.paths:
            item = QListWidgetItem(path.name, self.photos)
            item.setToolTip(str(path))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        select_layout.addWidget(self.photos, 1)
        select_buttons = QHBoxLayout()
        for label, state in [('全选', Qt.CheckState.Checked), ('清空选择', Qt.CheckState.Unchecked)]:
            button = QPushButton()
            bind(button, label)
            button.clicked.connect(lambda checked=False, state=state: self._select_all(state))
            button.setAutoDefault(False)
            select_buttons.addWidget(button)
        select_layout.addLayout(select_buttons)
        splitter.addWidget(selection)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('metadataFields')
        groups = list(dict.fromkeys(field.group for field in FIELDS))
        for group in groups:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            body = QWidget()
            grid = QGridLayout(body)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 2)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(10)
            for column, title in enumerate(('字段', '原始值', '待应用值')):
                header = QLabel()
                bind(header, title)
                grid.addWidget(header, 0, column)
            row = 1
            for field in (f for f in FIELDS if f.group == group):
                if field.tag == 'GPSLatitude':
                    location_hint = QLabel()
                    bind(location_hint, '纬度与经度合为地理位置，在水印中以度分秒显示')
                    location_hint.setWordWrap(True)
                    location_hint.setObjectName('secondaryText')
                    grid.addWidget(location_hint, row, 0, 1, 3)
                    row += 1
                check = QCheckBox()
                bind(check, field.label)
                check.setToolTip(field.tag)
                if field.tag in ('GPSLatitude', 'GPSLongitude'):
                    bind(check, '修改坐标时同时选择对应的半球方向', 'setToolTip')
                original = QLabel()
                original.setWordWrap(True)
                original.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                editor = self._make_editor(field)
                editor.setObjectName('metadata_' + field.tag)
                editor.setEnabled(False)
                check.toggled.connect(editor.setEnabled)
                check.toggled.connect(lambda checked, tag=field.tag: self._field_selected(tag, checked))
                grid.addWidget(check, row, 0)
                grid.addWidget(original, row, 1)
                grid.addWidget(editor, row, 2)
                self._field_rows[field.tag] = (field, check, original, editor)
                row += 1
            grid.setRowStretch(grid.rowCount(), 1)
            scroll.setWidget(body)
            self.tabs.addTab(scroll, tr(group))
            self._tabs.append(group)
        splitter.addWidget(self.tabs)
        splitter.setSizes([230, 790])
        layout.addWidget(splitter, 1)
        self.reference_label = QLabel()
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        save_row = QHBoxLayout()
        self.save_button = QPushButton()
        bind(self.save_button, '保存修改副本…')
        self.save_button.clicked.connect(self._save_copy)
        save_row.addWidget(self.save_button)
        self.transfer_button = QPushButton()
        bind(self.transfer_button, '将 EXIF 迁移到其他照片副本…')
        self.transfer_button.clicked.connect(self._transfer)
        save_row.addWidget(self.transfer_button)
        self.strip_maker = QCheckBox()
        bind(self.strip_maker, '排除厂商私有数据')
        bind(self.strip_maker, '避免将特定相机的私有结构复制到其他照片', 'setToolTip')
        self.strip_maker.setChecked(True)
        save_row.addWidget(self.strip_maker)
        save_row.addStretch()
        layout.addLayout(save_row)
        bottom = QHBoxLayout()
        self.clear_button = QPushButton()
        bind(self.clear_button, '清除水印修改')
        self.clear_button.clicked.connect(self._clear_overrides)
        bottom.addWidget(self.clear_button)
        bottom.addStretch()
        self.apply_button = QPushButton()
        bind(self.apply_button, '应用到勾选照片的水印')
        self.apply_button.setObjectName('primaryButton')
        self.apply_button.clicked.connect(self._apply)
        bottom.addWidget(self.apply_button)
        self.close_button = QPushButton()
        bind(self.close_button, '关闭')
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.current_combo.currentIndexChanged.connect(self._switch_current)

    def _make_editor(self, field):
        if field.kind == 'datetime':
            editor = QDateTimeEdit()
            editor.setCalendarPopup(True)
            editor.setDisplayFormat('yyyy-MM-dd HH:mm:ss')
            editor.setMinimumDateTime(QDateTime.fromString('1900-01-01 00:00:00', 'yyyy-MM-dd HH:mm:ss'))
            editor.setDateTime(editor.minimumDateTime())
            bind(editor, '留空保留原值', 'setSpecialValueText')
            return editor
        if field.choices:
            editor = QComboBox()
            editor.addItem(tr('留空保留原值'), '')
            for value, label in field.choices:
                editor.addItem(tr(label), value)
            return editor
        editor = QLineEdit()
        hints = {'FNumber': 'f/2.8', 'ExposureTime': '1/250', 'ISO': 'ISO 400',
                 'FocalLength': '50 mm', 'FocalLengthIn35mmFormat': '75 mm',
                 'OffsetTimeOriginal': '+08:00', 'GPSLatitude': '31.2304',
                 'GPSLongitude': '121.4737', 'GPSAltitude': '12.5', 'Rating': '0–5'}
        if field.tag in hints:
            editor.setPlaceholderText(hints[field.tag])
        else:
            bind(editor, '留空保留原值', 'setPlaceholderText')
        return editor

    def _field_selected(self, tag, checked):
        editor = self._field_rows[tag][3]
        if checked and tag in ('GPSLatitude', 'GPSLongitude'):
            reference = self._field_rows.get(tag + 'Ref')
            if reference is not None:
                reference[1].setChecked(True)
        if checked and isinstance(editor, QDateTimeEdit) and editor.dateTime() == editor.minimumDateTime():
            editor.setDateTime(QDateTime.currentDateTime())

    def _set_value(self, editor, value):
        value = str(value or '')
        if isinstance(editor, QDateTimeEdit):
            parsed = QDateTime.fromString(value, 'yyyy:MM:dd HH:mm:ss')
            if not parsed.isValid():
                parsed = QDateTime.fromString(value, 'yyyy-MM-dd HH:mm:ss')
            editor.setDateTime(parsed if parsed.isValid() else editor.minimumDateTime())
        elif isinstance(editor, QComboBox):
            index = editor.findData(value)
            if index < 0 and value:
                editor.addItem(value, value)
                index = editor.count() - 1
            editor.setCurrentIndex(max(0, index))
        else:
            editor.setText(value)

    def _value(self, editor):
        if isinstance(editor, QDateTimeEdit):
            return '' if editor.dateTime() == editor.minimumDateTime() else editor.dateTime().toString('yyyy:MM:dd HH:mm:ss')
        if isinstance(editor, QComboBox):
            return editor.currentData() or ''
        return editor.text().strip()

    def _snapshot(self):
        return tuple((tag, check.isChecked(), self._value(editor))
                     for tag, (field, check, original, editor) in self._field_rows.items())

    def _populate(self):
        changes = self.overrides.get(metadata_key(self.current), {}) if self.current else {}
        for tag, (field, check, original, editor) in self._field_rows.items():
            self._set_value(editor, changes.get(tag, self.original.get(tag, '')))
            check.setChecked(tag in changes)
            editor.setEnabled(check.isChecked())
        self._baseline = self._snapshot()
        self.retranslate_ui()

    def _changes(self):
        values = {tag: self._value(editor) for tag, (field, check, original, editor) in self._field_rows.items() if check.isChecked()}
        return normalize_changes(values)

    def _checked_paths(self):
        return [self.photos.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.photos.count())
                if self.photos.item(i).checkState() == Qt.CheckState.Checked]

    def _select_all(self, state):
        for index in range(self.photos.count()):
            self.photos.item(index).setCheckState(state)

    def _set_status(self, source, **kwargs):
        self._last_error = None
        self._status = (source, kwargs)
        self.status_label.setText(tr(source, **kwargs))
        self.status_label.setToolTip('')

    def _show_error(self, error):
        self._last_error = error
        codes = {
            'tool_missing': '未找到 ExifTool，请将程序和运行文件放入 exiftool 文件夹', 'file_missing': '照片文件不存在',
            'unsupported_tag': '不支持此字段：{field}', 'invalid_value': '请检查字段格式：{field}',
            'invalid_date': '请填写有效日期：{field}', 'invalid_timezone': '时区格式应为 +08:00 或 -05:00',
            'invalid_gps': '请检查经纬度范围及半球方向', 'destination_exists': '目标文件已存在，请使用新文件名',
            'source_conflict': '副本不能与原照片或参考照片相同', 'write_failed': '照片副本写入失败',
            'no_changes': '请勾选并填写需要修改的字段',
        }
        tag = getattr(error, 'field', '')
        label = next((f.label for f in FIELDS if f.tag == tag), tag)
        source = codes.get(getattr(error, 'code', ''), '操作失败：{error}')
        self.status_label.setText(tr(source, field=tr(label), error=localize_error(error)))
        self.status_label.setToolTip(str(error))
        if tag in self._field_rows:
            field, check, original, editor = self._field_rows[tag]
            self.tabs.setCurrentIndex(self._tabs.index(field.group))
            editor.setFocus()

    def _set_busy(self, busy):
        self.current_combo.setEnabled(not busy)
        self.reference_button.setEnabled(not busy and self.current is not None)
        self.tabs.setEnabled(not busy and self._loaded)
        for button in (self.save_button, self.transfer_button, self.clear_button, self.apply_button):
            button.setEnabled(not busy and self._loaded)
        self.strip_maker.setEnabled(not busy)

    def _start(self, operation, callback, message, **kwargs):
        if self._job is not None:
            return
        self._set_status(message, **kwargs)
        self._set_busy(True)
        self._callback = callback
        self._job = _MetadataTask(operation, self)
        self._job.finished.connect(self._finish)
        self._job.start()

    def _finish(self):
        job = self._job
        callback = self._callback
        self._job = None
        self._callback = None
        if job.error is not None:
            self._show_error(job.error)
            # 写入失败时保留窗口以便查看错误或重新保存
            self._close_when_done = False
        else:
            callback(job.result)
        self._set_busy(False)
        job.deleteLater()
        if self._close_when_done:
            self._close_when_done = False
            self.close()

    def _load_current(self):
        path = self.current
        self._loaded = False
        self.original = {}
        self._populate()

        def ready(result):
            self.original = result
            self._loaded = True
            self._populate()
            self._set_status('已读取 {name}', name=path.name)

        self._start(lambda: read_metadata(path), ready, '正在读取 {name}…', name=path.name)

    def _discard_pending(self):
        if not self._baseline or self._snapshot() == self._baseline:
            return True
        return QMessageBox.question(self, tr('信息尚未应用'), tr('放弃尚未应用的字段修改？'),
                                    QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                    QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Discard

    def _switch_current(self, index):
        selected = self.current_combo.itemData(index)
        if selected == self.current or selected is None:
            return
        if not self._discard_pending():
            self.current_combo.blockSignals(True)
            self.current_combo.setCurrentIndex(self.paths.index(self.current))
            self.current_combo.blockSignals(False)
            return
        self.current = selected
        self._load_current()

    def _photo_file(self, title):
        path, _ = QFileDialog.getOpenFileName(self, tr(title), str(self.current.parent if self.current else Path.cwd()),
                                             tr('照片与 RAW 文件 ({extensions});;所有文件 (*)', extensions=PHOTO_EXTENSIONS),
                                             options=QFileDialog.Option.DontUseNativeDialog)
        return Path(path) if path else None

    def _load_reference(self):
        if self._job or not self._discard_pending():
            return
        path = self._photo_file('选择参考照片')
        if not path:
            return

        def ready(values):
            self.reference = path
            for tag, (field, check, original, editor) in self._field_rows.items():
                value = values.get(tag, '')
                self._set_value(editor, value)
                check.setChecked(bool(value))
            self.retranslate_ui()
            self._set_status('已从 {name} 加载 {count} 个字段，请检查后应用',
                             name=path.name, count=sum(bool(values.get(f.tag, '')) for f in FIELDS))

        self._start(lambda: read_metadata(path), ready, '正在读取参考照片 {name}…', name=path.name)

    def _apply(self):
        if self._job:
            return
        paths = self._checked_paths()
        if not paths:
            self._set_status('请至少勾选一张照片')
            return
        try:
            changes = self._changes()
        except Exception as exc:
            self._show_error(exc)
            return
        if not changes:
            self._set_status('请勾选并填写需要修改的字段')
            return
        for path in paths:
            self.overrides.setdefault(metadata_key(path), {}).update(changes)
        self._baseline = self._snapshot()
        self.applied.emit({key: dict(values) for key, values in self.overrides.items()})
        self._set_status('已向 {count} 张照片应用 {fields} 个字段', count=len(paths), fields=len(changes))

    def _clear_overrides(self):
        if self._job:
            return
        paths = self._checked_paths()
        if not paths:
            self._set_status('请至少勾选一张照片')
            return
        for path in paths:
            self.overrides.pop(metadata_key(path), None)
        self._populate()
        self.applied.emit({key: dict(values) for key, values in self.overrides.items()})
        self._set_status('已清除 {count} 张照片的水印修改', count=len(paths))

    def _destination(self, photo):
        suggested = photo.with_name(photo.stem + '_metadata' + photo.suffix)
        name, _ = QFileDialog.getSaveFileName(self, tr('保存照片副本'), str(suggested),
                                             tr('照片文件 (*{suffix});;所有文件 (*)', suffix=photo.suffix),
                                             options=QFileDialog.Option.DontUseNativeDialog | QFileDialog.Option.DontConfirmOverwrite)
        if not name:
            return None
        destination = Path(name)
        if not destination.suffix:
            destination = destination.with_suffix(photo.suffix)
        if destination.suffix.lower() != photo.suffix.lower():
            self._set_status('副本必须保留原照片的扩展名')
            return None
        return destination

    def _saved(self, path):
        self._set_status('副本已保存：{path}', path=str(path))

    def _save_copy(self):
        if self._job or not self.current:
            return
        try:
            changes = self._changes()
        except Exception as exc:
            self._show_error(exc)
            return
        if not changes:
            self._set_status('请勾选并填写需要修改的字段')
            return
        destination = self._destination(self.current)
        if destination:
            photo = self.current
            strip = self.strip_maker.isChecked()
            self._start(lambda: save_metadata_copy(photo, destination, changes, strip_maker_notes=strip),
                        self._saved, '正在保存副本…')

    def _transfer(self):
        if self._job or not self.current:
            return
        try:
            changes = self._changes()
        except Exception as exc:
            self._show_error(exc)
            return
        target = self._photo_file('选择接收 EXIF 的照片')
        if not target:
            return
        destination = self._destination(target)
        if destination:
            source = self.reference or self.current
            strip = self.strip_maker.isChecked()
            self._start(lambda: save_metadata_copy(target, destination, changes, source=source, strip_maker_notes=strip),
                        self._saved, '正在迁移 EXIF 到副本…')

    def retranslate_ui(self):
        self.setWindowTitle(tr('编辑照片信息'))
        for index, group in enumerate(self._tabs):
            self.tabs.setTabText(index, tr(group))
        for tag, (field, check, original, editor) in self._field_rows.items():
            value = self.original.get(tag, '')
            choices = dict(field.choices)
            original.setText(tr(choices[value]) if value in choices else str(value) if value else tr('未记录'))
            original.setToolTip(str(value))
            if isinstance(editor, QComboBox):
                editor.setItemText(0, tr('留空保留原值'))
                for index, (choice, label) in enumerate(field.choices, 1):
                    editor.setItemText(index, tr(label))
            elif isinstance(editor, QDateTimeEdit):
                editor.setLocale(QLocale(language()))
                editor.calendarWidget().setLocale(QLocale(language()))
        self.reference_label.setText(tr('参考照片：{name}', name=str(self.reference)) if self.reference else tr('参考照片：未选择'))
        if self._last_error is not None:
            self._show_error(self._last_error)
        else:
            source, kwargs = self._status
            self.status_label.setText(tr(source, **kwargs))

    def confirm_close(self):
        if self._job is not None:
            self._close_when_done = True
            self._set_status('任务完成后将关闭此窗口')
            return False
        return self._discard_pending()

    def closeEvent(self, event):
        if self.confirm_close():
            super().closeEvent(event)
        else:
            event.ignore()

    def reject(self):
        if self.confirm_close():
            super().reject()
