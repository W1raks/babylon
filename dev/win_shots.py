"""Снимки настоящего экрана Windows (для CI): пёстрый фон, поверх него окно и всплывашка со стеклом.

    BABYLON_MODELS=<папка> python dev/win_shots.py <папка для png>
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from babylon.ui import theme  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "winshots"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
theme.load_fonts()
app.setFont(theme.font(10))
app.setStyleSheet(theme.stylesheet())


class Wallpaper(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#1e9bd7"))
        g.setColorAt(0.5, QColor("#7b2ff7"))
        g.setColorAt(1, QColor("#f5a623"))
        p.fillRect(self.rect(), g)
        f = QFont(theme.FAMILY)
        f.setPixelSize(18)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 200))
        for y in range(24, self.height(), 30):
            p.drawText(12, y, "Background text behind the window — фон за окном — 背景のテキスト " * 3)


wall = Wallpaper()
wall.setWindowFlags(Qt.WindowType.FramelessWindowHint)
geo = app.primaryScreen().geometry()
wall.setGeometry(geo)
wall.show()

from babylon.app import Babylon  # noqa: E402

t = Babylon(app, start_hidden=True)


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def shot(name):
    pm = app.primaryScreen().grabWindow(0)
    path = os.path.join(out, name)
    pm.save(path)
    print("saved", path, pm.width(), pm.height())


pump(1)
t.open_window()
t.win.move(geo.left() + 60, geo.top() + 40)
t.win.resize(1000, 640)
t.win.set_text("run")
end = time.time() + 20
while time.time() < end and "мс" not in t.win.status.text():
    pump(0.1)
pump(1)
print("blurred window:", t.win.blurred)
shot("win_window.png")

t.popup._pinned = True
t._translate_to_popup("Select any text in any program, press the hotkey and the translation appears "
                      "right next to the cursor.", at=QPoint(geo.left() + 700, geo.top() + 380))
end = time.time() + 20
while time.time() < end and t.popup._dots.isActive():
    pump(0.1)
pump(1)
print("blurred popup:", t.popup.blurred)
shot("win_popup.png")
t.keys.stop()
