"""Живые субтитры: область экрана читается несколько раз в секунду, новая фраза сразу переводится.

Скорость — главное:
- кадр берётся каждые 90 мс, распознавание идёт в своём потоке и всегда берёт самый свежий кадр;
- распознаватель OCR создаётся один раз, язык определяется по первой фразе и дальше не перебирается;
- если картинка не поменялась (пауза), OCR не запускается; одинаковая фраза не переводится второй раз;
- перевод идёт параллельно с распознаванием: онлайн и скачанной моделью сразу, показываем, кто успел
  первым, а ответ Google потом подменяет его, если он другой; переводы фраз запоминаются.
"""
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QImage

from . import lens, ocr
from .engine import join_broken_lines
from .langs import ARGOS, default_target, detect, warm_up
from .ocr import Line

INTERVAL_MS = 90
SAME = 0.86          # насколько похожий текст считать той же фразой
CLEAR_AFTER = 2      # столько пустых кадров подряд — фраза исчезла с экрана
HINT_AFTER = 3.0     # столько секунд без единой фразы — подсказать на панели, что видим


class LiveSubs(QObject):
    """Сигналы: phrase(исходный текст, перевод, строки в координатах экрана, задержка мс), clear(), status(текст)."""

    phrase = Signal(str, str, object, int)
    clear = Signal()
    status = Signal(str)

    def __init__(self, tr, settings):
        super().__init__()
        self.tr = tr
        self.s = settings
        self.target = settings["preferred"]
        self.rect = QRect()
        self.screen = None
        self.running = False
        self._timer = QTimer(self, interval=INTERVAL_MS)
        self._timer.timeout.connect(self._grab)
        self._cv = threading.Condition()
        self._frame = None
        self._job = 0
        self._cache: dict[tuple[str, str], str] = {}
        self.ocr_ms = 0
        self.lang = None

    # --- управление ---
    def start(self, rect: QRect, screen, target: str | None = None):
        self.stop()
        self.rect, self.screen = QRect(rect), screen
        self.target = target or self.s["preferred"]
        self.lang = None if self.s.get("ocr_lang", "auto") == "auto" else self.s["ocr_lang"]
        self.running = True
        threading.Thread(target=warm_up, daemon=True).start()
        self._worker = threading.Thread(target=self._loop, name="babylon-live", daemon=True)
        self._worker.start()
        self._timer.start()
        self._grab()

    def stop(self):
        if not self.running:
            return
        self.running = False
        self._timer.stop()
        with self._cv:
            self._frame = None
            self._cv.notify_all()
        self.clear.emit()

    def set_target(self, code: str):
        self.target = code
        self._last_src = ""  # переведём текущую фразу заново

    # --- кадр (главный поток: снимок экрана в Qt делается только здесь) ---
    def _grab(self):
        if not self.running or self.screen is None:
            return
        g = self.screen.geometry()
        r = self.rect.translated(-g.topLeft())
        img = self.screen.grabWindow(0, r.x(), r.y(), r.width(), r.height()).toImage()
        with self._cv:
            self._frame = (time.monotonic(), img, img.devicePixelRatio())
            self._cv.notify()

    # --- распознавание (свой поток) ---
    def _loop(self):
        prev_thumb = None
        empty = 0
        weak = 0
        shown = False
        ever, hinted, since = False, False, time.monotonic()
        self._last_src = ""
        while self.running:
            with self._cv:
                while self.running and self._frame is None:
                    self._cv.wait(0.5)
                if not self.running:
                    break
                t0, img, dpr = self._frame
                self._frame = None
            img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
            w, h = img.width(), img.height()
            if w < 8 or h < 8:
                continue
            k = 1.0
            if h < 90:  # мелкий текст OCR читает лучше увеличенным
                k = 2.0
                img = img.scaled(int(w * k), int(h * k))
                w, h = img.width(), img.height()
            buf = bytes(img.constBits())[: w * h * 4]
            arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
            thumb = arr[::3, ::3, :3].astype(np.int16)
            if not ever and not hinted and time.monotonic() - since > HINT_AFTER:
                hinted = True  # ни одной фразы: скажем, что видим (чёрный кадр бывает у видео с аппаратным ускорением)
                self.status.emit("вижу только чёрный кадр" if thumb.max() < 16 else "не вижу текста в области")
            if prev_thumb is not None and thumb.shape == prev_thumb.shape and \
                    not (np.abs(thumb - prev_thumb) > 24).any():
                # картинка стоит на месте (пауза): читать нечего, но пустой кадр продолжает считаться пустым
                if empty and shown:
                    empty += 1
                    if empty >= CLEAR_AFTER:
                        shown = False
                        self._last_src = ""
                        self._job += 1
                        self.clear.emit()
                continue
            prev_thumb = thumb
            t1 = time.perf_counter()
            try:
                if self.lang:
                    lines = ocr.read(buf, w, h, self.lang)
                    sc = ocr.score(ocr.text_of(lines), self.lang)
                else:
                    lines, lang, sc = ocr.read_auto(buf, w, h, "auto")
                    if lines and sc >= 0.5:
                        self.lang = lang  # язык нашли — дальше читаем только им (в 2–5 раз быстрее)
            except ocr.OcrUnavailable as e:
                self.status.emit(str(e).lower())
                self.running = False
                break
            except Exception as e:  # не роняем субтитры из-за одного кадра
                self.status.emit(f"ошибка распознавания: {e}")
                continue
            self.ocr_ms = int((time.perf_counter() - t1) * 1000)
            text = ocr.text_of(lines).strip()
            if lines and sc < 0.3:
                weak += 1
                if weak >= 6:  # язык на экране сменился (или в настройках выбран не тот) — определим заново
                    self.lang, weak = None, 0
            else:
                weak = 0
            if len(text.replace(" ", "")) < 2:
                empty += 1
                if empty >= CLEAR_AFTER and shown:
                    shown = False
                    self._last_src = ""
                    self._job += 1
                    self.clear.emit()
                continue
            empty = 0
            if lens.similar(text, self._last_src) >= SAME:
                continue
            self._last_src = text
            shown = ever = True
            # строки — в координаты экрана (логические точки), чтобы плашка легла ровно на оригинал
            sl = [Line(ln.text, self.rect.x() + ln.x / k / dpr, self.rect.y() + ln.y / k / dpr,
                       ln.w / k / dpr, ln.h / k / dpr) for ln in lines]
            self._translate(text, sl, t0)

    # --- перевод: кто первый, тот и показывает ---
    def _translate(self, text: str, lines, t0: float):
        self._job += 1
        job = self._job
        body = join_broken_lines(text)
        # en-OCR читает и немецкий, и французский; ru-OCR — и английский буквами-двойниками: язык — по тексту
        src = self.lang if self.lang and self.lang not in ("en", "ru") else detect(body)
        tgt = self.target
        if src == tgt:
            tgt = default_target(src, self.s["preferred"], self.s["fallback"])
        key = (lens.norm(body), tgt)
        if key in self._cache:
            self._emit(job, text, self._cache[key], lines, t0)
            return
        state = {"best": False}
        lock = threading.Lock()

        def done(out: str, best: bool):
            with lock:
                if state["best"] or not out.strip():
                    return
                state["best"] = best
                self._cache[key] = out
            self._emit(job, text, out, lines, t0)

        def online():
            try:
                done(self.tr.online.translate(body, "auto", tgt)["out"], True)
            except Exception as e:
                if not can_off:  # больше переводить некому — не молчим
                    self.status.emit(f"перевод не удался: {e}".lower()[:80])

        def offline():
            try:
                done(self.tr.engine.translate(body, ARGOS.get(src, src), ARGOS.get(tgt, tgt)), False)
            except Exception:
                pass

        can_on = self.tr.mode != "offline" and self.tr.online.available()
        can_off = self.tr.engine.can_translate(ARGOS.get(src, src), ARGOS.get(tgt, tgt))
        if not can_on and not can_off:
            self.status.emit("нет интернета, а язык не скачан")
            return
        if can_on:
            threading.Thread(target=online, daemon=True).start()
        if can_off:
            threading.Thread(target=offline, daemon=True).start()

    def _emit(self, job, text, out, lines, t0):
        if job == self._job and self.running:
            self.phrase.emit(text, out, lines, int((time.monotonic() - t0) * 1000))
