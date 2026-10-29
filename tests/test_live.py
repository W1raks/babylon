"""Живые субтитры без экрана и OCR Windows: кадры подсовываем сами, распознавание подменяем."""
import time

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from babylon import live, ocr
from babylon.ocr import Line

app = QApplication.instance() or QApplication([])
PHRASES = {1: "Where are you going?", 2: "Home. It is late.", 3: "Hold on!"}


def frame(n: int, noise: int = 0) -> QImage:
    """Кадр 400×60: номер фразы закодирован яркостью левого края, фон «шумит» как видео."""
    img = QImage(400, 60, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(20 + noise % 40, 30, 50))
    for x in range(10):
        for y in range(10):
            img.setPixelColor(x, y, QColor(n * 60, n * 60, n * 60))
    return img


def fake_read(buf, w, h, lang):
    arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    n = round(int(arr[2:8, 2:8, 1].mean()) / 60)
    return [Line(PHRASES[n], 40, 10, 300, 30)] if n else []


class FakeOnline:
    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def translate(self, text, src, tgt):
        self.calls.append(text)
        time.sleep(0.12)  # как Google
        return {"out": f"[{tgt}] {text}"}


class FakeEngine:
    def can_translate(self, a, b):
        return False


class FakeTr:
    mode = "online"

    def __init__(self):
        self.online = FakeOnline()
        self.engine = FakeEngine()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


def test_live_flow(monkeypatch):
    monkeypatch.setattr(ocr, "read", fake_read)
    monkeypatch.setattr(ocr, "read_auto", lambda b, w, h, p: (fake_read(b, w, h, "en"), "en", 0.95))
    tr = FakeTr()
    s = {"preferred": "ru", "fallback": "en", "ocr_lang": "auto"}
    subs = live.LiveSubs(tr, s)
    got, cleared = [], []
    subs.phrase.connect(lambda text, out, lines, ms: got.append((text, out, lines, ms)))
    subs.clear.connect(lambda: cleared.append(1))
    cur = {"n": 0, "i": 0}

    def grab():  # вместо снимка экрана
        cur["i"] += 1
        with subs._cv:
            subs._frame = (time.monotonic(), frame(cur["n"], cur["i"]), 1.0)
            subs._cv.notify()

    monkeypatch.setattr(subs, "_grab", grab)
    subs.start(QRect(100, 600, 400, 60), screen=None)
    subs._timer.timeout.disconnect()
    subs._timer.timeout.connect(grab)

    cur["n"] = 1
    pump(0.6)
    assert len(got) == 1, got
    text, out, lines, ms = got[0]
    assert out == "[ru] Where are you going?"
    assert ms < 400                       # от кадра до перевода
    assert lines[0].x == 100 + 40 / 2 and lines[0].y == 600 + 10 / 2   # мелкая область увеличена в 2 раза
    assert subs.lang == "en"              # язык запомнен после первой фразы

    cur["n"] = 0
    pump(0.5)
    assert cleared                         # фраза пропала — плашка убрана
    cur["n"] = 1
    pump(0.5)
    assert len(got) == 2 and tr.online.calls.count("Where are you going?") == 1   # второй раз из памяти

    cur["n"] = 2
    pump(0.6)
    assert got[-1][1] == "[ru] Home. It is late."
    subs.stop()
    assert not subs.running
