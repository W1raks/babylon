"""Оформление «тёмное стекло»: размытый полупрозрачный фон, Inter, строчные подписи, красный акцент.

Поверхности — полупрозрачные слои белого поверх стекла, поэтому всё смотрится цельно
при любой плотности фона. Цвета задаются только здесь.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

from ..config import asset

GLASS = (16, 16, 19)                     # цвет стекла (плотность — из настроек)
SURFACE = "rgba(255,255,255,0.055)"      # карточки
SURFACE_2 = "rgba(255,255,255,0.09)"     # кнопки, поля
SURFACE_3 = "rgba(255,255,255,0.14)"     # наведение
LINE = "rgba(255,255,255,0.09)"
LINE_STRONG = "rgba(255,255,255,0.18)"
TEXT = "#f4f4f5"
MUTED = "#a1a1aa"   # на стекле нужен контраст выше, чем на чёрном
FAINT = "#71717a"
ACCENT = "#ff3b3b"
ACCENT_SOFT = "rgba(255,59,59,0.16)"
OK = "#4ade80"

FAMILY = "Inter"

# акцент можно сменить в настройках; везде в стилях он записан как #ff3b3b / 255,59,59 и подменяется
DEFAULT_ACCENT = ACCENT
ACCENTS = {"#ff3b3b": "красный", "#ff8a3d": "оранжевый", "#f5c542": "янтарный", "#4ade80": "зелёный",
           "#38bdf8": "голубой", "#8b5cf6": "фиолетовый", "#f472b6": "розовый"}


def _rgb(hexcolor: str) -> str:
    c = QColor(hexcolor)
    return f"{c.red()},{c.green()},{c.blue()}"


def set_accent(hexcolor: str):
    global ACCENT, ACCENT_SOFT
    if not QColor(hexcolor).isValid():
        hexcolor = DEFAULT_ACCENT
    ACCENT = hexcolor
    ACCENT_SOFT = f"rgba({_rgb(hexcolor)},0.16)"


def recolor(css: str) -> str:
    return css.replace(DEFAULT_ACCENT, ACCENT).replace("255,59,59", _rgb(ACCENT))


def accent(alpha: int = 255) -> QColor:
    c = QColor(ACCENT)
    c.setAlpha(alpha)
    return c


def load_fonts():
    global FAMILY
    fid = QFontDatabase.addApplicationFont(asset("Inter.ttf"))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    FAMILY = fams[0] if fams else "Segoe UI"
    return FAMILY


def font(size: float, weight=QFont.Weight.Normal) -> QFont:
    f = QFont(FAMILY)
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferVerticalHinting)
    return f


def glass_color(opacity_pct: int, blurred: bool) -> QColor:
    """Цвет фона окна. Без размытия (старая Windows, удалённый рабочий стол) делаем плотнее,
    иначе сквозь окно читается пёстрый фон и текст теряется."""
    a = max(40, min(100, opacity_pct))
    if not blurred:
        a = max(a, 94)
    return QColor(*GLASS, int(a * 2.55))


def logo(size: int) -> QPixmap:
    """Башня Вавилона с огнём на вершине; до 48 px — упрощённый рисунок."""
    from PySide6.QtSvg import QSvgRenderer

    r = QSvgRenderer(asset("babylon_small.svg" if size <= 48 else "babylon.svg"))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(logo(size))
    return icon


QSS = f"""
* {{ font-family: "{{FAMILY}}"; color: {TEXT}; }}
QToolTip {{ background: #202024; color: {TEXT}; border: 1px solid {LINE_STRONG}; padding: 6px 9px; border-radius: 8px; }}

QLabel[role="caption"] {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel[role="title"] {{ font-size: 18pt; font-weight: 800; letter-spacing: -0.5px; }}
QLabel[role="h2"] {{ font-size: 13pt; font-weight: 700; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="faint"] {{ color: {FAINT}; font-size: 8.5pt; }}
QLabel[role="error"] {{ color: {ACCENT}; }}
QLabel[role="badge"] {{ color: {MUTED}; background: {SURFACE_2}; border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }}
QLabel[role="badge-ok"] {{ color: {OK}; background: rgba(74,222,128,0.12); border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; font-weight: 600; }}

QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 18px; }}
QFrame[role="card"] QLabel {{ background: transparent; }}

QPushButton {{
  background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 16px;
  padding: 7px 15px; min-height: 18px; font-weight: 600;
}}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {LINE_STRONG}; }}
QPushButton:pressed {{ background: rgba(255,255,255,0.18); }}
QPushButton:disabled {{ color: {FAINT}; }}
QPushButton:focus {{ border-color: rgba(255,59,59,0.7); }}
QPushButton[kind="primary"] {{ background: #ffffff; color: #0a0a0a; border: none; }}
QPushButton[kind="primary"]:hover {{ background: #e8e8e8; }}
QPushButton[kind="primary"]:disabled {{ background: rgba(255,255,255,0.25); color: rgba(0,0,0,0.5); }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {MUTED}; padding: 6px 10px; }}
QPushButton[kind="ghost"]:hover {{ color: {TEXT}; background: {SURFACE_2}; }}
QPushButton[kind="icon"] {{ background: transparent; border: none; border-radius: 15px; padding: 0;
  min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }}
QPushButton[kind="icon"]:hover {{ background: {SURFACE_2}; }}
QPushButton[kind="icon"]:checked {{ background: {ACCENT_SOFT}; }}
QPushButton[kind="lang"] {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 14px; padding: 5px 12px; font-weight: 700; }}
QPushButton[kind="lang"]:hover {{ border-color: {LINE_STRONG}; }}
QPushButton[kind="lang"]:checked {{ background: {ACCENT_SOFT}; border-color: rgba(255,59,59,0.55); }}
QPushButton[kind="nav"] {{ background: transparent; border: none; border-radius: 12px; padding: 9px 12px;
  text-align: left; color: {MUTED}; font-weight: 600; }}
QPushButton[kind="nav"]:hover {{ color: {TEXT}; background: {SURFACE}; }}
QPushButton[kind="nav"]:checked {{ color: {TEXT}; background: {SURFACE_2}; }}

QPlainTextEdit, QTextEdit {{ background: transparent; border: none; padding: 2px;
  selection-background-color: {ACCENT}; selection-color: #ffffff; }}
QLineEdit {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 13px; padding: 7px 12px;
  selection-background-color: {ACCENT}; font-size: 10.5pt; }}
QLineEdit:focus {{ border-color: {LINE_STRONG}; }}

QComboBox {{ background: {SURFACE_2}; border: 1px solid {LINE}; border-radius: 15px; padding: 6px 32px 6px 14px;
  font-weight: 600; min-height: 18px; }}
QComboBox:hover {{ border-color: {LINE_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox::down-arrow {{ image: url("{{CHEVRON}}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: #1c1c20; border: 1px solid {LINE_STRONG}; border-radius: 10px; padding: 6px;
  selection-background-color: rgba(255,255,255,0.12); outline: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #ffffff; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }}

QProgressBar {{ background: {SURFACE_2}; border: none; border-radius: 3px; max-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: #ffffff; border-radius: 3px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.3); }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.18); border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}

QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 14px; padding: 10px 12px; margin: 0 0 6px 0; }}
QListWidget::item:hover {{ background: {SURFACE_2}; }}
QListWidget::item:selected {{ background: {SURFACE_2}; border-color: {LINE_STRONG}; color: {TEXT}; }}

QMenu {{ background: #1c1c20; border: 1px solid {LINE_STRONG}; border-radius: 12px; padding: 6px; }}
QMenu::item {{ padding: 8px 18px; border-radius: 8px; }}
QMenu::item:selected {{ background: rgba(255,255,255,0.1); }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 5px 8px; }}
QMessageBox {{ background: #18181b; }}
"""


def stylesheet() -> str:
    return recolor(QSS).replace("{FAMILY}", FAMILY).replace("{CHEVRON}", asset("chevron.svg").replace("\\", "/"))
