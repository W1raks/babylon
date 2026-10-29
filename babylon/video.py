"""Перевод видео: читаем кадры через ffmpeg, находим надписи и субтитры, переводим и рисуем поверх.

Анализ: кадры 4 раза в секунду → строки OCR → блоки → отрезки времени с одной и той же надписью.
Экспорт: на каждый отрезок прозрачная картинка с плашками перевода, ffmpeg накладывает их на видео
одним проходом и сохраняет звук. Отдельно можно сохранить субтитры .srt.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter

from . import lens

SAMPLE_FPS = 4          # сколько кадров в секунду читаем для поиска надписей
ANALYSIS_SIDE = 1280    # кадры уменьшаем до этой стороны: OCR быстрее, субтитры читаются
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".3gp")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")


class VideoError(Exception):
    pass


def _quiet() -> dict:
    """Аргументы subprocess для оконной программы: без чёрного окна консоли и без наследования stdin."""
    kw = {"stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kw


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if not exe:
        raise VideoError("не найден ffmpeg для работы с видео")
    return exe


@dataclass
class Info:
    width: int
    height: int
    duration: float
    fps: float
    audio: bool


def probe(path: str) -> Info:
    p = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, **_quiet())
    err = p.stderr.decode("utf-8", "replace")
    m = re.search(r"Stream #\S+.*?Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not m:
        raise VideoError("в файле не нашлось видео")
    w, h = int(m.group(1)), int(m.group(2))
    rot = re.search(r"rotat(?:e\s*:\s*|ion of )(-?\d+)", err)
    if rot and abs(int(rot.group(1))) % 180 == 90:
        w, h = h, w  # телефонное видео снято «боком»: ffmpeg сам повернёт кадры
    d = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    f = re.search(r"(\d+(?:\.\d+)?) fps", err)
    return Info(w, h, dur, float(f.group(1)) if f else 25.0, "Audio:" in err)


def analysis_size(info: Info, side: int = ANALYSIS_SIDE) -> tuple[int, int]:
    k = min(1.0, side / max(info.width, info.height))
    return max(2, int(info.width * k) // 2 * 2), max(2, int(info.height * k) // 2 * 2)


def frames(path: str, w: int, h: int, fps: float = SAMPLE_FPS, start: float = 0.0, realtime=False,
           stop: threading.Event | None = None):
    """Кадры BGRA w×h: (время, bytes). realtime — отдавать с обычной скоростью (для просмотра)."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if realtime:
        cmd += ["-re"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", path, "-an", "-sn", "-vf", f"fps={fps},scale={w}:{h}:flags=bilinear",
            "-f", "rawvideo", "-pix_fmt", "bgra", "pipe:1"]
    kw = _quiet()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 4, **kw)
    size = w * h * 4
    i = 0
    try:
        while not (stop and stop.is_set()):
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield start + i / fps, buf
            i += 1
    finally:
        proc.kill()
        proc.wait()


# ---------------- отрезки с надписями ----------------
@dataclass
class Segment:
    start: float
    end: float
    blocks: list = field(default_factory=list)   # блоки кадра, где надпись прочиталась лучше всего
    key: str = ""
    outs: list = field(default_factory=list)     # переводы блоков

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)


class Timeline:
    """Собирает отрезки из кадров: пока надпись та же (OCR может ошибиться в букве), отрезок длится."""

    def __init__(self, step: float):
        self.step = step
        self.done: list[Segment] = []
        self.cur: Segment | None = None
        self.miss = 0
        self.last_t = 0.0

    def add(self, t: float, blocks: list):
        text = "\n".join(b.text for b in blocks)
        key = lens.norm(text)
        if len(key.replace(" ", "")) < 2:
            key = ""
        if self.cur and key and (lens.similar(key, self.cur.key) >= 0.72 or key.startswith(self.cur.key)):
            # та же надпись или она дописывается (текст в играх появляется по буквам)
            self.cur.end = t + self.step / 2
            self.miss = 0
            if len(key) > len(self.cur.key):  # самый полный вариант надписи
                self.cur.blocks, self.cur.key = blocks, key
            return
        if self.cur and not key and self.miss == 0:
            self.miss = 1  # один пустой кадр — возможно, OCR не прочитал; ждём следующий
            return
        self._close()
        if key:
            self.cur = Segment(max(0.0, t - self.step / 2), t + self.step / 2, blocks, key)

    def _close(self):
        if self.cur:
            self.done.append(self.cur)
        self.cur = None
        self.miss = 0

    def finish(self) -> list[Segment]:
        self._close()
        return self.done


def srt(segments: list[Segment]) -> str:
    def ts(t):
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    out = []
    for i, s in enumerate((s for s in segments if any(o.strip() for o in s.outs)), start=1):
        text = "\n".join(o.strip() for o in s.outs if o.strip())
        out.append(f"{i}\n{ts(s.start)} --> {ts(s.end)}\n{text}\n")
    return "\n".join(out)


def analyze(path: str, read_lines, progress=None, stop: threading.Event | None = None,
            fps: float = SAMPLE_FPS) -> tuple[Info, list[Segment], float]:
    """read_lines(bgra, w, h) → строки OCR. Вернуть (сведения, отрезки, во сколько раз уменьшены кадры)."""
    info = probe(path)
    w, h = analysis_size(info)
    k = info.width / w
    tl = Timeline(1 / fps)
    prev_thumb, prev_blocks = None, []
    total = max(1, int(info.duration * fps))
    for i, (t, buf) in enumerate(frames(path, w, h, fps, stop=stop)):
        arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
        thumb = arr[::4, ::4, :3].astype(np.int16)
        if prev_thumb is not None and not (np.abs(thumb - prev_thumb) > 24).any():
            blocks = prev_blocks  # кадр почти не изменился: OCR не нужен
        else:
            blocks = lens.group(read_lines(buf, w, h))
        prev_thumb, prev_blocks = thumb, blocks
        tl.add(t, blocks)
        if progress:
            progress(min(i + 1, total), total)
    if stop and stop.is_set():
        raise VideoError("остановлено")
    return info, tl.finish(), k


def translate_segments(segments: list[Segment], translate, workers: int = 4):
    """translate(text) → перевод. Одинаковые надписи переводятся один раз, по 4 запроса сразу."""
    from concurrent.futures import ThreadPoolExecutor

    texts = sorted({b.text for s in segments for b in s.blocks})
    with ThreadPoolExecutor(workers) as ex:
        done = dict(zip(texts, ex.map(translate, texts)))
    for s in segments:
        s.outs = [done.get(b.text, "") for b in s.blocks]


def overlay(info: Info, seg: Segment, k: float) -> QImage:
    """Прозрачная картинка размером с видео: плашки перевода на месте надписей."""
    img = QImage(info.width, info.height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    for b, out in zip(seg.blocks, seg.outs):
        if out.strip():
            lens._paint_plate(p, b.scaled(k), out.strip(), info.width, info.height)
    p.end()
    return img


def export(path: str, out_path: str, info: Info, segments: list[Segment], k: float, progress=None,
           stop: threading.Event | None = None):
    """Сохранить видео с переводом поверх (звук сохраняется)."""
    tmp = tempfile.mkdtemp(prefix="babylon-video-")
    try:
        blank = QImage(info.width, info.height, QImage.Format.Format_ARGB32_Premultiplied)
        blank.fill(Qt.GlobalColor.transparent)
        blank.save(os.path.join(tmp, "blank.png"))
        lines, t = [], 0.0

        def put(name, dur):
            if dur > 0.001:
                lines.append(f"file '{name}'\nduration {dur:.3f}")

        for i, s in enumerate(x for x in segments if any(o.strip() for o in x.outs)):
            start = max(s.start, t)
            put("blank.png", start - t)
            name = f"s{i:05d}.png"
            overlay(info, s, k).save(os.path.join(tmp, name))
            put(name, s.end - start)
            t = s.end
        put("blank.png", max(0.5, info.duration - t + 1))
        lines.append("file 'blank.png'")  # последний кадр повторяется — так требует concat
        with open(os.path.join(tmp, "list.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-nostdin", "-i", path,
               "-f", "concat", "-safe", "0", "-i", os.path.join(tmp, "list.txt"),
               "-filter_complex", "[1:v]format=rgba[o];[0:v][o]overlay=0:0:eof_action=pass:shortest=0,format=yuv420p[v]",
               "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
               "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats",
               out_path]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_quiet())
        err_lines: list[str] = []
        threading.Thread(target=lambda: err_lines.extend(proc.stderr.read().decode("utf-8", "replace")
                                                          .splitlines()[-8:]), daemon=True).start()
        for raw in proc.stdout:
            if stop and stop.is_set():
                proc.kill()
                break
            m = re.match(rb"out_time_us=(\d+)", raw)
            if m and progress and info.duration:
                progress(min(int(m.group(1)) / 1e6, info.duration), info.duration)
        proc.wait()
        if stop and stop.is_set():
            raise VideoError("остановлено")
        if proc.returncode != 0:
            raise VideoError("ffmpeg не смог сохранить видео: " + " ".join(err_lines[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def at(segments: list[Segment], t: float) -> Segment | None:
    return next((s for s in segments if s.start <= t < s.end), None)
