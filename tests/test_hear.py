"""Перевод речи: деление на фразы (всегда) и полный путь звук → Whisper → перевод (если есть модель).

Модель: BABYLON_WHISPER=<папка, где лежит whisper-base>. Звук — tests/audio/speech_ru.ogg (две фразы).
"""
import os
import subprocess
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from babylon import asr, audio, hear, video

app = QApplication.instance() or QApplication([])
CLIP = os.path.join(os.path.dirname(__file__), "audio", "speech_ru.ogg")


def load(path=CLIP) -> np.ndarray:
    raw = subprocess.run([video.ffmpeg_exe(), "-loglevel", "error", "-i", path, "-ar", "16000", "-ac", "1",
                          "-f", "f32le", "-"], stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def tone(sec, amp=0.2, f=220):
    t = np.arange(int(sec * audio.SR)) / audio.SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def test_resample():
    a = np.ones((4800, 2), np.float32)
    assert len(audio.to_mono16k(a, 48000)) == 1600
    assert len(audio.to_mono16k(np.ones(44100, np.float32), 44100)) == 16000


def test_segmenter_finds_phrases():
    seg = audio.Segmenter()
    noise = lambda s: (np.random.RandomState(1).randn(int(s * audio.SR)) * 0.001).astype(np.float32)  # noqa: E731
    stream = np.concatenate([noise(1), tone(1.2), noise(0.8), tone(2.5), noise(1)])
    ev = []
    for i in range(0, len(stream), 1600):
        ev += seg.feed(stream[i:i + 1600])
    finals = [len(a) / audio.SR for k, a in ev if k == "final"]
    assert len(finals) == 2
    assert 1.2 <= finals[0] <= 2.2 and 2.5 <= finals[1] <= 3.5
    assert any(k == "partial" for k, _ in ev)


def test_segmenter_cuts_long_speech():
    seg = audio.Segmenter(max_len=5)
    ev = []
    stream = tone(12)
    for i in range(0, len(stream), 1600):
        ev += seg.feed(stream[i:i + 1600])
    assert sum(1 for k, _ in ev if k == "final") == 2  # музыка без пауз режется на куски


def test_features_shape():
    f = asr.features(tone(2))
    assert f.shape == (80, 3000) and f.dtype == np.float32


needs_model = pytest.mark.skipif(not asr.installed("base"), reason="нет модели Whisper (BABYLON_WHISPER)")


@needs_model
def test_recognize_russian():
    r = asr.recognizer("base").transcribe(load()[: int(6.5 * audio.SR)])
    assert r["lang"] == "ru" and "язык" in r["text"].lower()


class FakeTr:
    def translate(self, text, src, tgt, *a, **k):
        return {"out": f"[{tgt}] {text}"}


@needs_model
def test_hearing_flow():
    s = {"preferred": "ru", "fallback": "en", "asr_model": "base", "voice_over": False}
    h = hear.Hearing(FakeTr(), s)
    got, drafts = [], []
    h.phrase.connect(got.append)
    h.draft.connect(lambda t, o: drafts.append(t))
    assert h.start("system", capture=False)
    a = load()
    t0 = time.time()
    for i in range(0, len(a), 1600):
        h.feed(a[i:i + 1600])
        time.sleep(0.02)  # быстрее реального времени
        app.processEvents()
    end = time.time() + 20
    while time.time() < end and len(got) < 2:
        app.processEvents()
        time.sleep(0.05)
    h.stop()
    print("phrases:", [(p["text"], p["out"], p["ms"]) for p in got], "drafts:", drafts, round(time.time() - t0, 1), "s")
    assert len(got) == 2
    assert "язык" in got[0]["text"] and "встреч" in got[1]["text"]
    # сказано по-русски, а переводим на русский — значит перевод на язык собеседника (английский)
    assert got[0]["tgt"] == "en" and got[0]["out"].startswith("[en]")
