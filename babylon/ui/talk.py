"""Раздел «разговор»: перевод речи вживую — видео без субтитров, онлайн-конференции, разговор рядом.

Слева направо: откуда слушать (звук компьютера / микрофон), на какой язык, «слушать».
Ниже — лента фраз (оригинал и перевод), внизу — ответ: пишете по-русски, Вавилон переводит
на язык собеседника и говорит вслух.
"""
import os
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import asr
from ..langs import name
from . import theme
from .widgets import LangButton, Toggle, btn

QSS = f"""
QLabel#when {{ color: {theme.FAINT}; font-size: 8.5pt; }}
QLabel#orig {{ color: {theme.MUTED}; }}
QLabel#out {{ font-size: 13pt; font-weight: 600; }}
QLabel#draft {{ color: {theme.MUTED}; font-size: 12pt; font-style: italic; }}
QFrame#bubble {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; }}
QFrame#mine {{ background: rgba(255,59,59,0.10); border: 1px solid rgba(255,59,59,0.25); border-radius: 16px; }}
"""


class Bubble(QFrame):
    def __init__(self, when: str, orig: str, out: str, mine=False):
        super().__init__()
        self.setObjectName("mine" if mine else "bubble")
        l = QVBoxLayout(self)
        l.setContentsMargins(16, 10, 16, 12)
        l.setSpacing(3)
        for text, obj in ((when, "when"), (orig, "orig"), (out, "out")):
            lb = QLabel(text, objectName=obj, wordWrap=True)
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            l.addWidget(lb)


class TalkPage(QWidget):
    start_requested = Signal(str, str)     # источник ('system' / 'mic'), язык перевода
    stop_requested = Signal()
    reply_requested = Signal(str)
    download_requested = Signal(str)       # размер модели
    overlay_toggled = Signal(bool)
    voice_toggled = Signal(bool)

    def __init__(self, settings, note=None):
        super().__init__()
        self.s = settings
        self.setStyleSheet(theme.recolor(QSS))
        self.items: list[dict] = []
        self.running = False
        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)

        head = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(0)
        cap = QLabel("разговор")
        cap.setProperty("role", "caption")
        tl.addWidget(cap)
        t = QLabel("перевод речи вживую")
        t.setProperty("role", "title")
        tl.addWidget(t)
        head.addLayout(tl, 1)
        self.status = QLabel("")
        self.status.setProperty("role", "badge")
        self.status.hide()
        head.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignBottom)
        l.addLayout(head)

        # --- откуда слушать и куда переводить ---
        row = QHBoxLayout()
        row.setSpacing(8)
        self.src_group = QButtonGroup(self)
        for i, (key, title, tip) in enumerate((
                ("system", "  звук компьютера", "Видео без субтитров, YouTube, фильмы, Zoom, Discord, Teams — всё, что слышно в колонках"),
                ("mic", "  микрофон", "Разговор рядом: Вавилон слышит обоих и переводит в обе стороны"))):
            b = btn(title, "lang", "speaker" if key == "system" else "mic", theme.TEXT, tip)
            b.setCheckable(True)
            b.setProperty("src", key)
            self.src_group.addButton(b, i)
            row.addWidget(b)
        self.src_group.button(0 if settings.get("hear_source", "system") == "system" else 1).setChecked(True)
        row.addSpacing(12)
        row.addWidget(QLabel("перевод на", styleSheet=f"color: {theme.MUTED};"))
        self.tgt = LangButton(settings["preferred"], note=note)
        row.addWidget(self.tgt)
        row.addStretch(1)
        self.b_go = btn("  слушать", "primary", "play")
        self.b_go.setMinimumWidth(150)
        self.b_go.clicked.connect(self._go)
        row.addWidget(self.b_go)
        l.addLayout(row)

        opts = QHBoxLayout()
        self.t_overlay = Toggle("субтитры поверх экрана")
        self.t_overlay.setChecked(settings.get("hear_overlay", True))
        self.t_overlay.toggled.connect(self.overlay_toggled)
        opts.addWidget(self.t_overlay)
        opts.addSpacing(18)
        self.t_voice = Toggle("озвучивать перевод")
        self.t_voice.setChecked(settings.get("voice_over", False))
        self.t_voice.toggled.connect(self.voice_toggled)
        opts.addWidget(self.t_voice)
        opts.addStretch(1)
        self.level = QProgressBar(maximum=100, textVisible=False)
        self.level.setFixedWidth(140)
        self.level.setToolTip("громкость, которую слышит Вавилон")
        opts.addWidget(self.level)
        l.addLayout(opts)

        # --- модель распознавания ---
        self.model_card = QFrame()
        self.model_card.setProperty("role", "card")
        ml = QHBoxLayout(self.model_card)
        ml.setContentsMargins(18, 14, 14, 14)
        mt = QLabel("для перевода речи нужна модель распознавания (нейросеть whisper). скачивается один раз, "
                    "дальше речь распознаётся прямо на компьютере, без интернета.", wordWrap=True)
        ml.addWidget(mt, 1)
        self.model_btns = {}
        for size, (_, mb, title) in asr.SIZES.items():
            b = btn(f"  {title} · {mb} мб", "primary" if size == "base" else None, "download")
            b.clicked.connect(lambda _=False, sz=size: self.download_requested.emit(sz))
            ml.addWidget(b)
            self.model_btns[size] = b
        self.model_prog = QProgressBar(maximum=1000, textVisible=False)
        self.model_prog.setFixedWidth(160)
        self.model_prog.hide()
        ml.addWidget(self.model_prog)
        l.addWidget(self.model_card)

        # --- лента ---
        self.scroll = QScrollArea(widgetResizable=True)
        self.feed = QWidget()
        self.fl = QVBoxLayout(self.feed)
        self.fl.setContentsMargins(0, 4, 8, 4)
        self.fl.setSpacing(8)
        self.empty = QLabel("нажмите «слушать» и включите видео или созвон. здесь появятся фразы и их перевод.\n"
                            "для разговора рядом выберите «микрофон»: русские фразы переведутся на язык собеседника.",
                            alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.empty.setProperty("role", "muted")
        self.fl.addWidget(self.empty)
        self.fl.addStretch(1)
        self.draft = QLabel("", objectName="draft", wordWrap=True)
        self.draft.hide()
        self.fl.addWidget(self.draft)
        self.scroll.setWidget(self.feed)
        l.addWidget(self.scroll, 1)

        # --- ответ ---
        foot = QHBoxLayout()
        self.reply = QLineEdit()
        self.reply.setPlaceholderText("ваш ответ по-русски — переведу на язык собеседника и скажу вслух")
        self.reply.returnPressed.connect(self._reply)
        foot.addWidget(self.reply, 1)
        b = btn("  сказать", None, "speaker")
        b.clicked.connect(self._reply)
        foot.addWidget(b)
        b = btn("", "icon", "download", theme.MUTED, "Сохранить разговор в текстовый файл")
        b.clicked.connect(self._save)
        foot.addWidget(b)
        b = btn("", "icon", "trash", theme.MUTED, "Очистить")
        b.clicked.connect(self.clear)
        foot.addWidget(b)
        l.addLayout(foot)
        self.refresh_model()

    # --- состояние ---
    def source(self) -> str:
        return self.src_group.checkedButton().property("src")

    def _go(self):
        if self.running:
            self.stop_requested.emit()
        else:
            self.start_requested.emit(self.source(), self.tgt.code)

    def set_running(self, on: bool):
        self.running = on
        self.b_go.setText("  стоп" if on else "  слушать")
        from .icons import icon

        self.b_go.setIcon(icon("pause" if on else "play", "#0a0a0a"))
        if not on:
            self.level.setValue(0)
            self.draft.hide()

    def set_status(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_level(self, v: float):
        self.level.setValue(int(min(1.0, v) * 100))

    def refresh_model(self, busy: str | None = None):
        have = any(asr.installed(sz) for sz in asr.SIZES)
        self.model_card.setVisible(not have or bool(busy))
        for sz, b in self.model_btns.items():
            b.setEnabled(not busy)
        self.model_prog.setVisible(bool(busy))

    def model_progress(self, done: int, total: int):
        self.model_prog.setValue(int(1000 * done / max(1, total)))

    # --- лента ---
    def _scroll_down(self):
        QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def add_phrase(self, p: dict, mine=False):
        self.empty.hide()
        self.draft.hide()
        when = time.strftime("%H:%M", time.localtime(p.get("at", time.time())))
        who = "вы" if mine else name(p["src"]).lower()
        self.items.append({**p, "mine": mine})
        self.fl.insertWidget(self.fl.count() - 1, Bubble(f"{when} · {who} → {name(p['tgt']).lower()}",
                                                         p["text"], p["out"], mine))
        self._scroll_down()

    def set_draft(self, text: str, out: str):
        self.draft.setText(out or text)
        self.draft.setToolTip(text)
        self.draft.show()
        self._scroll_down()

    def clear(self):
        for i in reversed(range(self.fl.count())):
            w = self.fl.itemAt(i).widget()
            if isinstance(w, Bubble):
                w.deleteLater()
        self.items = []
        self.empty.show()

    def _reply(self):
        text = self.reply.text().strip()
        if text:
            self.reply.clear()
            self.reply_requested.emit(text)

    def _save(self):
        if not self.items:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить разговор",
                                              os.path.join(os.path.expanduser("~"), time.strftime("разговор %Y-%m-%d %H-%M.txt")),
                                              "Текст (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8-sig") as f:
                for it in self.items:
                    when = time.strftime("%H:%M:%S", time.localtime(it.get("at", 0)))
                    who = "вы" if it["mine"] else name(it["src"]).lower()
                    f.write(f"[{when}] {who}: {it['text']}\n    → {it['out']}\n\n")
            self.set_status("разговор сохранён")
