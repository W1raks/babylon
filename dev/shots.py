"""Стенд: собрать окна на настоящем переводе и сохранить их кадры (работает и без экрана).

    QT_QPA_PLATFORM=offscreen BABYLON_MODELS=<папка> python dev/shots.py <папка для png>
Окна кладутся на пёстрый «рабочий стол», чтобы было видно стекло, скругления и читаемость.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("LOCALAPPDATA", "/tmp/babylon-dev")

from PySide6.QtCore import QPoint, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from babylon import config  # noqa: E402
from babylon.ui import theme  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
theme.load_fonts()
app.setFont(theme.font(10))
app.setStyleSheet(theme.stylesheet())

from babylon.app import Babylon  # noqa: E402

t = Babylon(app, start_hidden=True)


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(cond, sec=20):
    end = time.time() + sec
    while time.time() < end and not cond():
        pump(0.05)


def desktop(w, h):
    """Пёстрый фон: так видно, что окно на стекле, а текст читается."""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#2b5876"))
    g.setColorAt(0.5, QColor("#4e4376"))
    g.setColorAt(1, QColor("#c94b4b"))
    p.fillRect(pm.rect(), g)
    f = QFont(theme.FAMILY)
    f.setPixelSize(15)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 150))
    for y in range(20, h, 26):
        p.drawText(10, y, "Lorem ipsum dolor sit amet, the quick brown fox jumps over the lazy dog — 1234567890")
    p.end()
    return pm


def save(widget, filename, pad=40):
    pm = widget.grab()
    canvas = desktop(pm.width() + pad * 2, pm.height() + pad * 2)
    p = QPainter(canvas)
    p.drawPixmap(pad, pad, pm)
    p.end()
    path = os.path.join(out, filename)
    canvas.save(path)
    print("saved", path)


def popup_case(text, filename, at=QPoint(200, 200)):
    t.popup._pinned = True
    t._translate_to_popup(text, at=at)
    wait_for(lambda: not t.popup._dots.isActive())
    pump(0.4)
    save(t.popup, filename)


popup_case("Offline translation keeps your data on your own computer. Select any text, press the hotkey "
           "and the translation appears right next to the cursor.", "popup_text.png")
popup_case("run", "popup_word.png")
popup_case("Привет! Это мой собственный переводчик.", "popup_ru.png")
t._popup_retarget("ja")
wait_for(lambda: not t.popup._dots.isActive())
pump(0.4)
save(t.popup, "popup_ja.png")
long = " ".join(["I want to tell you about my family. I come from a big family. My sister is twelve."] * 10)
popup_case(long, "popup_long.png")
t.popup.hide()

t.open_window()
t.win.resize(1100, 700)
t.win.set_text("run")
wait_for(lambda: "мс" in t.win.status.text())
pump(0.4)
save(t.win, "window_translate.png", pad=24)
t.vocab.toggle("run", "бегать", "en", "ru")
t.vocab.toggle("dog", "собака", "en", "ru")
t._fill_vocab()
for key in ("vocab", "history", "langs", "settings"):
    t.win.show_page(key)
    pump(0.3)
    save(t.win, f"window_{key}.png", pad=24)
t.win.show_page("vocab")
t.win.start_study(t.vocab.due())
t.win._card_flip()
pump(0.3)
save(t.win, "window_study.png", pad=24)
t.keys.stop()
