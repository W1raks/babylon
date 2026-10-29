"""Звук для перевода речи: захват (звук компьютера или микрофон) и деление потока на фразы.

Звук компьютера — «петля» WASAPI (то, что играет в колонках или наушниках: видео, созвоны),
микрофон — обычная запись. Библиотека soundcard, без драйверов и виртуальных устройств.
"""
import sys
import threading
import time

import numpy as np

SR = 16000
FRAME = 320  # 20 мс


def to_mono16k(block: np.ndarray, rate: int) -> np.ndarray:
    """Кусок звука (кадры × каналы) любой частоты → моно 16 кГц float32."""
    a = block.mean(axis=1) if block.ndim == 2 else block
    a = a.astype(np.float32)
    if rate == SR or len(a) == 0:
        return a
    if rate % SR == 0:  # 48000 → 16000: сглаживаем и берём каждый k-й
        k = rate // SR
        n = len(a) // k * k
        return a[:n].reshape(-1, k).mean(axis=1)
    n = int(len(a) * SR / rate)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


class Segmenter:
    """Делит поток на фразы по паузам. feed(звук) → список событий:
    ('partial', звук фразы до этого места) — пока человек говорит, не чаще partial_every секунд;
    ('final', звук всей фразы) — после паузы или когда фраза стала слишком длинной."""

    def __init__(self, pause=0.55, max_len=7.0, min_len=0.45, partial_every=1.1, preroll=0.3):
        self.pause, self.max_len, self.min_len = pause, max_len, min_len
        self.partial_every, self.preroll = partial_every, int(preroll * SR)
        self.floor = 0.003          # уровень шума, подстраивается сам
        self.buf = np.zeros(0, np.float32)
        self.pre = np.zeros(0, np.float32)
        self.speaking = False
        self.silent = 0.0
        self.last_partial = 0.0
        self.level = 0.0
        self._rest = np.zeros(0, np.float32)

    def threshold(self) -> float:
        return max(self.floor * 3.0, 0.006)

    def feed(self, audio: np.ndarray) -> list:
        ev = []
        a = np.concatenate([self._rest, audio])
        n = len(a) // FRAME * FRAME
        self._rest = a[n:]
        for i in range(0, n, FRAME):
            fr = a[i:i + FRAME]
            rms = float(np.sqrt(np.mean(fr * fr)) + 1e-9)
            self.level = 0.8 * self.level + 0.2 * rms
            loud = rms > self.threshold()
            # шум: быстро вниз, медленно вверх (речь не должна «поднимать» порог)
            self.floor = self.floor * 0.9 + rms * 0.1 if rms < self.floor else self.floor * 0.9995 + rms * 0.0005
            if not self.speaking:
                self.pre = np.concatenate([self.pre, fr])[-self.preroll:]
                if loud:
                    self.speaking = True
                    self.buf = self.pre.copy()
                    self.silent = 0.0
                    self.last_partial = 0.0
                continue
            self.buf = np.concatenate([self.buf, fr])
            self.silent = 0.0 if loud else self.silent + FRAME / SR
            dur = len(self.buf) / SR
            if self.silent >= self.pause or dur >= self.max_len:
                if dur - self.silent >= self.min_len:
                    ev.append(("final", self._cut()))
                else:
                    self.buf = np.zeros(0, np.float32)
                self.speaking = False
                self.pre = np.zeros(0, np.float32)
            elif dur - self.last_partial >= self.partial_every:
                self.last_partial = dur
                ev.append(("partial", self.buf.copy()))
        return ev

    def _cut(self) -> np.ndarray:
        out, self.buf = self.buf, np.zeros(0, np.float32)
        return out

    def flush(self) -> list:
        if self.speaking and len(self.buf) / SR >= self.min_len:
            self.speaking = False
            return [("final", self._cut())]
        return []


class Capture:
    """Поток, который читает звук и отдаёт его в callback(моно 16 кГц float32) кусками по 0,1 с."""

    def __init__(self, source: str, callback, on_error=None):
        self.source = source  # 'system' или 'mic'
        self.callback = callback
        self.on_error = on_error
        self.stop_flag = threading.Event()
        self.thread = None

    def start(self):
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._run, name="babylon-audio", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_flag.set()

    def _run(self):
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.ole32.CoInitializeEx(None, 0)  # soundcard в своём потоке требует COM
        try:
            import soundcard as sc

            if self.source == "system":
                spk = sc.default_speaker()
                dev = sc.get_microphone(id=str(spk.name), include_loopback=True)
            else:
                dev = sc.default_microphone()
            rate = 48000
            with dev.recorder(samplerate=rate, blocksize=rate // 50) as rec:
                while not self.stop_flag.is_set():
                    data = rec.record(numframes=rate // 10)
                    self.callback(to_mono16k(np.asarray(data), rate))
        except Exception as e:
            if self.on_error:
                self.on_error(describe_error(e, self.source))


def describe_error(e: Exception, source: str) -> str:
    if isinstance(e, (ImportError, OSError)) and "soundcard" in repr(e).lower():
        return "не удалось включить запись звука"
    what = "звук компьютера" if source == "system" else "микрофон"
    text = str(e)
    if "0x80070490" in text or "0x88890004" in text:  # устройства нет или оно отключено
        dev = "колонки или наушники" if source == "system" else "микрофон"
        return f"не найдено устройство: {dev}. проверьте, что оно подключено и выбрано в звуке windows"
    if "0x80070005" in text:  # доступ запрещён (обычно к микрофону)
        return ("windows не разрешает слушать микрофон: параметры → конфиденциальность → микрофон → "
                "разрешить классическим приложениям")
    return f"не получилось слушать {what}: {text}"


def devices() -> dict:
    """Что есть в системе (для проверки и подсказок)."""
    try:
        import soundcard as sc

        spk = sc.default_speaker()
        mic = sc.default_microphone()
        return {"speaker": spk.name if spk else None, "microphone": mic.name if mic else None}
    except Exception as e:
        return {"error": str(e)}


def pace(chunks, rate_s: float = 0.1):
    """Для проверок: отдавать звук из файла кусками в реальном времени."""
    for c in chunks:
        yield c
        time.sleep(rate_s)
