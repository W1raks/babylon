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


def test_fix_twins():
    assert ocr.fix_twins("tаll аnd wild аnd Pоntus") == "tall and wild and Pontus"   # «а», «о» — кириллица
    assert ocr.fix_twins("Кот сидит на окне") == "Кот сидит на окне"                  # русский не трогаем
    assert ocr.fix_twins("Hello world") == "Hello world"


def run_live(monkeypatch, img_of, sec):
    tr = FakeTr()
    subs = live.LiveSubs(tr, {"preferred": "ru", "fallback": "en", "ocr_lang": "auto"})
    got, status = [], []
    subs.phrase.connect(lambda text, out, lines, ms: got.append((text, out)))
    subs.status.connect(status.append)
    i = {"n": 0}

    def grab():
        i["n"] += 1
        with subs._cv:
            subs._frame = (time.monotonic(), img_of(i["n"]), 1.0)
            subs._cv.notify()

    monkeypatch.setattr(subs, "_grab", grab)
    subs.start(QRect(0, 0, 400, 60), screen=None)
    subs._timer.timeout.disconnect()
    subs._timer.timeout.connect(grab)
    pump(sec)
    subs.stop()
    return got, status


def test_english_read_by_russian_ocr(monkeypatch):
    """В Windows только русский OCR: он пишет английский буквами-двойниками, а перевести надо как английский."""
    async def recognize(buf, w, h, lang):
        assert lang == "ru"
        return [Line("tаll аnd wild аnd Pоntus", 40, 10, 300, 30, [("tаll", 40, 10, 40, 30)])]

    monkeypatch.setattr(ocr, "available_languages", lambda: ["ru"])
    monkeypatch.setattr(ocr, "_recognize", recognize)
    got, status = run_live(monkeypatch, lambda n: frame(1, n), 0.6)
    assert got and got[0] == ("tall and wild and Pontus", "[ru] tall and wild and Pontus"), status


def test_hint_when_nothing_seen(monkeypatch):
    monkeypatch.setattr(live, "HINT_AFTER", 0.2)
    monkeypatch.setattr(ocr, "read_auto", lambda b, w, h, p: ([], "en", 0.0))
    black = QImage(400, 60, QImage.Format.Format_ARGB32_Premultiplied)
    black.fill(QColor(0, 0, 0))
    _, status = run_live(monkeypatch, lambda n: black, 0.5)
    assert status == ["вижу только чёрный кадр"]
    _, status = run_live(monkeypatch, lambda n: frame(0, n), 0.5)
    assert status == ["не вижу текста в области"]


def test_wrong_ocr_language_in_settings(monkeypatch):
    """В настройках «язык на картинках: русский», а субтитры английские (так было у Дмитрия)."""
    async def recognize(buf, w, h, lang):
        text = "tаll аnd wild аnd Pоntus" if lang == "ru" else "tall and wild and Pontus"
        return [Line(text, 40, 10, 300, 30, [])]

    monkeypatch.setattr(ocr, "available_languages", lambda: ["en", "ru", "zh"])
    monkeypatch.setattr(ocr, "_recognize", recognize)
    tr = FakeTr()
    subs = live.LiveSubs(tr, {"preferred": "ru", "fallback": "en", "ocr_lang": "ru"})
    got = []
    subs.phrase.connect(lambda text, out, lines, ms: got.append(out))
    i = {"n": 0}

    def grab():
        i["n"] += 1
        with subs._cv:
            subs._frame = (time.monotonic(), frame(1, i["n"] % 2 * 39), 1.0)  # видео идёт: кадры разные
            subs._cv.notify()

    monkeypatch.setattr(subs, "_grab", grab)
    subs.start(QRect(0, 0, 400, 60), screen=None)
    subs._timer.timeout.disconnect()
    subs._timer.timeout.connect(grab)
    pump(1.2)
    subs.stop()
    assert got and got[0] == "[ru] tall and wild and Pontus"   # переведено на русский, а не «на английский»
    assert subs.lang == "en"                                      # дальше читает английским OCR
