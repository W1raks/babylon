"""Размытие фона окна средствами Windows («акрил»).

Windows 11 22H2+: системный фон DWM (DWMSBT_TRANSIENTWINDOW) — то же стекло, что у меню Пуск.
Windows 10 и старые 11: SetWindowCompositionAttribute с ACCENT_ENABLE_ACRYLICBLURBEHIND.
Если ничего не вышло (удалённый рабочий стол, выключена прозрачность), apply() вернёт False,
и окно рисует плотный фон, чтобы текст читался.
"""
import ctypes
import sys

IS_WIN = sys.platform == "win32"

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND, DWMWCP_ROUNDSMALL = 2, 3
DWMSBT_TRANSIENTWINDOW = 3


def _build() -> int:
    if not IS_WIN:
        return 0
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def transparency_enabled() -> bool:
    """Включены ли «Эффекты прозрачности» в параметрах Windows."""
    if not IS_WIN:
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "EnableTransparency")[0])
    except OSError:
        return True


def _dwm(hwnd: int, attr: int, value: int) -> bool:
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0


class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class _ACCENT(ctypes.Structure):
    _fields_ = [("state", ctypes.c_int), ("flags", ctypes.c_int), ("color", ctypes.c_uint), ("anim", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("attr", ctypes.c_int), ("data", ctypes.c_void_p), ("size", ctypes.c_size_t)]


def _accent_blur(hwnd: int, tint_abgr: int) -> bool:
    accent = _ACCENT(4, 2, tint_abgr, 0)  # 4 = ACCENT_ENABLE_ACRYLICBLURBEHIND, 2 = рисовать цвет
    data = _WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
    try:
        return bool(ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data)))
    except AttributeError:
        return False


def apply(widget, popup: bool = False) -> bool:
    """Включить размытие под окном. Окно должно иметь WA_TranslucentBackground."""
    if not IS_WIN or not transparency_enabled():
        return False
    hwnd = int(widget.winId())
    _dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
    _dwm(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    if _build() >= 22621 and not popup:
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(_MARGINS(-1, -1, -1, -1)))
        if _dwm(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_TRANSIENTWINDOW):
            return True
    # всплывашки и Windows 10: акрил через композицию (цвет почти прозрачный: тон рисует Qt)
    return _accent_blur(hwnd, 0x01101010)


def set_dark_titlebar(widget):
    if IS_WIN:
        hwnd = int(widget.winId())
        _dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
