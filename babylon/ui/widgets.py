"""Общие элементы интерфейса: стеклянный фон, выбор языка с поиском, переключатель, поле сочетания."""
from PySide6.QtCore import Property, QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QFrame, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..langs import LANGS
from . import theme
from .icons import icon


class GlassRoot(QWidget):
    """Фон окна: полупрозрачное тёмное стекло (размытие под ним делает Windows)."""

    def __init__(self, radius: float = 0, parent=None):
        super().__init__(parent)
        self.radius = radius
        self.opacity = 78
        self.blurred = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_glass(self, opacity: int, blurred: bool):
        self.opacity, self.blurred = opacity, blurred
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, theme.glass_color(self.opacity, self.blurred))
        if self.radius:
            p.setPen(QPen(QColor(255, 255, 255, 34), 1))
            p.drawPath(path)


def btn(text="", kind=None, icon_name=None, color=None, tip=None):
    b = QPushButton(text)
    if kind:
        b.setProperty("kind", kind)
    if icon_name:
        b.setIcon(icon(icon_name, color or ("#0a0a0a" if kind == "primary" else theme.TEXT)))
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def repolish(w):
    w.style().unpolish(w)
    w.style().polish(w)


class LangPicker(QFrame):
    """Всплывающий список языков с поиском (по-русски и в самоназвании)."""

    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(f"QFrame#box {{ background: #1c1c20; border: 1px solid {theme.LINE_STRONG}; border-radius: 16px; }}"
                           "QListWidget::item { background: transparent; border: none; border-radius: 9px;"
                           " padding: 7px 10px; margin: 0; }"
                           "QListWidget::item:hover, QListWidget::item:selected { background: rgba(255,255,255,0.1); }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame(objectName="box")
        outer.addWidget(box)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.search = QLineEdit(placeholderText="поиск языка…")
        self.search.addAction(icon("search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._enter)
        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(lambda it: self._choose(it.data(Qt.ItemDataRole.UserRole)))
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        self.resize(300, 380)

    def open(self, anchor: QWidget, current: str, include_auto=False, note=None, codes=None):
        """note(code) -> короткая пометка справа (например, «офлайн»)."""
        self.list.clear()
        items = list(codes or LANGS)
        if include_auto:
            items = ["auto"] + items
        for code in items:
            if code == "auto":
                label = "определить язык"
            else:
                ru, own = LANGS.get(code, (code, code))
                label = ru.lower() if own.lower() == ru.lower() else f"{ru.lower()}  ·  {own}"
            mark = note(code) if note and code != "auto" else ""
            it = QListWidgetItem(f"{label}{'   ' + mark if mark else ''}")
            it.setData(Qt.ItemDataRole.UserRole, code)
            it.setData(Qt.ItemDataRole.UserRole + 1, f"{code} {label}".lower())
            if code == current:
                it.setIcon(icon("check", theme.ACCENT))
            self.list.addItem(it)
        self.search.clear()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        screen = anchor.screen().availableGeometry()
        pos.setX(min(pos.x(), screen.right() - self.width() - 8))
        if pos.y() + self.height() > screen.bottom():
            pos.setY(anchor.mapToGlobal(QPoint(0, 0)).y() - self.height() - 6)
        self.move(pos)
        self.show()
        self.search.setFocus()
        cur = next((i for i in range(self.list.count())
                    if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current), 0)
        self.list.setCurrentRow(cur)
        self.list.scrollToItem(self.list.item(cur), QListWidget.ScrollHint.PositionAtCenter)

    def _filter(self, text):
        t = text.strip().lower()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hide = bool(t) and t not in it.data(Qt.ItemDataRole.UserRole + 1)
            it.setHidden(hide)
            if not hide and first is None:
                first = i
        if first is not None:
            self.list.setCurrentRow(first)

    def _enter(self):
        it = self.list.currentItem()
        if it and not it.isHidden():
            self._choose(it.data(Qt.ItemDataRole.UserRole))

    def _choose(self, code):
        self.hide()
        self.picked.emit(code)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.list.keyPressEvent(e)
        else:
            super().keyPressEvent(e)


class LangButton(QPushButton):
    """Кнопка-пилюля с названием языка; по щелчку — список с поиском."""

    changed = Signal(str)

    def __init__(self, code: str, include_auto=False, note=None):
        super().__init__()
        self.setProperty("kind", "lang")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icon("chevron", theme.MUTED))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.include_auto = include_auto
        self.note = note
        self.detected = None
        self.picker = LangPicker(self)
        self.picker.picked.connect(self.set_code)
        self.clicked.connect(lambda: self.picker.open(self, self.code, self.include_auto, self.note))
        self.code = None
        self.set_code(code, emit=False)

    def set_code(self, code: str, emit=True):
        changed = code != self.code
        self.code = code
        self._label()
        if changed and emit:
            self.changed.emit(code)

    def set_detected(self, code):
        self.detected = code
        self._label()

    def _label(self):
        if self.code == "auto":
            txt = "определить язык"
            if self.detected and self.detected in LANGS:
                txt = f"{LANGS[self.detected][0].lower()} · определён"
        else:
            txt = LANGS.get(self.code, (self.code,))[0].lower()
        self.setText(txt)


class Toggle(QCheckBox):
    """Переключатель-пилюля с кружком, который плавно едет."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._go)

    def _go(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._x)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _get(self):
        return self._x

    def _set(self, v):
        self._x = v
        self.update()

    knob = Property(float, _get, _set)

    def setChecked(self, on):
        super().setChecked(on)
        self._x = 1.0 if on else 0.0

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(44 + 12 + fm.horizontalAdvance(self.text()), max(26, fm.height() + 8))

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = 22
        y = (self.height() - h) / 2
        off, on = QColor(255, 255, 255, 40), QColor(theme.ACCENT)
        c = QColor(int(off.red() + (on.red() - off.red()) * self._x),
                   int(off.green() + (on.green() - off.green()) * self._x),
                   int(off.blue() + (on.blue() - off.blue()) * self._x),
                   int(off.alpha() + (255 - off.alpha()) * self._x))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, y, 40, h), h / 2, h / 2)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(3 + 18 * self._x, y + 3, h - 6, h - 6))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(52, 0, self.width() - 52, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


class HotkeyEdit(QLineEdit):
    """Поле, в котором нажимаешь сочетание, и оно записывается как 'Ctrl+Alt+T'."""

    changed = Signal(str)

    def __init__(self, value: str):
        super().__init__(value)
        self.setReadOnly(True)
        self.setPlaceholderText("нажмите сочетание")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Щёлкните и нажмите сочетание клавиш. Backspace — отключить.")

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        if k in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.setText("")
            self.changed.emit("")
            return
        m = e.modifiers()
        parts = [n for flag, n in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                                   (Qt.KeyboardModifier.AltModifier, "Alt"),
                                   (Qt.KeyboardModifier.ShiftModifier, "Shift"),
                                   (Qt.KeyboardModifier.MetaModifier, "Win")) if m & flag]
        # по коду клавиши, чтобы русская раскладка не превращала T в «Е»
        vk = e.nativeVirtualKey()
        if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
            name = chr(vk)
        elif 0x70 <= vk <= 0x87:
            name = f"F{vk - 0x6F}"
        else:
            name = QKeySequence(k).toString() or ""
        if not name:
            return
        parts.append(name)
        self.setText("+".join(parts))
        self.changed.emit(self.text())


class Swatch(QPushButton):
    """Круглая кнопка-цвет для выбора акцента."""

    def __init__(self, color: str, tip: str):
        super().__init__()
        self.color = QColor(color)
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none; padding: 0; min-width: 30px; max-width: 30px; "
                           "min-height: 30px; max-height: 30px;")  # размер задаём стилем: общий стиль кнопок его перебивает

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height())
        outer = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        r = outer.adjusted(4, 4, -4, -4)
        if self.isChecked():
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawEllipse(outer.adjusted(1.5, 1.5, -1.5, -1.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(r)
