"""Единая точка перевода: онлайн (Google → MyMemory) или скачанные модели, по режиму и наличию сети."""
from .engine import Engine, MissingModel, join_broken_lines
from .langs import ARGOS, default_target, detect
from .online import Online, OnlineError, Result

MODES = {
    "online": "онлайн, если есть интернет",
    "offline_first": "сначала скачанные языки",
    "offline": "только без интернета",
}


def _argos(code: str) -> str:
    return ARGOS.get(code, code)


class Translator:
    def __init__(self, models_dir: str, mode: str = "online"):
        self.engine = Engine(models_dir)
        self.online = Online()
        self.mode = mode

    # --- офлайн-модели ---
    def can_offline(self, src: str, tgt: str) -> bool:
        return self.engine.can_translate(_argos(src), _argos(tgt))

    def can_translate(self, src: str, tgt: str) -> bool:
        """Может ли перевести прямо сейчас (для кнопок языков во всплывашке)."""
        if self.mode != "offline" and self.online.available():
            return True
        return self.can_offline(src, tgt)

    def missing_language(self, src: str, tgt: str) -> str:
        """Какой язык докачать, чтобы src→tgt работал офлайн."""
        return next((c for c in (src, tgt) if c not in ("ru", "en")), "ru")

    def _offline(self, text, src, tgt, join_lines) -> Result:
        out = self.engine.translate(text, _argos(src), _argos(tgt), join_lines)
        return Result(out=out, src=src, engine="offline")

    # --- перевод ---
    def translate(self, text: str, src: str, tgt: str | None, join_lines: bool = False,
                  preferred: str = "ru", fallback: str = "en") -> Result:
        """src может быть 'auto', tgt — None (тогда по правилу «на русский, а русский — на английский»)."""
        guess = detect(text) if src == "auto" else src
        target = tgt or default_target(guess, preferred, fallback)
        body = join_broken_lines(text) if join_lines else text

        order = {"online": ("online", "offline"), "offline_first": ("offline", "online"),
                 "offline": ("offline",)}[self.mode]
        online_error = None
        for way in order:
            if way == "online":
                if not self.online.available():
                    continue
                try:
                    res = self.online.translate(body, src if src != "auto" else "auto", target)
                except OnlineError as e:
                    online_error = e
                    continue
                if tgt is None and res["src"] == target:
                    # Google увидел язык точнее нас: текст уже на языке перевода — переводим на запасной
                    target = default_target(res["src"], preferred, fallback)
                    res = self.online.translate(body, res["src"], target)
                res["tgt"] = target
                return res
            if self.can_offline(guess, target):
                res = self._offline(text, guess, target, join_lines)
                res["tgt"] = target
                return res
        if online_error and self.mode == "online" and not self.can_offline(guess, target):
            raise NoWay(guess, target, f"нет интернета ({online_error}) и язык не скачан")
        raise MissingModel(_argos(guess), _argos(target))


class NoWay(MissingModel):
    def __init__(self, src, tgt, reason):
        super().__init__(src, tgt)
        self.reason = reason
