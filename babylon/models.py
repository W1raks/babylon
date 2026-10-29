"""Скачивание и установка моделей Argos (нужен интернет один раз)."""
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile

INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"

# Новые версии некоторых пакетов в каталоге идут со словарём BPE, который движок не читает.
# Для них берём последнюю версию со словарём SentencePiece (проверено 2026-10-28).
_BASE = "https://argos-net.com/v1/translate-{}-{}.argosmodel"
SP_VERSION = {
    ("es", "en"): "1_0", ("en", "es"): "1_0", ("cs", "en"): "1_5", ("en", "cs"): "1_5",
    ("da", "en"): "1_3", ("en", "da"): "1_3", ("hu", "en"): "1_5", ("en", "hu"): "1_5",
    ("id", "en"): "1_2", ("en", "id"): "1_2", ("fi", "en"): "1_5", ("en", "pl"): "1_1",
    ("uk", "en"): "1_4",
}
FALLBACK = {
    ("en", "ru"): _BASE.format("en_ru", "1_9"), ("ru", "en"): _BASE.format("ru_en", "1_9"),
    ("en", "de"): _BASE.format("en_de", "1_3"), ("de", "en"): _BASE.format("de_en", "1_3"),
    ("en", "fr"): _BASE.format("en_fr", "1_9"), ("fr", "en"): _BASE.format("fr_en", "1_9"),
    ("en", "it"): _BASE.format("en_it", "1_0"), ("it", "en"): _BASE.format("it_en", "1_0"),
    ("en", "ja"): _BASE.format("en_ja", "1_1"), ("ja", "en"): _BASE.format("ja_en", "1_1"),
    ("en", "zh"): _BASE.format("en_zh", "1_9"), ("zh", "en"): _BASE.format("zh_en", "1_9"),
    ("en", "ko"): _BASE.format("en_ko", "1_1"), ("ko", "en"): _BASE.format("ko_en", "1_1"),
    **{k: _BASE.format(f"{k[0]}_{k[1]}", v) for k, v in SP_VERSION.items()},
}

# Примерный размер одного направления, МБ (для подсказки в «языках»)
SIZE_MB = {"ru": 200, "de": 150, "fr": 190, "it": 90, "es": 88, "ja": 113, "zh": 70, "ko": 115}
DEFAULT_MB = 100

_UA = {"User-Agent": "Babylon/2.0"}


def catalog() -> dict[tuple[str, str], list[str]]:
    """Пары и ссылки на них: из свежего каталога, иначе из запасного списка."""
    links = {k: [v] for k, v in FALLBACK.items()}
    try:
        req = urllib.request.Request(INDEX_URL, headers=_UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            for p in json.load(r):
                key = (p["from_code"], p["to_code"])
                extra = [l for l in p.get("links", []) if l.startswith("http") and l not in links.get(key, [])]
                links[key] = links.get(key, []) + extra
    except Exception:
        pass
    return links


def install_pair(models_dir: str, src: str, tgt: str, urls: list[str], progress=None, cancel=None):
    """Скачать пакет и оставить в models_dir/src_tgt только модель и словарь."""
    os.makedirs(models_dir, exist_ok=True)
    last_err = None
    for url in urls:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip", dir=models_dir)
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=30) as r, tmp:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    if cancel and cancel():
                        raise InterruptedError("Отменено")
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            install_zip(models_dir, src, tgt, tmp.name)
            return
        except InterruptedError:
            raise
        except Exception as e:  # пробуем следующее зеркало
            last_err = e
        finally:
            tmp.close()
            if os.path.exists(tmp.name):
                os.remove(tmp.name)
    raise RuntimeError(f"Не удалось скачать {src}->{tgt}: {last_err}")


def install_zip(models_dir: str, src: str, tgt: str, zip_path: str):
    """Установить пакет .argosmodel, скачанный вручную или из install_pair."""
    dest = os.path.join(models_dir, f"{src}_{tgt}")
    work = dest + ".part"
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, "model"))
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        sp = next((n for n in names if n.endswith("sentencepiece.model")), None)
        if sp is None:
            raise RuntimeError("в пакете нет словаря sentencepiece.model (другой формат)")
        root = sp[: -len("sentencepiece.model")]
        wanted = {sp: "sentencepiece.model"}
        for n in names:
            rel = n[len(root):]
            if rel.startswith("model/") and not n.endswith("/"):
                wanted[n] = rel
            elif rel == "metadata.json":
                wanted[n] = rel
        for n, rel in wanted.items():
            with z.open(n) as fi, open(os.path.join(work, rel), "wb") as fo:
                shutil.copyfileobj(fi, fo)
    if not os.path.isfile(os.path.join(work, "model", "model.bin")):
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("В пакете нет model/model.bin")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(work, dest)


def remove_pair(models_dir: str, src: str, tgt: str):
    shutil.rmtree(os.path.join(models_dir, f"{src}_{tgt}"), ignore_errors=True)
