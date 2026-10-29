"""Проверка движка. Модели: BABYLON_MODELS=<папка> (без неё проверяются только разбор текста и язык).

    python -m pytest tests -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from babylon.engine import Engine, MissingModel, join_broken_lines, split_sentences  # noqa: E402
from babylon.langs import default_target, detect  # noqa: E402

MODELS = os.environ.get("BABYLON_MODELS", "")


@pytest.mark.parametrize(
    "text,lang",
    [
        ("Привет, как дела?", "ru"),
        ("The weather is nice and the sun is shining.", "en"),
        ("Ich habe heute keine Zeit, aber morgen gerne.", "de"),
        ("Je ne sais pas où est la gare, désolé.", "fr"),
        ("Non ho capito, puoi ripetere per favore?", "it"),
        ("¿Dónde está la estación? No lo sé.", "es"),
        ("Straße", "de"),
        ("12345", "en"),
    ],
)
def test_detect(text, lang):
    assert detect(text) == lang


def test_default_target():
    assert default_target("en") == "ru"
    assert default_target("ru") == "en"


def test_split_sentences():
    s = 'Hello there. How are you? I met Dr. Smith, e.g. yesterday! «Да.» Т.е. нет.'
    assert split_sentences(s) == ["Hello there.", "How are you?", "I met Dr. Smith, e.g. yesterday!", "«Да.»", "Т.е. нет."]


def test_join_broken_lines():
    raw = "This is a long sen-\ntence that was broken\nby the layout.\n\n- first item\n- second item"
    assert join_broken_lines(raw) == "This is a long sentence that was broken by the layout.\n\n- first item\n- second item"


def test_missing_model(tmp_path):
    with pytest.raises(MissingModel):
        Engine(str(tmp_path)).translate("hi", "en", "ru")


def test_same_language(tmp_path):
    assert Engine(str(tmp_path)).translate("Привет", "ru", "ru") == "Привет"


needs_models = pytest.mark.skipif(not MODELS, reason="нет BABYLON_MODELS")


@needs_models
def test_translate_keeps_structure():
    e = Engine(MODELS)
    out = e.translate("Good morning. The cat is sleeping.\n\n- Open the window\n- Close the door", "en", "ru")
    lines = out.split("\n")
    assert len(lines) == 4 and lines[1] == ""
    assert lines[2].startswith("- ") and lines[3].startswith("- ")
    assert any(ch in out.lower() for ch in "абвгд")


@needs_models
def test_pivot_via_english():
    e = Engine(MODELS)
    if not e.can_translate("it", "ru"):
        pytest.skip("нет it->en или en->ru")
    assert e.route("it", "ru") == [("it", "en"), ("en", "ru")]
    out = e.translate("Buongiorno, come stai?", "it", "ru")
    assert any("а" <= ch <= "я" for ch in out.lower())


def test_ocr_homoglyphs_not_russian():
    from babylon.ocr import looks_russian
    # так русский OCR читает английский текст: кириллические двойники е, о, а, р, с, Н
    assert not looks_russian("Ѕеlесt аnу tехt аnd рrеss thе hоtkеу")
    assert looks_russian("Привет, это проверка распознавания текста")
    assert looks_russian("Выделите любой текст и нажмите клавишу")


def test_models_prefer_sentencepiece_links():
    from babylon.models import FALLBACK
    assert FALLBACK[("es", "en")].endswith("es_en-1_0.argosmodel")


def test_install_rejects_bpe_package(tmp_path):
    import zipfile
    from babylon.models import install_zip
    z = tmp_path / "bpe.argosmodel"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("translate-es_en-1_9/bpe.model", "#version: 0.2\n")
        f.writestr("translate-es_en-1_9/model/model.bin", "x")
    with pytest.raises(RuntimeError, match="sentencepiece"):
        install_zip(str(tmp_path / "m"), "es", "en", str(z))


@pytest.mark.parametrize("text,lang", [
    ("今日はとても暑いですね。", "ja"),
    ("我今天很忙，明天再说吧。", "zh"),
    ("안녕하세요, 만나서 반갑습니다.", "ko"),
])
def test_detect_asian(text, lang):
    assert detect(text) == lang


def test_split_cjk():
    assert split_sentences("今日は暑いですね。明日は雨でしょう！本当？") == ["今日は暑いですね。", "明日は雨でしょう！", "本当？"]
    assert join_broken_lines("今日はとても\n暑いですね。") == "今日はとても暑いですね。"


def test_ocr_score_picks_right_reader():
    from babylon.ocr import score
    english = "Select any text and press the hotkey"
    as_ru = "Ѕеlесt аnу tехt аnd рrеss thе hоtkеу"  # русский OCR на английском тексте
    assert score(english, "en") > score(as_ru, "ru")
    russian = "Выделите любой текст и нажмите клавишу"
    as_latin = "BbIgeлnTe nI06oN TekcT n HaжMnTe kлaBnwy"
    assert score(russian, "ru") > score(as_latin, "en")
    assert score("今日はとても暑いですね", "ja") > score("今日はとても暑いですね", "zh")
    assert score("我今天很忙明天再说吧", "zh") > score("我今天很忙明天再说吧", "ja")


@needs_models
def test_translate_to_chinese_no_marks():
    e = Engine(MODELS)
    if not e.can_translate("en", "zh"):
        pytest.skip("нет en->zh")
    out = e.translate("Hello, my friend. How are you?", "en", "zh")
    assert "▁" not in out and " " not in out
