"""Кадры настоящего интерфейса для промо-ролика (в 2 раза крупнее, с прозрачностью).

    QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=2 python promo/assets.py <папка>
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
os.environ.setdefault("LOCALAPPDATA", "/tmp/babylon-promo")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
from babylon.ui import theme  # noqa: E402

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


def wait_for(cond, sec=30):
    end = time.time() + sec
    while time.time() < end and not cond():
        pump(0.05)


t.popup._pinned = True
t._translate_to_popup("The best way to learn a language is to use it every single day.", at=QPoint(300, 300))
wait_for(lambda: not t.popup._dots.isActive())
pump(0.5)
t.popup.grab().save(os.path.join(out, "popup.png"))
t.popup.hide()

from babylon.ui.subs import LiveBar  # noqa: E402

bar = LiveBar("ru", 92)
bar.set_lang("en")
bar.set_speed(310, 40)
bar.adjustSize()
bar.grab().save(os.path.join(out, "livebar.png"))

t.open_window()
t.win.resize(1100, 700)
t.win.set_text("Hello! How are you today?")
wait_for(lambda: "мс" in t.win.status.text())
pump(0.4)
t.win.grab().save(os.path.join(out, "window.png"))
t.keys.stop()
print("ok")
