"""Связь с Windows: глобальные горячие клавиши, двойное Ctrl+C, нажатие Ctrl+C за пользователя.

Все хуки живут в отдельном потоке со своим циклом сообщений, наружу идут сигналы Qt.
На других системах модуль загружается, но ничего не делает (для разработки и тестов).
"""
import ctypes
import sys
import threading
import time

from PySide6.QtCore import QObject, Signal

IS_WIN = sys.platform == "win32"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT, WM_APP = 0x0312, 0x0012, 0x8000
WH_KEYBOARD_LL, WM_KEYDOWN, WM_SYSKEYDOWN = 13, 0x0100, 0x0104
VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN, VK_C, VK_V = 0x11, 0x10, 0x12, 0x5B, 0x5C, 0x43, 0x56
INPUT_KEYBOARD, KEYEVENTF_KEYUP = 1, 0x2

_MODS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED = {
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "insert": 0x2D, "pause": 0x13,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "\\": 0xDC,
}


def parse_hotkey(text: str) -> tuple[int, int]:
    """'Ctrl+Alt+T' -> (модификаторы, код клавиши). Ошибка ValueError, если не разобрать."""
    mods, vk = 0, None
    for part in [p.strip().lower() for p in text.replace(" ", "").split("+") if p.strip()]:
        if part in _MODS:
            mods |= _MODS[part]
        elif part in ("control",):
            mods |= MOD_CONTROL
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])
        elif part in _NAMED:
            vk = _NAMED[part]
        else:
            raise ValueError(f"Не знаю клавишу «{part}»")
    if vk is None:
        raise ValueError("Нужна основная клавиша, например T")
    if not mods and not (0x70 <= vk <= 0x87 or vk == 0x13):
        raise ValueError("Добавьте Ctrl, Alt, Shift или Win")
    return mods, vk


if IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t
    LRESULT = ctypes.c_ssize_t

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = LRESULT
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x20, 0x80000, 0x08000000, 0x80
WDA_EXCLUDEFROMCAPTURE = 0x11


def click_through(hwnd: int):
    """Окно пропускает мышь сквозь себя (субтитры не мешают нажимать на видео) и не забирает фокус."""
    if not IS_WIN:
        return
    get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    put = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get.restype = put.restype = ctypes.c_ssize_t
    get.argtypes = [wintypes.HWND, ctypes.c_int]
    put.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    put(hwnd, GWL_EXSTYLE, get(hwnd, GWL_EXSTYLE) | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
        | WS_EX_TOOLWINDOW)


def exclude_from_capture(hwnd: int) -> bool:
    """Скрыть окно от снимков экрана (Windows 10 2004+): тогда субтитры можно класть прямо на оригинал,
    а распознавание всё равно видит исходный текст под ними."""
    if not IS_WIN:
        return False
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))


def key_down(vk: int) -> bool:
    return IS_WIN and bool(user32.GetAsyncKeyState(vk) & 0x8000)


def clipboard_seq() -> int:
    return user32.GetClipboardSequenceNumber() if IS_WIN else 0


def _send_keys(seq: list[tuple[int, bool]]):
    arr = (INPUT * len(seq))()
    for i, (vk, up) in enumerate(seq):
        arr[i].type = INPUT_KEYBOARD
        arr[i].u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    user32.SendInput(len(seq), arr, ctypes.sizeof(INPUT))


def press_copy(wait_release: float = 0.8):
    """Нажать Ctrl+C в активном окне. Сначала ждём, пока пользователь отпустит клавиши сочетания,
    иначе вместо Ctrl+C уйдёт, например, Ctrl+Alt+C."""
    _press_ctrl(VK_C, wait_release)


def press_paste(wait_release: float = 0.8):
    """Нажать Ctrl+V в активном окне (замена выделенного текста переводом)."""
    _press_ctrl(VK_V, wait_release)


def _press_ctrl(vk_key: int, wait_release: float):
    if not IS_WIN:
        return
    mods = (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)
    end = time.monotonic() + wait_release
    while time.monotonic() < end and any(key_down(k) for k in mods):
        time.sleep(0.01)
    still = [k for k in mods if key_down(k)]
    # Alt и Win, если их держат, отпускаем программно (иначе откроется меню / Пуск)
    _send_keys([(k, True) for k in still if k != VK_CONTROL]
               + [(VK_CONTROL, False), (vk_key, False), (vk_key, True)]
               + ([] if VK_CONTROL in still else [(VK_CONTROL, True)]))


class Hotkeys(QObject):
    """Глобальные сочетания и двойное Ctrl+C. Сигнал fired(имя действия)."""

    fired = Signal(str)
    failed = Signal(str, str)  # имя, текст ошибки (сочетание занято другой программой)

    def __init__(self, double_copy_ms: int = 450):
        super().__init__()
        self._wanted: dict[str, str] = {}
        self._double_copy = True
        self._double_ms = double_copy_ms
        self._last_copy = 0.0
        self._suspend_until = 0.0
        self._tid = 0
        self._ready = threading.Event()
        self._thread = None

    def set_double_copy(self, on: bool):
        self._double_copy = on

    def suspend_copy_detection(self, seconds: float = 1.0):
        """Не считать наши собственные Ctrl+C за двойное нажатие."""
        self._suspend_until = time.monotonic() + seconds

    def start(self, bindings: dict[str, str]):
        self._wanted = dict(bindings)
        if not IS_WIN:
            return
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="babylon-hotkeys", daemon=True)
            self._thread.start()
            self._ready.wait(2)
        else:
            user32.PostThreadMessageW(self._tid, WM_APP + 1, 0, 0)

    def stop(self):
        if IS_WIN and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    # --- поток с циклом сообщений ---
    def _register_all(self, ids: dict[int, str]):
        for i in list(ids):
            user32.UnregisterHotKey(None, i)
        ids.clear()
        for n, (name, combo) in enumerate(self._wanted.items(), start=1):
            if not combo:
                continue
            try:
                mods, vk = parse_hotkey(combo)
            except ValueError as e:
                self.failed.emit(name, str(e))
                continue
            if user32.RegisterHotKey(None, n, mods | MOD_NOREPEAT, vk):
                ids[n] = name
            else:
                self.failed.emit(name, f"{combo} уже занято другой программой")

    def _loop(self):
        self._tid = kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        self._register_all(ids)

        c_held = [False]  # зажатая C даёт автоповтор - это не второе нажатие

        def hook(code, wparam, lparam):
            if code == 0 and self._double_copy:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                injected = kb.flags & 0x10
                is_down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                repeat = kb.vkCode == VK_C and is_down and c_held[0]
                if kb.vkCode == VK_C:
                    c_held[0] = is_down
                if (is_down and not repeat and kb.vkCode == VK_C and not injected
                        and key_down(VK_CONTROL) and not key_down(VK_MENU)):
                    now = time.monotonic()
                    if now > self._suspend_until:
                        if now - self._last_copy <= self._double_ms / 1000:
                            self._last_copy = 0.0
                            self.fired.emit("double_copy")
                        else:
                            self._last_copy = now
            return user32.CallNextHookEx(None, code, wparam, lparam)

        proc = HOOKPROC(hook)  # держим ссылку, иначе сборщик мусора уронит процесс
        hhook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.fired.emit(ids[msg.wParam])
            elif msg.message == WM_APP + 1:
                self._register_all(ids)
        for i in ids:
            user32.UnregisterHotKey(None, i)
        if hhook:
            user32.UnhookWindowsHookEx(hhook)
