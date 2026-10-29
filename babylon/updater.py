"""Обновление из архива: новая версия распаковывается рядом, а после выхода программы
сама новая версия (режим --finish-update) подменяет файлы и запускается из старой папки. Языки и история не трогаются:
они лежат в %LOCALAPPDATA%\\Babylon или в папке data, которую копирование пропускает.
"""
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

from . import config

EXE = "Babylon.exe"
EXES = (EXE, "Vavilon.exe")  # архивы 1.x назывались «Вавилон» латиницей: Vavilon.exe


class UpdateError(Exception):
    pass


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def read_zip(zip_path: str) -> tuple[str, str]:
    """(версия, папка внутри архива, где лежит Babylon.exe). Ошибка, если это не архив Вавилона."""
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = {_norm(n): n for n in z.namelist()}  # некоторые архиваторы пишут пути через «\»
            exe = next((n for e in EXES for n in names if n.endswith("/" + e) or n == e), None)
            if exe is None:
                raise UpdateError("в архиве нет Babylon.exe: это не архив Вавилона")
            root = exe[: exe.rfind("/") + 1]
            vname = root + "_internal/version.txt"
            version = z.read(names[vname]).decode("utf-8", "ignore").strip() if vname in names else "?"
    except zipfile.BadZipFile as e:
        raise UpdateError("файл повреждён или это не zip-архив") from e
    return version, root


def stage(zip_path: str) -> str:
    """Распаковать новую версию во временную папку и вернуть путь к ней."""
    _, root = read_zip(zip_path)
    dest = os.path.join(config.data_dir(), "update", "new")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    base = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = _norm(info.filename)
            if not name.startswith(root) or name.endswith("/"):
                continue
            rel = name[len(root):]
            target = os.path.realpath(os.path.join(dest, rel))
            if not target.startswith(base + os.sep):
                continue  # защита от путей вида ../../ внутри архива
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as fi, open(target, "wb") as fo:
                shutil.copyfileobj(fi, fo)
    if not any(os.path.isfile(os.path.join(dest, e)) for e in EXES):
        raise UpdateError("после распаковки не нашёлся Babylon.exe")
    return dest


def _norm(name: str) -> str:
    return name.replace("\\", "/")


def launch_swap(new_dir: str, app_dir: str, pid: int, restart_args: list[str] | None = None):
    """Запустить уже распакованную новую версию в режиме подмены: она дождётся выхода этой
    программы, скопирует себя на её место и запустится оттуда. Без PowerShell: его скрипты
    на многих компьютерах блокируют политики и антивирусы."""
    exe = next(e for e in EXES if os.path.isfile(os.path.join(new_dir, e)))
    args = [os.path.join(new_dir, exe), "--finish-update", app_dir, str(pid), "--then", *(restart_args or [])]
    subprocess.Popen(
        args, cwd=new_dir, close_fds=True, creationflags=0x08000000,  # CREATE_NO_WINDOW
        # у оконной сборки нет консоли: без явных потоков запуск падает с «неверный дескриптор»
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _wait_pid(pid: int, timeout_ms: int = 60000):
    if sys.platform != "win32":
        return
    import ctypes

    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if h:
        k.WaitForSingleObject(h, timeout_ms)
        k.CloseHandle(h)


def _copy_retry(src: str, dst: str, tries: int = 40):
    """Файл может быть ещё занят (антивирус, задержка выхода) — пробуем несколько секунд."""
    for i in range(tries):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.25)


def mirror(new_dir: str, app_dir: str) -> tuple[int, int]:
    """Сделать app_dir копией new_dir. Папка data (переносные языки и история) не трогается."""
    copied = removed = 0
    keep = set()
    for root, _, files in os.walk(new_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), new_dir)
            keep.add(os.path.normcase(rel))
            _copy_retry(os.path.join(root, f), os.path.join(app_dir, rel))
            copied += 1
    for root, dirs, files in os.walk(app_dir, topdown=True):
        if os.path.normcase(os.path.relpath(root, app_dir)) == ".":
            dirs[:] = [d for d in dirs if d.lower() != "data"]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), app_dir)
            if os.path.normcase(rel) not in keep:
                try:
                    os.remove(os.path.join(root, f))
                    removed += 1
                except OSError:
                    pass
    return copied, removed


def finish(argv: list[str]) -> int:
    """Работает в новой версии (из папки update/new): Babylon.exe --finish-update <папка> <pid> --then ..."""
    i = argv.index("--finish-update")
    app_dir, pid = argv[i + 1], int(argv[i + 2])
    then = argv[argv.index("--then") + 1:] if "--then" in argv else []
    new_dir = config.app_dir()
    log = os.path.join(os.path.dirname(new_dir), "swap.log")
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"ждём выхода {pid}\n")
        f.flush()
        _wait_pid(pid)
        time.sleep(0.5)
        try:
            copied, removed = mirror(new_dir, app_dir)
            f.write(f"скопировано {copied}, удалено старых {removed}\n")
        except Exception as e:
            f.write(f"ошибка копирования: {type(e).__name__}: {e}\n")
        f.flush()
        exe = next((os.path.join(app_dir, e) for e in EXES if os.path.isfile(os.path.join(app_dir, e))),
                   os.path.join(app_dir, EXE))
        subprocess.Popen([exe, *then], cwd=app_dir, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        f.write("запущена новая версия\n")
    return 0


def cleanup_staging():
    """После обновления удалить распакованную копию (её нельзя удалить, пока она работала)."""
    staging = os.path.join(config.data_dir(), "update", "new")
    if os.path.normcase(os.path.realpath(config.app_dir())) != os.path.normcase(os.path.realpath(staging)):
        shutil.rmtree(staging, ignore_errors=True)


def can_update() -> bool:
    """Подмена файлов возможна только у собранной программы на Windows."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def cli(argv: list[str]) -> int:
    """Babylon.exe --update-from <zip> [--then аргументы нового запуска] — без окон (для проверки)."""
    zip_path = argv[argv.index("--update-from") + 1]
    then = argv[argv.index("--then") + 1:] if "--then" in argv else []
    log = os.path.join(config.data_dir(), "update", "update.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    try:
        new_dir = stage(zip_path)
        launch_swap(new_dir, config.app_dir(), os.getpid(), then)
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"распаковано в {new_dir}, запущена подмена\n")
    except Exception as e:  # у оконной программы нет консоли: причину пишем в файл
        with open(log, "w", encoding="utf-8") as f:
            f.write(f"{type(e).__name__}: {e}\n")
        return 1
    return 0


# ---------------- новые версии с GitHub ----------------
REPO = "W1raks/babylon"
PAGE = f"https://github.com/{REPO}"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = re.compile(r"^Babylon-[\d.]+-win64\.zip$")


def latest(timeout: float = 8) -> dict:
    """Последний выпуск: {'version', 'notes', 'url', 'size', 'page'}. Ошибка — UpdateError."""
    import json
    import urllib.request

    req = urllib.request.Request(API, headers={"User-Agent": "Babylon", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except OSError as e:
        raise UpdateError(f"нет связи с github: {e}") from e
    asset = next((a for a in data.get("assets", []) if ASSET.match(a.get("name", ""))), None)
    if asset is None:
        raise UpdateError("в последнем выпуске нет архива для windows")
    return {"version": data.get("tag_name", "").lstrip("vV"), "notes": (data.get("body") or "").strip(),
            "url": asset["browser_download_url"], "size": asset.get("size", 0), "name": asset["name"],
            "page": data.get("html_url", PAGE)}


def is_newer(version: str, current: str | None = None) -> bool:
    return version_tuple(version) > version_tuple(current or config.VERSION)


def download(url: str, dest: str, progress=None, size: int = 0):
    """Скачать архив новой версии (во временный файл, потом переименовать — недокачанный не останется)."""
    import urllib.request

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "Babylon"})
    with urllib.request.urlopen(req, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or size or 0)
        done = 0
        while True:
            buf = r.read(1 << 16)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if progress:
                progress(done, total)
    os.replace(tmp, dest)
    return dest
