"""Распознавание речи нейросетью Whisper прямо на компьютере (без интернета).

Модель — версия Whisper для CTranslate2 (тот же движок, что и офлайн-перевод), скачивается
один раз в папку моделей. Звук: 16 кГц, моно, float32. Мел-спектрограмма считается здесь же
(numpy), токены расшифровывает библиотека tokenizers — без torch и onnxruntime.
"""
import json
import os
import re
import threading
import urllib.request

import numpy as np

from . import config

SR = 16000
N_FFT, HOP, CHUNK = 400, 160, 30
SIZES = {  # какие модели можно скачать: (папка на HuggingFace, примерный размер, подпись)
    "base": ("Systran/faster-whisper-base", 145, "быстрая"),
    "small": ("Systran/faster-whisper-small", 485, "точная"),
}
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
HOSTS = ("https://huggingface.co", "https://hf-mirror.com")

# Whisper на тишине и музыке иногда «слышит» стандартные фразы из субтитров — их выбрасываем
JUNK = re.compile(r"(субтитр|редактор субтитров|продолжение следует|спасибо за просмотр|подписывайтесь|"
                  r"thank you for watching|thanks for watching|please subscribe|amara\.org|♪|\[музыка\]|\[music\])",
                  re.IGNORECASE)
WHISPER_CODES = {"he": "iw", "jv": "jw"}  # наш код → код Whisper


# ---------------- модели ----------------
def model_dir(size: str) -> str:
    return os.path.join(os.environ.get("BABYLON_WHISPER") or config.models_dir(), f"whisper-{size}")


def installed(size: str) -> bool:
    d = model_dir(size)
    return all(os.path.isfile(os.path.join(d, f)) for f in FILES)


def download(size: str, progress=None):
    """Скачать модель; progress(скачано, всего) в байтах."""
    repo, mb, _ = SIZES[size]
    d = model_dir(size)
    tmp = d + ".part"
    os.makedirs(tmp, exist_ok=True)
    total = mb * 1024 * 1024
    done = 0
    for f in FILES:
        last = None
        for host in HOSTS:
            try:
                req = urllib.request.Request(f"{host}/{repo}/resolve/main/{f}", headers={"User-Agent": "Babylon"})
                with urllib.request.urlopen(req, timeout=30) as r, open(os.path.join(tmp, f), "wb") as out:
                    while True:
                        buf = r.read(1 << 16)
                        if not buf:
                            break
                        out.write(buf)
                        done += len(buf)
                        if progress:
                            progress(min(done, total), total)
                last = None
                break
            except OSError as e:
                last = e
        if last:
            raise RuntimeError(f"не скачалась модель распознавания речи: {last}")
    if os.path.isdir(d):
        import shutil

        shutil.rmtree(d, ignore_errors=True)
    os.replace(tmp, d)


# ---------------- мел-спектрограмма (как в Whisper) ----------------
def _mel_filters(n_mels: int) -> np.ndarray:
    fftfreqs = np.fft.rfftfreq(n=N_FFT, d=1.0 / SR)
    mels = np.linspace(0.0, 45.245640471924965, n_mels + 2)
    f_sp = 200.0 / 3
    freqs = f_sp * mels
    min_log_mel = 1000.0 / f_sp
    log_t = mels >= min_log_mel
    freqs[log_t] = 1000.0 * np.exp(np.log(6.4) / 27.0 * (mels[log_t] - min_log_mel))
    fdiff = np.diff(freqs)
    ramps = freqs.reshape(-1, 1) - fftfreqs.reshape(1, -1)
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lower, upper))
    w *= (2.0 / (freqs[2:n_mels + 2] - freqs[:n_mels]))[:, None]
    return w.astype(np.float32)


_FILTERS: dict[int, np.ndarray] = {}
_WINDOW = np.hanning(N_FFT + 1)[:-1].astype(np.float32)


def features(audio: np.ndarray, n_mels: int = 80) -> np.ndarray:
    """Лог-мел признаки окна 30 с: (n_mels, 3000)."""
    a = np.zeros(SR * CHUNK, np.float32)
    a[: min(len(audio), len(a))] = audio[: len(a)]
    a = np.pad(a, N_FFT // 2, mode="reflect")
    n = 1 + (len(a) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(a[idx] * _WINDOW, axis=1)) ** 2
    spec = spec[:-1].T  # как в Whisper: последний кадр отбрасывается
    if n_mels not in _FILTERS:
        _FILTERS[n_mels] = _mel_filters(n_mels)
    mel = _FILTERS[n_mels] @ spec
    log = np.log10(np.maximum(mel, 1e-10))
    log = np.maximum(log, log.max() - 8.0)
    return ((log + 4.0) / 4.0).astype(np.float32)


# ---------------- распознаватель ----------------
class Recognizer:
    """transcribe(звук) → {'text', 'lang', 'prob', 'no_speech'}. Один экземпляр на поток не нужен:
    вызовы защищены замком (CTranslate2 и так считает в нескольких потоках)."""

    def __init__(self, path: str, threads: int = 0):
        import ctranslate2
        from tokenizers import Tokenizer

        self.model = ctranslate2.models.Whisper(path, device="cpu", compute_type="int8",
                                                intra_threads=threads or min(8, os.cpu_count() or 4))
        self.tok = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        with open(os.path.join(path, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.n_mels = getattr(self.model, "n_mels", 80)
        self.suppress = cfg.get("suppress_ids", [])
        t = self.tok.token_to_id
        self.sot, self.transcribe_id, self.notimestamps = t("<|startoftranscript|>"), t("<|transcribe|>"), t("<|notimestamps|>")
        self.eot = t("<|endoftext|>")
        self.lock = threading.Lock()

    def lang_id(self, code: str):
        return self.tok.token_to_id(f"<|{WHISPER_CODES.get(code, code)}|>")

    def transcribe(self, audio: np.ndarray, lang: str | None = None, beam: int = 1) -> dict:
        import ctranslate2

        feats = features(audio, self.n_mels)[None]
        with self.lock:
            enc = self.model.encode(ctranslate2.StorageView.from_array(feats), to_cpu=False)
            prob = 1.0
            if not lang or self.lang_id(lang) is None:
                tokens = self.model.detect_language(enc)[0]
                best, prob = tokens[0]
                lang = best.strip("<|>")
                lang = next((k for k, v in WHISPER_CODES.items() if v == lang), lang)
            prompt = [self.sot, self.lang_id(lang), self.transcribe_id, self.notimestamps]
            res = self.model.generate(enc, [prompt], beam_size=beam, max_length=224, return_scores=True,
                                      return_no_speech_prob=True, suppress_blank=True, suppress_tokens=[-1],
                                      repetition_penalty=1.1, no_repeat_ngram_size=0)[0]
        ids = [i for i in res.sequences_ids[0] if i < self.eot]
        text = self.tok.decode(ids).strip()
        logprob = res.scores[0] if res.scores else 0.0  # средняя логвероятность токена
        if JUNK.search(text) or (res.no_speech_prob > 0.6 and logprob < -0.8):
            text = ""
        return {"text": text, "lang": lang, "prob": prob, "no_speech": res.no_speech_prob}


_cache: dict[str, Recognizer] = {}
_cache_lock = threading.Lock()


def recognizer(size: str) -> Recognizer:
    with _cache_lock:
        if size not in _cache:
            _cache[size] = Recognizer(model_dir(size))
        return _cache[size]
