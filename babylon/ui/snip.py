"""Выделение области экрана мышью (по окну-затемнению на каждый монитор)."""
from PySide6.QtCore import QPoint, QRect, Qt, Signal, QObject
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class _Shade(QWidget):
    def __init__(self, owner, screen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.owner = owner
        self.scr = screen
        self.shot = screen.grabWindow(0)  # кадр экрана до появления затемнения
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.a = self.b = None

    def rect_sel(self) -> QRect:
        return QRect(self.a, self.b).normalized() if self.a and self.b else QRect()

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 140))
        r = self.rect_sel()
        if r.isValid():
            dpr = self.shot.devicePixelRatio()
            src = QRect(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr))
            p.drawPixmap(r, self.shot, src)
            p.setPen(QPen(QColor(theme.ACCENT), 1.5))
            p.drawRect(r.adjusted(0, 0, -1, -1))
            label = f"{src.width()} × {src.height()}"
            f = QFont(theme.FAMILY)
            f.setPointSizeF(9)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(label) + 16
            box = QRect(r.left(), r.top() - 26 if r.top() > 30 else r.bottom() + 6, w, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        else:
            hint = self.owner.hint
            f = QFont(theme.FAMILY)
            f.setPointSizeF(11)
            f.setWeight(QFont.Weight.DemiBold)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(hint) + 36
            box = QRect((self.width() - w) // 2, 40, w, 38)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(13, 13, 13, 235))
            p.drawRoundedRect(box, 19, 19)
            p.setPen(QColor(theme.TEXT))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, hint)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self.owner.cancel()
            return
        self.a = self.b = e.position().toPoint()
        self.update()

    def mouseMoveEvent(self, e):
        if self.a is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.b = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.a is None:
            return
        r = self.rect_sel()
        if r.width() < 6 or r.height() < 6:
            self.a = self.b = None
            self.update()
            return
        if self.owner.live:
            self.owner.done_region(QRect(self.mapToGlobal(r.topLeft()), r.size()), self.scr)
            return
        dpr = self.shot.devicePixelRatio()
        crop = self.shot.copy(QRect(int(r.x() * dpr), int(r.y() * dpr), int(r.width() * dpr), int(r.height() * dpr)))
        self.owner.done(crop.toImage(), self.mapToGlobal(r.bottomLeft()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.owner.cancel()


class Snipper(QObject):
    """captured(QImage, точка под областью) или cancelled(); для живых субтитров — region(область, экран)."""

    captured = Signal(QImage, QPoint)
    region = Signal(QRect, object)
    cancelled = Signal()

    HINT = "выделите область с текстом · esc отмена"
    LIVE_HINT = "выделите строку, где появляются субтитры · esc отмена"

    def __init__(self):
        super().__init__()
        self.shades: list[_Shade] = []
        self.live = False
        self.hint = self.HINT

    def start(self, live: bool = False):
        if self.shades:
            return
        self.live = live
        self.hint = self.LIVE_HINT if live else self.HINT
        self.shades = [_Shade(self, s) for s in QGuiApplication.screens()]
        for s in self.shades:
            s.show()
            s.raise_()
        under = QGuiApplication.screenAt(QCursor.pos())
        for s in self.shades:
            if s.scr is under:
                s.activateWindow()

    def _close(self):
        for s in self.shades:
            s.close()
            s.deleteLater()
        self.shades = []

    def done(self, img: QImage, at: QPoint):
        self._close()
        self.captured.emit(img, at)

    def done_region(self, rect: QRect, screen):
        self._close()
        self.region.emit(rect, screen)

    def cancel(self):
        self._close()
        self.cancelled.emit()
