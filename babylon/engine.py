"""Офлайн-перевод на моделях Argos (CTranslate2 + SentencePiece).

Из пакета Argos берём только модель и словарь: библиотека stanza не нужна,
предложения режем сами. Пары без английского переводим через английский.
"""
import os
import re
import threading
from collections import OrderedDict

from .langs import is_cjk

PIVOT = "en"

# Конец предложения: . ! ? … и закрывающие кавычки/скобки, дальше пробел и заглавная/цифра/кавычка
_SENT_END = re.compile(r'[.!?…]+["»”)\]]*(?=\s+["«“(\[]?[A-ZÀ-ÖØ-ÞА-ЯЁ0-9¿¡])')
# Сокращения, после которых предложение не кончается
_ABBR = re.compile(
    r"(?:\b(?:mr|mrs|ms|dr|prof|st|vs|etc|e\.g|i\.e|z\.b|bzw|usw|ca|nr|mme|sr|sra|т\.е|т\.к|т\.п|т\.д|др|см|им|г|гг|ул|д)\.|\b[A-ZА-Я]\.)$",
    re.IGNORECASE,
)
_BULLET = re.compile(r"^\s*(?:[-–—•*·▪●]|\d{1,3}[.)]|[a-zа-я][.)])\s")
_MAX_PIECES = 180  # длиннее режем по запятым, чтобы модель не теряла хвост


# Пробелы между иероглифами/каной (модели иногда их вставляют), в ja и zh они не нужны
_CJK_SPACE = re.compile(r"(?<=[\u3000-\u30ff\u4e00-\u9fff\uff00-\uffef])[ \t]+(?=[\u3000-\u30ff\u4e00-\u9fff\uff00-\uffef])")

# Конец предложения в японском и китайском: 。！？ без пробела после
_CJK_END = re.compile(r"(?<=[。！？])(?![。！？」』）】])")


def split_sentences(par: str) -> list[str]:
    parts = []
    for piece in _CJK_END.split(par):
        start = 0
        for m in _SENT_END.finditer(piece):
            if not _ABBR.search(piece[start : m.end()]):
                parts.append(piece[start : m.end()])
                start = m.end()
        parts.append(piece[start:])
    return [p.strip() for p in parts if p.strip()]


def group_sentences(parts: list[str], limit: int = 200) -> list[str]:
    """Склеить соседние короткие предложения в куски до limit символов.
    Модели переводят «How are you?» в одиночку хуже, чем вместе с соседним предложением."""
    groups = []
    for p in parts:
        if groups and len(groups[-1]) + 1 + len(p) <= limit:
            glue = "" if is_cjk(groups[-1][-1]) else " "
            groups[-1] = f"{groups[-1]}{glue}{p}"
        else:
            groups.append(p)
    return groups


def _regroup(sents: list[str], plan: list[tuple[str, int]]):
    out, new_plan, i = [], [], 0
    for indent, n in plan:
        g = group_sentences(sents[i : i + n]) if n else []
        out.extend(g)
        new_plan.append((indent, len(g)))
        i += n
    return out, new_plan


def join_broken_lines(text: str) -> str:
    """Склеить строки, порванные вёрсткой (PDF, скриншоты), обратно в абзацы."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            out.append("")
            continue
        prev = out[-1] if out else ""
        if prev and not _BULLET.match(s) and not re.search(r'[.!?…:;»"”)]$', prev):
            if prev.endswith("-") and s[:1].islower():
                out[-1] = prev[:-1] + s  # пере-\nнос
            else:
                glue = "" if is_cjk(prev[-1]) and is_cjk(s[0]) else " "  # в японском и китайском без пробелов
                out[-1] = f"{prev}{glue}{s}"
        else:
            out.append(s)
    return "\n".join(out)


class _Pair:
    """Одна загруженная модель (например en->ru)."""

    def __init__(self, path: str, threads: int):
        import ctranslate2
        import sentencepiece as spm

        self.sp = spm.SentencePieceProcessor(model_file=os.path.join(path, "sentencepiece.model"))
        self.tr = ctranslate2.Translator(
            os.path.join(path, "model"), device="cpu", compute_type="int8", intra_threads=threads
        )
        self.lock = threading.Lock()

    def run(self, sentences: list[str]) -> list[str]:
        if not sentences:
            return []
        toks = [self.sp.encode(s, out_type=str) for s in sentences]
        # длинные куски дробим, иначе модель обрезает конец
        batch, owner = [], []
        for i, t in enumerate(toks):
            for k in range(0, max(len(t), 1), _MAX_PIECES):
                batch.append(t[k : k + _MAX_PIECES])
                owner.append(i)
        with self.lock:
            res = self.tr.translate_batch(
                batch, beam_size=2, max_batch_size=32, max_decoding_length=512, repetition_penalty=1.1
            )
        out = [""] * len(sentences)
        for i, r in zip(owner, res):
            piece = self.sp.decode(r.hypotheses[0]).replace("\u2581", " ").strip()  # «▁» от SentencePiece
            out[i] = f"{out[i]} {piece}".strip()
        return out


class Engine:
    def __init__(self, models_dir: str, threads: int = 0):
        self.models_dir = models_dir
        self.threads = threads or max(1, min(4, (os.cpu_count() or 2) - 1))
        self._pairs: dict[tuple[str, str], _Pair] = {}
        self._load_lock = threading.Lock()
        self._cache: OrderedDict = OrderedDict()

    # --- какие модели есть ---
    def pair_dir(self, src: str, tgt: str) -> str:
        return os.path.join(self.models_dir, f"{src}_{tgt}")

    def has_pair(self, src: str, tgt: str) -> bool:
        d = self.pair_dir(src, tgt)
        return os.path.isfile(os.path.join(d, "model", "model.bin")) and os.path.isfile(
            os.path.join(d, "sentencepiece.model")
        )

    def route(self, src: str, tgt: str) -> list[tuple[str, str]] | None:
        """Цепочка моделей для перевода src->tgt или None, если моделей не хватает."""
        if src == tgt:
            return []
        if self.has_pair(src, tgt):
            return [(src, tgt)]
        if PIVOT not in (src, tgt) and self.has_pair(src, PIVOT) and self.has_pair(PIVOT, tgt):
            return [(src, PIVOT), (PIVOT, tgt)]
        return None

    def can_translate(self, src: str, tgt: str) -> bool:
        return self.route(src, tgt) is not None

    def _pair(self, src: str, tgt: str) -> _Pair:
        key = (src, tgt)
        with self._load_lock:
            if key not in self._pairs:
                self._pairs[key] = _Pair(self.pair_dir(src, tgt), self.threads)
            return self._pairs[key]

    def warm_up(self, src: str, tgt: str):
        """Загрузить модели заранее, чтобы первый перевод был мгновенным."""
        for a, b in self.route(src, tgt) or []:
            self._pair(a, b)

    def unload(self):
        with self._load_lock:
            self._pairs.clear()
        self._cache.clear()

    # --- перевод ---
    def translate(self, text: str, src: str, tgt: str, join_lines: bool = False) -> str:
        if not text.strip():
            return ""
        route = self.route(src, tgt)
        if route is None:
            raise MissingModel(src, tgt)
        if not route:
            return text
        key = (text, src, tgt, join_lines)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        body = join_broken_lines(text) if join_lines else text
        # абзацы и пустые строки сохраняем, переводим все предложения одним пакетом
        lines = body.split("\n")
        plan = []  # (отступ, число предложений) на каждую строку
        sents = []
        for line in lines:
            s = line.strip()
            if not s:
                plan.append((line, 0))
                continue
            indent = line[: len(line) - len(line.lstrip())]
            m = _BULLET.match(s)
            if m:
                indent += m.group(0)
                s = s[m.end() :]
            parts = split_sentences(s)
            plan.append((indent, len(parts)))
            sents.extend(parts)

        for a, b in route:
            if b in ("ja", "zh", "ko"):
                # на азиатские языки модели лучше переводят короткие фразы вместе с соседними
                sents, plan = _regroup(sents, plan)
            sents = self._pair(a, b).run(sents)

        joiner = "" if tgt in ("ja", "zh") else " "
        out, i = [], 0
        for indent, n in plan:
            if n == 0:
                out.append("")
            else:
                out.append(indent + joiner.join(sents[i : i + n]))
                i += n
        result = "\n".join(out)
        if tgt in ("ja", "zh"):
            result = _CJK_SPACE.sub("", result)
        self._cache[key] = result
        if len(self._cache) > 200:
            self._cache.popitem(last=False)
        return result


class MissingModel(Exception):
    def __init__(self, src, tgt):
        super().__init__(f"Нет модели для {src} -> {tgt}")
        self.src, self.tgt = src, tgt
