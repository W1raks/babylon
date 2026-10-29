"""Перевод речи вживую: звук → фразы → Whisper → перевод → субтитры и окно «разговор».

Источник — звук компьютера (видео без субтитров, онлайн-конференции) или микрофон (разговор рядом).
Пока человек говорит, раз в ~1 с показывается черновик (распознанное и его перевод),
после паузы — окончательная фраза. Если сказано на языке перевода (вы сами по-русски),
фраза переводится на язык собеседника: так один микрофон переводит разговор в обе стороны.
"""
import queue
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

from . import asr, audio, speech
from .langs import LANGS, default_target


class Hearing(QObject):
    draft = Signal(str, str)        # распознаётся сейчас: текст, перевод
    phrase = Signal(object)         # готовая фраза: dict(text, out, src, tgt, at, ms)
    status = Signal(str)
    level = Signal(float)           # громкость 0..1 (для индикатора)
    running_changed = Signal(bool)

    def __init__(self, tr, settings):
        super().__init__()
        self.tr = tr
        self.s = settings
        self.running = False
        self.source = "system"
        self.target = settings["preferred"]
        self.their = None            # язык собеседника (последний услышанный не наш)
        self._q: queue.Queue = queue.Queue()
        self._cap = None
        self._n = 0                  # номер текущей фразы: поздний черновик старой фразы не показываем
        self._spoken: list[tuple[float, str]] = []  # что Вавилон сам сказал вслух — это не собеседник
        self._speak_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._speaker, name="babylon-voiceover", daemon=True).start()

    # --- управление ---
    def start(self, source: str = "system", target: str | None = None, capture: bool = True):
        self.stop()
        self.source = source
        self.target = target or self.s["preferred"]
        size = self.s.get("asr_model", "base")
        if not asr.installed(size):
            self.status.emit("нужно скачать модель распознавания речи")
            return False
        self.running = True
        self._q = queue.Queue()
        self._worker = threading.Thread(target=self._loop, args=(size,), name="babylon-hear", daemon=True)
        self._worker.start()
        if capture:
            self._cap = audio.Capture(source, self._q.put, on_error=self._capture_failed)
            self._cap.start()
        self.running_changed.emit(True)
        self.status.emit("слушаю звук компьютера" if source == "system" else "слушаю микрофон")
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self._cap:
            self._cap.stop()
            self._cap = None
        self._q.put(None)
        self.running_changed.emit(False)

    def feed(self, chunk: np.ndarray):
        """Подать звук вручную (16 кГц моно) — для проверок и файлов."""
        self._q.put(chunk)

    def _capture_failed(self, msg: str):
        self.status.emit(msg)
        self.stop()

    # --- распознавание (свой поток) ---
    def _loop(self, size: str):
        try:
            rec = asr.recognizer(size)
        except Exception as e:
            self.status.emit(f"не загрузилась модель речи: {e}")
            self.running = False
            self.running_changed.emit(False)
            return
        seg = audio.Segmenter()
        lang = None
        last_draft = 0.0
        while True:
            chunk = self._q.get()
            if chunk is None:
                events = seg.flush()
            else:
                events = seg.feed(chunk)
                self.level.emit(min(1.0, seg.level / 0.08))
            backlog = self._q.qsize() * 0.1
            for kind, a in events:
                if kind == "partial" and (backlog > 0.6 or time.monotonic() - last_draft < 0.9):
                    continue  # не успеваем — черновик пропускаем, главное не отстать
                t0 = time.perf_counter()
                try:
                    r = rec.transcribe(a, lang if kind == "partial" else None, beam=1 if kind == "partial" else 3)
                except Exception as e:
                    self.status.emit(f"ошибка распознавания: {e}")
                    continue
                text = r["text"]
                if not text or self._is_echo(text):
                    continue
                if kind == "final" and r["prob"] >= 0.5:
                    lang = r["lang"]
                src = r["lang"] if kind == "final" else (lang or r["lang"])
                if kind == "partial":
                    last_draft = time.monotonic()
                    self._translate(text, src, draft=True)
                else:
                    self._translate(text, src, draft=False, asr_ms=int((time.perf_counter() - t0) * 1000))
            if chunk is None:
                break

    def _pick_target(self, src: str) -> str:
        tgt = self.target
        if src == tgt:  # сказано на нашем языке — переводим на язык собеседника
            tgt = self.their or default_target(src, self.s["preferred"], self.s["fallback"])
        elif src in LANGS:
            self.their = src
        return tgt

    def _translate(self, text: str, src: str, draft: bool, asr_ms: int = 0):
        tgt = self._pick_target(src)
        at = time.time()
        n = self._n
        if not draft:
            self._n += 1

        def run():
            t0 = time.perf_counter()
            try:
                out = self.tr.translate(text, src if src in LANGS else "auto", tgt)["out"] if src != tgt else text
            except Exception:
                out = ""
            if draft and (n != self._n or not self.running):
                return
            if draft:
                self.draft.emit(text, out)
            else:
                ms = asr_ms + int((time.perf_counter() - t0) * 1000)
                self.phrase.emit({"text": text, "out": out, "src": src, "tgt": tgt, "at": at, "ms": ms})
                if out and self.s.get("voice_over"):
                    self.say(out, tgt)

        threading.Thread(target=run, daemon=True).start()

    # --- озвучка перевода по очереди ---
    def say(self, text: str, lang: str):
        """Сказать вслух (ответ или озвучка перевода). Сказанное запоминаем, чтобы не переводить своё эхо."""
        self._speak_q.put((text, lang))

    def _is_echo(self, text: str) -> bool:
        from .lens import similar

        now = time.monotonic()
        self._spoken = [(t, s) for t, s in self._spoken if now - t < 30]
        return any(similar(text, s) >= 0.6 for _, s in self._spoken)

    def _speaker(self):
        while True:
            text, lang = self._speak_q.get()
            self._spoken.append((time.monotonic(), text))
            try:
                speech.speak(text, lang)
            except Exception as e:
                self.status.emit(f"озвучка: {e}")
            self._spoken.append((time.monotonic(), text))
