"""Озвучка: голоса Windows (без интернета), а для языков без голоса — Google (онлайн).

Звук проигрывается через MCI (winmm), он умеет и wav, и mp3 без лишних библиотек.
"""
import asyncio
import ctypes
import os
import sys
import tempfile
import threading
import urllib.request

from .online import UA, tts_url

IS_WIN = sys.platform == "win32"
_lock = threading.Lock()
_alias = "babylon_tts"


class SpeechError(Exception):
    pass


def _winrt_voice(lang: str):
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer

    voices = list(SpeechSynthesizer.all_voices)
    for v in voices:
        if v.language.lower().split("-")[0] == lang:
            return v
    return None


def voices() -> list[str]:
    """Языки, для которых в Windows установлен голос (['ru', 'en', ...])."""
    if not IS_WIN:
        return []
    try:
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        return sorted({v.language.lower().split("-")[0] for v in SpeechSynthesizer.all_voices})
    except Exception:
        return []


async def _synth(text: str, voice) -> bytes:
    from winrt.windows.media.speechsynthesis import SpeechSynthesizer
    from winrt.windows.storage.streams import DataReader

    s = SpeechSynthesizer()
    s.voice = voice
    stream = await s.synthesize_text_to_stream_async(text)
    size = stream.size
    reader = DataReader(stream.get_input_stream_at(0))
    await reader.load_async(size)
    buf = bytearray(size)
    reader.read_bytes(buf)
    return bytes(buf)


def synthesize(text: str, lang: str) -> tuple[bytes, str]:
    """Вернуть (звук, расширение). Сначала голос Windows, потом Google."""
    if IS_WIN:
        try:
            voice = _winrt_voice(lang)
        except Exception:
            voice = None
        if voice is not None:
            return asyncio.run(_synth(text[:3000], voice)), ".wav"
    try:
        req = urllib.request.Request(tts_url(text, lang), headers=UA)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read()
        if len(data) < 500:
            raise SpeechError("пустой ответ")
        return data, ".mp3"
    except Exception as e:
        raise SpeechError(f"для языка «{lang}» нет голоса в Windows, а онлайн-озвучка недоступна") from e


def _mci(cmd: str) -> int:
    buf = ctypes.create_unicode_buffer(256)
    return ctypes.windll.winmm.mciSendStringW(cmd, buf, 255, 0)


def stop():
    if IS_WIN:
        with _lock:
            _mci(f"close {_alias}")


def play(data: bytes, ext: str):
    if not IS_WIN:
        return
    stop()
    path = os.path.join(tempfile.gettempdir(), f"babylon_tts{ext}")
    with open(path, "wb") as f:
        f.write(data)
    with _lock:
        if _mci(f'open "{path}" type mpegvideo alias {_alias}') != 0:
            raise SpeechError("не удалось открыть звук")
        _mci(f"play {_alias}")


def speak(text: str, lang: str):
    """Озвучить в фоне (вызывать из потока: синтез занимает до секунды)."""
    data, ext = synthesize(text, lang)
    play(data, ext)
