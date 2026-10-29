"""Раздел «фото и видео»: перевод прямо на картинке (как Google Объектив) и перевод надписей в видео.

Фото: распознаём строки с рамками, склеиваем в абзацы, переводим и рисуем перевод на месте текста.
Видео: находим надписи и субтитры по времени, показываем видео с переводом поверх и сохраняем
новый файл (со звуком) или субтитры .srt.
"""
import os
import threading
import time

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QProgressBar, QSlider, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import docs, lens, ocr, video
from ..ocr import Line
from . import theme
from .icons import icon
from .widgets import LangButton, btn

FILTER = ("Фото, видео и документы (" + " ".join("*" + e for e in video.IMAGE_EXT + video.VIDEO_EXT + docs.EXT) + ");;"
          "Документы (" + " ".join("*" + e for e in docs.EXT) + ");;"
          "Фото (" + " ".join("*" + e for e in video.IMAGE_EXT) + ");;"
          "Видео (" + " ".join("*" + e for e in video.VIDEO_EXT) + ")")


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    return ("image" if ext in video.IMAGE_EXT else "video" if ext in video.VIDEO_EXT
            else "doc" if ext in docs.EXT else None)


class _Bus(QObject):
    photo_done = Signal(int, object, object, object)   # номер, блоки, переводы, картинка с переводом
    photo_failed = Signal(int, str)
    probe_done = Signal(int, object, object)            # номер, сведения о видео, первый кадр
    progress = Signal(int, str, int, int)               # номер, что делаем, сделано, всего
    video_done = Signal(int, object, float)             # номер, отрезки, масштаб
    video_ready = Signal(int)                           # номер: переводы надписей готовы
    doc_done = Signal(int, str, int)                    # номер, путь к переводу, сколько фрагментов
    video_failed = Signal(int, str)
    frame = Signal(int, float, QImage)                  # номер показа, время, кадр
    saved = Signal(str, str)                            # путь, ошибка


class Canvas(QWidget):
    """Картинка или кадр видео, вписанные в рамку со скруглением; можно показать оригинал."""

    def __init__(self):
        super().__init__()
        self.img: QImage | None = None
        self.overlay = None          # функция: картинка → картинка с переводом (для кадров видео)
        self.hint = ""
        self.setMinimumSize(320, 200)

    def set_image(self, img: QImage | None):
        self.img = img
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if not self.img or self.img.isNull():
            return
        k = min(r.width() / self.img.width(), r.height() / self.img.height())
        w, h = self.img.width() * k, self.img.height() * k
        box = QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)
        path = QPainterPath()
        path.addRoundedRect(box, 14, 14)
        p.setClipPath(path)
        p.drawImage(box, self.img)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawPath(path)
        if self.hint:
            p.setFont(theme.font(10.5, QFont.Weight.DemiBold))
            tw = p.fontMetrics().horizontalAdvance(self.hint) + 34
            pill = QRectF(box.center().x() - tw / 2, box.bottom() - 54, tw, 36)
            pp = QPainterPath()
            pp.addRoundedRect(pill, 18, 18)
            p.fillPath(pp, QColor(12, 12, 14, 225))
            p.setPen(QColor(theme.TEXT))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.hint)


class DropZone(QWidget):
    def __init__(self):
        super().__init__()
        self.hover = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(r, 22, 22)
        p.fillPath(path, QColor(255, 255, 255, 22 if self.hover else 12))
        pen = QPen(theme.accent(200) if self.hover else QColor(255, 255, 255, 60), 1.6, Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 5])
        p.setPen(pen)
        p.drawPath(path)


class MediaPage(QWidget):
    """translate(text, tgt) → перевод (вызывается в фоновых потоках). note — пометка к языкам."""

    live_requested = Signal()

    def __init__(self, settings, translate, note=None):
        super().__init__()
        self.s = settings
        self.translate = translate
        self.bus = _Bus()
        self.job = 0
        self.path = ""
        self.kind = None
        self.src_img: QImage | None = None
        self.result_img: QImage | None = None
        self.blocks, self.outs = [], []
        self.info = None
        self.segments = []
        self.k = 1.0
        self.play_id = 0
        self.playing = False
        self.pos = 0.0
        self._stop = threading.Event()
        self._play_stop = threading.Event()
        self.show_orig = False
        self.last_frame = None
        self.setAcceptDrops(True)

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(12)
        head = QHBoxLayout()
        tl = QVBoxLayout()
        tl.setSpacing(0)
        cap = QLabel("файлы")
        cap.setProperty("role", "caption")
        tl.addWidget(cap)
        self.title = QLabel("фото, видео и документы")
        self.title.setProperty("role", "title")
        tl.addWidget(self.title)
        head.addLayout(tl, 1)
        head.addWidget(QLabel("на", styleSheet=f"color: {theme.MUTED};"))
        self.tgt = LangButton(settings["preferred"], note=note)
        self.tgt.changed.connect(self._retarget)
        head.addWidget(self.tgt)
        l.addLayout(head)

        self.stack = QStackedWidget()
        l.addWidget(self.stack, 1)

        # --- пусто: куда бросить файл ---
        self.drop = DropZone()
        dl = QVBoxLayout(self.drop)
        dl.setContentsMargins(30, 30, 30, 30)
        dl.addStretch(1)
        ic = QLabel()
        ic.setPixmap(icon("scan", theme.TEXT, 44).pixmap(QSize(44, 44)))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(ic)
        big = QLabel("перетащите сюда фото, видео или документ")
        big.setStyleSheet("font-size: 16pt; font-weight: 800;")
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(big)
        small = QLabel("текст на картинке заменится переводом, как в google объективе. в видео переводятся субтитры и надписи.\n"
                       "документы word и pdf переводятся с сохранением оформления — рядом появится копия с переводом.")
        small.setProperty("role", "muted")
        small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(small)
        dl.addSpacing(14)
        row = QHBoxLayout()
        row.addStretch(1)
        b = btn("  выбрать файл…", "primary", "download")
        b.clicked.connect(self.pick)
        row.addWidget(b)
        b = btn("  вставить картинку · ctrl+v", None, "copy")
        b.clicked.connect(self.paste)
        row.addWidget(b)
        self.b_live = btn("  живые субтитры поверх видео", None, "subs")
        self.b_live.setToolTip("Перевод субтитров прямо во время просмотра, в любом плеере или браузере")
        self.b_live.clicked.connect(self.live_requested)
        row.addWidget(self.b_live)
        row.addStretch(1)
        dl.addLayout(row)
        dl.addSpacing(8)
        fmt = QLabel("png, jpg, webp, bmp · mp4, mkv, mov, webm, avi · docx, pdf, txt, srt")
        fmt.setProperty("role", "faint")
        fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dl.addWidget(fmt)
        dl.addStretch(1)
        self.stack.addWidget(self.drop)

        # --- результат ---
        res = QWidget()
        rl = QVBoxLayout(res)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        self.canvas = Canvas()
        rl.addWidget(self.canvas, 1)
        self.vbar = QWidget()
        vb = QHBoxLayout(self.vbar)
        vb.setContentsMargins(0, 0, 0, 0)
        self.b_play = btn("", "icon", "play", theme.TEXT, "Смотреть (пробел)")
        self.b_play.clicked.connect(self.toggle_play)
        vb.addWidget(self.b_play)
        self.slider = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=1000)
        self.slider.sliderReleased.connect(self._seek)
        self.slider.sliderMoved.connect(lambda v: self.time_lbl.setText(self._fmt(self._slider_t())))
        vb.addWidget(self.slider, 1)
        self.time_lbl = QLabel("0:00")
        self.time_lbl.setProperty("role", "muted")
        self.time_lbl.setMinimumWidth(90)
        vb.addWidget(self.time_lbl)
        rl.addWidget(self.vbar)
        self.prog = QProgressBar(maximum=1000)
        rl.addWidget(self.prog)
        foot = QHBoxLayout()
        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        foot.addWidget(self.status, 1)
        self.b_orig = btn("  оригинал", "ghost", "swap", theme.MUTED, "Пока нажата — показать оригинал")
        self.b_orig.pressed.connect(lambda: self._show_original(True))
        self.b_orig.released.connect(lambda: self._show_original(False))
        foot.addWidget(self.b_orig)
        self.b_text = btn("  текст", None, "copy", theme.TEXT, "Копировать переведённый текст")
        self.b_text.clicked.connect(self.copy_text)
        foot.addWidget(self.b_text)
        self.b_srt = btn("  субтитры .srt", None, "download", theme.TEXT, "Сохранить перевод субтитрами")
        self.b_srt.clicked.connect(self.save_srt)
        foot.addWidget(self.b_srt)
        self.b_save = btn("  сохранить", "primary", "download")
        self.b_save.clicked.connect(self.save)
        foot.addWidget(self.b_save)
        self.b_folder = btn("  показать в папке", None, "doc")
        self.b_folder.clicked.connect(self._show_in_folder)
        foot.addWidget(self.b_folder)
        self.b_close = btn("", "icon", "close", theme.MUTED, "Другой файл")
        self.b_close.clicked.connect(self.reset)
        foot.addWidget(self.b_close)
        rl.addLayout(foot)
        self.stack.addWidget(res)

        self.bus.photo_done.connect(self._photo_done)
        self.bus.photo_failed.connect(self._failed)
        self.bus.video_failed.connect(self._failed)
        self.bus.probe_done.connect(self._probe_done)
        self.bus.progress.connect(self._progress)
        self.bus.video_done.connect(self._video_done)
        self.bus.video_ready.connect(self._video_ready)
        self.bus.doc_done.connect(self._doc_done)
        self.bus.frame.connect(self._frame)
        self.bus.saved.connect(self._saved)
        QShortcut(QKeySequence("Ctrl+V"), self, self.paste)
        QShortcut(QKeySequence("Space"), self, lambda: self.kind == "video" and self.toggle_play())
        self.reset()

    # ---------------- общее ----------------
    def reset(self):
        self.job += 1
        self._stop.set()
        self._stop_play()
        self.kind, self.path = None, ""
        self.src_img = self.result_img = None
        self.segments, self.blocks, self.outs = [], [], []
        self.title.setText("фото, видео и документы")
        self.stack.setCurrentIndex(0)

    def pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Фото или видео для перевода", os.path.expanduser("~"), FILTER)
        if path:
            self.open(path)

    def paste(self):
        img = QGuiApplication.clipboard().image()
        if not img.isNull():
            self.open_image(img, "картинка из буфера")
        else:
            urls = QGuiApplication.clipboard().mimeData().urls()
            files = [u.toLocalFile() for u in urls if kind_of(u.toLocalFile())]
            if files:
                self.open(files[0])

    def open(self, path: str):
        k = kind_of(path)
        if k == "image":
            img = QImage(path)
            if img.isNull():
                self._failed(self.job, "не получилось открыть картинку")
                return
            self.open_image(img, os.path.basename(path), path)
        elif k == "video":
            self.open_video(path)
        elif k == "doc":
            self.open_doc(path)

    def _begin(self, kind, title):
        self.job += 1
        self._stop.set()
        self._stop = threading.Event()
        self._stop_play()
        self.kind = kind
        self.title.setText(title if len(title) < 46 else title[:43] + "…")
        self.stack.setCurrentIndex(1)
        self.prog.setValue(0)
        self.prog.show()
        is_video = kind == "video"
        self.vbar.setVisible(is_video)
        self.b_srt.setVisible(is_video)
        self.b_text.setVisible(kind == "image")
        self.b_orig.setVisible(kind != "doc")
        self.b_folder.setVisible(kind == "doc")
        self.b_save.setText("  открыть" if kind == "doc" else "  сохранить")
        for b in (self.b_save, self.b_text, self.b_srt, self.b_orig):
            b.setEnabled(False)
        return self.job

    def _failed(self, job, msg):
        if job != self.job:
            return
        self.prog.hide()
        self.canvas.hint = ""
        self.canvas.update()
        self.status.setText(msg)
        self.status.setStyleSheet(f"color: {theme.ACCENT};")

    def _say(self, text):
        self.status.setStyleSheet("")
        self.status.setText(text)

    def _progress(self, job, what, done, total):
        if job != self.job:
            return
        self.prog.setValue(int(1000 * done / max(1, total)))
        self._say(what)

    def _retarget(self, _code):
        if self.kind == "image" and self.src_img is not None:
            self.open_image(self.src_img, self.title.text(), self.path)
        elif self.kind == "video" and self.segments:
            self._translate_video(self.job)
        elif self.kind == "doc" and self.path:
            self.open_doc(self.path)

    def _show_original(self, on: bool):
        if self.kind == "image":
            self.canvas.set_image(self.src_img if on or self.result_img is None else self.result_img)
        else:
            self.show_orig = on
            if self.last_frame is not None:
                self._frame(self.play_id, self.pos, self.last_frame)

    def copy_text(self):
        QGuiApplication.clipboard().setText("\n\n".join(o for o in self.outs if o.strip()))
        self._say("перевод скопирован")

    # ---------------- фото ----------------
    def open_image(self, img: QImage, title: str, path: str = ""):
        job = self._begin("image", title)
        self.path = path
        self.src_img = img.convertToFormat(QImage.Format.Format_ARGB32)
        self.result_img = None
        self.canvas.set_image(self.src_img)
        self.canvas.hint = "ищу текст…"
        self._say("распознаю текст на картинке")
        tgt = self.tgt.code
        src = self.src_img

        def run():
            try:
                w, h = src.width(), src.height()
                k = 1.0
                if max(w, h) > 4000:      # огромные фото: быстрее и в пределах OCR Windows
                    k = 4000 / max(w, h)
                elif max(w, h) < 900:     # мелкий текст читается лучше увеличенным
                    k = 2.0
                im = src if k == 1.0 else src.scaled(int(w * k), int(h * k), Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)
                im = im.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                lines, lang, _ = ocr.read_auto(bytes(im.constBits())[: im.width() * im.height() * 4],
                                               im.width(), im.height(), self.s.get("ocr_lang", "auto"))
                lines = [Line(l.text, l.x / k, l.y / k, l.w / k, l.h / k) for l in lines]
                blocks = lens.group(lines)
                if not blocks:
                    self.bus.photo_failed.emit(job, "на картинке не нашлось текста")
                    return
                self.bus.progress.emit(job, f"перевожу {len(blocks)} фрагм.", 1, 2)
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(4) as ex:
                    outs = list(ex.map(lambda b: self.translate(b.text, tgt), blocks))
                self.bus.photo_done.emit(job, blocks, outs, lens.paint(src, blocks, outs, "photo"))
            except ocr.OcrUnavailable as e:
                self.bus.photo_failed.emit(job, str(e).lower())
            except Exception as e:
                self.bus.photo_failed.emit(job, f"не получилось: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _photo_done(self, job, blocks, outs, img):
        if job != self.job:
            return
        self.blocks, self.outs, self.result_img = blocks, outs, img
        self.canvas.hint = ""
        self.canvas.set_image(img)
        self.prog.hide()
        self._say(f"переведено: {sum(1 for o in outs if o.strip())} · зажмите «оригинал» для сравнения")
        for b in (self.b_save, self.b_text, self.b_orig):
            b.setEnabled(True)

    # ---------------- видео ----------------
    def open_video(self, path: str):
        job = self._begin("video", os.path.basename(path))
        self.path = path
        self.segments = []
        self.info = None
        self.pos = 0.0
        self.show_orig = False
        self.last_frame = None
        self.canvas.set_image(None)
        self.canvas.hint = "ищу надписи…"
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        self.b_play.setEnabled(False)
        self._say("открываю видео")
        stop = self._stop
        reader = self._video_reader()

        def run():
            try:
                info = video.probe(path)
                w, h = video.analysis_size(info)
                first = next(video.frames(path, w, h, fps=1), None)
                self.bus.probe_done.emit(job, info, QImage(first[1], w, h, QImage.Format.Format_ARGB32).copy()
                                         if first else None)
                t0 = time.perf_counter()

                def prog(d, t):
                    left = (time.perf_counter() - t0) / d * (t - d)
                    self.bus.progress.emit(job, f"ищу субтитры и надписи · осталось ≈ {int(left) + 1} с", d, t)

                info, segs, k = video.analyze(path, reader, prog, stop)
                self.bus.progress.emit(job, f"перевожу {len({b.text for s in segs for b in s.blocks})} фраз", 1, 1)
                self.bus.video_done.emit(job, segs, k)
            except video.VideoError as e:
                self.bus.video_failed.emit(job, str(e))
            except ocr.OcrUnavailable as e:
                self.bus.video_failed.emit(job, str(e).lower())
            except Exception as e:
                self.bus.video_failed.emit(job, f"не получилось: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _video_reader(self):
        """OCR кадров: язык определяем по первым надписям, дальше читаем только им (быстрее)."""
        state = {"lang": None if self.s.get("ocr_lang", "auto") == "auto" else self.s["ocr_lang"]}

        def read(buf, w, h):
            if state["lang"]:
                return ocr.read(buf, w, h, state["lang"])
            lines, lang, sc = ocr.read_auto(buf, w, h, "auto")
            if lines and sc >= 0.5:
                state["lang"] = lang
            return lines

        return read

    def _probe_done(self, job, info, first):
        if job != self.job:
            return
        self.info = info
        if first is not None:
            self.last_frame = first
            self.canvas.set_image(first)
        self.time_lbl.setText(f"0:00 / {self._fmt(info.duration)}")

    def _video_done(self, job, segs, k):
        if job != self.job:
            return
        self.segments, self.k = segs, k
        if not segs:
            self._failed(job, "в видео не нашлось субтитров или надписей")
            return
        self._translate_video(job)

    def _translate_video(self, job):
        tgt = self.tgt.code
        segs = self.segments
        self.canvas.hint = "перевожу…"
        self.canvas.update()

        def run():
            try:
                video.translate_segments(segs, lambda t: self.translate(t, tgt))
                self.bus.video_ready.emit(job)
            except Exception as e:
                self.bus.video_failed.emit(job, f"не получилось перевести: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _video_ready(self, job):
        if job != self.job:
            return
        self.canvas.hint = ""
        self.prog.hide()
        n = sum(1 for s in self.segments if any(o.strip() for o in s.outs))
        self._say(f"переведено надписей: {n}")
        self.slider.setEnabled(True)
        self.b_play.setEnabled(True)
        for b in (self.b_save, self.b_srt, self.b_orig):
            b.setEnabled(True)
        self._show_at(self.pos)

    # --- просмотр (без звука; со звуком — в сохранённом файле) ---
    def _fmt(self, t):
        t = int(t)
        return f"{t // 60}:{t % 60:02d}"

    def _slider_t(self):
        return self.slider.value() / 1000 * (self.info.duration if self.info else 0)

    def _stop_play(self):
        self._play_stop.set()
        self.playing = False
        self.play_id += 1
        self.b_play.setIcon(icon("play", theme.TEXT))

    def toggle_play(self):
        if not self.info or not self.segments:
            return
        if self.playing:
            self._stop_play()
            return
        if self.pos >= self.info.duration - 0.2:
            self.pos = 0.0
        self._run_player(self.pos, single=False)

    def _seek(self):
        was = self.playing
        self._stop_play()
        self.pos = self._slider_t()
        self._run_player(self.pos, single=not was)

    def _show_at(self, t):
        self._run_player(t, single=True)

    def _run_player(self, start, single):
        self._play_stop = threading.Event()
        stop = self._play_stop
        self.play_id += 1
        pid = self.play_id
        info, path = self.info, self.path
        w, h = video.analysis_size(info)
        fps = min(30.0, info.fps or 25.0)
        if not single:
            self.playing = True
            self.b_play.setIcon(icon("pause", theme.TEXT))

        def run():
            for t, buf in video.frames(path, w, h, fps=fps, start=start, realtime=not single, stop=stop):
                self.bus.frame.emit(pid, t, QImage(buf, w, h, QImage.Format.Format_ARGB32).copy())
                if single:
                    break
            if not single and not stop.is_set():
                self.bus.frame.emit(pid, -1.0, QImage())  # конец

        threading.Thread(target=run, daemon=True).start()

    def _frame(self, pid, t, img):
        if pid != self.play_id:
            return
        if t < 0:
            self._stop_play()
            return
        self.pos, self.last_frame = t, img
        seg = video.at(self.segments, t)
        if seg and not getattr(self, "show_orig", False) and any(o.strip() for o in seg.outs):
            p = QPainter(img := img.copy())
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            for b, o in zip(seg.blocks, seg.outs):
                if o.strip():
                    lens._paint_plate(p, b, o.strip(), img.width(), img.height())
            p.end()
        self.canvas.set_image(img)
        if self.info and not self.slider.isSliderDown():
            self.slider.setValue(int(1000 * t / max(0.1, self.info.duration)))
            self.time_lbl.setText(f"{self._fmt(t)} / {self._fmt(self.info.duration)}")

    # ---------------- сохранение ----------------
    def _default_name(self, ext):
        base = os.path.splitext(os.path.basename(self.path))[0] if self.path else "картинка"
        folder = os.path.dirname(self.path) if self.path else os.path.expanduser("~/Pictures")
        return os.path.join(folder, f"{base} (перевод {self.tgt.code}){ext}")

    # ---------------- документы ----------------
    def open_doc(self, path: str):
        job = self._begin("doc", os.path.basename(path))
        self.path = path
        self.doc_out = docs.out_name(path, self.tgt.code)
        self.canvas.set_image(self._doc_preview(path))
        self.canvas.hint = "перевожу документ…"
        self._say("перевожу документ, оформление сохранится")
        tgt = self.tgt.code
        out = self.doc_out

        def many(texts):
            from concurrent.futures import ThreadPoolExecutor

            def one(t):
                try:
                    return self.translate(t, tgt)
                except Exception:
                    return ""

            with ThreadPoolExecutor(4) as ex:
                return list(ex.map(one, texts))

        def run():
            try:
                n = docs.translate_file(path, out, many,
                                        lambda d, t: self.bus.progress.emit(job, f"перевожу: {d} из {t} фрагментов", d, t))
                self.bus.doc_done.emit(job, out, n)
            except docs.DocError as e:
                self.bus.photo_failed.emit(job, str(e))
            except PermissionError:
                self.bus.photo_failed.emit(job, "не получилось записать рядом с документом: файл открыт или папка только для чтения")
            except Exception as e:
                self.bus.photo_failed.emit(job, f"не получилось: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _doc_preview(self, path: str) -> QImage | None:
        """Первая страница pdf картинкой; для остальных — карточка с названием."""
        if path.lower().endswith(".pdf"):
            try:
                import pymupdf as fitz

                pix = fitz.open(path)[0].get_pixmap(dpi=110)
                return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            except Exception:
                pass
        img = QImage(900, 1200, QImage.Format.Format_ARGB32)
        img.fill(QColor(246, 246, 248))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(40, 40, 46))
        p.setFont(theme.font(26, QFont.Weight.Bold))
        p.drawText(QRectF(80, 120, 740, 200), int(Qt.AlignmentFlag.AlignLeft) | int(Qt.TextFlag.TextWordWrap),
                   os.path.basename(path))
        p.setPen(QColor(200, 200, 206))
        for i in range(14):
            p.fillRect(80, 380 + i * 52, 740 - (i % 3) * 120, 16, QColor(222, 222, 228))
        p.end()
        return img

    def _doc_done(self, job, out, n):
        if job != self.job:
            return
        self.canvas.hint = ""
        self.prog.hide()
        prev = self._doc_preview(out) if out.lower().endswith(".pdf") else None
        if prev is not None:
            self.canvas.set_image(prev)
        else:
            self.canvas.update()
        self._say(f"готово: {os.path.basename(out)} · переведено фрагментов: {n}")
        self.b_save.setEnabled(True)
        self.b_folder.setEnabled(True)

    def _show_in_folder(self):
        import subprocess
        import sys

        out = getattr(self, "doc_out", "")
        if out and os.path.exists(out) and sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(out)])

    def save(self):
        if self.kind == "doc":
            out = getattr(self, "doc_out", "")
            if out and os.path.exists(out) and hasattr(os, "startfile"):
                os.startfile(out)  # откроется в Word / программе для pdf
            return
        if self.kind == "image" and self.result_img is not None:
            ext = os.path.splitext(self.path)[1].lower() if self.path else ".png"
            ext = ext if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") else ".png"
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить картинку с переводом", self._default_name(ext),
                                                  "Картинка (*.png *.jpg *.webp *.bmp)")
            if path:
                ok = self.result_img.save(path, quality=93)
                self._say(f"сохранено: {os.path.basename(path)}" if ok else "не получилось сохранить")
        elif self.kind == "video" and self.segments:
            path, _ = QFileDialog.getSaveFileName(self, "Сохранить видео с переводом", self._default_name(".mp4"),
                                                  "Видео (*.mp4)")
            if path:
                self.export_video(path)

    def export_video(self, path: str):
        info, segs, k, src, job = self.info, self.segments, self.k, self.path, self.job
        self.b_save.setEnabled(False)
        self.prog.setValue(0)
        self.prog.show()
        self._say("сохраняю видео с переводом…")

        def run():
            try:
                video.export(src, path, info, segs, k,
                             lambda d, t: self.bus.progress.emit(job, "сохраняю видео с переводом…", int(d * 10),
                                                                 int(t * 10)), self._stop)
                self.bus.saved.emit(path, "")
            except Exception as e:
                self.bus.saved.emit(path, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _saved(self, path, err):
        self.prog.hide()
        self.b_save.setEnabled(True)
        if err:
            self._failed(self.job, f"не получилось сохранить: {err}")
        else:
            self._say(f"готово: {os.path.basename(path)} (со звуком)")

    def save_srt(self):
        path, _ = QFileDialog.getSaveFileName(self, "Субтитры с переводом", self._default_name(".srt"),
                                              "Субтитры (*.srt)")
        if path:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(video.srt(self.segments))
            self._say(f"сохранено: {os.path.basename(path)} — откройте вместе с видео в плеере")

    # ---------------- перетаскивание ----------------
    def dragEnterEvent(self, e):
        if any(kind_of(u.toLocalFile()) for u in e.mimeData().urls()) or e.mimeData().hasImage():
            self.drop.hover = True
            self.drop.update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.drop.hover = False
        self.drop.update()

    def dropEvent(self, e):
        self.drop.hover = False
        self.drop.update()
        for u in e.mimeData().urls():
            if kind_of(u.toLocalFile()):
                self.open(u.toLocalFile())
                return
        if e.mimeData().hasImage():
            self.open_image(QImage(e.mimeData().imageData()), "картинка")
