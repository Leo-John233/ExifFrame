"""启动画面及真实工作台就绪后的平滑交接"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path

from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QIcon, QImage, QImageReader,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from core.runtime_paths import resource_path
from .i18n import tr, translator


_CARD_WIDTH = 640
_CARD_HEIGHT = 380
_SHADOW = 18
_FADE_MS = 200


def _color(value, alpha=255):
    color = QColor(value)
    color.setAlpha(max(0, min(255, round(alpha))))
    return color


def _version():
    try:
        import tomllib
        with resource_path('pyproject.toml').open('rb') as stream:
            value = tomllib.load(stream).get('project', {}).get('version')
        return value.strip() if isinstance(value, str) and value.strip() else ''
    except (OSError, ValueError, TypeError):
        return ''


def _read_background(path):
    """在解码时限制分辨率并按 EXIF 方向读取自定义图片"""
    if not path:
        return QImage()
    try:
        if Path(path).stat().st_size > 32 * 1024 * 1024:
            return QImage()
    except OSError:
        return QImage()
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.isEmpty() or size.width() * size.height() > 40_000_000:
        return QImage()
    if max(size.width(), size.height()) > 1920:
        reader.setScaledSize(size.scaled(QSize(1920, 1920), Qt.AspectRatioMode.KeepAspectRatio))
    return reader.read()


def _cover(painter, image, rect):
    """完整覆盖卡片，裁掉超出区域而不拉伸"""
    image_ratio = image.width() / image.height()
    target_ratio = rect.width() / rect.height()
    if image_ratio > target_ratio:
        width = image.height() * target_ratio
        source = QRectF((image.width() - width) / 2, 0, width, image.height())
    else:
        height = image.width() / target_ratio
        source = QRectF(0, (image.height() - height) / 2, image.width(), height)
    painter.drawImage(rect, image, source)


def _ensure_fonts():
    """主题加载之前补足无窗口环境中缺失的系统字体"""
    if os.name != 'nt':
        return
    families = {name.casefold() for name in QFontDatabase.families()}
    fonts = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts'
    for family, names in (('segoe ui', ('segoeui.ttf', 'segoeuib.ttf')),
                          ('microsoft yahei ui', ('msyh.ttc', 'msyhbd.ttc')),
                          ('segoe ui symbol', ('seguisym.ttf',)), ('cambria math', ('cambria.ttc',))):
        if family not in families:
            for name in names:
                if (fonts / name).is_file():
                    QFontDatabase.addApplicationFont(str(fonts / name))


def _font(size, *, weight=QFont.Weight.Normal, spacing=None):
    font = QFont('Segoe UI')
    font.setFamilies(['Segoe UI', 'Microsoft YaHei UI', 'Segoe UI Symbol', 'Cambria Math'])
    font.setPixelSize(size)
    font.setWeight(weight)
    if spacing is not None:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


class SplashScreen(QWidget):
    """无边框启动卡片，只有真实阶段推进时才增长进度"""

    finished = Signal()

    def __init__(self, settings, *, theme='dark', version=None, parent=None):
        super().__init__(parent, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName('startupSplash')
        _ensure_fonts()
        self.setWindowTitle('ExifFrame')
        self._settings = settings
        self._theme = 'light' if theme == 'light' else 'dark'
        self._version = _version() if version is None else str(version or '')
        self._mode = getattr(settings, 'background_mode', 'follow')
        if self._mode not in ('follow', 'photo', 'custom'):
            self._mode = 'follow'
        try:
            self._mask = max(0, min(100, int(getattr(settings, 'overlay_opacity', 40)))) / 100
        except (TypeError, ValueError):
            self._mask = .4
        self._show_version = bool(getattr(settings, 'show_version', True))
        self._show_status = bool(getattr(settings, 'show_status', True))
        try:
            self._minimum_ms = max(0, min(15000, int(getattr(settings, 'minimum_ms', 800))))
        except (TypeError, ValueError):
            self._minimum_ms = 800
        self._progress = 0.0
        self._target = 0.0
        self._status = '正在启动…'
        self._started_at = None
        self._finishing = False
        self._cancelled = False
        self._minimum_ready = False
        self._main_painted = False
        self._fade_started = False
        self._main_window = None
        self._after_finish = None
        self._delete_on_finish = False
        self._background = QImage()
        self._background_key = None
        self._photographic = False
        self._icon = QIcon(str(resource_path('static/logo.ico')))
        self._progress_animation = QVariantAnimation(self)
        self._progress_animation.setDuration(180)
        self._progress_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._progress_animation.valueChanged.connect(self._set_progress)
        self._fade = QPropertyAnimation(self, b'windowOpacity', self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._fade.finished.connect(self._closed_after_fade)
        self._minimum_timer = QTimer(self)
        self._minimum_timer.setSingleShot(True)
        self._minimum_timer.timeout.connect(self._minimum_elapsed)
        translator.language_changed.connect(self.update)
        self._fit_to_screen(parent)

    def _fit_to_screen(self, parent):
        if parent is not None:
            screen = parent.screen() or QGuiApplication.primaryScreen()
        else:
            from .path_memory import workspace_preferences
            try:
                name = workspace_preferences().value('window/screen', '', type=str)
            except (OSError, RuntimeError, TypeError):
                name = ''
            screen = next((item for item in QGuiApplication.screens() if item.name() == name), None)
            screen = screen or QGuiApplication.primaryScreen()
        total_width, total_height = _CARD_WIDTH + _SHADOW * 2, _CARD_HEIGHT + _SHADOW * 2
        if screen is None:
            self.resize(total_width, total_height)
            return
        available = screen.availableGeometry()
        scale = max(.1, min(1.0, (available.width() - 16) / total_width,
                            (available.height() - 16) / total_height))
        self.resize(round(total_width * scale), round(total_height * scale))
        center = available.center()
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if self._started_at is None:
            self._started_at = time.monotonic()

    def set_stage(self, status, progress):
        """接收已经完成的启动阶段，进度范围为 0 到 1"""
        if self._cancelled:
            return
        self._status = str(status)
        try:
            target = float(progress)
            if not math.isfinite(target):
                target = self._target
        except (ValueError, TypeError):
            target = self._target
        target = max(self._target, max(0.0, min(1.0, target)))
        self._target = target
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self._progress)
        self._progress_animation.setEndValue(target)
        self._progress_animation.start()
        self.update()

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    def finish(self, window=None, on_finished=None):
        """等待首帧和最短时长后淡出，最终激活已呈现的主窗口"""
        if self._finishing or self._cancelled:
            return
        self._finishing = True
        self._main_window, self._after_finish = window, on_finished
        self.set_stage('准备就绪', 1.0)
        elapsed = (time.monotonic() - self._started_at) * 1000 if self._started_at is not None else 0
        remaining = max(0, math.ceil(self._minimum_ms - elapsed))
        if remaining:
            self._minimum_timer.start(remaining)
        else:
            self._minimum_ready = True
        if window is None:
            self._main_painted = True
            self._try_fade()
        else:
            from .window_presentation import present_window
            present_window(window, self._window_painted)

    def _window_painted(self):
        if self._cancelled:
            return
        self._main_painted = True
        if self.isVisible():
            self.raise_()
        self._try_fade()

    def _minimum_elapsed(self):
        self._minimum_ready = True
        self._try_fade()

    def _try_fade(self):
        if self._cancelled or self._fade_started or not self._minimum_ready or not self._main_painted:
            return
        self._fade_started = True
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _closed_after_fade(self):
        if self._cancelled:
            return
        self.hide()
        window = self._main_window
        if window is not None:
            window.raise_()
            window.activateWindow()
        self.finished.emit()
        if self._after_finish is not None:
            self._after_finish()
        if self._delete_on_finish:
            self.deleteLater()

    def abort(self):
        """启动失败时立即撤销定时器和动画"""
        self._cancelled = True
        self._minimum_timer.stop()
        self._progress_animation.stop()
        self._fade.stop()
        self.hide()

    def _image_path(self):
        if self._mode == 'photo':
            return resource_path('static/preview.jpg')
        if self._mode == 'custom':
            try:
                from core.splash_settings import resolve_splash_image
                return resolve_splash_image(getattr(self._settings, 'image_path', ''))
            except (OSError, ValueError, TypeError, ImportError):
                return None
        return None

    def _background_image(self):
        ratio = max(1.0, self.devicePixelRatioF())
        path = self._image_path()
        try:
            info = Path(path).stat() if path else None
            version = (str(path), info.st_mtime_ns, info.st_size) if info else None
        except OSError:
            version = None
        key = (self._mode, self._theme, self._mask, round(ratio, 3), version)
        if key == self._background_key and not self._background.isNull():
            return self._background
        image = QImage(round(_CARD_WIDTH * ratio), round(_CARD_HEIGHT * ratio), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, _CARD_WIDTH, _CARD_HEIGHT)
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        photo = _read_background(path)
        self._photographic = not photo.isNull()
        if self._photographic:
            _cover(painter, photo, rect)
            self._draw_photo_mask(painter, rect)
        else:
            self._draw_darkroom(painter, rect, light=self._theme == 'light')
            self._draw_darkroom_mask(painter, rect, light=self._theme == 'light')
        painter.end()
        self._background_key, self._background = key, image
        return image

    def _draw_photo_mask(self, painter, rect):
        # 可调暗度之上保留最低对比度，浅色照片上也能读清标题和状态
        overlay = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        overlay.setColorAt(0.0, _color('#080B10', 35 + 28 * self._mask))
        overlay.setColorAt(.35, _color('#080B10', 45 + 38 * self._mask))
        overlay.setColorAt(.72, _color('#080B10', 165 + 45 * self._mask))
        overlay.setColorAt(1.0, _color('#080B10', 200 + 42 * self._mask))
        painter.fillRect(rect, overlay)
        side = QLinearGradient(rect.topLeft(), rect.topRight())
        side.setColorAt(0, _color('#080B10', 188 + 34 * self._mask))
        side.setColorAt(.48, _color('#080B10', 132 + 28 * self._mask))
        side.setColorAt(.76, _color('#080B10', 32 + 16 * self._mask))
        side.setColorAt(1, _color('#080B10', 0))
        painter.fillRect(rect, side)

    def _draw_darkroom_mask(self, painter, rect, *, light):
        overlay = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        overlay.setColorAt(0, _color('#080B10', 0))
        overlay.setColorAt(.52, _color('#080B10', 0))
        overlay.setColorAt(1, _color('#080B10', (72 if light else 130) * self._mask))
        painter.fillRect(rect, overlay)

    @staticmethod
    def _draw_darkroom(painter, rect, *, light):
        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if light:
            base.setColorAt(0, QColor('#F1F0EC'))
            base.setColorAt(.55, QColor('#DCDDD9'))
            base.setColorAt(1, QColor('#B5BFC0'))
            rim, warm = '#56676C', '#8E6E50'
        else:
            base.setColorAt(0, QColor('#0E151A'))
            base.setColorAt(.55, QColor('#1B252B'))
            base.setColorAt(1, QColor('#303439'))
            rim, warm = '#91A9AA', '#D7AC7D'
        painter.fillRect(rect, base)
        center = QPointF(488, 167)
        halo = QRadialGradient(center, 244)
        halo.setColorAt(0, _color('#728E91' if not light else '#789296', 58 if not light else 38))
        halo.setColorAt(.58, _color(warm, 28 if not light else 18))
        halo.setColorAt(1, _color(warm, 0))
        painter.fillRect(rect, halo)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for radius, alpha, width in ((220, 20, 1), (204, 33, 1), (193, 45, 2), (178, 60, 1),
                                     (166, 34, 8), (153, 55, 1), (142, 35, 2), (127, 30, 1), (106, 32, 1)):
            painter.setPen(QPen(_color(rim, alpha), width))
            painter.drawEllipse(center, radius, radius)
        # 光圈叶片与细刻度压低对比度，让文案保持视觉主次
        painter.save()
        lens_clip = QPainterPath()
        lens_clip.addEllipse(center, 145, 145)
        painter.setClipPath(lens_clip, Qt.ClipOperation.IntersectClip)
        for index in range(7):
            angle = math.tau * index / 7 - .28
            def point(radius, turn=0):
                return QPointF(center.x() + radius * math.cos(angle + turn),
                               center.y() + radius * math.sin(angle + turn))
            blade = QPolygonF([point(57, .04), point(145, -.12), point(150, .82), point(57, .94)])
            painter.setPen(QPen(_color(rim, 53 if light else 64), .9))
            painter.setBrush(_color('#71898C' if light else '#A6C0BD',
                                    (44 if index % 2 else 57) if light else (29 if index % 2 else 43)))
            painter.drawPolygon(blade)
        painter.restore()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for tick in range(52):
            angle = math.tau * tick / 52
            start = 186 if tick % 4 else 182
            painter.setPen(QPen(_color(rim, 37 if tick % 4 else 73), 1))
            painter.drawLine(QPointF(center.x() + start * math.cos(angle), center.y() + start * math.sin(angle)),
                             QPointF(center.x() + 195 * math.cos(angle), center.y() + 195 * math.sin(angle)))
        veil = QLinearGradient(rect.topLeft(), rect.topRight())
        veil.setColorAt(0, _color('#FFFFFF' if light else '#0A1014', 96 if light else 112))
        veil.setColorAt(.54, _color('#FFFFFF' if light else '#0A1014', 20 if light else 30))
        veil.setColorAt(1, _color('#FFFFFF' if light else '#0A1014', 0))
        painter.fillRect(rect, veil)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        scale = min(self.width() / (_CARD_WIDTH + _SHADOW * 2), self.height() / (_CARD_HEIGHT + _SHADOW * 2))
        painter.translate((self.width() - (_CARD_WIDTH + _SHADOW * 2) * scale) / 2,
                          (self.height() - (_CARD_HEIGHT + _SHADOW * 2) * scale) / 2)
        painter.scale(scale, scale)
        card = QRectF(_SHADOW, _SHADOW, _CARD_WIDTH, _CARD_HEIGHT)
        for spread in range(14, 0, -1):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color('#000000', 3 + (14 - spread) * .85))
            painter.drawRoundedRect(card.adjusted(-spread, -spread + 3, spread, spread + 3), 13 + spread, 13 + spread)
        painter.drawImage(card, self._background_image())
        border = '#FFFFFF' if self._photographic or self._theme == 'dark' else '#1E2A2C'
        painter.setPen(QPen(_color(border, 38 if border == '#FFFFFF' else 28), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(.5, .5, -.5, -.5), 12, 12)
        painter.save()
        painter.translate(card.topLeft())
        self._draw_foreground(painter)
        painter.restore()

    def _draw_foreground(self, painter):
        light_text = self._photographic or self._theme != 'light'
        primary = QColor('#F7F8F7' if light_text else '#202A2C')
        secondary = QColor('#D3D9D9' if light_text else '#4E5C5E')
        muted = QColor('#A7B2B2' if light_text else '#3F5154')
        if not self._icon.isNull():
            pixmap = self._icon.pixmap(QSize(96, 96))
            painter.drawPixmap(QRectF(40, 37, 42, 42), pixmap, QRectF(pixmap.rect()))
        painter.setPen(primary)
        painter.setFont(_font(28, weight=QFont.Weight.DemiBold, spacing=.1))
        painter.drawText(QRectF(95, 36, 310, 39), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, 'ExifFrame')
        if self._show_version and self._version:
            painter.setFont(_font(10, weight=QFont.Weight.DemiBold))
            label = 'v' + self._version
            width = painter.fontMetrics().horizontalAdvance(label) + 16
            title_width = QFontMetricsF(_font(28, weight=QFont.Weight.DemiBold, spacing=.1)).horizontalAdvance('ExifFrame')
            capsule = QRectF(95 + title_width + 13, 46, width, 21)
            painter.setPen(QPen(_color('#FFFFFF' if light_text else '#3B4D50', 65), 1))
            painter.setBrush(_color('#0B1117', 155) if self._photographic else
                             _color('#FFFFFF' if light_text else '#566C6F', 20))
            painter.drawRoundedRect(capsule, 10, 10)
            painter.setPen(secondary)
            painter.drawText(capsule, Qt.AlignmentFlag.AlignCenter, label)
        painter.setPen(secondary)
        painter.setFont(_font(14))
        painter.drawText(QRectF(40, 101, 440, 28), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         tr('摄影水印与 EXIF 工作台'))
        if self._show_status:
            painter.setFont(_font(12))
            painter.setPen(secondary)
            text = painter.fontMetrics().elidedText(tr(self._status), Qt.TextElideMode.ElideRight, 460)
            painter.drawText(QRectF(40, 303, 470, 21), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            painter.setPen(secondary if self._photographic else muted)
            painter.drawText(QRectF(535, 303, 65, 21), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f'{round(self._progress * 100)}%')
        track = QRectF(40, 337, 560, 2.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color('#FFFFFF' if light_text else '#374B4E', 58 if light_text else 62))
        painter.drawRoundedRect(track, 1.2, 1.2)
        if self._progress > 0:
            fill = QRectF(track.x(), track.y(), track.width() * self._progress, track.height())
            painter.setBrush(QColor('#E4E9E6' if light_text else '#34494B'))
            painter.drawRoundedRect(fill, 1.2, 1.2)



def preview_splash(settings, parent=None):
    """用设置页的未保存参数播放一次完整预览"""
    from .theme import theme
    owner = parent or QApplication.instance()
    previous = getattr(owner, '_active_splash_preview', None)
    if previous is not None:
        try:
            previous.abort()
            previous.deleteLater()
        except RuntimeError:
            pass
    splash = SplashScreen(settings, theme=theme(), parent=parent)
    owner._active_splash_preview = splash
    def release():
        if getattr(owner, '_active_splash_preview', None) is splash:
            owner._active_splash_preview = None
    splash.finished.connect(release)
    splash._delete_on_finish = True
    splash.setWindowOpacity(0.0)
    splash.show()
    splash.raise_()
    splash._fade_in = QPropertyAnimation(splash, b'windowOpacity', splash)
    splash._fade_in.setDuration(_FADE_MS)
    splash._fade_in.setEasingCurve(QEasingCurve.Type.InOutCubic)
    splash._fade_in.setStartValue(0.0)
    splash._fade_in.setEndValue(1.0)
    splash._fade_in.start()
    splash.set_stage('正在加载主题与字体…', .12)
    QTimer.singleShot(260, splash, lambda: splash.set_stage('正在初始化 EXIF 引擎…', .42))
    QTimer.singleShot(560, splash, lambda: splash.set_stage('正在构建工作台…', .72))
    QTimer.singleShot(950, splash, lambda: splash.finish())
    return splash
