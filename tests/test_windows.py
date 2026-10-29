"""Проверки, которые имеют смысл только на настоящей Windows (запускаются в GitHub Actions)."""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="только Windows")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from babylon import ocr, winapi  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication(sys.argv)


def pump(app, sec):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def test_parse_hotkey():
    assert winapi.parse_hotkey("Ctrl+Alt+T") == (winapi.MOD_CONTROL | winapi.MOD_ALT, ord("T"))
    assert winapi.parse_hotkey("ctrl + shift + f2") == (winapi.MOD_CONTROL | winapi.MOD_SHIFT, 0x71)
    with pytest.raises(ValueError):
        winapi.parse_hotkey("T")


def test_hotkeys_register(app):
    k = winapi.Hotkeys()
    errors = []
    k.failed.connect(lambda n, m: errors.append((n, m)))
    k.start({"selection": "Ctrl+Alt+Shift+F11", "screen": "Ctrl+Alt+Shift+F12"})
    pump(app, 0.5)
    k.stop()
    assert errors == []


def _text_image(text, w=1000, h=140):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.white)
    p = QPainter(img)
    p.setPen(Qt.GlobalColor.black)
    f = QFont("Segoe UI")
    f.setPixelSize(40)
    p.setFont(f)
    p.drawText(30, 90, text)
    p.end()
    return bytes(img.constBits())[: w * h * 4], w, h


def test_ocr_english(app):
    langs = ocr.available_languages()
    print("OCR languages on runner:", langs)
    assert langs, "в Windows нет языков OCR"
    data, w, h = _text_image("Select any text and press the hotkey")
    text, lang = ocr.recognize(data, w, h)
    print("OCR:", lang, repr(text))
    assert "hotkey" in text.lower()


def test_ocr_russian_if_installed(app):
    if "ru" not in ocr.available_languages():
        pytest.skip("русский OCR не установлен на этой машине")
    data, w, h = _text_image("Привет, это проверка распознавания")
    text, lang = ocr.recognize(data, w, h)
    print("OCR ru:", lang, repr(text))
    assert "провер" in text.lower()


def test_press_copy_takes_selection(app):
    """Полный путь «выделил -> Ctrl+C за пользователя -> текст в буфере»."""
    e = QLineEdit("babylon selection test")
    e.show()
    e.raise_()
    e.activateWindow()
    e.setFocus()
    e.selectAll()
    pump(app, 0.6)
    if not e.isActiveWindow():
        pytest.skip("на сервере окно не стало активным")
    cb = app.clipboard()
    cb.setText("old")
    seq0 = winapi.clipboard_seq()
    winapi.press_copy()
    end = time.time() + 2
    while time.time() < end and winapi.clipboard_seq() == seq0:
        pump(app, 0.02)
    pump(app, 0.1)
    assert cb.text() == "babylon selection test"


def test_tts_windows_voice(app):
    from babylon import speech

    voices = speech.voices()
    print("voices on runner:", voices)
    if "en" not in voices:
        pytest.skip("нет английского голоса")
    data, ext = speech.synthesize("Hello from Babylon", "en")
    print("tts bytes:", len(data))
    assert ext == ".wav" and len(data) > 5000 and data[:4] == b"RIFF"


def test_glass_api_does_not_crash(app):
    from PySide6.QtWidgets import QWidget
    from babylon.ui import glass

    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    w.show()
    pump(app, 0.2)
    print("blur:", glass.apply(w), glass.apply(w, popup=True), "build", glass._build())
    w.close()


# ---------------- 2.1: строки с рамками, живые субтитры, фото и видео ----------------
def test_ocr_lines_have_boxes(app):
    data, w, h = _text_image("Where are you going?")
    t = time.perf_counter()
    lines = ocr.read(data, w, h, "en")
    first = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    for _ in range(5):
        ocr.read(data, w, h, "en")
    again = (time.perf_counter() - t) * 1000 / 5
    print(f"OCR lines: {lines} first {first:.0f} ms, then {again:.0f} ms per read")
    assert lines and "going" in lines[0].text
    ln = lines[0]
    assert 20 < ln.x < 45 and 45 < ln.y < 75 and 20 < ln.h < 50 and ln.w > 250


def _solid(app, rect, color):
    from PySide6.QtWidgets import QWidget

    w = QWidget(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
    w.setStyleSheet(f"background: {color};")
    w.setGeometry(*rect)
    w.show()
    pump(app, 0.4)
    return w


def _grab_mean(app, rect):
    img = app.primaryScreen().grabWindow(0, *rect).toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return c.red(), c.green(), c.blue()


def test_exclude_from_capture(app):
    """Плашка субтитров не попадает в снимок экрана: значит, её можно класть прямо на оригинал."""
    rect = (60, 60, 240, 80)
    w = _solid(app, rect, "#ff0000")
    seen = _grab_mean(app, rect)
    ok = winapi.exclude_from_capture(int(w.winId()))
    pump(app, 0.4)
    hidden = _grab_mean(app, rect)
    print("capture: visible", seen, "after exclude", hidden, "api ok", ok)
    w.close()
    assert seen[0] > 200 and seen[1] < 60
    if ok:
        assert not (hidden[0] > 200 and hidden[1] < 60)


class _Player:
    """«Плеер»: чёрное окно с белыми субтитрами, текст меняем как в видео."""

    def __init__(self, app, rect=(80, 420, 860, 110)):
        from PySide6.QtWidgets import QLabel

        self.w = QLabel()
        self.w.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                              | Qt.WindowType.Tool)
        self.w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.w.setStyleSheet("background: #101418; color: white; font-family: 'Segoe UI'; font-size: 34px;"
                             " font-weight: 600;")
        self.w.setGeometry(*rect)
        self.w.show()
        self.app = app

    def say(self, text):
        self.w.setText(text)
        self.w.repaint()
        self.app.processEvents()


@pytest.mark.parametrize("recordable", [False, True])
def test_live_subtitles_speed(app, recordable):
    """Полный путь на настоящем экране: фраза появилась → OCR → перевод → плашка. Печатаем скорость."""
    from PySide6.QtCore import QRect
    from babylon import live
    from babylon.ui import theme
    from babylon.ui.subs import LiveBar, SubsOverlay

    theme.load_fonts()

    class Tr:  # перевод мгновенный — меряем именно экран и распознавание
        mode = "online"

        class online:
            @staticmethod
            def available():
                return True

            @staticmethod
            def translate(text, src, tgt):
                return {"out": "RU: " + text}

        class engine:
            @staticmethod
            def can_translate(a, b):
                return False

    player = _Player(app)
    pump(app, 0.5)
    rect = QRect(80, 440, 860, 70)
    screen = app.primaryScreen()
    subs = live.LiveSubs(Tr(), {"preferred": "ru", "fallback": "en", "ocr_lang": "auto"})
    ov = SubsOverlay()
    bar = LiveBar("ru", 90)
    got = []
    subs.phrase.connect(lambda text, out, lines, ms: (got.append((time.perf_counter(), text, out, ms)),
                                                       ov.set_phrase(out, lines)))
    ov.place(rect, screen, recordable)
    bar.place(rect, screen, recordable)
    subs.start(rect, screen, "ru")
    print("overlay covers original:", ov.cover, "recordable:", recordable)
    if recordable:  # видно на записи — значит, не поверх оригинала, иначе прочли бы свой перевод
        assert not ov.cover and ov.geometry().top() > rect.bottom()
    before = screen.grabWindow(0, 40, 360, 940, 260).toImage()
    results = []
    for phrase in ("Where are you going?", "It is late. Let's go home.", "I can't leave you here alone."):
        n = len(got)
        t0 = time.perf_counter()
        player.say(phrase)
        end = time.time() + 5
        while time.time() < end and len(got) == n:
            pump(app, 0.005)
        assert len(got) > n, f"фраза не распознана: {phrase}"
        took = (got[-1][0] - t0) * 1000
        results.append(took)
        print(f"live: {phrase!r} -> {got[-1][2]!r} за {took:.0f} мс (OCR {subs.ocr_ms} мс, язык {subs.lang})")
        assert "going" in got[-1][1] or "late" in got[-1][1] or "alone" in got[-1][1]
        pump(app, 0.4)
    tag = "_rec" if recordable else ""
    ov.grab().save(os.path.join(os.environ.get("BABYLON_SHOTS", "."), f"live_overlay_real{tag}.png"))
    full = screen.grabWindow(0, 40, 360, 940, 260)
    full.save(os.path.join(os.environ.get("BABYLON_SHOTS", "."), f"live_screen_real{tag}.png"))
    if recordable:  # плашка перевода под областью попала в снимок экрана: там изменились пиксели
        img = full.toImage()
        diff = sum(abs(img.pixelColor(x, y).lightness() - before.pixelColor(x, y).lightness()) > 40
                   for x in range(0, img.width(), 4) for y in range(rect.bottom() - 360 + 4, img.height(), 2))
        print("changed pixels under the region:", diff)
        assert diff > 100, "плашки нет на снимке экрана"
    subs.stop()
    ov.close()
    bar.close()
    player.w.close()
    print("live latency ms:", [int(x) for x in results])
    assert max(results) < 1500


def test_photo_real_ocr(app):
    from babylon import lens
    from babylon.ui import theme
    from samples import photo

    theme.load_fonts()
    img = photo().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    t = time.perf_counter()
    lines, lang, sc = ocr.read_auto(bytes(img.constBits())[: img.width() * img.height() * 4], img.width(),
                                    img.height())
    blocks = lens.group(lines)
    print(f"photo OCR {lang} {sc:.2f} in {(time.perf_counter() - t) * 1000:.0f} ms:", [b.text for b in blocks])
    texts = " | ".join(b.text for b in blocks).lower()
    assert "coffee" in texts and "cappuccino" in texts and "chocolate" in texts
    out = lens.paint(img, blocks, [b.text.upper() for b in blocks], "photo")
    out.save(os.path.join(os.environ.get("BABYLON_SHOTS", "."), "photo_real_ocr.png"))


def test_video_real_ocr(app, tmp_path):
    from babylon import video
    from babylon.ui import theme
    import test_lens as T

    theme.load_fonts()
    print("ffmpeg:", video.ffmpeg_exe())
    src = str(tmp_path / "in.mp4")
    T._make_video(src, 960, 540, 4.5)
    t = time.perf_counter()
    info, segs, k = video.analyze(src, lambda b, w, h: ocr.read(b, w, h, "en"))
    took = time.perf_counter() - t
    print(f"video analyze {took:.1f} s for {info.duration:.1f} s:", [(round(s.start, 2), round(s.end, 2), s.text)
                                                                     for s in segs])
    found = [s.text.lower() for s in segs]
    assert any("going" in f for f in found) and any("late" in f for f in found)
    video.translate_segments(segs, lambda x: "RU " + x)
    out = str(tmp_path / "out.mp4")
    video.export(src, out, info, segs, k)
    oi = video.probe(out)
    assert oi.audio and abs(oi.duration - 4.5) < 0.2


# ---------------- 2.2: перевод речи ----------------
def test_audio_devices_and_loopback(app):
    """Есть ли звуковые устройства на машине и пишет ли «петля» звука компьютера (на сервере может не быть)."""
    from babylon import audio

    print("audio devices:", audio.devices())
    got, errors = [], []
    cap = audio.Capture("system", got.append, on_error=errors.append)
    cap.start()
    time.sleep(1.5)
    cap.stop()
    total = sum(len(c) for c in got) / audio.SR
    print(f"loopback: {total:.1f} s of audio, errors: {errors}")
    if errors:
        pytest.skip("на этой машине нет устройства вывода звука")
    assert total > 0.5


def test_speech_recognition_windows_voice(app):
    """Голос Windows говорит по-английски → Whisper распознаёт → переводится."""
    import subprocess
    import tempfile

    import numpy as np
    from babylon import asr, speech, video

    if not asr.installed("base"):
        pytest.skip("нет модели whisper")
    if "en" not in speech.voices():
        pytest.skip("нет английского голоса")
    data, ext = speech.synthesize("Hello my friend. The weather is beautiful today, let's go for a walk.", "en")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
        f.write(data)
    raw = subprocess.run([video.ffmpeg_exe(), "-loglevel", "error", "-i", f.name, "-ar", "16000", "-ac", "1", "-f",
                          "f32le", "-"], stdout=subprocess.PIPE, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    t = time.perf_counter()
    r = asr.recognizer("base").transcribe(a)
    took = (time.perf_counter() - t) * 1000
    print(f"whisper on Windows voice: {r} in {took:.0f} ms for {len(a) / 16000:.1f} s of speech")
    assert r["lang"] == "en" and "weather" in r["text"].lower()
