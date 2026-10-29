"""Распознавание текста на картинке встроенным OCR Windows 10/11 (без интернета).

Языки OCR ставятся вместе с языковыми пакетами Windows. Русский:
Параметры -> Время и язык -> Язык и регион -> Русский -> Языковые параметры -> «Оптическое распознавание символов».
"""
import asyncio
import re
import sys
import threading
from dataclasses import dataclass, field

from .langs import is_han, is_hangul, is_kana

IS_WIN = sys.platform == "win32"


class OcrUnavailable(Exception):
    pass


def _winrt():
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
    except Exception as e:  # не Windows или не установлены пакеты winrt-*
        raise OcrUnavailable(f"OCR Windows недоступен: {e}") from e
    return Language, BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap, OcrEngine, DataWriter


def available_languages() -> list[str]:
    """Коды языков, для которых в Windows установлен OCR (например ['en', 'ru'])."""
    if not IS_WIN:
        return []
    try:
        *_, OcrEngine, _ = _winrt()
    except OcrUnavailable:
        return []
    codes = []
    for lang in OcrEngine.available_recognizer_languages:
        code = lang.language_tag.split("-")[0].lower()
        if code not in codes:
            codes.append(code)
            _TAGS[code] = lang.language_tag  # «zh» сам по себе не создаётся, нужен «zh-Hans-CN»
    return codes


_TAGS: dict[str, str] = {}


def _cyr_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters) if letters else 0.0


# Буквы, у которых нет латинского двойника: в русском тексте они почти в каждом слове,
# а когда русский OCR читает английский текст, он пишет «Неllо» буквами-двойниками без них.
_CYR_ONLY = set("бвгдёжзийлмнпфцчшщъыьэюяБГДЁЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯ")


def looks_russian(text: str) -> bool:
    words = [w for w in text.split() if sum(c.isalpha() for c in w) >= 3]
    if not words:
        return _cyr_share(text) > 0.5
    real = sum(1 for w in words if any(c in _CYR_ONLY for c in w))
    return real / len(words) >= 0.4


@dataclass
class Line:
    """Строка текста на картинке и её рамка в пикселях (words — слова с рамками)."""

    text: str
    x: float
    y: float
    w: float
    h: float
    words: list = field(default_factory=list)


_local = threading.local()


def _engine(lang: str):
    # создавать распознаватель на каждый кадр дорого: живые субтитры держат готовые (свои у каждого потока)
    cache = getattr(_local, "engines", None)
    if cache is None:
        cache = _local.engines = {}
    if lang not in cache:
        Language, *_, OcrEngine, _ = _winrt()
        cache[lang] = OcrEngine.try_create_from_language(Language(_TAGS.get(lang, lang)))
    return cache[lang]


def _loop():
    if getattr(_local, "loop", None) is None:
        _local.loop = asyncio.new_event_loop()
    return _local.loop


async def _recognize(bgra: bytes, width: int, height: int, lang: str):
    _, BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap, _, DataWriter = _winrt()
    engine = _engine(lang)
    if engine is None:
        return None
    w = DataWriter()
    w.write_bytes(bgra)
    bmp = SoftwareBitmap.create_copy_from_buffer(
        w.detach_buffer(), BitmapPixelFormat.BGRA8, width, height, BitmapAlphaMode.PREMULTIPLIED
    )
    res = await engine.recognize_async(bmp)
    lines = []
    for ln in res.lines:
        words = []
        for wd in ln.words:
            r = wd.bounding_rect
            words.append((wd.text, r.x, r.y, r.width, r.height))
        if not words:
            continue
        x0 = min(w[1] for w in words)
        y0 = min(w[2] for w in words)
        x1 = max(w[1] + w[3] for w in words)
        y1 = max(w[2] + w[4] for w in words)
        lines.append(Line(ln.text, x0, y0, x1 - x0, y1 - y0, words))
    return lines


_LATIN_WORD = re.compile(r"^[(«\"']?[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ]+)*[.,!?;:)»\"']*$")
_ASIAN_SPACE = re.compile(r"(?<=[\u3000-\u30ff\u4e00-\u9fff\uff00-\uffef])[ \t]+(?=[\u3000-\u30ff\u4e00-\u9fff\uff00-\uffef])")


def score(text: str, lang: str) -> float:
    """Насколько текст похож на правильно прочитанный на языке lang (0..1)."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    if lang == "ru":
        words = [w for w in text.split() if sum(c.isalpha() for c in w) >= 3]
        if not words:
            return 0.0
        return sum(1 for w in words if any(c in _CYR_ONLY for c in w)) / len(words)
    if lang in ("ja", "zh", "ko"):
        kana = sum(map(is_kana, chars))
        han = sum(map(is_han, chars))
        hangul = sum(map(is_hangul, chars))
        own = {"ja": kana + han, "zh": han, "ko": hangul}[lang] / len(chars)
        if lang == "ja" and not kana:
            own *= 0.6  # без каны это скорее китайский
        if lang == "zh" and kana:
            own *= 0.6
        return own
    words = [w for w in text.split() if any(c.isalpha() for c in w)]
    if not words:
        return 0.0
    good = sum(1 for w in words if _LATIN_WORD.match(w) and not re.search(r"[a-z][A-Z]", w))
    return 0.95 * good / len(words)


def read(bgra: bytes, width: int, height: int, lang: str) -> list[Line]:
    """Строки с рамками одним распознавателем (быстро: для живых субтитров и кадров видео)."""
    lines = _loop().run_until_complete(_recognize(bgra, width, height, lang)) or []
    if lang in ("ja", "zh"):
        for ln in lines:
            ln.text = _ASIAN_SPACE.sub("", ln.text)
    return lines


def text_of(lines: list[Line]) -> str:
    return "\n".join(ln.text for ln in lines)


def candidates() -> list[str]:
    langs = available_languages()
    latin = next((l for l in ("en", "de", "fr", "it", "es") if l in langs), None)
    out = [l for l in ("ru", "ja", "zh", "ko") if l in langs] + ([latin] if latin else [])
    return out or langs[:1]


def read_auto(bgra: bytes, width: int, height: int, prefer: str = "auto") -> tuple[list[Line], str, float]:
    """Вернуть (строки, код языка OCR, уверенность 0..1). prefer: 'auto' или код языка.

    В режиме auto читаем картинку всеми подходящими распознавателями (русский, латиница,
    японский, китайский, корейский — какие установлены) и берём самый правдоподобный текст.
    """
    langs = available_languages()
    if not langs:
        raise OcrUnavailable("В Windows не установлен ни один язык распознавания текста (OCR)")
    max_side = 10000  # предел OCR Windows
    if width > max_side or height > max_side:
        raise OcrUnavailable("Область слишком большая для распознавания")

    if prefer != "auto":
        lang = prefer if prefer in langs else langs[0]
        lines = read(bgra, width, height, lang)
        return lines, lang, score(text_of(lines), lang)

    cands = candidates()
    best = ([], cands[0], -1.0)
    for lang in cands:
        lines = read(bgra, width, height, lang)
        sc = score(text_of(lines), lang)
        if sc > best[2]:
            best = (lines, lang, sc)
        if sc >= 0.85:
            break  # уверенно: остальные распознаватели не нужны
    return best


def recognize(bgra: bytes, width: int, height: int, prefer: str = "auto") -> tuple[str, str]:
    """Вернуть (текст, код языка OCR)."""
    lines, lang, _ = read_auto(bgra, width, height, prefer)
    return text_of(lines), lang
