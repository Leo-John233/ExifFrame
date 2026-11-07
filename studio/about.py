"""展示项目作者和引用"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.configs import load_project_info
from .i18n import bind, register_translations


register_translations({
    '关于': 'About',
    '版本 {version}': 'Version {version}',
    '版本未知': 'Version unavailable',
    '作者': 'Author',
    '项目引用': 'Project references',
    '基于': 'Based on',
    '照片信息功能参考': 'Photo information reference',
    'EXIF 读写工具': 'EXIF tool',
    '关闭': 'Close',
})


def _link(title: str, url: str) -> QLabel:
    label = QLabel(f'<a href="{url}">{title}</a>')
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(True)
    return label


class AboutDialog(QDialog):
    """显示作者、项目来源和工具信息"""

    def __init__(self, parent=None):
        super().__init__(parent)
        bind(self, '关于', 'setWindowTitle')
        self.setMinimumWidth(440)
        self.resize(500, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)
        title = QLabel('ExifFrame')
        title.setStyleSheet('font-size: 20px; font-weight: 600;')
        layout.addWidget(title)

        try:
            version = load_project_info()['project']['version']
            if not isinstance(version, str) or not version.strip():
                version = None
        except (OSError, ValueError, TypeError, KeyError):
            version = None
        details = QHBoxLayout()
        version_label = QLabel()
        version_label.setObjectName('secondaryText')
        if version:
            bind(version_label, '版本 {version}', version=version)
        else:
            bind(version_label, '版本未知')
        details.addWidget(version_label)
        license_label = QLabel('Apache License 2.0')
        license_label.setObjectName('secondaryText')
        details.addWidget(license_label)
        details.addStretch()
        layout.addLayout(details)

        layout.addSpacing(10)
        author_heading = bind(QLabel(), '作者')
        author_heading.setStyleSheet('font-weight: 600;')
        layout.addWidget(author_heading)
        layout.addWidget(_link('Leo-John233', 'https://github.com/Leo-John233'))

        layout.addSpacing(10)
        references_heading = bind(QLabel(), '项目引用')
        references_heading.setStyleSheet('font-weight: 600;')
        layout.addWidget(references_heading)
        references = QFormLayout()
        references.setHorizontalSpacing(12)
        references.setVerticalSpacing(8)
        references.addRow(bind(QLabel(), '基于'), _link('leslievan/semi-utils', 'https://github.com/leslievan/semi-utils'))
        references.addRow(bind(QLabel(), '照片信息功能参考'),
                          _link('Leo-John233/ExifEditor-GUI', 'https://github.com/Leo-John233/ExifEditor-GUI'))
        references.addRow(bind(QLabel(), 'EXIF 读写工具'), _link('ExifTool (Phil Harvey)', 'https://exiftool.org/'))
        layout.addLayout(references)
        layout.addStretch()
        close_button = bind(QPushButton(), '关闭')
        close_button.setAutoDefault(False)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
