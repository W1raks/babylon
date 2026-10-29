"""Всплывающая карточка с переводом рядом с курсором: стекло, словарь для слов, озвучка, словарик."""
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..langs import LANGS, name
from . import glass, theme
from .icons import icon
from .widgets import GlassRoot, LangButton, btn, repolish

QSS = f"""
QLabel#src {{ color: {theme.MUTED}; }}
QLabel#translit {{ color: {theme.FAINT}; font-size: 9pt; }}
QLabel#out[state="note"] {{ color: {theme.MUTED}; }}
QLabel#pos {{ color: {theme.ACCENT}; font-size: 8.5pt; font-weight: 700; }}
QLabel#terms {{ color: {theme.TEXT}; font-size: 10pt; }}
QLabel#example {{ color: {theme.MUTED}; font-size: 9.5pt; font-style: italic; }}
QLabel#from {{ color: {theme.MUTED}; font-weight: 700; font-size: 9.5pt; }}
"""


def needs_reading(text: str) -> bool:
    """Чтение латиницей нужно только для «чужой» письменности (японский, арабский…), не для кириллицы и латиницы."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    plain = sum(c.isascii() or "\u00c0" <= c <= "\u024f" or "\u0400" <= c <= "\u04ff" for c in letters)
    return plain / len(letters) < 0.5


class Popup(QWidget):
    retarget = Signal(str)
    swap = Signal()
    star = Signal()
    speak = Signal(str)          # "src" или "out"
    open_window = Signal(str)
    download = Signal(str)
    closed = Signal()

    def __init__(self, settings):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(theme.recolor(QSS))
        self.s = settings
        self._pinned = False
        self._drag = None
        self._source = ""
        self._out = ""
        self._missing = None
        self.blurred = False
        self.note = None  # функция-пометка для списка языков (ставит приложение)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = GlassRoot(radius=16)
        outer.addWidget(self.root)
        lay = QVBoxLayout(self.root)
        lay.setContentsMargins(14, 10, 8, 12)
        lay.setSpacing(8)

        # шапка: откуда → куда, действия
        top = QHBoxLayout()
        top.setSpacing(2)
        self.from_lbl = QLabel(objectName="from")
        top.addWidget(self.from_lbl)
        top.addSpacing(4)
        self.tgt_btn = LangButton("ru", note=lambda c: self.note(c) if self.note else "")
        self.tgt_btn.changed.connect(self.retarget)
        self.tgt_btn.picker.picked.connect(lambda _: None)
        top.addWidget(self.tgt_btn)
        top.addStretch(1)
        self.b_speak = self._icon_btn("speaker", "Озвучить перевод", lambda: self.speak.emit("out"))
        self.b_swap = self._icon_btn("swap", "Перевести обратно (поменять языки)", self.swap.emit)
        self.b_star = self._icon_btn("star", "В словарик для заучивания", self.star.emit)
        self.b_copy = self._icon_btn("copy", "Копировать перевод (Ctrl+C)", self.copy)
        self.b_pin = self._icon_btn("pin", "Закрепить: не закрывать при клике мимо", self._toggle_pin)
        self.b_pin.setCheckable(True)
        self.b_open = self._icon_btn("expand", "Открыть в окне", lambda: self.open_window.emit(self._source))
        self.b_close = self._icon_btn("close", "Закрыть (Esc)", self.hide_animated)
        for b in (self.b_speak, self.b_swap, self.b_star, self.b_copy, self.b_pin, self.b_open, self.b_close):
            top.addWidget(b)
        lay.addLayout(top)

        self.src = QLabel(objectName="src", wordWrap=True)
        self.src.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.src.setCursor(Qt.CursorShape.PointingHandCursor)
        self.src.setToolTip("Щёлкните, чтобы послушать оригинал")
        self.src.mousePressEvent = lambda e: self.speak.emit("src")
        lay.addWidget(self.src)

        # перевод, чтение и словарь — в прокручиваемой области
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 8, 0)
        bl.setSpacing(4)
        self.out = QLabel(objectName="out", wordWrap=True)
        self.out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.out.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.translit = QLabel(objectName="translit", wordWrap=True)
        self.dict_box = QWidget()
        self.dict_lay = QVBoxLayout(self.dict_box)
        self.dict_lay.setContentsMargins(0, 8, 0, 0)
        self.dict_lay.setSpacing(3)
        bl.addWidget(self.out)
        bl.addWidget(self.translit)
        bl.addWidget(self.dict_box)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.setWidget(self.body)
        lay.addWidget(self.scroll)

        self.action = btn("", "primary", "download")
        self.action.clicked.connect(lambda: self._missing and self.download.emit(self._missing))
        self.action.hide()
        lay.addWidget(self.action, alignment=Qt.AlignmentFlag.AlignLeft)

        foot = QHBoxLayout()
        self.engine_lbl = QLabel()
        self.engine_lbl.setProperty("role", "badge")
        self.hint = QLabel("esc закрыть · ctrl+c копировать · щелчок по оригиналу — озвучка")
        self.hint.setProperty("role", "faint")
        foot.addWidget(self.engine_lbl)
        foot.addSpacing(6)
        foot.addWidget(self.hint, 1)
        lay.addLayout(foot)

        QShortcut(QKeySequence("Esc"), self, self.hide_animated)
        QShortcut(QKeySequence.StandardKey.Copy, self, self.copy)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(150)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(190)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._dots = QTimer(self, interval=280)
        self._dots.timeout.connect(self._tick)
        self._dot_n = 0
        self.apply_style()

    def _icon_btn(self, name_, tip, slot):
        b = btn("", "icon", name_, theme.MUTED, tip)
        b.clicked.connect(slot)
        return b

    def apply_style(self):
        """Плотность стекла и размер шрифта из настроек."""
        size = float(self.s.get("font_size", 12.5))
        self.out.setStyleSheet(f"QLabel#out {{ font-size: {size}pt; }}")
        self.src.setStyleSheet(f"QLabel#src {{ font-size: {max(9.0, size - 2.5)}pt; }}")
        self.root.set_glass(self.s.get("opacity", 78), self.blurred)

    def showEvent(self, e):
        if not getattr(self, "_glass_done", False):
            self.blurred = glass.apply(self, popup=True)
            self._glass_done = True
            self.apply_style()
        super().showEvent(e)

    # --- содержимое ---
    def _set_langs(self, src: str, tgt: str):
        self.from_lbl.setText(f"{name(src) if src in LANGS else src} →")
        self.tgt_btn.set_code(tgt, emit=False)

    def _set_source(self, text: str, translit: str = ""):
        self._source = text
        one = " ".join(text.split())
        self.src.setText(one if len(one) <= 180 else one[:177].rstrip() + "…")
        self.src.setVisible(bool(one))
        self.src.setToolTip(translit or "Щёлкните, чтобы послушать оригинал")

    def _state(self, s: str):
        self.out.setProperty("state", s)
        repolish(self.out)

    def _clear_dict(self):
        while self.dict_lay.count():
            w = self.dict_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.dict_box.hide()

    def show_loading(self, text, src, tgt, at=None, label="перевожу"):
        self._missing = None
        self.action.hide()
        self._set_langs(src, tgt)
        self._set_source(text)
        self.translit.hide()
        self._clear_dict()
        self.engine_lbl.hide()
        self._label = label
        self._dot_n = 0
        self._tick()
        self._dots.start()
        self._present(at)

    def _tick(self):
        self._dot_n = (self._dot_n + 1) % 4
        self._state("note")
        self.out.setText(self._label + "." * self._dot_n)

    def show_result(self, res: dict, starred: bool = False):
        self._dots.stop()
        self._out = res["out"]
        self._set_langs(res["src"], res["tgt"])
        self._set_source(self._source, res.get("src_translit", ""))
        self._state("")
        self.out.setText(res["out"])
        tr = res.get("translit", "")
        self.translit.setText(tr)
        self.translit.setVisible(needs_reading(res["out"]) and bool(tr) and tr != res["out"])
        self._clear_dict()
        for g in (res.get("dict") or [])[:3]:
            pos = QLabel(g["pos"].upper(), objectName="pos")
            terms = QLabel(", ".join(t["word"] for t in g["terms"][:7]), objectName="terms", wordWrap=True)
            terms.setToolTip("\n".join(f"{t['word']} — {', '.join(t['back'])}" for t in g["terms"] if t["back"]))
            self.dict_lay.addWidget(pos)
            self.dict_lay.addWidget(terms)
        for ex in (res.get("examples") or [])[:2]:
            self.dict_lay.addWidget(QLabel(f"«{ex}»", objectName="example", wordWrap=True))
        self.dict_box.setVisible(self.dict_lay.count() > 0)
        eng = {"google": "google", "mymemory": "mymemory", "offline": "офлайн"}.get(res.get("engine"), "")
        self.engine_lbl.setText(eng)
        self.engine_lbl.setVisible(bool(eng))
        self.set_starred(starred)
        self._fit()

    def set_starred(self, on: bool):
        self.b_star.setIcon(icon("star-fill" if on else "star", theme.ACCENT if on else theme.MUTED))
        self.b_star.setToolTip("Убрать из словарика" if on else "В словарик для заучивания")

    def show_message(self, text, src=None, tgt=None, at=None, missing=None, source=""):
        self._dots.stop()
        self._out = ""
        if src and tgt:
            self._set_langs(src, tgt)
        else:
            self.from_lbl.setText("вавилон")
        self._set_source(source)
        self._state("note")
        self.out.setText(text)
        self.translit.hide()
        self._clear_dict()
        self.engine_lbl.hide()
        self._missing = missing
        if missing:
            self.action.setText(f"  скачать {name(missing)}")
        self.action.setVisible(bool(missing))
        self._present(at)

    def flash(self, text, at=None, ms=1400):
        """Короткое сообщение, которое само исчезает (например, «заменено»)."""
        self.show_message(text, at=at)
        QTimer.singleShot(ms, lambda: not self._pinned and self.hide_animated())

    # --- размеры и показ ---
    def _fit(self):
        # высоты всех текстов задаём явно: иначе Qt считает их до того, как узнает ширину
        w = max(int(self.s.get("popup_width", 460)), 400)
        inner = w - 14 - 8
        self.src.setMinimumHeight(0)
        self.src.setMaximumHeight(16777215)
        self.src.setFixedWidth(inner - 6)
        self.src.setFixedHeight(self.src.heightForWidth(inner - 6) if self.src.isVisibleTo(self) else 0)
        tw = inner - 14

        def size(lbl):
            lbl.setMinimumHeight(0)  # снять прошлую фиксированную высоту, иначе QLabel её же и вернёт
            lbl.setMaximumHeight(16777215)
            lbl.setFixedWidth(tw)
            lh = lbl.heightForWidth(tw)
            lbl.setFixedHeight(lh)
            return lh

        parts = [size(self.out)]
        if self.translit.isVisibleTo(self):
            parts.append(size(self.translit))
        n = self.dict_lay.count()
        if n:
            dh = self.dict_lay.contentsMargins().top() + self.dict_lay.spacing() * (n - 1)
            dh += sum(size(self.dict_lay.itemAt(i).widget()) for i in range(n))
            self.dict_box.setFixedHeight(dh)
            parts.append(dh)
        h = sum(parts) + self.body.layout().spacing() * (len(parts) - 1)
        self.body.setFixedSize(tw + 8, max(h, 20))
        self.body.layout().invalidate()
        self.body.layout().activate()
        self.scroll.setFixedHeight(max(24, min(h + 2, 360)))
        self.scroll.verticalScrollBar().setValue(0)
        rl = self.root.layout()
        rl.invalidate()
        rl.activate()
        self.setFixedSize(w, rl.sizeHint().height())
        # после смены размера окна раскладку пересчитываем сразу, а не «когда-нибудь»
        self.layout().setGeometry(self.rect())
        rl.setGeometry(self.root.rect())
        self.body.layout().setGeometry(self.body.rect())
        self._clamp()

    def _present(self, at):
        self._fit()
        if not self.isVisible():
            p = at or QCursor.pos() + QPoint(14, 18)
            self.move(p)
            self._clamp()
            target = self.pos()
            self.setWindowOpacity(0.0)
            self.show()
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
            self._slide.stop()
            self._slide.setStartValue(target + QPoint(0, 8))
            self._slide.setEndValue(target)
            self._slide.start()
        self.raise_()
        self.activateWindow()

    def _clamp(self):
        scr = QGuiApplication.screenAt(self.pos() + QPoint(20, 20)) or QGuiApplication.primaryScreen()
        a: QRect = scr.availableGeometry()
        x = min(max(self.x(), a.left() + 4), a.right() - self.width() - 4)
        y = self.y()
        if y + self.height() > a.bottom() - 4:  # не влезает вниз: показываем над курсором
            y = max(a.top() + 4, QCursor.pos().y() - self.height() - 10)
        self.move(x, max(y, a.top() + 4))

    def hide_animated(self):
        if not self.isVisible():
            return
        self._dots.stop()
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._fade.finished.connect(self._really_hide)
        self._fade.start()

    def _really_hide(self):
        self._fade.finished.disconnect()
        self.hide()
        self.closed.emit()

    def copy(self):
        sel = self.out.selectedText()
        QGuiApplication.clipboard().setText(sel or self._out)
        self.b_copy.setIcon(icon("check", theme.ACCENT))
        QTimer.singleShot(900, lambda: self.b_copy.setIcon(icon("copy", theme.MUTED)))

    def _toggle_pin(self):
        self._pinned = self.b_pin.isChecked()
        self.b_pin.setIcon(icon("pin", theme.ACCENT if self._pinned else theme.MUTED))

    # --- закрытие по клику мимо и перетаскивание ---
    def changeEvent(self, e):
        if e.type() == e.Type.ActivationChange and not self.isActiveWindow() and not self._pinned:
            QTimer.singleShot(150, self._maybe_hide)
        super().changeEvent(e)

    def _maybe_hide(self):
        if self.isActiveWindow() or self._pinned or self.tgt_btn.picker.isVisible():
            return
        self.hide_animated()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 48:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
