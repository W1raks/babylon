"""Онлайн-перевод: разбор ответа Google, нарезка текста, выбор пути перевода (сеть подменена)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from babylon import online  # noqa: E402
from babylon.engine import MissingModel  # noqa: E402
from babylon.translator import Translator  # noqa: E402

GOOGLE_HELLO = {
    "sentences": [{"trans": "Привет", "orig": "hello", "backend": 10},
                  {"translit": "Privet", "src_translit": "həˈlō"}],
    "dict": [{"pos": "interjection", "terms": ["привет", "здравствуйте"],
              "entry": [{"word": "здравствуйте", "reverse_translation": ["hello", "how do you do"], "score": 0.1},
                        {"word": "привет", "reverse_translation": ["hello", "hi", "hey"], "score": 0.6}]},
             {"pos": "noun", "terms": ["приветствие"],
              "entry": [{"word": "приветствие", "reverse_translation": ["greeting"], "score": 0.01}]}],
    "src": "en",
    "examples": {"example": [{"text": "<b>hello</b> there, Katie!", "source_type": 5}]},
}


def test_parse_google_word():
    r = online.parse_google(GOOGLE_HELLO)
    assert r["out"] == "Привет" and r["src"] == "en" and r["engine"] == "google"
    assert r["translit"] == "Privet" and r["src_translit"] == "həˈlō"
    assert r["dict"][0]["pos"] == "междометие"
    assert r["dict"][0]["terms"][0] == {"word": "привет", "back": ["hello", "hi", "hey"]}  # по частоте
    assert r["examples"] == ["hello there, Katie!"]


def test_parse_google_chinese_code():
    r = online.parse_google({"sentences": [{"trans": "x"}], "src": "zh-CN"})
    assert r["src"] == "zh"


def test_chunks_keep_text():
    text = ("Первое предложение. " * 300).strip() + "\n\nВторой абзац."
    parts = online._chunks(text, 1000)
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(parts) == text


@pytest.fixture
def tr(tmp_path, monkeypatch):
    t = Translator(str(tmp_path / "models"), "online")
    return t


def test_online_first_then_offline(tr, monkeypatch):
    calls = []

    def fake_google(text, src, tgt):
        calls.append((src, tgt))
        return online.Result(out="Привет", src="en", engine="google")

    monkeypatch.setattr(online, "google", fake_google)
    res = tr.translate("hello", "auto", None)
    assert res["out"] == "Привет" and res["tgt"] == "ru" and calls == [("auto", "ru")]


def test_google_sees_target_language(tr, monkeypatch):
    """Мы решили, что текст английский, а Google видит русский: переводим на английский."""
    def fake_google(text, src, tgt):
        if tgt == "ru":
            return online.Result(out=text, src="ru", engine="google")
        return online.Result(out="Hello", src=src, engine="google")

    monkeypatch.setattr(online, "google", fake_google)
    monkeypatch.setattr("babylon.translator.detect", lambda t: "en")
    res = tr.translate("Привет", "auto", None)
    assert res["out"] == "Hello" and res["tgt"] == "en"


def test_no_network_no_model(tr, monkeypatch):
    def down(*a):
        raise online.OnlineError("нет связи с сервером перевода")

    monkeypatch.setattr(online, "google", down)
    monkeypatch.setattr(online, "mymemory", down)
    with pytest.raises(MissingModel):
        tr.translate("hello world, how are you", "auto", None)
    assert not tr.online.available()  # минуту не ждём сеть


def test_offline_mode_never_goes_online(tmp_path, monkeypatch):
    t = Translator(str(tmp_path), "offline")
    monkeypatch.setattr(online, "google", lambda *a: pytest.fail("в офлайн-режиме сеть не нужна"))
    with pytest.raises(MissingModel):
        t.translate("hello", "en", "ru")


@pytest.mark.skipif(not os.environ.get("BABYLON_NET"), reason="без BABYLON_NET=1 в сеть не ходим")
def test_live_online():
    o = online.Online()
    r = o.translate("Good morning, my friend.", "en", "ru")
    print("live:", r["engine"], r["out"])
    assert any("а" <= c <= "я" for c in r["out"].lower())
