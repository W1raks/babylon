"""Кадры для README: окно и всплывашка без обращения к сети (переводы — настоящие ответы Google, записанные заранее).

    QT_QPA_PLATFORM=offscreen python dev/readme_shots.py <папка>
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("LOCALAPPDATA", "/tmp/babylon-readme")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "readme"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)
from babylon.ui import theme  # noqa: E402

theme.load_fonts()
app.setFont(theme.font(10))
app.setStyleSheet(theme.stylesheet())
from babylon.app import Babylon  # noqa: E402
from babylon.online import Result  # noqa: E402

REAL = {  # ответы Google, полученные программой раньше
    "Offline translation keeps your data on your own computer. Select any text, press the hotkey and the translation "
    "appears right next to the cursor.":
        "Офлайн-перевод сохраняет ваши данные на вашем компьютере. Выделите любой текст, нажмите горячую клавишу и "
        "перевод появится прямо рядом с курсором.",
    "The best way to learn a language is to use it every single day.":
        "Лучший способ выучить язык — использовать его каждый день.",
}
t = Babylon(app, start_hidden=True)
t.tr.translate = lambda text, src, tgt, *a, **k: (time.sleep(0.35), Result(out=REAL[text.strip()], src="en", tgt=tgt or "ru",
                                                         engine="google"))[1]


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def backdrop(w, h):
    pm = QPixmap(w, h)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#1e1b4b"))
    g.setColorAt(0.6, QColor("#3b0d1a"))
    g.setColorAt(1, QColor("#7c2d12"))
    p.fillRect(pm.rect(), g)
    p.end()
    return pm


# главное окно + всплывашка над ним
t.open_window()
t.win.resize(1100, 680)
t.win.set_text(list(REAL)[1])
end = time.time() + 5
while time.time() < end and "мс" not in t.win.status.text():
    pump(0.05)
pump(0.3)
win = t.win.grab()
t.popup._pinned = True
t._translate_to_popup(list(REAL)[0], at=QPoint(300, 300))
end = time.time() + 5
while time.time() < end and t.popup._dots.isActive():
    pump(0.05)
pump(0.4)
pop = t.popup.grab()
hero = backdrop(1300, 820)
p = QPainter(hero)
p.drawPixmap(40, 40, win)
p.drawPixmap(1300 - pop.width() - 30, 820 - pop.height() - 30, pop)
p.end()
hero.save(os.path.join(out, "hero.png"))
pop.save(os.path.join(out, "popup.png"))
win.save(os.path.join(out, "window.png"))
t.popup.hide()

# настройки: вид и обновления
t.win.show_page("settings")
pump(0.3)
sc = t.win.stack.currentWidget().findChild(QScrollArea)
sc.verticalScrollBar().setValue(520)
pump(0.3)
t.win.grab().save(os.path.join(out, "settings.png"))
t.keys.stop()
print("saved hero.png, popup.png, settings.png")
