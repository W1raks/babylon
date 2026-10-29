"""Образцы для проверок и кадров: «фото» вывески кофейни с известными строками текста."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter

from babylon.ocr import Line
from babylon.ui import theme

LINES: list[Line] = []


def text(p, s, x, y, px, color, weight=QFont.Weight.Bold):
    f = QFont(theme.FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    p.setFont(f)
    p.setPen(QColor(color))
    fm = QFontMetricsF(f)
    p.drawText(int(x), int(y + fm.ascent()), s)
    LINES.append(Line(s, x, y + fm.ascent() - fm.capHeight() - 1, fm.horizontalAdvance(s), fm.capHeight() + fm.descent() + 2))


def photo() -> QImage:
    """«Фото» вывески кофейни: разные фоны и цвета букв."""
    img = QImage(1100, 720, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, 0, 720)
    g.setColorAt(0, QColor("#3b2a20"))
    g.setColorAt(1, QColor("#1d1410"))
    p.fillRect(img.rect(), g)
    for i in range(0, 1100, 22):  # доски
        p.fillRect(i, 0, 1, 720, QColor(0, 0, 0, 40))
    p.setBrush(QColor("#f3e6c8"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(80, 60, 940, 170), 18, 18)
    text(p, "COFFEE HOUSE", 250, 95, 92, "#5a2f17", QFont.Weight.Black)
    p.setBrush(QColor("#1f3b2f"))
    p.drawRoundedRect(QRectF(80, 270, 520, 380), 18, 18)
    text(p, "Cappuccino", 120, 310, 44, "#f6f1e6")
    text(p, "Hot chocolate", 120, 380, 44, "#f6f1e6")
    text(p, "Fresh pastries baked", 120, 480, 34, "#e8c27a", QFont.Weight.DemiBold)
    text(p, "every morning", 120, 522, 34, "#e8c27a", QFont.Weight.DemiBold)
    p.setBrush(QColor("#c0392b"))
    p.drawRoundedRect(QRectF(640, 300, 380, 200), 100, 100)
    text(p, "SALE -20%", 690, 368, 56, "#fff4e2", QFont.Weight.Black)
    p.setBrush(QColor("#f3e6c8"))
    p.drawRoundedRect(QRectF(640, 560, 380, 90), 14, 14)
    text(p, "Open daily 8am - 10pm", 668, 590, 30, "#3b2a20", QFont.Weight.DemiBold)
    p.end()
    return img


