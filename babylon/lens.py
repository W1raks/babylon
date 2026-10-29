"""Перевод поверх картинки, как в Google Объективе: строки → блоки → перевод рисуется на месте текста.

Здесь только раскладка и рисование (без OCR и сети), поэтому всё проверяется тестами на любой ОС.
Стили: «photo» — закрашиваем текст цветом фона и пишем перевод цветом букв;
«subs» — тёмная плашка с белым текстом (для видео и живых субтитров).
"""
import difflib
import re
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen

from .ocr import Line
from .ui import theme


@dataclass
class Block:
    """Абзац на картинке: соседние строки одного размера."""

    lines: list = field(default_factory=list)
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    centered: bool = False

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    @property
    def line_h(self) -> float:
        hs = sorted(ln.h for ln in self.lines)
        return hs[len(hs) // 2] if hs else 0

    def rect(self) -> QRectF:
        return QRectF(self.x, self.y, self.w, self.h)

    def _fit(self):
        self.x = min(ln.x for ln in self.lines)
        self.y = min(ln.y for ln in self.lines)
        self.w = max(ln.x + ln.w for ln in self.lines) - self.x
        self.h = max(ln.y + ln.h for ln in self.lines) - self.y
        if len(self.lines) > 1:
            lefts = [ln.x for ln in self.lines]
            mids = [ln.x + ln.w / 2 for ln in self.lines]
            self.centered = (max(mids) - min(mids)) < (max(lefts) - min(lefts)) * 0.6

    def scaled(self, k: float) -> "Block":
        b = Block([Line(ln.text, ln.x * k, ln.y * k, ln.w * k, ln.h * k) for ln in self.lines])
        b._fit()
        b.centered = self.centered
        return b


def group(lines: list[Line]) -> list[Block]:
    """Склеить строки в абзацы: близко по вертикали, похожая высота, пересекаются по горизонтали."""
    blocks: list[Block] = []
    for ln in sorted((l for l in lines if l.text.strip()), key=lambda l: (l.y, l.x)):
        best = None
        for b in blocks:
            lh = max(b.line_h, ln.h)
            gap = ln.y - (b.y + b.h)
            if not (-0.5 * lh < gap < 0.9 * lh):
                continue
            if not (0.6 < ln.h / max(b.line_h, 1) < 1.6):
                continue
            overlap = min(b.x + b.w, ln.x + ln.w) - max(b.x, ln.x)
            if overlap < -0.5 * lh:
                continue
            if _list_item(b.lines[-1].text, ln.text):
                continue
            best = b
        if best is None:
            best = Block()
            blocks.append(best)
        best.lines.append(ln)
        best._fit()
    return blocks


def _list_item(prev: str, new: str) -> bool:
    """Строки меню или списка («Cappuccino», «Hot chocolate») — отдельные надписи, а не абзац:
    короткая предыдущая строка без запятой/дефиса в конце и новая строка с заглавной буквы."""
    first = next((c for c in new if c.isalpha()), "")
    prev = prev.strip()
    return bool(first) and first.isupper() and len(prev.split()) <= 3 and not prev.endswith((",", "-", "—", ":"))


# ---------------- сходство текстов (для субтитров и видео) ----------------
_NORM = re.compile(r"[\W_]+", re.UNICODE)


def norm(text: str) -> str:
    return _NORM.sub(" ", text.lower()).strip()


def similar(a: str, b: str) -> float:
    """0..1: насколько два распознанных текста — одна и та же надпись (OCR чуть ошибается от кадра к кадру)."""
    a, b = norm(a), norm(b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


# ---------------- цвета ----------------
def as_array(img: QImage) -> np.ndarray:
    """Пиксели картинки как массив H×W×4 (B, G, R, A) без копирования."""
    if img.format() != QImage.Format.Format_ARGB32:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, count=img.bytesPerLine() * img.height())
    return arr.reshape(img.height(), img.bytesPerLine() // 4, 4)[:, : img.width(), :]


def _lum(c) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def colors(arr: np.ndarray, r: QRectF) -> tuple[QColor, QColor]:
    """(фон, буквы) у текста в рамке r: фон — по кольцу вокруг рамки, буквы — самые непохожие на фон пиксели."""
    H, W = arr.shape[:2]
    pad = max(2, int(r.height() * 0.12))
    x0, y0 = max(0, int(r.left()) - pad), max(0, int(r.top()) - pad)
    x1, y1 = min(W, int(r.right()) + pad + 1), min(H, int(r.bottom()) + pad + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return QColor(255, 255, 255), QColor(0, 0, 0)
    box = arr[y0:y1, x0:x1, :3].astype(np.int16)
    ring = np.concatenate([box[:2].reshape(-1, 3), box[-2:].reshape(-1, 3),
                           box[:, :2].reshape(-1, 3), box[:, -2:].reshape(-1, 3)])
    bg = np.median(ring, axis=0)
    inner = box[pad:-pad or None, pad:-pad or None].reshape(-1, 3)
    if len(inner) == 0:
        inner = box.reshape(-1, 3)
    dist = np.abs(inner - bg).sum(axis=1)
    far = inner[dist >= np.percentile(dist, 88)]
    fg = np.median(far, axis=0) if len(far) else 255 - bg
    bgc = QColor(int(bg[2]), int(bg[1]), int(bg[0]))  # в массиве B, G, R
    fgc = QColor(int(fg[2]), int(fg[1]), int(fg[0]))
    if abs(_lum((bgc.red(), bgc.green(), bgc.blue())) - _lum((fgc.red(), fgc.green(), fgc.blue()))) < 90:
        fgc = QColor(20, 20, 20) if _lum((bgc.red(), bgc.green(), bgc.blue())) > 128 else QColor(250, 250, 250)
    return bgc, fgc


# ---------------- рисование ----------------
def _font(px: float, weight=QFont.Weight.DemiBold) -> QFont:
    f = QFont(theme.FAMILY)
    f.setPixelSize(max(6, int(round(px))))
    f.setWeight(weight)
    return f


def fit_font(text: str, width: float, height: float, start_px: float, min_px: float = 9,
             weight=QFont.Weight.DemiBold, align=Qt.AlignmentFlag.AlignLeft) -> tuple[QFont, float]:
    """Самый крупный шрифт (не больше start_px), которым текст влезает в width×height с переносами."""
    px = start_px
    flags = int(align) | int(Qt.TextFlag.TextWordWrap)
    while True:
        f = _font(px, weight)
        h = QFontMetricsF(f).boundingRect(QRectF(0, 0, width, 1e6), flags, text).height()
        if h <= height or px <= min_px:
            return f, h
        px = max(min_px, px * 0.92)


def paint(img: QImage, blocks: list[Block], outs: list[str], style: str = "photo") -> QImage:
    """Новая картинка: переводы outs нарисованы на месте блоков."""
    res = img.convertToFormat(QImage.Format.Format_ARGB32)
    arr = as_array(res).copy() if style == "photo" else None  # цвета берём с оригинала
    p = QPainter(res)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    W, H = res.width(), res.height()
    for b, out in zip(blocks, outs):
        out = (out or "").strip()
        if not out:
            continue
        lh = max(b.line_h, 8)
        if style == "subs":
            _paint_plate(p, b, out, W, H)
            continue
        bg, fg = colors(arr, b.rect())
        pad = lh * 0.14
        r = b.rect().adjusted(-pad, -pad, pad, pad)
        align = Qt.AlignmentFlag.AlignHCenter if b.centered else Qt.AlignmentFlag.AlignLeft
        f, th = fit_font(out, r.width(), r.height() * 1.08, lh * 0.92, align=align)
        if th > r.height():  # даже мелким не влезло — расширяем закраску вниз
            r.setHeight(min(H - r.top(), th + pad))
        path = QPainterPath()
        path.addRoundedRect(r, lh * 0.18, lh * 0.18)
        p.fillPath(path, bg)
        p.setPen(fg)
        p.setFont(f)
        p.drawText(r.adjusted(0, (r.height() - th) / 2 if th < r.height() else 0, 0, 0),
                   int(align | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap), out)
    p.end()
    return res


def plate_geometry(b: Block, out: str, W: float, H: float) -> tuple[QRectF, QFont, float]:
    """Где рисовать плашку субтитра: по центру исходной надписи, шире неё, если перевод длиннее."""
    lh = max(b.line_h, 10)
    px = min(max(lh * 0.95, 14), 64)
    max_w = W * 0.92
    f = _font(px)
    fm = QFontMetricsF(f)
    flags = int(Qt.AlignmentFlag.AlignHCenter) | int(Qt.TextFlag.TextWordWrap)
    want_w = min(max_w, max(b.w, fm.horizontalAdvance(out) + 2) + px * 0.2)
    text_h = fm.boundingRect(QRectF(0, 0, want_w, 1e6), flags, out).height()
    padx, pady = px * 0.55, px * 0.28
    w, h = want_w + 2 * padx, max(text_h + 2 * pady, b.h + 2 * pady)
    cx, cy = b.x + b.w / 2, b.y + b.h / 2
    x = min(max(cx - w / 2, 0), max(0, W - w))
    y = min(max(cy - h / 2, 0), max(0, H - h))
    return QRectF(x, y, w, h), f, px


def _paint_plate(p: QPainter, b: Block, out: str, W: float, H: float):
    r, f, px = plate_geometry(b, out, W, H)
    path = QPainterPath()
    path.addRoundedRect(r, px * 0.42, px * 0.42)
    p.fillPath(path, QColor(12, 12, 14, 250))  # почти непрозрачно: оригинал не просвечивает
    p.setPen(QPen(QColor(255, 255, 255, 30), 1))
    p.drawPath(path)
    p.setFont(f)
    p.setPen(QColor(248, 248, 250))
    p.drawText(r, int(Qt.AlignmentFlag.AlignCenter) | int(Qt.TextFlag.TextWordWrap), out)
