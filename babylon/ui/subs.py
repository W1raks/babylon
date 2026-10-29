"""Окна живых субтитров: прозрачный слой с плашкой перевода и маленькая панель управления.

Слой пропускает мышь насквозь (видео можно ставить на паузу как обычно) и скрыт от снимков экрана,
поэтому плашка ложится прямо на оригинальные субтитры, а распознавание видит их под ней.
Если Windows не умеет скрывать окно от снимков (старше 10 версии 2004), плашка встаёт под областью.
"""
from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .. import lens, winapi
from ..langs import name
from ..ocr import Line
from . import glass, theme
from .widgets import GlassRoot, LangButton, btn

_TOP = (Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)


class SubsOverlay(QWidget):
    def __init__(self):
        super().__init__(None, _TOP | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.cover = False
        self.region = QRect()
        self.block = None
        self.out = ""
        self.alpha = 0.0
        self.flash = 0.0
        self._fade = QVariantAnimation(self, duration=90, startValue=0.0, endValue=1.0)
        self._fade.valueChanged.connect(lambda v: (setattr(self, "alpha", v), self.update()))
        self._flash = QVariantAnimation(self, duration=1400, startValue=1.0, endValue=0.0,
                                        easingCurve=QEasingCurve.Type.InQuad)
        self._flash.valueChanged.connect(lambda v: (setattr(self, "flash", v), self.update()))

    def place(self, region: QRect, screen):
        """Слой над полосой вокруг области (шире её: перевод бывает длиннее оригинала)."""
        self.region = QRect(region)
        sg = screen.geometry()
        self.show()
        hwnd = int(self.winId())
        winapi.click_through(hwnd)
        self.cover = winapi.exclude_from_capture(hwnd)
        pad = max(40, region.height())
        if self.cover:
            top, bottom = region.top() - pad, region.bottom() + pad
        else:  # не можем спрятаться от снимка — встаём под областью, чтобы не читать свой же перевод
            top, bottom = region.bottom() + 6, region.bottom() + 6 + max(120, region.height() * 2)
            if bottom > sg.bottom():
                top, bottom = region.top() - 6 - max(120, region.height() * 2), region.top() - 6
        top, bottom = max(sg.top(), top), min(sg.bottom(), bottom)
        self.setGeometry(QRect(sg.left(), top, sg.width(), bottom - top))
        self.block = None
        self.out = ""
        self._flash.start()

    def set_phrase(self, out: str, lines: list):
        if not lines:
            return
        o = self.geometry().topLeft()
        if self.cover:
            local = [Line(l.text, l.x - o.x(), l.y - o.y(), l.w, l.h) for l in lines]
        else:  # те же размеры, но строка — вверху/внизу слоя, по центру области
            lh = sorted(l.h for l in lines)[len(lines) // 2]
            cx = self.region.center().x() - o.x()
            y = 4 if self.geometry().top() > self.region.top() else self.height() - lh - 4
            local = [Line(lines[0].text, cx - 50, y, 100, lh)]
        b = lens.Block(local)
        b._fit()
        new = not self.out
        self.block, self.out = b, out
        if new:
            self._fade.start()
        else:
            self.update()  # смена фразы — мгновенно, без анимации: так быстрее

    def clear_phrase(self):
        self.out = ""
        self.block = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.flash > 0 and self.cover:
            r = QRectF(self.region.translated(-self.geometry().topLeft())).adjusted(-3, -3, 3, 3)
            p.setPen(QPen(theme.accent(int(230 * self.flash)), 2))
            p.drawRoundedRect(r, 10, 10)
        if self.block and self.out:
            p.setOpacity(self.alpha)
            lens._paint_plate(p, self.block, self.out, self.width(), self.height())


class LiveBar(GlassRoot):
    """Панель над областью: язык перевода, скорость, стоп."""

    stop = Signal()
    target_changed = Signal(str)

    def __init__(self, target: str, opacity: int):
        super().__init__(radius=17)
        self.setWindowFlags(_TOP | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.opacity = max(88, opacity)
        l = QHBoxLayout(self)
        l.setContentsMargins(12, 4, 4, 4)
        l.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {theme.ACCENT}; font-size: 9pt;")
        l.addWidget(dot)
        self.src_lbl = QLabel("субтитры")
        self.src_lbl.setStyleSheet("font-weight: 700;")
        l.addWidget(self.src_lbl)
        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: {theme.MUTED};")
        l.addWidget(arrow)
        self.tgt = LangButton(target)
        self.tgt.changed.connect(self.target_changed)
        l.addWidget(self.tgt)
        self.speed = QLabel("")
        self.speed.setProperty("role", "badge")
        self.speed.setMinimumWidth(54)
        self.speed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(self.speed)
        b = btn("", "icon", "close", theme.TEXT, "Остановить субтитры")
        b.clicked.connect(self.stop)
        l.addWidget(b)

    def place(self, region: QRect, screen):
        self.adjustSize()
        sg = screen.geometry()
        x = min(max(sg.left() + 4, region.right() - self.width()), sg.right() - self.width() - 4)
        y = region.top() - self.height() - 8
        if y < sg.top() + 4:
            y = region.bottom() + 8
        self.move(x, y)
        self.show()
        self.set_glass(self.opacity, glass.apply(self, popup=True))
        winapi.exclude_from_capture(int(self.winId()))
        self.src_lbl.setText("слушаю экран")
        self.speed.setText("")

    def set_lang(self, src: str):
        self.src_lbl.setText(name(src).lower() if src else "субтитры")
        self.adjustSize()

    def set_speed(self, ms: int, ocr_ms: int):
        self.speed.setText(f"{ms / 1000:.2f} с")
        self.speed.setToolTip(f"от появления фразы до перевода: {ms} мс (распознавание {ocr_ms} мс)")

    def set_status(self, text: str):
        self.src_lbl.setText(text)
        self.adjustSize()


# ---------------- субтитры из речи (звук компьютера или микрофон) ----------------
class SpeechOverlay(QWidget):
    """Полоса субтитров внизу (или вверху) экрана: перевод крупно, оригинал мелко над ним.
    Черновик (человек ещё говорит) — бледнее; через несколько секунд тишины полоса исчезает."""

    def __init__(self, settings):
        super().__init__(None, _TOP | Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.s = settings
        self.orig = self.out = ""
        self.draft = False
        self.alpha = 0.0
        self._fade = QVariantAnimation(self, duration=160, startValue=0.0, endValue=1.0)
        self._fade.valueChanged.connect(lambda v: (setattr(self, "alpha", v), self.update()))
        from PySide6.QtCore import QTimer

        self._hide = QTimer(self, singleShot=True, interval=7000)
        self._hide.timeout.connect(self._fade_out)

    def place(self, screen, offset=None):
        g = screen.availableGeometry()
        w = int(g.width() * 0.66)
        h = int(self.s.get("subs_size", 30) * 4.6)
        x = g.center().x() - w // 2
        y = g.top() + int(g.height() * 0.06) if self.s.get("subs_pos") == "top" else g.bottom() - h - int(g.height() * 0.07)
        if offset is not None:
            x, y = offset.x(), offset.y()
        self.setGeometry(x, y, w, h)
        self.show()
        winapi.click_through(int(self.winId()))

    def set_text(self, orig: str, out: str, draft: bool):
        self.orig, self.out, self.draft = orig, out or ("…" if draft else ""), draft
        if self.alpha < 0.99 or self._fade.direction() == QVariantAnimation.Direction.Backward:
            self._fade.setDirection(QVariantAnimation.Direction.Forward)
            self._fade.start()
        self._hide.start()
        self.update()

    def _fade_out(self):
        self._fade.setDirection(QVariantAnimation.Direction.Backward)
        self._fade.start()
        self._fade.finished.connect(self._clear_once)

    def _clear_once(self):
        self._fade.finished.disconnect(self._clear_once)
        if self._fade.direction() == QVariantAnimation.Direction.Backward:
            self.orig = self.out = ""
            self.update()

    def paintEvent(self, _):
        if not self.out and not self.orig:
            return
        from PySide6.QtGui import QFont, QFontMetricsF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(self.alpha)
        px = float(self.s.get("subs_size", 30))
        big = QFont(theme.FAMILY)
        big.setPixelSize(int(px))
        big.setWeight(QFont.Weight.DemiBold)
        small = QFont(theme.FAMILY)
        small.setPixelSize(int(px * 0.58))
        show_orig = self.s.get("subs_original", True) and self.orig
        flags = int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap)
        maxw = self.width() - px * 1.6
        fb, fs = QFontMetricsF(big), QFontMetricsF(small)
        rb = fb.boundingRect(QRectF(0, 0, maxw, 1e5), flags, self.out)
        rs = fs.boundingRect(QRectF(0, 0, maxw, 1e5), flags, self.orig) if show_orig else QRectF()
        w = max(rb.width(), rs.width()) + px * 1.4
        h = rb.height() + (rs.height() + px * 0.2 if show_orig else 0) + px * 0.7
        top = self.height() - h if self.s.get("subs_pos") != "top" else 0
        box = QRectF((self.width() - w) / 2, max(0, top), w, min(h, self.height()))
        path = QPainterPath()
        path.addRoundedRect(box, px * 0.45, px * 0.45)
        p.fillPath(path, QColor(12, 12, 14, int(2.55 * self.s.get("subs_opacity", 86))))
        y = box.top() + px * 0.35
        if show_orig:
            p.setFont(small)
            p.setPen(QColor(200, 200, 208))
            p.drawText(QRectF(box.left() + px * 0.7, y, w - px * 1.4, rs.height() + 2), flags, self.orig)
            y += rs.height() + px * 0.2
        p.setFont(big)
        p.setPen(QColor(248, 248, 250, 165 if self.draft else 255))
        p.drawText(QRectF(box.left() + px * 0.7, y, w - px * 1.4, rb.height() + 2), flags, self.out)


class HearBar(GlassRoot):
    """Панель субтитров речи: откуда звук, на какой язык, озвучка, окно разговора, стоп. Её можно таскать —
    вместе с ней двигаются и субтитры."""

    stop = Signal()
    target_changed = Signal(str)
    voice_toggled = Signal(bool)
    open_window = Signal()
    moved = Signal(QPointF)

    def __init__(self, target: str, opacity: int, voice: bool):
        super().__init__(radius=17)
        self.setWindowFlags(_TOP | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.opacity = max(88, opacity)
        self._drag = None
        self.lvl = 0.0
        l = QHBoxLayout(self)
        l.setContentsMargins(12, 4, 4, 4)
        l.setSpacing(8)
        self.dot = QLabel("●")
        l.addWidget(self.dot)
        self.src_lbl = QLabel("звук компьютера")
        self.src_lbl.setStyleSheet("font-weight: 700;")
        l.addWidget(self.src_lbl)
        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: {theme.MUTED};")
        l.addWidget(arrow)
        self.tgt = LangButton(target)
        self.tgt.changed.connect(self.target_changed)
        l.addWidget(self.tgt)
        self.b_voice = btn("", "icon", "speaker", theme.TEXT, "Озвучивать перевод голосом")
        self.b_voice.setCheckable(True)
        self.b_voice.setChecked(voice)
        self.b_voice.toggled.connect(self.voice_toggled)
        l.addWidget(self.b_voice)
        b = btn("", "icon", "expand", theme.TEXT, "Открыть разговор целиком")
        b.clicked.connect(self.open_window)
        l.addWidget(b)
        b = btn("", "icon", "close", theme.TEXT, "Остановить")
        b.clicked.connect(self.stop)
        l.addWidget(b)
        self.set_level(0)

    def set_level(self, v: float):
        a = 0.35 + 0.65 * min(1.0, v * 1.6)
        c = theme.accent()
        self.dot.setStyleSheet(f"color: rgba({c.red()},{c.green()},{c.blue()},{a:.2f}); font-size: 9pt;")

    def set_source(self, text: str):
        self.src_lbl.setText(text)
        self.adjustSize()

    def place_near(self, overlay: QWidget):
        self.adjustSize()
        g = overlay.geometry()
        self.move(g.right() - self.width(), g.top() - self.height() - 6)
        self.show()
        self.set_glass(self.opacity, glass.apply(self, popup=True))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            new = e.globalPosition() - self._drag
            delta = new - QPointF(self.pos())
            self.move(new.toPoint())
            self.moved.emit(delta)

    def mouseReleaseEvent(self, e):
        self._drag = None
