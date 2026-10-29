"""Перевод поверх картинок и видео: раскладка блоков, цвета, рисование, отрезки, экспорт (без OCR и сети)."""
import os
import subprocess

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from babylon import lens, video
from babylon.ocr import Line
from babylon.ui import theme

app = QApplication.instance() or QApplication([])
theme.load_fonts()


def test_group_paragraphs_and_separate_labels():
    lines = [
        Line("The quick brown fox", 40, 40, 300, 24),
        Line("jumps over the lazy dog", 40, 70, 330, 24),
        Line("and runs away.", 40, 100, 200, 24),
        Line("EXIT", 600, 45, 80, 40),          # другая надпись справа, крупнее
        Line("Caption far below", 40, 400, 250, 24),
    ]
    blocks = lens.group(lines)
    texts = sorted(b.text for b in blocks)
    assert "The quick brown fox\njumps over the lazy dog\nand runs away." in texts
    assert "EXIT" in texts and "Caption far below" in texts
    assert len(blocks) == 3
    para = next(b for b in blocks if b.text.startswith("The"))
    assert (para.x, para.y, para.w, para.h) == (40, 40, 330, 84)


def test_menu_lines_stay_separate():
    blocks = lens.group([Line("Cappuccino", 10, 10, 200, 30), Line("Hot chocolate", 10, 50, 240, 30),
                         Line("Fresh pastries baked", 10, 100, 300, 24), Line("every morning", 10, 128, 200, 24)])
    assert [b.text for b in blocks] == ["Cappuccino", "Hot chocolate", "Fresh pastries baked\nevery morning"]


def test_centered_block():
    b = lens.group([Line("Hello there friend", 100, 10, 300, 20), Line("hi", 230, 36, 40, 20)])[0]
    assert b.centered


def test_similar_tolerates_ocr_noise():
    assert lens.similar("I'm going home now.", "Im going horne now") > 0.8
    assert lens.similar("I'm going home now.", "Where are you?") < 0.5
    assert lens.similar("", "") == 1.0


def _sample_image():
    img = QImage(500, 200, QImage.Format.Format_ARGB32)
    img.fill(QColor(250, 230, 120))  # жёлтый фон
    p = QPainter(img)
    p.setPen(QColor(30, 30, 160))    # синие буквы
    f = QFont(theme.FAMILY)
    f.setPixelSize(30)
    p.setFont(f)
    p.drawText(30, 80, "Fresh coffee")
    p.end()
    return img


def test_colors_from_picture():
    img = _sample_image()
    bg, fg = lens.colors(lens.as_array(img), QRectF(28, 55, 190, 32))
    assert abs(bg.red() - 250) < 8 and abs(bg.green() - 230) < 8 and abs(bg.blue() - 120) < 8
    assert fg.blue() > fg.red() and fg.blue() > 100


def test_paint_photo_and_subs():
    img = _sample_image()
    b = lens.group([Line("Fresh coffee", 28, 55, 190, 32)])[0]
    out = lens.paint(img, [b], ["Свежий кофе с молоком и корицей"], "photo")
    assert out.size() == img.size()
    # на месте надписи теперь фон и синие буквы перевода, а не старый текст
    arr = lens.as_array(out)
    region = arr[55:90, 28:220, :3]
    assert (abs(region.astype(int) - [120, 230, 250]).sum(axis=2) > 200).any()
    subs = lens.paint(img, [b], ["Свежий кофе"], "subs")
    r, _, fpx = lens.plate_geometry(b, "Свежий кофе", 500, 200)
    px = subs.pixelColor(int(r.left() + fpx * 0.25), int(r.center().y()))
    assert px.red() < 80 and px.green() < 80  # тёмная плашка


def test_plate_wider_for_long_translation():
    b = lens.group([Line("Hi", 300, 600, 40, 30)])[0]
    r, f, px = lens.plate_geometry(b, "Привет, как у тебя сегодня дела?", 1280, 720)
    assert r.width() > 200 and r.right() <= 1280 and r.bottom() <= 720
    assert abs(r.center().x() - 320) < 2


def test_timeline_merges_noisy_frames():
    def blk(text):
        return [lens.Block([Line(text, 10, 10, 100, 20)])]

    tl = video.Timeline(0.25)
    for i, t in enumerate([0, .25, .5, .75, 1.0, 1.25, 1.5, 1.75, 2.0]):
        text = ["Hello there", "Hel1o there", "Hello there", "", "Hello there", "", "", "Bye", "Bye now"][i]
        tl.add(t, blk(text) if text else [])
    segs = tl.finish()
    assert [s.text for s in segs] == ["Hello there", "Bye now"]
    assert segs[0].start == 0 and segs[0].end == pytest.approx(1.125)
    assert segs[1].start == pytest.approx(1.625)


def test_srt():
    s = video.Segment(1.0, 2.5, [], "a", ["Привет"])
    s2 = video.Segment(62.25, 63.0, [], "b", ["Как дела?", "Хорошо"])
    assert video.srt([s, s2]) == ("1\n00:00:01,000 --> 00:00:02,500\nПривет\n\n"
                                  "2\n00:01:02,250 --> 00:01:03,000\nКак дела?\nХорошо\n")


SUBS = [(0.5, 2.0, "Where are you going?"), (2.5, 4.0, "Home. It is late.")]


def _make_video(path, w=640, h=360, dur=4.5, fps=25):
    """Видео с «вшитыми» субтитрами: номер субтитра закодирован яркостью квадрата в углу (для поддельного OCR)."""
    cmd = [video.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={dur}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    f = QFont(theme.FAMILY)
    f.setPixelSize(26)
    for i in range(int(dur * fps)):
        t = i / fps
        img = QImage(w, h, QImage.Format.Format_ARGB32)
        img.fill(QColor(40 + i % 60, 70, 110))  # фон меняется каждый кадр, как в настоящем видео
        p2 = QPainter(img)
        cur = next((n for n, (a, b, _) in enumerate(SUBS, 1) if a <= t < b), 0)
        p2.fillRect(0, 0, 24, 24, QColor(cur * 80, cur * 80, cur * 80))
        if cur:
            p2.setFont(f)
            p2.setPen(Qt.GlobalColor.white)
            p2.drawText(QRectF(0, h - 70, w, 40), Qt.AlignmentFlag.AlignCenter, SUBS[cur - 1][2])
        p2.end()
        p.stdin.write(bytes(img.constBits())[: w * h * 4])
    p.stdin.close()
    assert p.wait() == 0


def _fake_reader(buf, w, h):
    import numpy as np

    arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
    n = round(int(arr[4:12, 4:12, 1].mean()) / 80)
    if not n:
        return []
    text = SUBS[n - 1][2]
    return [Line(text, w * 0.25, h - h * 70 / 360, w * 0.5, h * 30 / 360)]


@pytest.mark.skipif(not (os.path.exists("/usr/bin/ffmpeg") or os.name == "nt"), reason="нужен ffmpeg")
def test_video_analyze_and_export(tmp_path):
    src = str(tmp_path / "in.mp4")
    _make_video(src)
    info = video.probe(src)
    assert (info.width, info.height, info.audio) == (640, 360, True)
    assert info.duration == pytest.approx(4.5, abs=0.1)
    calls = []
    info, segs, k = video.analyze(src, _fake_reader, progress=lambda d, t: calls.append(d))
    assert [s.text for s in segs] == [t for _, _, t in SUBS]
    assert segs[0].start == pytest.approx(0.5, abs=0.25) and segs[0].end == pytest.approx(2.0, abs=0.25)
    tr = {"Where are you going?": "Куда ты идёшь?", "Home. It is late.": "Домой. Уже поздно."}
    video.translate_segments(segs, lambda t: tr[t])
    assert segs[1].outs == ["Домой. Уже поздно."]
    out = str(tmp_path / "out.mp4")
    video.export(src, out, info, segs, k)
    oi = video.probe(out)
    assert (oi.width, oi.height, oi.audio) == (640, 360, True)
    assert oi.duration == pytest.approx(4.5, abs=0.15)
    # кадр на 1 с: поверх субтитра — тёмная плашка перевода; на 2.2 с — без плашки
    shots = {t: buf for t, buf in video.frames(out, 640, 360, fps=5)}
    import numpy as np

    def mid(t):
        a = np.frombuffer(shots[t], np.uint8).reshape(360, 640, 4)
        return a[300:325, 150:170, :3].mean()  # край плашки, без букв

    assert mid(1.0) < 40          # плашка (почти чёрная)
    assert mid(2.2) > 50          # фон видео
