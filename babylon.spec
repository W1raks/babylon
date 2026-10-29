# Сборка: pyinstaller babylon.spec  ->  dist/Babylon/Babylon.exe
# Папка (а не один exe): запускается быстрее, модели лежат отдельно в %LOCALAPPDATA%\Babylon\models
import os
import re

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

# номер версии кладём в _internal/version.txt: по нему обновление из архива узнаёт, что ставит
VERSION = re.search(r'VERSION = "([^"]+)"', open("babylon/config.py", encoding="utf-8").read()).group(1)
os.makedirs("build", exist_ok=True)
with open("build/version.txt", "w", encoding="utf-8") as f:
    f.write(VERSION)

hidden = collect_submodules("winrt") + collect_submodules("pymupdf") + ["imageio_ffmpeg", "soundcard", "tokenizers", "docx"]
binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("pymupdf")

a = Analysis(
    ["run_babylon.py"],
    binaries=binaries,
    # imageio_ffmpeg: внутри лежит ffmpeg.exe — им читаются и сохраняются видео
    datas=[("babylon/assets", "assets"), ("build/version.txt", ".")] + collect_data_files("py3langid")
    + collect_data_files("imageio_ffmpeg") + collect_data_files("soundcard") + collect_data_files("docx")
    + collect_data_files("pymupdf"),
    hiddenimports=hidden,
    excludes=["tkinter", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtWebEngineCore",
              "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtDesigner"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Babylon",
    icon="babylon/assets/babylon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Babylon", upx=False)

