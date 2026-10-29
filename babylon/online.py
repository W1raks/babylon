"""Онлайн-перевод: Google (без ключа, как в расширениях браузеров), запасной — MyMemory.

Google заодно отдаёт словарь для отдельных слов: части речи, варианты, примеры и чтение.
"""
import json
import time
import urllib.parse
import urllib.request

from .langs import from_google, google_code

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Babylon/2.0"}
GOOGLE_URL = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
TIMEOUT = 6

POS_RU = {
    "noun": "существительное", "verb": "глагол", "adjective": "прилагательное", "adverb": "наречие",
    "pronoun": "местоимение", "preposition": "предлог", "conjunction": "союз", "interjection": "междометие",
    "abbreviation": "сокращение", "phrase": "фраза", "article": "артикль", "particle": "частица",
    "prefix": "приставка", "suffix": "суффикс", "auxiliary verb": "вспомогательный глагол",
}


class OnlineError(Exception):
    pass


class Result(dict):
    """out, src (определённый язык), engine, а для слов ещё dict/examples/translit."""


def _chunks(text: str, limit: int) -> list[str]:
    """Разрезать длинный текст по абзацам/предложениям, не длиннее limit символов."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for piece in text.replace("\r", "").split("\n"):
        piece += "\n"
        while len(piece) > limit:  # очень длинный абзац — по предложениям
            cut = max(piece.rfind(". ", 0, limit), piece.rfind(" ", 0, limit))
            cut = cut + 1 if cut > 0 else limit
            parts.append(piece[:cut])
            piece = piece[cut:]
        if len(cur) + len(piece) > limit:
            parts.append(cur)
            cur = ""
        cur += piece
    if cur:
        parts.append(cur)
    out = [p for p in parts if p]
    if out and not text.endswith("\n"):
        out[-1] = out[-1].rstrip("\n")
    return out


def _post(url: str, params: dict, data: dict | None = None):
    q = urllib.parse.urlencode(params, doseq=True)
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(f"{url}?{q}", data=body, headers={
        **UA, **({"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise OnlineError(f"сервер ответил {e.code}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OnlineError("нет связи с сервером перевода") from e
    except ValueError as e:
        raise OnlineError("непонятный ответ сервера") from e


def parse_google(data: dict) -> Result:
    """Разобрать ответ Google (параметр dj=1) в Result."""
    sentences = data.get("sentences") or []
    out = "".join(s.get("trans", "") for s in sentences if "trans" in s)
    translit = "".join(s.get("translit", "") for s in sentences if "translit" in s)
    src_translit = "".join(s.get("src_translit", "") for s in sentences if "src_translit" in s)
    res = Result(out=out, src=from_google(data.get("src", "auto")), engine="google")
    if translit:
        res["translit"] = translit
    if src_translit:
        res["src_translit"] = src_translit
    groups = []
    for d in data.get("dict") or []:
        entries = [(e.get("word", ""), e.get("reverse_translation") or [], e.get("score", 0))
                   for e in d.get("entry") or []]
        entries.sort(key=lambda e: -e[2])
        if entries:
            groups.append({"pos": POS_RU.get(d.get("pos", ""), d.get("pos", "")),
                           "terms": [{"word": w, "back": back[:4]} for w, back, _ in entries[:8]]})
    if groups:
        res["dict"] = groups
    ex = [e.get("text", "") for e in ((data.get("examples") or {}).get("example") or [])]
    if ex:
        import re

        res["examples"] = [re.sub(r"</?b>", "", e) for e in ex[:3]]
    return res


def google(text: str, src: str, tgt: str) -> Result:
    params = {"client": "gtx", "sl": "auto" if src == "auto" else google_code(src), "tl": google_code(tgt),
              "dt": ["t", "bd", "rm", "ex"], "dj": "1", "ie": "UTF-8", "oe": "UTF-8"}
    pieces = _chunks(text, 4000)
    results = [parse_google(_post(GOOGLE_URL, params, {"q": p})) for p in pieces]
    res = results[0]
    if len(results) > 1:
        res = Result(out="".join(r["out"] for r in results), src=results[0]["src"], engine="google")
    return res


def mymemory(text: str, src: str, tgt: str) -> Result:
    """Запасной онлайн-переводчик (бесплатно до 5000 символов в день). Язык исходника нужен заранее."""
    out = []
    for piece in _chunks(text, 480):
        data = _post(MYMEMORY_URL, {"q": piece, "langpair": f"{google_code(src)}|{google_code(tgt)}"})
        if int(data.get("responseStatus", 200)) != 200:
            raise OnlineError(str(data.get("responseDetails", "ошибка MyMemory"))[:120])
        out.append(data["responseData"]["translatedText"])
    return Result(out="".join(out), src=src, engine="mymemory")


class Online:
    """Онлайн-перевод с памятью о том, что сеть недоступна (чтобы не ждать таймаут на каждом слове)."""

    def __init__(self):
        self.down_until = 0.0
        self.last_error = ""

    def available(self) -> bool:
        return time.time() >= self.down_until

    def translate(self, text: str, src: str, tgt: str) -> Result:
        errors = []
        for label, fn in (("google", google), ("mymemory", mymemory)):
            if label == "mymemory" and src == "auto":
                continue  # MyMemory не определяет язык сам
            try:
                res = fn(text, src, tgt)
                if res.get("out", "").strip():
                    self.down_until = 0
                    return res
            except OnlineError as e:
                errors.append(f"{label}: {e}")
        self.last_error = "; ".join(errors) or "пустой ответ"
        if all("нет связи" in e for e in errors) and errors:
            self.down_until = time.time() + 60  # сети нет — минуту сразу идём в офлайн
        raise OnlineError(self.last_error)


def tts_url(text: str, lang: str) -> str:
    """Озвучка Google (mp3, до ~200 символов) для языков без голоса в Windows."""
    q = urllib.parse.urlencode({"ie": "UTF-8", "client": "tw-ob", "tl": google_code(lang), "q": text[:200]})
    return f"https://translate.google.com/translate_tts?{q}"
