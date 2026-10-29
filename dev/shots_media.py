"""Кадры раздела «фото и видео» и живых субтитров (без Windows: OCR подменён, текст рисуем сами).

    QT_QPA_PLATFORM=offscreen python dev/shots_media.py <папка для png>
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("LOCALAPPDATA", "/tmp/babylon-dev")

from PySide6.QtCore import QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else "shots"
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv)

from babylon import lens, ocr, video  # noqa: E402
from babylon.ocr import Line  # noqa: E402
from babylon.ui import theme  # noqa: E402

theme.load_fonts()
app.setFont(theme.font(10))
app.setStyleSheet(theme.stylesheet())

TR = {
    "COFFEE HOUSE": "КОФЕЙНЯ",
    "Fresh pastries baked\nevery morning": "Свежая выпечка\nкаждое утро",
    "Cappuccino": "Капучино",
    "Hot chocolate": "Горячий шоколад",
    "Open daily 8am - 10pm": "Открыто ежедневно с 8 до 22",
    "SALE -20%": "СКИДКА 20%",
    "Where are you going?": "Куда ты идёшь?",
    "Home. It is late.": "Домой. Уже поздно.",
    "I can't leave you here alone.": "Я не могу оставить тебя здесь одного.",
}
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
from samples import LINES, photo  # noqa: E402

REAL_OCR = sys.platform == "win32" and bool(ocr.available_languages())
img = photo()
img.save(os.path.join(out, "sample_photo.png"))
if not REAL_OCR:  # без Windows: «распознаём» строки, которые сами нарисовали
    ocr.read_auto = lambda b, w, h, prefer="auto": (
        [Line(l.text, l.x * w / img.width(), l.y * h / img.height(), l.w * w / img.width(), l.h * h / img.height())
         for l in LINES], "en", 0.95)

from babylon.ui.window import MainWindow  # noqa: E402
from babylon import config  # noqa: E402


def fake_translate(t, tgt):
    time.sleep(0.05)
    return TR.get(t) or TR.get(t.replace("\n", " ")) or TR.get(" ".join(t.split())) or t


win = MainWindow(config.Settings(), ["en", "ru"], media_translate=fake_translate)
win.resize(1180, 760)
win.show()
win.show_page("media")


def pump(sec=0.3):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def wait_for(cond, sec=60):
    end = time.time() + sec
    while time.time() < end and not cond():
        pump(0.05)


def save(widget, name):
    widget.grab().save(os.path.join(out, name))
    print("saved", name)


pump(0.4)
save(win, "media_empty.png")
win.media.open(os.path.join(out, "sample_photo.png"))
wait_for(lambda: win.media.result_img is not None)
pump(0.3)
save(win, "media_photo.png")
win.media.result_img.save(os.path.join(out, "media_photo_full.png"))

# видео: синтетический ролик с субтитрами, OCR — по кодовому квадрату (как в тестах)
import test_lens as T  # noqa: E402

T.SUBS[:] = [(0.3, 2.0, "Where are you going?"), (2.3, 4.2, "I can't leave you here alone.")]
sample = os.path.join(out, "sample_video.mp4")
T._make_video(sample, 1280, 720, 4.5)
if not REAL_OCR:
    win.media._video_reader = lambda: T._fake_reader
win.media.open(sample)
wait_for(lambda: win.media.b_play.isEnabled())
win.media.pos = 3.0
win.media._show_at(3.0)
pump(1.0)
save(win, "media_video.png")


# живые субтитры поверх «плеера»
from babylon.ui.subs import LiveBar, SubsOverlay  # noqa: E402

bg = QPixmap(1280, 720)
p = QPainter(bg)
g = QLinearGradient(0, 0, 1280, 720)
g.setColorAt(0, QColor("#0f2027"))
g.setColorAt(0.5, QColor("#203a43"))
g.setColorAt(1, QColor("#2c5364"))
p.fillRect(bg.rect(), g)
p.setPen(Qt.GlobalColor.white)
f = QFont(theme.FAMILY)
f.setPixelSize(34)
f.setWeight(QFont.Weight.DemiBold)
p.setFont(f)
p.drawText(QRectF(0, 600, 1280, 50), Qt.AlignmentFlag.AlignCenter, "I can't leave you here alone.")
p.end()
region = QRect(240, 590, 800, 70)
ov = SubsOverlay()
ov.cover = True
ov.region = region
ov.setGeometry(QRect(0, 520, 1280, 200))
fm = QFontMetricsF(f)
ov.set_phrase("Я не могу оставить тебя здесь одного.",
              [Line("I can't leave you here alone.", 640 - fm.horizontalAdvance("I can't leave you here alone.") / 2,
                    610, fm.horizontalAdvance("I can't leave you here alone."), 32)])
ov.alpha = 1.0
bar = LiveBar("ru", 90)
bar.set_lang("en")
bar.set_speed(312, 41)
bar.adjustSize()
comp = QPixmap(bg)
p = QPainter(comp)
p.drawPixmap(0, 520, ov.grab())
p.drawPixmap(region.right() - bar.width(), region.top() - bar.height() - 8, bar.grab())
p.end()
comp.save(os.path.join(out, "live_subs.png"))
print("saved live_subs.png")

# документ: pdf с абзацем и рамкой
import pymupdf as fitz  # noqa: E402

pdf = os.path.join(out, "sample_doc.pdf")
d = fitz.open()
pg = d.new_page()
pg.insert_text((72, 90), "Report on languages", fontsize=24, color=(0.1, 0.2, 0.5))
pg.insert_textbox(fitz.Rect(72, 120, 520, 220), "Most people give up after a few weeks. The best way to learn a "
                  "language is to use it every day, even for ten minutes.", fontsize=13)
pg.draw_rect(fitz.Rect(60, 250, 520, 330), color=(0.8, 0.2, 0.2), fill=(1, 0.95, 0.93))
pg.insert_text((80, 296), "Open daily 8am - 10pm", fontsize=18, color=(0.6, 0, 0))
d.save(pdf)
TR.update({"Report on languages": "Отчёт о языках",
           "Most people give up after a few weeks. The best way to learn a language is to use it every day, even for "
           "ten minutes.": "Большинство бросает через несколько недель. Лучший способ выучить язык — пользоваться им "
           "каждый день, хотя бы десять минут."})
win.media.open(pdf)
wait_for(lambda: not win.media.prog.isVisible())
pump(0.4)
save(win, "media_doc.png")
