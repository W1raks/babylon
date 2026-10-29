"""Обновление из архива: разбор архива и распаковка (сама подмена файлов проверяется на Windows в CI)."""
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from babylon import config, updater  # noqa: E402


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(path)


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", lambda: str(tmp_path / "data"))
    return tmp_path


def test_read_zip_with_install_note(data):
    z = _zip(data / "u.zip", {"Как установить.txt": "x", "Babylon/Babylon.exe": "exe",
                               "Babylon/_internal/version.txt": "1.3.0\n"})
    assert updater.read_zip(z) == ("1.3.0", "Babylon/")


def test_read_zip_rejects_other_archives(data):
    z = _zip(data / "other.zip", {"photo.jpg": "x"})
    with pytest.raises(updater.UpdateError):
        updater.read_zip(z)
    bad = data / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(updater.UpdateError):
        updater.read_zip(str(bad))


def test_stage_extracts_only_program(data):
    z = _zip(data / "u.zip", {"Как установить.txt": "x", "Babylon/Babylon.exe": "exe",
                               "Babylon/_internal/version.txt": "1.3.0", "Babylon/../../evil.txt": "no"})
    new = updater.stage(z)
    assert open(os.path.join(new, "Babylon.exe")).read() == "exe"
    assert os.path.isfile(os.path.join(new, "_internal", "version.txt"))
    assert not os.path.exists(os.path.join(new, "Как установить.txt"))
    assert not any("evil" in f for _, _, fs in os.walk(data) for f in fs)


def test_version_compare():
    assert updater.version_tuple("1.10.0") > updater.version_tuple("1.9.3")
    assert updater.version_tuple("?") == (0,)


def test_main_runs_update_before_selftest(monkeypatch):
    """Babylon.exe --update-from x.zip --then --selftest: обновление, а не самопроверка."""
    from babylon import app
    called = []
    monkeypatch.setattr(sys, "argv", ["Babylon.exe", "--update-from", "x.zip", "--then", "--selftest"])
    monkeypatch.setattr(updater, "cli", lambda argv: called.append("update") or 0)
    monkeypatch.setattr(app, "selftest", lambda: called.append("selftest") or 0)
    assert app.main() == 0
    assert called == ["update"]


def test_backslash_paths(data):
    """Архив, где пути записаны через «\\» (так делают некоторые архиваторы Windows)."""
    z = _zip(data / "bs.zip", {"Babylon\\Babylon.exe": "exe", "Babylon\\_internal\\version.txt": "2.0.0"})
    assert updater.read_zip(z) == ("2.0.0", "Babylon/")
    new = updater.stage(z)
    assert os.path.isfile(os.path.join(new, "_internal", "version.txt"))


def test_mirror_keeps_data_and_removes_stale(tmp_path):
    new, app = tmp_path / "new", tmp_path / "app"
    (new / "_internal").mkdir(parents=True)
    (new / "Babylon.exe").write_text("v2")
    (new / "_internal" / "version.txt").write_text("9.9.9")
    (app / "_internal").mkdir(parents=True)
    (app / "data").mkdir()
    (app / "Babylon.exe").write_text("v1")
    (app / "_internal" / "old.dll").write_text("x")
    (app / "data" / "history.json").write_text("[]")
    copied, removed = updater.mirror(str(new), str(app))
    assert (app / "Babylon.exe").read_text() == "v2"
    assert (app / "_internal" / "version.txt").read_text() == "9.9.9"
    assert not (app / "_internal" / "old.dll").exists()
    assert (app / "data" / "history.json").exists()
    assert (copied, removed) == (2, 1)


def test_old_name_archive(data):
    """Архив 1.x (Vavilon/Vavilon.exe) тоже принимается."""
    z = _zip(data / "old.zip", {"Vavilon/Vavilon.exe": "exe", "Vavilon/_internal/version.txt": "1.2.0"})
    assert updater.read_zip(z) == ("1.2.0", "Vavilon/")
    assert os.path.isfile(os.path.join(updater.stage(z), "Vavilon.exe"))


def test_mirror_removes_old_vavilon_copy(tmp_path):
    """В 2.1.1 копии Vavilon.exe больше нет: при обновлении старая копия из папки программы удаляется."""
    app, new = tmp_path / "app", tmp_path / "new"
    for d, files in ((app, ("Babylon.exe", "Vavilon.exe", "_internal/version.txt", "data/history.json")),
                     (new, ("Babylon.exe", "_internal/version.txt"))):
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("x")
    updater.mirror(str(new), str(app))
    assert (app / "Babylon.exe").exists() and (app / "data" / "history.json").exists()
    assert not (app / "Vavilon.exe").exists()


def test_latest_release_parsing(monkeypatch):
    import io
    import json
    import urllib.request

    body = {"tag_name": "v2.4.0", "body": "что нового", "html_url": "https://github.com/W1raks/babylon/releases/v2.4.0",
            "assets": [{"name": "notes.txt", "browser_download_url": "x"},
                       {"name": "Babylon-2.4.0-win64.zip", "browser_download_url": "https://e/zip", "size": 123}]}

    class R(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: R(json.dumps(body).encode()))
    info = updater.latest()
    assert info["version"] == "2.4.0" and info["url"] == "https://e/zip" and info["size"] == 123
    assert updater.is_newer("2.4.0", "2.3.0") and not updater.is_newer("2.3.0", "2.3.0")
    assert not updater.is_newer("2.2.9", "2.3.0")


def test_download_atomic(monkeypatch, tmp_path):
    import io
    import urllib.request

    class R(io.BytesIO):
        headers = {"Content-Length": "5"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: R(b"hello"))
    seen = []
    p = updater.download("https://e/zip", str(tmp_path / "u" / "Babylon-2.4.0-win64.zip"), lambda d, t: seen.append((d, t)))
    assert open(p, "rb").read() == b"hello" and seen[-1] == (5, 5)
    assert not (tmp_path / "u" / "Babylon-2.4.0-win64.zip.part").exists()
