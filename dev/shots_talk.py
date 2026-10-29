"""Кадры раздела «разговор» и субтитров речи на настоящем распознавании (звук из tests/audio).

    QT_QPA_PLATFORM=offscreen BABYLON_WHISPER=<папка с whisper-base> python dev/shots_talk.py <папка>
Без модели снимается карточка «скачайте модель».
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
os.environ.setdefault("LOCALAPPDATA", "/tmp/babylon-dev-talk")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
from babylon.ui import theme  # noqa: E402

theme.load_fonts()
app.setFont(theme.font(10))
app.setStyleSheet(theme.stylesheet())
from babylon import asr  # noqa: E402
from babylon.app import Babylon  # noqa: E402

t = Babylon(app, start_hidden=True)

# Google с облачных адресов бывает недоступен (429): тогда берём его же ответы, записанные раньше
KNOWN = {
    "Привет! Сегодня мы поговорим о том, как быстро выучить новый язык.":
        "Hello! Today we will talk about how to quickly learn a new language.",
    "Добрый вечер! Я опаздываю на встречу. Подожди меня у входа.":
        "Good evening! I'm late for a meeting. Wait for me at the entrance.",
    "Okay, see you at the entrance in ten minutes.": "Хорошо, увидимся у входа через десять минут.",
}
_real = t.tr.translate


def _translate(text, src, tgt, *a, **k):
    try:
        return _real(text, src, tgt, *a, **k)
    except Exception:
        from babylon.online import Result

        if text.strip() in KNOWN:
            return Result(out=KNOWN[text.strip()], src=src if src != "auto" else "en", tgt=tgt or "ru", engine="google")
        raise


t.tr.translate = _translate


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


t.open_window()
t.win.resize(1120, 720)
t.win.show_page("talk")
pump(0.4)
t.win.grab().save(os.path.join(out, "talk_empty.png"))
print("saved talk_empty.png, model:", asr.installed("base"))

if asr.installed("base"):
    from test_hear import load

    t.s["hear_overlay"] = False
    t.hearing.start("system", "en", capture=False)  # без звуковой карты: звук подаём сами; речь русская — переводим на английский
    a = load()
    for i in range(0, len(a), 1600):
        t.hearing.feed(a[i:i + 1600])
        pump(0.03)
    end = time.time() + 20
    while time.time() < end and len(t.win.talk.items) < 2:
        pump(0.1)
    t._reply("Okay, see you at the entrance in ten minutes.")
    end = time.time() + 10
    while time.time() < end and len(t.win.talk.items) < 3:
        pump(0.1)
    t.hearing.stop()
    pump(0.5)
    t.win.grab().save(os.path.join(out, "talk_phrases.png"))
    print("phrases:", [(i["text"], i["out"]) for i in t.win.talk.items])

# субтитры речи поверх «видео»
from babylon.ui.subs import HearBar, SpeechOverlay  # noqa: E402

bg = QPixmap(1600, 900)
p = QPainter(bg)
g = QLinearGradient(0, 0, 1600, 900)
g.setColorAt(0, QColor("#1f2937"))
g.setColorAt(1, QColor("#7c2d12"))
p.fillRect(bg.rect(), g)
f = QFont(theme.FAMILY)
f.setPixelSize(22)
p.setFont(f)
p.setPen(QColor(255, 255, 255, 120))
p.drawText(QRectF(0, 380, 1600, 40), Qt.AlignmentFlag.AlignCenter, "▶  видео без субтитров — человек говорит по-английски")
p.end()
ov = SpeechOverlay(t.s)
ov.resize(1056, int(t.s["subs_size"] * 4.6))
ov.set_text("So the main idea is to practice every single day, even for ten minutes.",
            "Главная идея — заниматься каждый день, хотя бы по десять минут.", draft=False)
ov.alpha = 1.0
bar = HearBar("ru", 90, False)
bar.set_source("звук компьютера")
bar.set_level(0.6)
bar.adjustSize()
comp = QPixmap(bg)
p = QPainter(comp)
oy = 900 - ov.height() - 60
p.drawPixmap(272, oy, ov.grab())
p.drawPixmap(272 + ov.width() - bar.width(), oy - bar.height() - 6, bar.grab())
p.end()
comp.save(os.path.join(out, "speech_subs.png"))
print("saved speech_subs.png")
t.keys.stop()
