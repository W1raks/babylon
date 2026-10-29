"""Настройки и пути. Всё хранится в %LOCALAPPDATA%\\Babylon (на Linux ~/.local/share/babylon)."""
import json
import os
import sys
import time

APP = "Babylon"
VERSION = "2.3.0"
OLD_APPS = ("Vavilon", "Tolmach")  # прежние имена: данные и автозапуск переносим

DEFAULTS = {
    "preferred": "ru",       # на какой язык переводить
    "fallback": "en",        # куда переводить текст, который уже на preferred
    "mode": "online",        # online: Google, без интернета модели; offline: только модели
    "hotkeys": {
        "selection": "Ctrl+Alt+T",   # перевести выделенное
        "screen": "Ctrl+Alt+S",      # область экрана
        "window": "Ctrl+Alt+Space",  # открыть окно
        "replace": "Ctrl+Alt+R",     # заменить выделенное переводом
        "live": "Ctrl+Alt+L",        # живые субтитры: включить / выключить
        "hear": "Ctrl+Alt+H",        # перевод речи из звука компьютера: включить / выключить
    },
    "replace_target": "en",  # на какой язык заменять свой текст
    "double_copy": True,     # двойное Ctrl+C = перевести скопированное
    "ocr_lang": "auto",
    "autostart": False,
    "check_updates": True,   # раз в день проверять новую версию на github
    "last_update_check": 0,
    "skip_version": "",      # «пропустить эту версию»
    "popup_width": 460,
    "opacity": 78,           # плотность стекла, % (100 — непрозрачное)
    "font_size": 12.5,
    "history_size": 100,
    # перевод речи
    "asr_model": "base",     # base — быстрая модель whisper, small — точная
    "hear_source": "system", # system — звук компьютера, mic — микрофон
    "hear_overlay": True,    # субтитры поверх экрана
    "voice_over": False,     # озвучивать перевод голосом
    # вид
    "accent": "#ff3b3b",
    "subs_size": 30,         # размер субтитров речи, px
    "subs_opacity": 86,      # плотность их плашки, %
    "subs_original": True,   # показывать оригинал мелко над переводом
    "subs_pos": "bottom",    # bottom / top
}


def app_dir() -> str:
    """Папка с программой (рядом с .exe или корень проекта)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    # переносная версия: папка data рядом с программой
    portable = os.path.join(app_dir(), "data")
    if os.path.isdir(portable):
        return portable
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        new = os.path.join(base, APP)
        if not os.path.exists(new):
            for name in OLD_APPS:
                old = os.path.join(base, name)
                if os.path.isdir(old):
                    try:
                        os.rename(old, new)  # скачанные языки и история Вавилона/Толмача не пропадут
                    except OSError:
                        return old  # папка занята (например, идёт обновление) — перенесём в следующий раз
                    break
        return new
    return os.path.join(os.path.expanduser("~/.local/share"), APP.lower())


def models_dir() -> str:
    return os.environ.get("BABYLON_MODELS") or os.path.join(data_dir(), "models")


def asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "assets", name)
    return path if os.path.exists(path) else os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Settings(dict):
    def __init__(self):
        super().__init__(json.loads(json.dumps(DEFAULTS)))
        self.path = os.path.join(data_dir(), "settings.json")
        saved = _load(self.path, {})
        hk = {**self["hotkeys"], **saved.pop("hotkeys", {})}
        self.update({k: v for k, v in saved.items() if k in DEFAULTS})
        self["hotkeys"] = hk

    def save(self):
        _save(self.path, dict(self))


class History:
    def __init__(self, limit: int):
        self.limit = limit
        self.path = os.path.join(data_dir(), "history.json")
        self.items = _load(self.path, [])

    def add(self, src_text: str, out_text: str, src: str, tgt: str):
        if not src_text.strip() or not out_text.strip():
            return
        self.items = [i for i in self.items if i["text"] != src_text]
        self.items.insert(0, {"text": src_text[:4000], "out": out_text[:4000], "src": src, "tgt": tgt})
        del self.items[self.limit:]
        try:
            _save(self.path, self.items)
        except OSError:
            pass

    def clear(self):
        self.items = []
        try:
            os.remove(self.path)
        except OSError:
            pass


# Словарик: интервалы повторения по «коробкам» Лейтнера, в днях
BOX_DAYS = (0, 1, 3, 7, 16, 35)


class Vocab:
    """Сохранённые слова и фразы для заучивания карточками."""

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(data_dir(), "vocab.json")
        self.items: list[dict] = _load(self.path, [])

    def _write(self):
        try:
            _save(self.path, self.items)
        except OSError:
            pass

    def find(self, text: str, src: str, tgt: str):
        key = text.strip().lower()
        return next((i for i in self.items if i["text"].strip().lower() == key and i["src"] == src
                     and i["tgt"] == tgt), None)

    def has(self, text, src, tgt) -> bool:
        return self.find(text, src, tgt) is not None

    def toggle(self, text: str, out: str, src: str, tgt: str) -> bool:
        """Добавить или убрать; вернуть True, если слово теперь в словарике."""
        found = self.find(text, src, tgt)
        if found:
            self.items.remove(found)
            self._write()
            return False
        self.items.insert(0, {"text": text.strip()[:500], "out": out.strip()[:1000], "src": src, "tgt": tgt,
                              "added": int(time.time()), "box": 0, "due": 0})
        self._write()
        return True

    def remove(self, item: dict):
        if item in self.items:
            self.items.remove(item)
            self._write()

    def due(self, now: float | None = None) -> list[dict]:
        now = now or time.time()
        return [i for i in self.items if i.get("due", 0) <= now]

    def answer(self, item: dict, remembered: bool, now: float | None = None):
        """Помню — в следующую коробку (реже), не помню — в первую (сегодня ещё раз)."""
        now = now or time.time()
        box = min(item.get("box", 0) + 1, len(BOX_DAYS) - 1) if remembered else 0
        item["box"] = box
        item["due"] = int(now + BOX_DAYS[box] * 86400) if remembered else int(now + 60)
        self._write()

    def export_csv(self, path: str) -> int:
        """Для Anki: «слово;перевод» в каждой строке."""
        import csv

        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            for i in self.items:
                w.writerow([i["text"], i["out"]])
        return len(self.items)


def set_autostart(on: bool):
    """Запуск вместе с Windows через раздел Run в реестре пользователя."""
    if sys.platform != "win32":
        return
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                         winreg.KEY_SET_VALUE)
    with key:
        if on:
            exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" -m babylon'
            main = os.path.join(os.path.dirname(sys.executable), "Babylon.exe")
            if getattr(sys, "frozen", False) and os.path.isfile(main):
                exe = main  # запущены через старую копию Vavilon.exe: автозапуск — на основной файл
            cmd = f'"{exe}" --tray' if getattr(sys, "frozen", False) else f"{exe} --tray"
            winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP)
            except FileNotFoundError:
                pass
        for name in OLD_APPS:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass
