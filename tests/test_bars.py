"""Панели субтитров: свернуть в значок, развернуть щелчком, перетащить, скрыть и вернуть."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from babylon.ui import theme  # noqa: E402
from babylon.ui.subs import HearBar, LiveBar  # noqa: E402

theme.load_fonts()


def test_live_bar_modes():
    bar = LiveBar("ru", 90)
    modes, placed = [], []
    bar.mode_changed.connect(modes.append)
    bar.placed.connect(placed.append)
    screen = app.primaryScreen()
    bar.place(QRect(200, 500, 600, 60), screen)
    full = bar.size()
    assert bar.isVisible() and full.width() > 200

    right = bar.geometry().right()
    bar.set_mode("icon")
    assert bar.width() == 34 and bar.height() == 34 and abs(bar.geometry().right() - right) <= 1
    assert modes == ["icon"]

    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=QPoint(17, 17))   # щелчок по значку — развернуть
    assert bar.mode == "full" and bar.width() == full.width() and modes == ["icon", "full"]

    start = bar.pos()
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(20, 10))
    QTest.mouseMove(bar, QPoint(80, 40))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
    assert placed and bar.pos() != start and bar.mode == "full"           # перетащили, не свернули

    bar.set_mode("hidden")
    assert not bar.isVisible() and modes[-1] == "hidden"
    bar.set_mode("full")
    assert bar.isVisible()

    bar.hide()
    bar.place(QRect(200, 500, 600, 60), screen, mode="icon", pos=QPoint(50, 60))   # запомненные место и вид
    assert bar.isVisible() and bar.mode == "icon" and bar.pos() == QPoint(50, 60)
    bar.hide()
    bar.place(QRect(200, 500, 600, 60), screen, mode="hidden")
    assert not bar.isVisible()


def test_hear_bar_drag_moves_subtitles():
    bar = HearBar("ru", 90, False)
    moved = []
    bar.moved.connect(moved.append)
    bar.show_at(QPoint(300, 300), app.primaryScreen(), "icon")
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=QPoint(17, 17))
    QTest.mouseMove(bar, QPoint(60, 17))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=QPoint(60, 17))
    assert moved and bar.mode == "icon"   # потащили значок — остался значком
