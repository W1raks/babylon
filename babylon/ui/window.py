"""Главное окно: боковое меню и разделы «перевод», «словарик», «история», «языки», «настройки»."""
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit, QProgressBar,
                               QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from ..langs import LANGS, OFFLINE, name
from ..translator import MODES
from . import glass, theme
from .icons import icon
from .widgets import GlassRoot, HotkeyEdit, LangButton, Swatch, Toggle, btn, repolish

PAGES = (("translate", "перевод", "translate"), ("talk", "разговор", "mic"), ("media", "файлы", "image"), ("vocab", "словарик", "book"), ("history", "история", "clock"),
         ("langs", "языки", "globe"), ("settings", "настройки", "settings"))


def _card() -> QFrame:
    f = QFrame()
    f.setProperty("role", "card")
    return f


def _label(text, role=None, wrap=False):
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def _header(top: str, title: str) -> QWidget:
    w = QWidget()
    l = QVBoxLayout(w)
    l.setContentsMargins(0, 0, 0, 0)
    l.setSpacing(0)
    l.addWidget(_label(top, "caption"))
    l.addWidget(_label(title, "title"))
    return w


class MainWindow(QMainWindow):
    translate_requested = Signal(str, str, str)   # текст, src ('auto' или код), tgt
    snip_requested = Signal()
    download_requested = Signal(str)
    remove_requested = Signal(str)
    settings_changed = Signal(dict)
    history_cleared = Signal()
    update_requested = Signal(str)
    speak_requested = Signal(str, str)             # текст, язык
    star_requested = Signal(str, str, str, str)    # текст, перевод, src, tgt
    vocab_answer = Signal(object, bool)
    vocab_remove = Signal(object)
    vocab_export = Signal(str)
    study_requested = Signal()
    live_requested = Signal()
    check_updates_requested = Signal()

    def __init__(self, settings, ocr_langs: list[str], note=None, media_translate=None):
        super().__init__()
        self.s = settings
        self.note = note  # пометка к языку в списках («скачан»)
        self.setWindowTitle("Вавилон")
        self.setWindowIcon(theme.app_icon())
        self.resize(1080, 700)
        self.setMinimumSize(820, 560)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.blurred = False
        self._last = None  # последний результат перевода в окне

        self.root = GlassRoot()
        self.setCentralWidget(self.root)
        row = QHBoxLayout(self.root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # --- боковое меню ---
        side = QWidget()
        side.setFixedWidth(210)
        side.setStyleSheet(f"background: rgba(0,0,0,0.18); border-right: 1px solid {theme.LINE};")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 16)
        sl.setSpacing(4)
        brand = QHBoxLayout()
        mark = QLabel()
        dpr = self.devicePixelRatioF()
        pm = theme.logo(int(40 * dpr))
        pm.setDevicePixelRatio(dpr)
        mark.setPixmap(pm)
        mark.setStyleSheet("background: transparent; border: none;")
        brand.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(0)
        t1 = _label("вавилон")
        t1.setStyleSheet("font-size: 14pt; font-weight: 800; background: transparent; border: none;")
        t2 = _label("babylon · переводчик", "faint")
        t2.setStyleSheet("background: transparent; border: none;")
        names.addWidget(t1)
        names.addWidget(t2)
        brand.addLayout(names, 1)
        sl.addLayout(brand)
        sl.addSpacing(18)
        self.nav = QButtonGroup(self)
        self.stack = QStackedWidget()
        for i, (key, title, ic) in enumerate(PAGES):
            b = btn(f"  {title}", "nav", ic, theme.MUTED)
            b.setCheckable(True)
            b.setStyleSheet("border-right: none;")
            self.nav.addButton(b, i)
            sl.addWidget(b)
        self.nav.idClicked.connect(self.show_page)
        sl.addStretch(1)
        self.net = _label("", "badge")
        self.net.setStyleSheet("border-right: none;")
        sl.addWidget(self.net, alignment=Qt.AlignmentFlag.AlignLeft)
        row.addWidget(side)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(26, 20, 26, 20)
        cl.addWidget(self.stack)
        row.addWidget(content, 1)

        self.stack.addWidget(self._page_translate())
        from .media import MediaPage
        from .talk import TalkPage

        self.talk = TalkPage(settings, note=self._note)
        self.stack.addWidget(self.talk)

        self.media = MediaPage(settings, media_translate, note=self._note)
        self.media.live_requested.connect(self.live_requested)
        self.stack.addWidget(self.media)
        self.stack.addWidget(self._page_vocab())
        self.stack.addWidget(self._page_history())
        self.stack.addWidget(self._page_langs())
        self.stack.addWidget(self._page_settings(ocr_langs))
        self.show_page(0)

        self._debounce = QTimer(self, singleShot=True, interval=500)
        self._debounce.timeout.connect(self._emit_translate)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._emit_translate)
        QShortcut(QKeySequence("Esc"), self, self.hide)

    def page_index(self, key: str) -> int:
        return [p[0] for p in PAGES].index(key)

    def show_page(self, i):
        if isinstance(i, str):
            i = self.page_index(i)
        self.nav.button(i).setChecked(True)
        self.stack.setCurrentIndex(i)
        if PAGES[i][0] == "vocab":
            self._vocab_list_mode()

    def set_glass(self):
        self.root.set_glass(self.s.get("opacity", 78), self.blurred)

    def showEvent(self, e):
        if not getattr(self, "_glass_done", False):
            self.blurred = glass.apply(self)
            self._glass_done = True
        self.set_glass()
        super().showEvent(e)

    def set_online(self, online: bool, mode: str):
        if mode == "offline":
            txt, role = "только офлайн", "badge"
        elif online:
            txt, role = "● онлайн", "badge-ok"
        else:
            txt, role = "○ нет сети · офлайн", "badge"
        self.net.setText(txt)
        self.net.setProperty("role", role)
        repolish(self.net)

    # ================= перевод =================
    def _page_translate(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(14)

        cards = QHBoxLayout()
        cards.setSpacing(14)

        # исходный текст
        left = _card()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 12, 12, 10)
        head = QHBoxLayout()
        self.src_btn = LangButton("auto", include_auto=True, note=self._note)
        self.src_btn.changed.connect(lambda _: self._debounce.start(0))
        head.addWidget(self.src_btn)
        head.addStretch(1)
        self.swap = btn("", "icon", "swap", theme.TEXT, "Поменять языки местами")
        self.swap.clicked.connect(self._swap)
        head.addWidget(self.swap)
        ll.addLayout(head)
        self.inp = QPlainTextEdit()
        self.inp.setPlaceholderText("введите или вставьте текст…")
        ll.addWidget(self.inp, 1)
        foot = QHBoxLayout()
        self.count = _label("", "faint")
        foot.addWidget(self.count, 1)
        b = btn("", "icon", "speaker", theme.MUTED, "Озвучить")
        b.clicked.connect(lambda: self.speak_requested.emit(self.inp.toPlainText(), self._src_code()))
        foot.addWidget(b)
        b = btn("", "icon", "scan", theme.MUTED, "Текст с экрана")
        b.clicked.connect(self.snip_requested)
        foot.addWidget(b)
        b = btn("", "icon", "subs", theme.MUTED, "Живые субтитры поверх видео")
        b.clicked.connect(self.live_requested)
        foot.addWidget(b)
        b = btn("", "icon", "close", theme.MUTED, "Очистить")
        b.clicked.connect(lambda: (self.inp.clear(), self.outp.clear(), self.status.setText("")))
        foot.addWidget(b)
        ll.addLayout(foot)

        # перевод
        right = _card()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 12, 12, 10)
        head = QHBoxLayout()
        self.tgt_btn = LangButton(self.s["preferred"], note=self._note)
        self.tgt_btn.changed.connect(lambda _: self._debounce.start(0))
        head.addWidget(self.tgt_btn)
        head.addStretch(1)
        self.engine_lbl = _label("", "badge")
        self.engine_lbl.hide()
        head.addWidget(self.engine_lbl)
        rl.addLayout(head)
        self.outp = QPlainTextEdit(readOnly=True)
        self.outp.setPlaceholderText("здесь появится перевод")
        rl.addWidget(self.outp, 1)
        self.translit = _label("", "faint", wrap=True)
        self.translit.hide()
        rl.addWidget(self.translit)
        foot = QHBoxLayout()
        self.status = _label("", "faint")
        foot.addWidget(self.status, 1)
        b = btn("", "icon", "speaker", theme.MUTED, "Озвучить перевод")
        b.clicked.connect(lambda: self._last and self.speak_requested.emit(self._last["out"], self._last["tgt"]))
        foot.addWidget(b)
        self.star_btn = btn("", "icon", "star", theme.MUTED, "В словарик")
        self.star_btn.clicked.connect(self._star)
        foot.addWidget(self.star_btn)
        self.copy_btn = btn("", "icon", "copy", theme.MUTED, "Копировать")
        self.copy_btn.clicked.connect(self._copy_out)
        foot.addWidget(self.copy_btn)
        rl.addLayout(foot)

        cards.addWidget(left, 1)
        cards.addWidget(right, 1)
        l.addLayout(cards, 3)

        # словарь для одного слова
        self.dict_card = _card()
        dl = QVBoxLayout(self.dict_card)
        dl.setContentsMargins(16, 12, 16, 12)
        dl.addWidget(_label("словарь", "caption"))
        self.dict_text = QLabel(wordWrap=True)
        self.dict_text.setTextFormat(Qt.TextFormat.RichText)
        self.dict_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.dict_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        dl.addWidget(self.dict_text, 1)
        self.dict_card.hide()
        l.addWidget(self.dict_card, 2)

        self.inp.textChanged.connect(self._on_input)
        return w

    def _note(self, code):
        return self.note(code) if self.note else ""

    def _src_code(self):
        return self.src_btn.detected if self.src_btn.code == "auto" and self.src_btn.detected else self.src_btn.code

    def _on_input(self):
        n = len(self.inp.toPlainText())
        self.count.setText(f"{n} симв." if n else "")
        self._debounce.start()

    def _swap(self):
        src = self._src_code()
        if src == "auto":
            src = self.s["fallback"]
        tgt = self.tgt_btn.code
        out = self.outp.toPlainText()
        self.src_btn.set_code(tgt, emit=False)
        self.tgt_btn.set_code(src, emit=False)
        if out.strip():
            self.inp.setPlainText(out)
        else:
            self._debounce.start(0)

    def _emit_translate(self):
        text = self.inp.toPlainText()
        if not text.strip():
            self.outp.clear()
            self.status.setText("")
            self.dict_card.hide()
            self.translit.hide()
            self.engine_lbl.hide()
            return
        self.status.setText("перевожу…")
        self.translate_requested.emit(text, self.src_btn.code, self.tgt_btn.code)

    def set_text(self, text: str):
        self.show_page(0)
        self.inp.setPlainText(text)
        self._debounce.start(0)

    def show_translation(self, text: str, res: dict, ms: int, starred: bool):
        if text != self.inp.toPlainText():
            return  # пока переводили, текст поменялся
        self._last = {**res, "text": text}
        self.outp.setPlainText(res["out"])
        if self.src_btn.code == "auto":
            self.src_btn.set_detected(res["src"])
        if res["tgt"] != self.tgt_btn.code:
            self.tgt_btn.set_code(res["tgt"], emit=False)
        from .popup import needs_reading

        tr = res.get("translit")
        self.translit.setText(tr or "")
        self.translit.setVisible(bool(tr) and tr != res["out"] and needs_reading(res["out"]))
        eng = {"google": "google", "mymemory": "mymemory", "offline": "офлайн"}.get(res.get("engine"), "")
        self.engine_lbl.setText(eng)
        self.engine_lbl.setVisible(bool(eng))
        self.status.setText(f"{ms} мс")
        self.set_starred(starred)
        self._show_dict(res)

    def _show_dict(self, res):
        groups = res.get("dict") or []
        if not groups:
            self.dict_card.hide()
            return
        html = []
        for g in groups[:4]:
            html.append(f"<p style='margin:6px 0 2px 0'><span style='color:{theme.ACCENT}; font-size:8.5pt; "
                        f"font-weight:700'>{g['pos'].upper()}</span></p>")
            rows = []
            for t in g["terms"][:8]:
                back = ", ".join(t["back"][:3])
                rows.append(f"<b>{t['word']}</b>" + (f" <span style='color:{theme.MUTED}'>({back})</span>"
                                                       if back else ""))
            html.append(f"<span style='color:{theme.FAINT}'> · </span>".join(rows))
        for ex in (res.get("examples") or [])[:3]:
            html.append(f"<p style='color:{theme.MUTED}; margin-top:8px'><i>«{ex}»</i></p>")
        self.dict_text.setText("".join(html))
        self.dict_card.show()

    def show_error(self, msg: str):
        self.status.setText(msg)

    def set_starred(self, on: bool):
        self.star_btn.setIcon(icon("star-fill" if on else "star", theme.ACCENT if on else theme.MUTED))

    def _star(self):
        if self._last:
            r = self._last
            self.star_requested.emit(r["text"], r["out"], r["src"], r["tgt"])

    def _copy_out(self):
        QGuiApplication.clipboard().setText(self.outp.toPlainText())
        self.copy_btn.setIcon(icon("check", theme.ACCENT))
        QTimer.singleShot(1000, lambda: self.copy_btn.setIcon(icon("copy", theme.MUTED)))

    # ================= словарик =================
    def _page_vocab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_header("словарик", "слова для заучивания"))
        top.addStretch(1)
        self.vocab_info = _label("", "muted")
        top.addWidget(self.vocab_info)
        top.addSpacing(10)
        exp = btn("экспорт в anki", "ghost")
        exp.clicked.connect(self._export)
        top.addWidget(exp)
        self.study_btn = btn("  учить", "primary", "book")
        self.study_btn.clicked.connect(self._study_start)
        top.addWidget(self.study_btn)
        l.addLayout(top)

        self.vocab_stack = QStackedWidget()
        # список
        lw = QWidget()
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        self.vocab_search = QLineEdit(placeholderText="поиск по словарику…")
        self.vocab_search.addAction(icon("search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.vocab_search.textChanged.connect(lambda: self.fill_vocab(self._vocab_items))
        ll.addWidget(self.vocab_search)
        self.vocab_list = QListWidget()
        self.vocab_list.setWordWrap(True)
        self.vocab_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.vocab_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.vocab_list.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        ll.addWidget(self.vocab_list, 1)
        hint = _label("звёздочка во всплывашке или в окне перевода добавляет сюда слово. "
                      "правый щелчок по слову — удалить.", "faint", wrap=True)
        ll.addWidget(hint)
        from PySide6.QtGui import QAction

        act = QAction("удалить из словарика", self.vocab_list)
        act.triggered.connect(self._vocab_delete)
        self.vocab_list.addAction(act)
        self.vocab_stack.addWidget(lw)

        # карточка
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 10, 0, 0)
        self.card = _card()
        self.card.setMinimumHeight(280)
        kl = QVBoxLayout(self.card)
        kl.setContentsMargins(30, 26, 30, 26)
        self.card_meta = _label("", "faint")
        self.card_front = QLabel(wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter)
        self.card_front.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.card_back = QLabel(wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter)
        self.card_back.setStyleSheet(f"font-size: 15pt; color: {theme.MUTED};")
        kl.addWidget(self.card_meta, alignment=Qt.AlignmentFlag.AlignCenter)
        kl.addStretch(1)
        kl.addWidget(self.card_front)
        kl.addSpacing(10)
        kl.addWidget(self.card_back)
        kl.addStretch(1)
        cl.addWidget(self.card, 1)
        bar = QHBoxLayout()
        self.b_listen = btn("  послушать", None, "speaker")
        self.b_listen.clicked.connect(lambda: self._cur and self.speak_requested.emit(self._cur["text"], self._cur["src"]))
        self.b_show = btn("показать перевод", "primary")
        self.b_show.clicked.connect(self._card_flip)
        self.b_no = btn("не помню")
        self.b_no.clicked.connect(lambda: self._card_answer(False))
        self.b_yes = btn("помню", "primary")
        self.b_yes.clicked.connect(lambda: self._card_answer(True))
        b_stop = btn("закончить", "ghost")
        b_stop.clicked.connect(self._vocab_list_mode)
        bar.addWidget(b_stop)
        bar.addStretch(1)
        for b in (self.b_listen, self.b_show, self.b_no, self.b_yes):
            bar.addWidget(b)
        cl.addLayout(bar)
        self.vocab_stack.addWidget(cw)
        l.addWidget(self.vocab_stack, 1)
        self._vocab_items = []
        self._queue = []
        self._cur = None
        return w

    def fill_vocab(self, items, due_count=None):
        self._vocab_items = items
        q = self.vocab_search.text().strip().lower()
        self.vocab_list.clear()
        for it in items:
            if q and q not in it["text"].lower() and q not in it["out"].lower():
                continue
            box = it.get("box", 0)
            row = QListWidgetItem(f"{it['text']}  →  {it['out']}\n{it['src']} → {it['tgt']} · "
                                  f"{'новое' if box == 0 else f'выучено на {box}/5'}")
            row.setData(Qt.ItemDataRole.UserRole, it)
            self.vocab_list.addItem(row)
        if not items:
            row = QListWidgetItem("пока пусто: нажмите ☆ у любого перевода")
            row.setFlags(Qt.ItemFlag.NoItemFlags)
            self.vocab_list.addItem(row)
        due = due_count if due_count is not None else len(items)
        self.vocab_info.setText(f"{len(items)} слов · к повторению {due}")
        self.study_btn.setEnabled(due > 0)

    def _vocab_delete(self):
        it = self.vocab_list.currentItem()
        if it and it.data(Qt.ItemDataRole.UserRole):
            self.vocab_remove.emit(it.data(Qt.ItemDataRole.UserRole))

    def _export(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "Экспорт словарика", os.path.expanduser("~/Desktop/вавилон-словарик.csv"),
                                              "CSV для Anki (*.csv)")
        if path:
            self.vocab_export.emit(path)

    def _study_start(self):
        self.study_requested.emit()

    def start_study(self, queue):
        self._queue = list(queue)
        self.vocab_stack.setCurrentIndex(1)
        self._next_card()

    def _vocab_list_mode(self):
        self.vocab_stack.setCurrentIndex(0)

    def _next_card(self):
        if not self._queue:
            self._cur = None
            self.card_meta.setText("")
            self.card_front.setText("на сегодня всё")
            self.card_back.setText("возвращайтесь завтра — слова придут на повторение сами")
            for b in (self.b_show, self.b_no, self.b_yes, self.b_listen):
                b.hide()
            return
        self._cur = self._queue.pop(0)
        self.card_meta.setText(f"{name(self._cur['src'])} → {name(self._cur['tgt'])} · осталось {len(self._queue) + 1}")
        self.card_front.setText(self._cur["text"])
        self.card_back.setText("")
        self.b_show.show()
        self.b_listen.show()
        self.b_no.hide()
        self.b_yes.hide()

    def _card_flip(self):
        if self._cur:
            self.card_back.setText(self._cur["out"])
            self.b_show.hide()
            self.b_no.show()
            self.b_yes.show()

    def _card_answer(self, ok: bool):
        if self._cur:
            self.vocab_answer.emit(self._cur, ok)
            if not ok:
                self._queue.append(self._cur)  # «не помню» — ещё раз в конце
            self._next_card()

    # ================= история =================
    def _page_history(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(_header("история", "последние переводы"))
        top.addStretch(1)
        b = btn("  очистить", "ghost", "trash", theme.MUTED)
        b.clicked.connect(self.history_cleared)
        top.addWidget(b)
        l.addLayout(top)
        self.hist_search = QLineEdit(placeholderText="поиск по истории…")
        self.hist_search.addAction(icon("search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.hist_search.textChanged.connect(lambda: self.fill_history(self._hist_items))
        l.addWidget(self.hist_search)
        self.hist = QListWidget()
        self.hist.setWordWrap(True)
        self.hist.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hist.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.hist.itemClicked.connect(self._open_history)
        l.addWidget(self.hist, 1)
        self._hist_items = []
        return w

    def fill_history(self, items):
        self._hist_items = items
        q = self.hist_search.text().strip().lower()
        self.hist.clear()
        short = lambda s: " ".join(s.split())[:140] + ("…" if len(s) > 140 else "")
        for h in items:
            if q and q not in h["text"].lower() and q not in h["out"].lower():
                continue
            it = QListWidgetItem(f"{short(h['text'])}\n{short(h['out'])}")
            it.setToolTip(f"{name(h['src'])} → {name(h['tgt'])}")
            it.setData(Qt.ItemDataRole.UserRole, h)
            self.hist.addItem(it)
        if not items:
            it = QListWidgetItem("пока пусто")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.hist.addItem(it)

    def _open_history(self, it):
        h = it.data(Qt.ItemDataRole.UserRole)
        if not h:
            return
        self.src_btn.set_code(h["src"] if h["src"] in LANGS else "auto", emit=False)
        self.tgt_btn.set_code(h["tgt"], emit=False)
        self.set_text(h["text"])

    # ================= языки =================
    def _page_langs(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        l.addWidget(_header("языки", "офлайн-перевод"))
        l.addWidget(_label(f"онлайн доступны все {len(LANGS)} языков без скачивания. чтобы переводить без "
                           "интернета, скачайте нужные: каждый переводится на русский и обратно "
                           "(через английский, он скачается вместе с первым языком).", "muted", wrap=True))
        self.lang_search = QLineEdit(placeholderText="поиск языка…")
        self.lang_search.addAction(icon("search", theme.MUTED), QLineEdit.ActionPosition.LeadingPosition)
        self.lang_search.textChanged.connect(self._filter_langs)
        l.addWidget(self.lang_search)
        scroll = QScrollArea(widgetResizable=True)
        holder = QWidget()
        self.lang_grid = QGridLayout(holder)
        self.lang_grid.setContentsMargins(0, 0, 6, 0)
        self.lang_grid.setHorizontalSpacing(10)
        self.lang_grid.setVerticalSpacing(8)
        self.model_rows = {}
        codes = [c for c in LANGS if c in OFFLINE and c != "en"]
        for i, code in enumerate(codes):
            ru, own = LANGS[code]
            card = _card()
            cl = QHBoxLayout(card)
            cl.setContentsMargins(16, 10, 10, 10)
            names = QVBoxLayout()
            names.setSpacing(1)
            t = _label("английский ⇄ русский" if code == "ru" else f"{ru.lower()} ⇄ русский")
            t.setStyleSheet("font-weight: 700;")
            sub = _label("", "faint")
            names.addWidget(t)
            names.addWidget(sub)
            cl.addLayout(names, 1)
            bar = QProgressBar(maximum=1000)
            bar.setFixedWidth(110)
            bar.hide()
            cl.addWidget(bar)
            act = btn("")
            act.clicked.connect(lambda _=False, c=code: self._model_action(c))
            cl.addWidget(act)
            self.lang_grid.addWidget(card, i // 2, i % 2)
            self.model_rows[code] = (sub, bar, act, card, f"{code} {ru} {own}".lower())
        self.lang_grid.setRowStretch(len(codes) // 2 + 1, 1)
        scroll.setWidget(holder)
        l.addWidget(scroll, 1)
        return w

    def _filter_langs(self, text):
        t = text.strip().lower()
        for code, (_, _, _, card, key) in self.model_rows.items():
            card.setVisible(not t or t in key)

    def _model_action(self, code):
        sub, bar, act, *_ = self.model_rows[code]
        if act.property("installed"):
            self.remove_requested.emit(code)
        else:
            self.download_requested.emit(code)

    def set_model_state(self, code: str, installed: bool, size_mb: int, busy: bool = False):
        if code not in self.model_rows:
            return
        sub, bar, act, *_ = self.model_rows[code]
        act.setProperty("installed", installed)
        act.setEnabled(not busy)
        bar.setVisible(busy)
        if busy:
            sub.setText("скачиваю…")
            act.setText("подождите")
            return
        if installed:
            sub.setText("скачан · работает без интернета")
            sub.setProperty("role", "badge-ok")
            act.setText("удалить")
            act.setProperty("kind", "ghost")
            act.setIcon(icon("trash", theme.MUTED))
        else:
            sub.setText(f"≈{size_mb} МБ")
            sub.setProperty("role", "faint")
            act.setText("  скачать")
            act.setProperty("kind", "primary")
            act.setIcon(icon("download", "#0a0a0a"))
        repolish(sub)
        repolish(act)

    def set_model_progress(self, code: str, done: int, total: int):
        if code not in self.model_rows:
            return
        sub, bar, *_ = self.model_rows[code]
        bar.show()
        bar.setValue(int(done * 1000 / total) if total else 0)
        sub.setText(f"скачиваю… {done / 1048576:.0f} из {total / 1048576:.0f} МБ" if total else "скачиваю…")

    def model_error(self, code: str, err: str):
        if code in self.model_rows:
            sub = self.model_rows[code][0]
            sub.setText(f"не удалось скачать: {err[:80]}")
            sub.setToolTip(err)

    # ================= настройки =================
    def _page_settings(self, ocr_langs):
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(_header("настройки", "как работает вавилон"))
        scroll = QScrollArea(widgetResizable=True)
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 8, 8, 0)
        l.setSpacing(12)
        s = self.s

        def section(title):
            c = _card()
            g = QGridLayout(c)
            g.setColumnMinimumWidth(0, 230)
            g.setContentsMargins(18, 14, 18, 14)
            g.setHorizontalSpacing(16)
            g.setVerticalSpacing(10)
            g.addWidget(_label(title, "h2"), 0, 0, 1, 3)
            g.setColumnStretch(2, 1)
            l.addWidget(c)
            return g

        def combo(items, current, key):
            cb = QComboBox()
            for val, text in items:
                cb.addItem(text, val)
            cb.setCurrentIndex(max(0, cb.findData(current)))
            cb.currentIndexChanged.connect(lambda: self._set(key, cb.currentData()))
            return cb

        lang_items = [(c, n[0].lower()) for c, n in LANGS.items()]

        g = section("перевод")
        g.addWidget(_label("режим"), 1, 0)
        g.addWidget(combo(list(MODES.items()), s["mode"], "mode"), 1, 1)
        g.addWidget(_label("онлайн — google: лучше и 100+ языков, но текст уходит в интернет", "faint", True), 1, 2)
        g.addWidget(_label("переводить на"), 2, 0)
        g.addWidget(combo(lang_items, s["preferred"], "preferred"), 2, 1)
        g.addWidget(_label("а текст на этом языке — на"), 3, 0)
        g.addWidget(combo(lang_items, s["fallback"], "fallback"), 3, 1)
        g.addWidget(_label("заменять свой текст на"), 4, 0)
        g.addWidget(combo(lang_items, s["replace_target"], "replace_target"), 4, 1)
        g.addWidget(_label("для клавиши «заменить переводом»", "faint"), 4, 2)

        g = section("клавиши")
        self.hk_edits = {}
        rows = [("selection", "перевести выделенное"), ("replace", "заменить выделенное переводом"),
                ("screen", "перевести область экрана"), ("live", "живые субтитры: вкл / выкл"),
                ("hear", "перевод речи из звука компьютера"),
                ("window", "открыть это окно")]
        for i, (key, label) in enumerate(rows, start=1):
            g.addWidget(_label(label), i, 0)
            e = HotkeyEdit(s["hotkeys"].get(key, ""))
            e.setFixedWidth(200)
            e.changed.connect(lambda v, k=key: self._set_hotkey(k, v))
            g.addWidget(e, i, 1)
            err = _label("", "error")
            g.addWidget(err, i, 2)
            self.hk_edits[key] = e
            self.hk_edits[key + "_err"] = err
        dc = Toggle("двойное ctrl+c — перевести скопированное")
        dc.setChecked(s["double_copy"])
        dc.toggled.connect(lambda v: self._set("double_copy", v))
        g.addWidget(dc, len(rows) + 1, 0, 1, 3)

        g = section("вид")
        g.addWidget(_label("прозрачность"), 1, 0)
        sl = QSlider(Qt.Orientation.Horizontal, minimum=40, maximum=100, value=int(s["opacity"]))
        sl.setFixedWidth(200)
        sl.setInvertedAppearance(False)
        sl.valueChanged.connect(lambda v: self._set("opacity", v))
        g.addWidget(sl, 1, 1)
        g.addWidget(_label("левее — прозрачнее. фон под окном размывается, текст остаётся чётким", "faint", True), 1, 2)
        g.addWidget(_label("размер текста перевода"), 2, 0)
        fs = QSlider(Qt.Orientation.Horizontal, minimum=10, maximum=18, value=int(s["font_size"]))
        fs.setFixedWidth(200)
        fs.valueChanged.connect(lambda v: self._set("font_size", float(v)))
        g.addWidget(fs, 2, 1)
        g.addWidget(_label("цвет акцента"), 3, 0)
        sw = QWidget()
        swl = QHBoxLayout(sw)
        swl.setContentsMargins(0, 0, 0, 0)
        swl.setSpacing(8)
        self.swatches = QButtonGroup(self)
        for color, title in theme.ACCENTS.items():
            b = Swatch(color, title)
            b.setChecked(color == s.get("accent", theme.DEFAULT_ACCENT))
            b.clicked.connect(lambda _=False, c=color: self._set("accent", c))
            self.swatches.addButton(b)
            swl.addWidget(b)
        swl.addStretch(1)
        g.addWidget(sw, 3, 1, 1, 2)
        g.addWidget(_label("ширина всплывашки"), 4, 0)
        pw = QSlider(Qt.Orientation.Horizontal, minimum=400, maximum=720, value=int(s["popup_width"]))
        pw.setFixedWidth(200)
        pw.valueChanged.connect(lambda v: self._set("popup_width", v))
        g.addWidget(pw, 4, 1)

        g = section("перевод речи")
        g.addWidget(_label("распознавание"), 1, 0)
        g.addWidget(combo([("base", "быстрое (модель 145 мб)"), ("small", "точное (485 мб, медленнее)")],
                          s.get("asr_model", "base"), "asr_model"), 1, 1)
        g.addWidget(_label("модель скачается при первом запуске в разделе «разговор»", "faint", True), 1, 2)
        g.addWidget(_label("размер субтитров"), 2, 0)
        ss = QSlider(Qt.Orientation.Horizontal, minimum=20, maximum=48, value=int(s.get("subs_size", 30)))
        ss.setFixedWidth(200)
        ss.valueChanged.connect(lambda v: self._set("subs_size", v))
        g.addWidget(ss, 2, 1)
        g.addWidget(_label("плотность фона субтитров"), 3, 0)
        so = QSlider(Qt.Orientation.Horizontal, minimum=30, maximum=100, value=int(s.get("subs_opacity", 86)))
        so.setFixedWidth(200)
        so.valueChanged.connect(lambda v: self._set("subs_opacity", v))
        g.addWidget(so, 3, 1)
        g.addWidget(_label("где показывать"), 4, 0)
        g.addWidget(combo([("bottom", "внизу экрана"), ("top", "вверху экрана")], s.get("subs_pos", "bottom"),
                          "subs_pos"), 4, 1)
        og = Toggle("показывать оригинал мелко над переводом")
        og.setChecked(s.get("subs_original", True))
        og.toggled.connect(lambda v: self._set("subs_original", v))
        g.addWidget(og, 5, 0, 1, 3)

        g = section("распознавание текста с экрана")
        g.addWidget(_label("язык на картинках"), 1, 0)
        ocr_items = [("auto", "определять сам")] + [(c, name(c)) for c in ocr_langs]
        g.addWidget(combo(ocr_items, s["ocr_lang"], "ocr_lang"), 1, 1)
        note = _label("установлено: " + (", ".join(ocr_langs) if ocr_langs else "ничего"), "faint" if ocr_langs else "error")
        note.setToolTip("Параметры Windows → Время и язык → Язык и регион → добавить язык → "
                        "Языковые параметры → «Оптическое распознавание символов»")
        g.addWidget(note, 1, 2)

        from ..config import VERSION

        g = section("система")
        au = Toggle("запускать вместе с windows")
        au.setChecked(s["autostart"])
        au.toggled.connect(lambda v: self._set("autostart", v))
        g.addWidget(au, 1, 0, 1, 3)
        g.addWidget(_label(f"версия {VERSION}. новая версия ставится поверх этой: языки, словарик и "
                           "история останутся.", "muted", True), 2, 0, 1, 2)
        ub = QHBoxLayout()
        ub.addStretch(1)
        self.b_check = btn("  проверить обновления", "primary", "download")
        self.b_check.clicked.connect(self.check_updates_requested)
        ub.addWidget(self.b_check)
        b_upd = btn("  из архива…", None, "doc")
        b_upd.setToolTip("Поставить версию из скачанного архива (можно просто перетащить архив на окно)")
        b_upd.clicked.connect(self._pick_update)
        ub.addWidget(b_upd)
        g.addLayout(ub, 2, 2)
        cu = Toggle("проверять обновления раз в день")
        cu.setChecked(s.get("check_updates", True))
        cu.toggled.connect(lambda v: self._set("check_updates", v))
        g.addWidget(cu, 3, 0, 1, 2)
        self.upd_status = _label("", "faint", True)
        g.addWidget(self.upd_status, 3, 2)
        self.upd_prog = QProgressBar(maximum=1000, textVisible=False)
        self.upd_prog.hide()
        g.addWidget(self.upd_prog, 4, 0, 1, 3)

        l.addStretch(1)
        l.addWidget(_label("перевод: google, mymemory, argos translate (офлайн) · распознавание и голоса: windows",
                           "faint"))
        scroll.setWidget(w)
        ol.addWidget(scroll, 1)
        return outer

    def set_update_status(self, text: str, progress: float | None = None):
        self.upd_status.setText(text)
        self.upd_prog.setVisible(progress is not None)
        if progress is not None:
            self.upd_prog.setValue(int(progress * 1000))
        self.b_check.setEnabled(progress is None)

    def _pick_update(self):
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "Архив с новой версией Вавилона",
                                              os.path.expanduser("~/Downloads"), "Архив (*.zip)")
        if path:
            self.update_requested.emit(path)

    def dragEnterEvent(self, e):
        from .media import kind_of

        if any(u.toLocalFile().lower().endswith(".zip") or kind_of(u.toLocalFile()) for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        from .media import kind_of

        for u in e.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(".zip"):
                self.update_requested.emit(path)
                return
            if kind_of(path):  # фото или видео, брошенные на любой раздел
                self.show_page("media")
                self.media.open(path)
                return

    def _set(self, key, value):
        self.s[key] = value
        self.settings_changed.emit({key: value})

    def _set_hotkey(self, key, value):
        self.s["hotkeys"][key] = value
        self.hk_edits[key + "_err"].setText("")
        self.settings_changed.emit({"hotkeys": dict(self.s["hotkeys"])})

    def hotkey_error(self, key: str, msg: str):
        if key + "_err" in self.hk_edits:
            self.hk_edits[key + "_err"].setText(msg)
