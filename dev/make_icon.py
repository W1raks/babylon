"""Собрать babylon/assets/babylon.ico из SVG (все размеры для Windows).

    QT_QPA_PLATFORM=offscreen python dev/make_icon.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from babylon.ui import theme  # noqa: E402

app = QGuiApplication(sys.argv)
sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
frames = []
for s in sizes:
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.ReadWrite)
    theme.logo(s).save(buf, "PNG")
    frames.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
out = os.path.join(os.path.dirname(__file__), "..", "babylon", "assets", "babylon.ico")
# у каждого размера свой рисунок (мелкие - упрощённые), поэтому кладём кадры как есть
frames[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
print("saved", os.path.abspath(out))
