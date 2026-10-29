"""Вавилон (Babylon): связывает перевод, горячие клавиши, всплывашку, окно и значок у часов."""
import os
import sys
import threading
import time

from PySide6.QtCore import QMimeData, QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QImage
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import config, models, ocr, speech, updater, winapi
from .hear import Hearing
from .live import LiveSubs
from .engine import MissingModel
from .langs import ARGOS, LANGS, OFFLINE, name
from .translator import NoWay, Translator
from .ui import theme
from .ui.popup import Popup
from .ui.snip import Snipper
from .ui.window import MainWindow

SERVER = "babylon-single-instance"


def detect_lang(text: str, ocr_lang: str) -> str:
    """Язык фразы для подписи: распознаватель «en» читает всю латиницу, поэтому уточняем по тексту."""
    from .langs import detect

    return detect(text) if ocr_lang == "en" else ocr_lang


class Bus(QObject):
    """Сигналы из фоновых потоков в окна (Qt сам перенесёт вызов в главный поток)."""

    translated = Signal(int, str, object, int)   # номер запроса, исходный текст, результат, мс
    failed = Signal(int, str, str)                # номер, текст ошибки, язык, который надо скачать
    recognized = Signal(str, str, QPoint)
    ocr_failed = Signal(str, QPoint)
    progress = Signal(str, int, int)
    installed = Signal(str, str)
    update_ready = Signal(str, str)
    spoke = Signal(str)                           # ошибка озвучки (пусто — всё хорошо)
    replaced = Signal(str, str, str)              # перевод, src, tgt (для замены выделенного)
    replace_failed = Signal(str)
    asr_progress = Signal(int, int)
    asr_installed = Signal(str, str)              # размер модели, ошибка
    replied = Signal(object)                      # мой ответ в разговоре (переведён)
    update_info = Signal(object, str, bool)       # сведения о выпуске, ошибка, тихая проверка
    update_progress = Signal(int, int)
    update_downloaded = Signal(str, str)          # путь к архиву, ошибка


class Babylon(QObject):
    def __init__(self, app: QApplication, start_hidden: bool):
        super().__init__()
        self.app = app
        self.s = config.Settings()
        self.hist = config.History(self.s["history_size"])
        self.vocab = config.Vocab()
        self.tr = Translator(config.models_dir(), self.s["mode"])
        self.bus = Bus()
        self._req = 0
        self._popup_req = -1
        self._win_req = -1
        self._popup_ctx = None  # (текст, src, join_lines)
        self._popup_res = None
        self._downloads: set[str] = set()

        self.popup = Popup(self.s)
        self.popup.note = self._note
        self.popup.retarget.connect(self._popup_retarget)
        self.popup.swap.connect(self._popup_swap)
        self.popup.star.connect(self._popup_star)
        self.popup.speak.connect(self._popup_speak)
        self.popup.open_window.connect(self.open_window_with)
        self.popup.download.connect(self.download)

        self.win = MainWindow(self.s, ocr.available_languages(), note=self._note,
                              media_translate=self._media_translate)
        self.win.live_requested.connect(self.toggle_live)
        self.win.translate_requested.connect(self._window_translate)
        self.win.snip_requested.connect(self.snip)
        self.win.download_requested.connect(self.download)
        self.win.remove_requested.connect(self.remove_model)
        self.win.settings_changed.connect(self._settings_changed)
        self.win.update_requested.connect(self.update_from)
        self.win.speak_requested.connect(self.speak)
        self.win.star_requested.connect(self._star)
        self.win.study_requested.connect(lambda: self.win.start_study(self.vocab.due()))
        self.win.vocab_answer.connect(lambda item, ok: (self.vocab.answer(item, ok), self._fill_vocab()))
        self.win.vocab_remove.connect(lambda item: (self.vocab.remove(item), self._fill_vocab()))
        self.win.vocab_export.connect(self._export_vocab)
        self.win.history_cleared.connect(lambda: (self.hist.clear(), self.win.fill_history([])))
        self.win.fill_history(self.hist.items)
        self._fill_vocab()
        self._refresh_models()
        self.win.set_online(True, self.s["mode"])

        self.snipper = Snipper()
        self.snipper.captured.connect(self._snipped)
        self.snipper.region.connect(self._live_region)

        self.live = LiveSubs(self.tr, self.s)
        self.live.phrase.connect(self._live_phrase)
        self.live.clear.connect(lambda: self.subs and self.subs.clear_phrase())
        self.live.status.connect(lambda msg: self.live_bar and self.live_bar.set_status(msg))
        self.subs = None
        self.live_bar = None

        # перевод речи
        self.hearing = Hearing(self.tr, self.s)
        self.speech_subs = None
        self.hear_bar = None
        tk = self.win.talk
        tk.start_requested.connect(self.start_hearing)
        tk.stop_requested.connect(self.stop_hearing)
        tk.reply_requested.connect(self._reply)
        tk.download_requested.connect(self._download_asr)
        tk.overlay_toggled.connect(self._hear_overlay_toggled)
        tk.voice_toggled.connect(self._voice_toggled)
        self.hearing.phrase.connect(self._heard)
        self.hearing.draft.connect(self._heard_draft)
        self.hearing.status.connect(tk.set_status)
        self.hearing.level.connect(self._hear_level)
        self.hearing.running_changed.connect(self._hear_running)
        self.bus.asr_progress.connect(tk.model_progress)
        self.bus.asr_installed.connect(self._asr_installed)

        self.bus.translated.connect(self._on_translated)
        self.bus.failed.connect(self._on_failed)
        self.bus.recognized.connect(self._on_recognized)
        self.bus.ocr_failed.connect(lambda msg, at: self.popup.show_message(msg, at=at))
        self.bus.progress.connect(self.win.set_model_progress)
        self.bus.installed.connect(self._on_installed)
        self.bus.update_ready.connect(self._update_ready)
        self.bus.spoke.connect(lambda err: err and self._notify(err))
        self.bus.replaced.connect(self._paste_replacement)
        self.bus.replace_failed.connect(lambda msg: self.popup.show_message(msg))
        self.bus.replied.connect(self._replied)
        self.bus.update_info.connect(self._update_info)
        self.bus.update_progress.connect(lambda d, t: self.win.set_update_status(
            f"скачиваю {d / 1048576:.0f} из {t / 1048576:.0f} мб", d / max(1, t)))
        self.bus.update_downloaded.connect(self._update_downloaded)
        self.win.check_updates_requested.connect(lambda: self.check_updates(quiet=False))
        QTimer.singleShot(15000, self._auto_check)

        self.keys = winapi.Hotkeys()
        self.keys.fired.connect(self._hotkey)
        self.keys.failed.connect(self.win.hotkey_error)
        self.keys.set_double_copy(self.s["double_copy"])
        self.keys.start(self.s["hotkeys"])

        self._make_tray()
        self._listen_second_instance()
        app.aboutToQuit.connect(self.keys.stop)
        app.aboutToQuit.connect(self.live.stop)
        app.aboutToQuit.connect(self.hearing.stop)
        app.aboutToQuit.connect(speech.stop)
        if self.s["autostart"]:
            try:
                config.set_autostart(True)  # путь мог смениться (Vavilon.exe → Babylon.exe)
            except OSError:
                pass

        if "--updated" in sys.argv:
            self.open_window()
            self._notify(f"Обновлён до версии {config.VERSION}")
        elif not start_hidden:
            self.open_window()

    # --- значок у часов ---
    def _make_tray(self):
        self.tray = QSystemTrayIcon(theme.app_icon(), self)
        hk = self.s["hotkeys"]
        self.tray.setToolTip(f"Вавилон\n{hk['selection']} — перевести выделенное\n"
                             f"{hk['screen']} — текст с экрана\n{hk['live']} — живые субтитры")
        m = QMenu()
        m.addAction("перевести выделенное", lambda: self._hotkey("selection"))
        m.addAction("текст с экрана", self.snip)
        self._live_action = m.addAction("живые субтитры", self.toggle_live)
        self._hear_action = m.addAction("перевод речи (звук компьютера)", self.toggle_hearing)
        self._bars_action = m.addAction("показать панель субтитров", self._show_bars)
        self._bars_action.setVisible(False)
        m.addAction("разговор", lambda: (self.win.show_page("talk"), self.open_window()))
        m.addAction("перевести фото или видео", lambda: (self.win.show_page("media"), self.open_window()))
        m.addAction("открыть окно", self.open_window)
        m.addSeparator()
        m.addAction("словарик", lambda: (self.win.show_page("vocab"), self.open_window()))
        m.addAction("языки", lambda: (self.win.show_page("langs"), self.open_window()))
        m.addAction("настройки", lambda: (self.win.show_page("settings"), self.open_window()))
        m.addSeparator()
        m.addAction("выход", self.app.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda r: self.open_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self._tray_menu = m

    def _notify(self, text: str):
        if self.tray.supportsMessages():
            self.tray.showMessage("Вавилон", text, theme.app_icon(), 3500)

    def _listen_second_instance(self):
        QLocalServer.removeServer(SERVER)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(lambda: (self.server.nextPendingConnection(), self.open_window()))
        self.server.listen(SERVER)

    def open_window(self):
        self.win.fill_history(self.hist.items)
        self._fill_vocab()
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def open_window_with(self, text: str):
        self.popup.hide_animated()
        self.open_window()
        if text:
            self.win.set_text(text)

    def _note(self, code: str) -> str:
        """Пометка в списке языков: скачан ли офлайн."""
        if code in ("en",):
            return ""
        if code in OFFLINE and self.tr.can_offline(code, "ru") and self.tr.can_offline("ru", code):
            return "· офлайн"
        return ""

    # --- горячие клавиши ---
    def _hotkey(self, key: str):
        if key == "selection":
            self._grab_selection(self._translate_to_popup)
        elif key == "replace":
            self._grab_selection(self._replace_selection)
        elif key == "double_copy":
            QTimer.singleShot(90, lambda: self._translate_to_popup(QGuiApplication.clipboard().text()))
        elif key == "screen":
            self.snip()
        elif key == "live":
            self.toggle_live()
        elif key == "hear":
            self.toggle_hearing()
        elif key == "window":
            if self.win.isVisible() and self.win.isActiveWindow():
                self.win.hide()
            else:
                self.open_window()

    def _snapshot_clipboard(self) -> QMimeData:
        saved = QMimeData()
        old = QGuiApplication.clipboard().mimeData()
        for f in old.formats() if old else []:
            saved.setData(f, old.data(f))
        return saved

    def _grab_selection(self, then):
        """Скопировать выделенное в активной программе и вернуть буфер обмена как был."""
        cb = QGuiApplication.clipboard()
        saved = self._snapshot_clipboard()
        seq0 = winapi.clipboard_seq()
        self.keys.suspend_copy_detection(1.5)
        threading.Thread(target=winapi.press_copy, daemon=True).start()
        start = time.monotonic()

        def poll():
            if winapi.clipboard_seq() != seq0:
                QTimer.singleShot(40, finish)  # даём программе дописать все форматы
            elif time.monotonic() - start < 1.2:
                QTimer.singleShot(15, poll)
            else:
                self.popup.show_message("выделите текст и нажмите сочетание ещё раз.\n"
                                        "или откройте окно, чтобы ввести текст вручную.")

        def finish():
            text = cb.text()
            if saved.formats():
                cb.setMimeData(saved)
            then(text)

        poll()

    # --- всплывашка ---
    def _translate_to_popup(self, text: str, join_lines: bool = False, at: QPoint | None = None,
                            label: str = "перевожу"):
        text = (text or "").strip()
        if not text:
            self.popup.show_message("буфер обмена пуст", at=at)
            return
        self._popup_ctx = (text, "auto", join_lines)
        self._run_popup(text, "auto", None, join_lines, at, label)

    def _run_popup(self, text, src, tgt, join_lines, at=None, label="перевожу"):
        from .langs import default_target, detect

        guess = detect(text) if src == "auto" else src
        self.popup.show_loading(text, guess, tgt or default_target(guess, self.s["preferred"], self.s["fallback"]),
                                at, label)
        self._popup_req = self._start(text, src, tgt, join_lines)

    def _popup_swap(self):
        """⇄: перевод становится исходным текстом и переводится обратно."""
        r = self._popup_res
        if not r or not r["out"].strip():
            return
        self._popup_ctx = (r["out"], r["tgt"], False)
        self._run_popup(r["out"], r["tgt"], r["src"], False)

    def _popup_retarget(self, tgt: str):
        if self._popup_ctx:
            text, src, join_lines = self._popup_ctx
            if self._popup_res and src == "auto":
                src = self._popup_res["src"]
            self._run_popup(text, src, tgt, join_lines)

    def _popup_star(self):
        r = self._popup_res
        if r and self._popup_ctx:
            on = self.vocab.toggle(self._popup_ctx[0], r["out"], r["src"], r["tgt"])
            self.popup.set_starred(on)
            self._fill_vocab()

    def _popup_speak(self, which: str):
        r = self._popup_res
        if not r or not self._popup_ctx:
            return
        if which == "src":
            self.speak(self._popup_ctx[0], r["src"])
        else:
            self.speak(r["out"], r["tgt"])

    # --- перевод в фоне ---
    def _start(self, text, src, tgt, join_lines) -> int:
        self._req += 1
        n = self._req
        pref, fb = self.s["preferred"], self.s["fallback"]

        def run():
            t = time.perf_counter()
            try:
                res = self.tr.translate(text, src, tgt, join_lines, pref, fb)
                self.bus.translated.emit(n, text, res, int((time.perf_counter() - t) * 1000))
            except NoWay as e:
                self.bus.failed.emit(n, e.reason, self.tr.missing_language(e.src, e.tgt))
            except MissingModel as e:
                lang = self.tr.missing_language(e.src, e.tgt)
                self.bus.failed.emit(n, f"язык «{name(lang)}» не скачан для перевода без интернета", lang)
            except Exception as e:  # покажем ошибку, а не уроним программу
                self.bus.failed.emit(n, f"ошибка перевода: {e}", "")

        threading.Thread(target=run, daemon=True).start()
        return n

    def _on_translated(self, n, text, res, ms):
        self.win.set_online(self.tr.online.available(), self.s["mode"])
        starred = self.vocab.has(text, res["src"], res["tgt"])
        if n == self._popup_req and self.popup.isVisible():
            self._popup_res = res
            self.popup.show_result(res, starred)
        elif n == self._win_req:
            self.win.show_translation(text, res, ms, starred)
        self.hist.add(text, res["out"], res["src"], res["tgt"])

    def _on_failed(self, n, msg, lang):
        self.win.set_online(self.tr.online.available(), self.s["mode"])
        if n == self._popup_req:
            src_text = self._popup_ctx[0] if self._popup_ctx else ""
            self.popup.show_message(msg + (". скачайте его один раз — дальше всё работает без сети." if lang else ""),
                                    missing=lang if lang in OFFLINE else None, source=src_text)
        else:
            self.win.show_error(msg)

    def _window_translate(self, text, src, tgt):
        self._win_req = self._start(text, src, tgt, False)

    # --- озвучка ---
    def speak(self, text: str, lang: str):
        text = (text or "").strip()
        if not text or not lang or lang == "auto":
            return

        def run():
            try:
                speech.speak(text, lang)
                self.bus.spoke.emit("")
            except Exception as e:
                self.bus.spoke.emit(str(e))

        threading.Thread(target=run, daemon=True).start()

    # --- замена выделенного переводом ---
    def _replace_selection(self, text: str):
        text = (text or "").strip()
        if not text:
            self.popup.flash("выделите свой текст и нажмите сочетание ещё раз")
            return
        from .langs import detect

        src = detect(text)
        tgt = self.s["replace_target"]
        if src == tgt:  # уже на этом языке — переводим на любимый
            tgt = self.s["preferred"] if src != self.s["preferred"] else self.s["fallback"]

        def run():
            try:
                res = self.tr.translate(text, "auto", tgt)
                self.bus.replaced.emit(res["out"], res["src"], res["tgt"])
            except NoWay as e:
                self.bus.replace_failed.emit(e.reason)
            except MissingModel as e:
                lang = self.tr.missing_language(e.src, e.tgt)
                self.bus.replace_failed.emit(f"язык «{name(lang)}» не скачан, а интернета нет")
            except Exception as e:
                self.bus.replace_failed.emit(f"не получилось перевести: {e}")

        threading.Thread(target=run, daemon=True).start()

    def _paste_replacement(self, out: str, src: str, tgt: str):
        """Подложить перевод в буфер, нажать Ctrl+V и вернуть буфер как был."""
        cb = QGuiApplication.clipboard()
        saved = self._snapshot_clipboard()
        cb.setText(out)
        self.keys.suspend_copy_detection(1.0)

        def paste():
            winapi.press_paste()
            QTimer.singleShot(400, lambda: saved.formats() and cb.setMimeData(saved))

        QTimer.singleShot(60, lambda: threading.Thread(target=paste, daemon=True).start())
        self.popup.flash(f"заменено: {name(src)} → {name(tgt)}", at=QCursor.pos() + QPoint(14, 18))

    # --- словарик ---
    def _star(self, text, out, src, tgt):
        on = self.vocab.toggle(text, out, src, tgt)
        self.win.set_starred(on)
        self._fill_vocab()

    def _fill_vocab(self):
        self.win.fill_vocab(self.vocab.items, len(self.vocab.due()))

    def _export_vocab(self, path):
        try:
            n = self.vocab.export_csv(path)
            self._notify(f"Словарик сохранён: {n} слов. В Anki: Файл → Импорт.")
        except OSError as e:
            QMessageBox.warning(self.win, "Вавилон", f"Не получилось сохранить: {e}")

    # --- фото и видео ---
    def _media_translate(self, text: str, tgt: str) -> str:
        """Для раздела «фото и видео» (вызывается в фоновых потоках)."""
        try:
            return self.tr.translate(text, "auto", tgt, True, self.s["preferred"], self.s["fallback"])["out"]
        except NoWay as e:
            raise RuntimeError(e.reason) from e
        except MissingModel as e:
            raise RuntimeError(f"язык «{name(self.tr.missing_language(e.src, e.tgt))}» не скачан, "
                               "а интернета нет") from e

    # --- живые субтитры ---
    def toggle_live(self):
        if self.live.running:
            self.stop_live()
            return
        self.popup.hide()
        if self.win.isVisible() and self.win.isActiveWindow():
            self.win.showMinimized()  # не мешаем выделять область на видео
        QTimer.singleShot(150, lambda: self.snipper.start(live=True))

    def _live_region(self, rect, screen):
        from .ui.subs import LiveBar, SubsOverlay

        if self.subs is None:
            self.subs = SubsOverlay()
            self.live_bar = LiveBar(self.s["preferred"], self.s["opacity"])
            self.live_bar.stop.connect(self.stop_live)
            self.live_bar.target_changed.connect(self.live.set_target)
            self.live_bar.mode_changed.connect(lambda m: self._bar_mode("live_bar", m))
            self.live_bar.placed.connect(lambda p: (self.s.__setitem__("live_bar_pos", [p.x(), p.y()]), self.s.save()))
        rec = bool(self.s.get("live_recordable", False))
        self.subs.place(rect, screen, rec)
        pos = self.s.get("live_bar_pos")
        self.live_bar.place(rect, screen, rec, self.s.get("live_bar", "full"), QPoint(*pos) if pos else None)
        self.live.start(rect, screen, self.live_bar.tgt.code)
        self._live_action.setText("остановить живые субтитры")
        self._update_bars_action()

    def _live_phrase(self, text, out, lines, ms):
        if not self.subs:
            return
        self.subs.set_phrase(out, lines)
        self.live_bar.set_lang(self.live.lang and detect_lang(text, self.live.lang))
        self.live_bar.set_speed(ms, self.live.ocr_ms)

    def stop_live(self):
        self.live.stop()
        if self.subs:
            self.subs.hide()
            self.live_bar.hide()
        self._live_action.setText("живые субтитры")
        self._update_bars_action()

    # --- панели субтитров: свернуть в значок, скрыть, вернуть из трея ---
    def _bar_mode(self, key: str, mode: str):
        self.s[key] = mode
        self.s.save()
        self._update_bars_action()
        if mode == "hidden":
            self._notify("Панель скрыта, субтитры работают. Вернуть панель — в меню значка в трее, "
                         "выключить субтитры — " + ("Ctrl+Alt+L" if key == "live_bar" else "Ctrl+Alt+H"))

    def _hidden_bars(self):
        return [b for b, on in ((self.live_bar, self.live.running), (self.hear_bar, self.hearing.running))
                if b is not None and on and b.mode == "hidden"]

    def _update_bars_action(self):
        self._bars_action.setVisible(bool(self._hidden_bars()))

    def _show_bars(self):
        for b in self._hidden_bars():
            b.set_mode("full")

    # --- перевод речи ---
    def toggle_hearing(self):
        if self.hearing.running:
            self.stop_hearing()
        else:
            self.start_hearing("system", self.win.talk.tgt.code)

    def start_hearing(self, source: str, target: str):
        from . import asr

        self.s["hear_source"] = source
        self.s.save()
        if not any(asr.installed(sz) for sz in asr.SIZES):
            self.win.show_page("talk")
            self.open_window()
            self.win.talk.set_status("сначала скачайте модель распознавания речи")
            return
        if not asr.installed(self.s.get("asr_model", "base")):  # выбрана модель, которой нет — берём скачанную
            self.s["asr_model"] = next(sz for sz in asr.SIZES if asr.installed(sz))
        if not self.hearing.start(source, target):
            return
        if self.s.get("hear_overlay", True):
            self._show_speech_subs()

    def stop_hearing(self):
        self.hearing.stop()

    def _show_speech_subs(self):
        from .ui.subs import HearBar, SpeechOverlay

        if self.speech_subs is None:
            self.speech_subs = SpeechOverlay(self.s)
            self.hear_bar = HearBar(self.win.talk.tgt.code, self.s["opacity"], self.s.get("voice_over", False))
            self.hear_bar.stop.connect(self.stop_hearing)
            self.hear_bar.open_window.connect(lambda: (self.win.show_page("talk"), self.open_window()))
            self.hear_bar.target_changed.connect(self._hear_target)
            self.hear_bar.voice_toggled.connect(self._voice_toggled)
            self.hear_bar.moved.connect(lambda d: self.speech_subs.move(self.speech_subs.pos() + d.toPoint()))
            self.hear_bar.mode_changed.connect(lambda m: self._bar_mode("hear_bar", m))
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.speech_subs.place(screen)
        self.hear_bar.tgt.set_code(self.hearing.target, emit=False)
        self.hear_bar.set_source("звук компьютера" if self.hearing.source == "system" else "микрофон")
        self.hear_bar.place_near(self.speech_subs, self.s.get("hear_bar", "full"))
        self._update_bars_action()

    def _hide_speech_subs(self):
        if self.speech_subs:
            self.speech_subs.hide()
            self.hear_bar.hide()

    def _hear_running(self, on: bool):
        self.win.talk.set_running(on)
        self._hear_action.setText("остановить перевод речи" if on else "перевод речи (звук компьютера)")
        if not on:
            self._hide_speech_subs()
        self._update_bars_action()

    def _hear_target(self, code: str):
        self.hearing.target = code
        self.win.talk.tgt.set_code(code, emit=False)

    def _hear_overlay_toggled(self, on: bool):
        self.s["hear_overlay"] = on
        self.s.save()
        if self.hearing.running:
            self._show_speech_subs() if on else self._hide_speech_subs()

    def _voice_toggled(self, on: bool):
        self.s["voice_over"] = on
        self.s.save()
        for w in (self.win.talk.t_voice, self.hear_bar and self.hear_bar.b_voice):
            if w and w.isChecked() != on:
                w.blockSignals(True)
                w.setChecked(on)
                w.blockSignals(False)

    def _hear_level(self, v: float):
        self.win.talk.set_level(v)
        if self.hear_bar and self.hear_bar.isVisible():
            self.hear_bar.set_level(v)

    def _heard(self, p: dict):
        self.win.talk.add_phrase(p)
        if self.speech_subs and self.speech_subs.isVisible():
            self.speech_subs.set_text(p["text"], p["out"], draft=False)
        if p["out"]:
            self.hist.add(p["text"], p["out"], p["src"], p["tgt"])

    def _heard_draft(self, text: str, out: str):
        self.win.talk.set_draft(text, out)
        if self.speech_subs and self.speech_subs.isVisible():
            self.speech_subs.set_text(text, out, draft=True)

    def _reply(self, text: str):
        """Мой ответ: переводим на язык собеседника и говорим вслух."""
        # пишем на своём языке (на который переводим собеседника), переводим — на язык собеседника
        mine = self.hearing.target
        tgt = self.hearing.their or (self.s["fallback"] if mine == self.s["preferred"] else self.s["preferred"])

        def run():
            src = mine
            try:
                res = self.tr.translate(text, "auto", tgt)
                out, src = res["out"], res.get("src", mine)
            except Exception as e:
                out = f"(не переведено: {e})"
            self.bus.replied.emit({"text": text, "out": out, "src": src, "tgt": tgt, "at": time.time()})

        threading.Thread(target=run, daemon=True).start()

    def _replied(self, p: dict):
        self.win.talk.add_phrase(p, mine=True)
        if not p["out"].startswith("(не переведено"):
            self.hearing.say(p["out"], p["tgt"])

    def _download_asr(self, size: str):
        from . import asr

        self.win.talk.refresh_model(busy=size)
        self.win.talk.set_status("скачиваю модель распознавания речи…")

        def run():
            try:
                asr.download(size, progress=lambda d, t: self.bus.asr_progress.emit(d, t))
                self.bus.asr_installed.emit(size, "")
            except Exception as e:
                self.bus.asr_installed.emit(size, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _asr_installed(self, size: str, err: str):
        self.win.talk.refresh_model()
        if err:
            self.win.talk.set_status(err)
            return
        self.s["asr_model"] = size
        self.s.save()
        self.win.talk.set_status("модель скачана — можно слушать")
        self._notify("Модель распознавания речи скачана: перевод речи работает без интернета")

    # --- текст с экрана ---
    def snip(self):
        self.popup.hide()
        QTimer.singleShot(120, self.snipper.start)  # даём всплывашке исчезнуть с экрана

    def _snipped(self, img: QImage, at: QPoint):
        self.popup.show_message("распознаю текст…", at=at + QPoint(0, 10))
        img = img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        w, h = img.width(), img.height()
        # мелкий текст OCR читает лучше, если картинку увеличить
        if max(w, h) < 900:
            k = 2 if max(w, h) * 2 <= 4000 else 1
            img = img.scaled(w * k, h * k)
            w, h = img.width(), img.height()
        data = bytes(img.constBits())[: w * h * 4]

        def run():
            try:
                text, lang = ocr.recognize(data, w, h, self.s["ocr_lang"])
                self.bus.recognized.emit(text, lang, at)
            except ocr.OcrUnavailable as e:
                self.bus.ocr_failed.emit(str(e).lower(), at)
            except Exception as e:
                self.bus.ocr_failed.emit(f"не удалось распознать: {e}", at)

        threading.Thread(target=run, daemon=True).start()

    def _on_recognized(self, text: str, lang: str, at: QPoint):
        if not text.strip():
            self.popup.show_message("на этой области не нашлось текста", at=at)
            return
        self._translate_to_popup(text, join_lines=True, at=at)

    # --- офлайн-модели ---
    def _pairs_for(self, code: str) -> list[tuple[str, str]]:
        """Какие модели нужны, чтобы язык переводился на русский и обратно (через английский)."""
        need = [("ru", "en"), ("en", "ru")]
        c = ARGOS.get(code, code)
        if code != "ru":
            need += [(c, "en"), ("en", c)]
        return need

    def _refresh_models(self):
        eng = self.tr.engine
        for code in LANGS:
            if code == "en" or code not in OFFLINE:
                continue
            missing = [p for p in self._pairs_for(code) if not eng.has_pair(*p)]
            size = sum(models.SIZE_MB.get(a if a != "en" else b, models.DEFAULT_MB) for a, b in missing)
            self.win.set_model_state(code, not missing, size, busy=code in self._downloads)

    def download(self, code: str):
        if code in self._downloads or code not in OFFLINE:
            return
        self._downloads.add(code)
        self.win.show_page("langs")
        self.open_window()
        self.popup.hide_animated()
        self._refresh_models()
        eng = self.tr.engine

        def run():
            try:
                cat = models.catalog()
                for pair in self._pairs_for(code):
                    if eng.has_pair(*pair):
                        continue
                    if pair not in cat:
                        raise RuntimeError(f"в каталоге нет модели {pair[0]}→{pair[1]}")
                    models.install_pair(eng.models_dir, *pair, cat[pair],
                                        progress=lambda d, t: self.bus.progress.emit(code, d, t))
                self.bus.installed.emit(code, "")
            except Exception as e:
                self.bus.installed.emit(code, str(e))

        threading.Thread(target=run, daemon=True).start()

    def _on_installed(self, code: str, err: str):
        self._downloads.discard(code)
        self.tr.engine.unload()
        self._refresh_models()
        if err:
            self.win.model_error(code, err)
        else:
            self._notify(f"{LANGS[code][0]} скачан, работает без интернета")

    def remove_model(self, code: str):
        self.tr.engine.unload()
        c = ARGOS.get(code, code)
        for pair in ((c, "en"), ("en", c)):
            models.remove_pair(self.tr.engine.models_dir, *pair)
        self._refresh_models()

    # --- обновление из архива ---
    # --- новые версии с github ---
    def _auto_check(self):
        if self.s.get("check_updates", True) and time.time() - self.s.get("last_update_check", 0) > 20 * 3600:
            self.check_updates(quiet=True)

    def check_updates(self, quiet: bool):
        if not quiet:
            self.win.set_update_status("проверяю…")

        def run():
            try:
                self.bus.update_info.emit(updater.latest(), "", quiet)
            except Exception as e:
                self.bus.update_info.emit(None, str(e), quiet)

        threading.Thread(target=run, daemon=True).start()

    def _update_info(self, info, err: str, quiet: bool):
        self.s["last_update_check"] = int(time.time())
        self.s.save()
        if err:
            if not quiet:
                self.win.set_update_status(f"не получилось проверить: {err}")
            return
        if not updater.is_newer(info["version"]):
            self.win.set_update_status(f"у вас последняя версия {config.VERSION}")
            if not quiet:
                QMessageBox.information(self.win, "Вавилон", f"У вас последняя версия: {config.VERSION}.")
            return
        if quiet and self.s.get("skip_version") == info["version"]:
            return
        self.win.set_update_status(f"доступна версия {info['version']}")
        notes = info["notes"][:900] + ("…" if len(info["notes"]) > 900 else "")
        box = QMessageBox(self.win)
        box.setWindowTitle("Новая версия Вавилона")
        box.setText(f"Доступна версия {info['version']} (у вас {config.VERSION}).\n"
                    f"Скачать ({info['size'] / 1048576:.0f} МБ) и установить? Языки, словарик и настройки останутся.")
        if notes:
            box.setDetailedText(notes)
        yes = box.addButton("Установить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        skip = box.addButton("Пропустить эту версию", QMessageBox.ButtonRole.DestructiveRole) if quiet else None
        self.open_window()
        box.exec()
        if box.clickedButton() is skip:
            self.s["skip_version"] = info["version"]
            self.s.save()
        elif box.clickedButton() is yes:
            self._download_update(info)

    def _download_update(self, info: dict):
        if not updater.can_update():
            import webbrowser

            webbrowser.open(info["page"])  # запуск из исходников: просто открываем страницу выпуска
            return
        self.win.show_page("settings")
        self.open_window()
        dest = os.path.join(config.data_dir(), "update", info["name"])
        self.win.set_update_status("скачиваю…", 0.0)

        def run():
            try:
                updater.download(info["url"], dest, lambda d, t: self.bus.update_progress.emit(d, t), info["size"])
                self.bus.update_downloaded.emit(dest, "")
            except Exception as e:
                self.bus.update_downloaded.emit("", str(e))

        threading.Thread(target=run, daemon=True).start()

    def _update_downloaded(self, path: str, err: str):
        if err:
            self.win.set_update_status(f"не скачалось: {err}")
            return
        self.win.set_update_status("скачано, ставлю…")
        self.update_from(path, ask=False)

    def update_from(self, path: str, ask: bool = True):
        self.open_window()
        try:
            new_ver, _ = updater.read_zip(path)
        except updater.UpdateError as e:
            QMessageBox.warning(self.win, "Вавилон", f"Не получилось обновить: {e}.")
            return
        if not updater.can_update():
            QMessageBox.information(self.win, "Вавилон", "Обновление из архива работает только в собранной "
                                    "программе Babylon.exe.")
            return
        older = updater.version_tuple(new_ver) <= updater.version_tuple(config.VERSION)
        q = (f"Сейчас стоит версия {config.VERSION}, в архиве — {new_ver}."
             + (" Это не новее текущей, всё равно поставить?" if older else "")
             + "\n\nВавилон закроется на пару секунд и откроется снова. Языки, словарик и настройки останутся.")
        if ask and QMessageBox.question(self.win, "Обновить Вавилон?", q) != QMessageBox.StandardButton.Yes:
            return
        self.win.show_error("распаковываю обновление…")

        def run():
            try:
                new_dir = updater.stage(path)
                self.bus.update_ready.emit(new_dir, "")
            except Exception as e:
                self.bus.update_ready.emit("", str(e))

        threading.Thread(target=run, daemon=True).start()

    def _update_ready(self, new_dir: str, err: str):
        if err:
            QMessageBox.warning(self.win, "Вавилон", f"Не получилось распаковать обновление: {err}")
            return
        updater.launch_swap(new_dir, config.app_dir(), os.getpid(), ["--updated"])
        self.app.quit()

    # --- настройки ---
    def _settings_changed(self, changed: dict):
        self.s.save()
        if "hotkeys" in changed:
            self.keys.start(self.s["hotkeys"])
        if "double_copy" in changed:
            self.keys.set_double_copy(self.s["double_copy"])
        if "mode" in changed:
            self.tr.mode = self.s["mode"]
            self.win.set_online(self.tr.online.available(), self.s["mode"])
        if "opacity" in changed or "font_size" in changed:
            self.popup.apply_style()
            self.win.set_glass()
        if "accent" in changed:
            from .ui import popup as popup_mod, talk as talk_mod

            theme.set_accent(self.s["accent"])
            self.app.setStyleSheet(theme.stylesheet())
            self.popup.setStyleSheet(theme.recolor(popup_mod.QSS))
            self.win.talk.setStyleSheet(theme.recolor(talk_mod.QSS))
            self.win.show_error("цвет сменён · часть значков обновится после перезапуска")
        if self.speech_subs and changed.keys() & {"subs_size", "subs_pos", "subs_opacity", "subs_original"}:
            if self.speech_subs.isVisible():
                self.speech_subs.place(self.speech_subs.screen())
                self.hear_bar.place_near(self.speech_subs, self.hear_bar.mode)
            self.speech_subs.update()
        if "autostart" in changed:
            try:
                config.set_autostart(self.s["autostart"])
            except OSError as e:
                self.win.show_error(f"автозапуск: {e}")


def selftest() -> int:
    """Проверка собранной программы без окон: модули грузятся, OCR, перевод и голос работают."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QPainter

    # результат всегда в файл рядом (у оконной сборки консоли нет или вывод уходит в никуда)
    log = open(os.path.join(os.getcwd(), "babylon-selftest.txt"), "w", encoding="utf-8")

    def print(*a):  # noqa: A001
        line = " ".join(str(x) for x in a) + "\n"
        log.write(line)
        log.flush()
        try:
            if sys.stdout:
                sys.stdout.write(line)
        except (OSError, ValueError):
            pass

    QApplication.instance() or QApplication(sys.argv)
    theme.load_fonts()
    print("version:", config.VERSION, "font:", theme.FAMILY)
    langs = ocr.available_languages()
    print("ocr languages:", langs)
    if langs:
        img = QImage(900, 160, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.white)
        p = QPainter(img)
        p.setPen(Qt.GlobalColor.black)
        f = QFont(theme.FAMILY)
        f.setPixelSize(40)
        p.setFont(f)
        p.drawText(30, 95, "Hello world from Babylon")
        p.end()
        text, lang = ocr.recognize(bytes(img.constBits())[: 900 * 160 * 4], 900, 160)
        print("ocr:", lang, repr(text))
    from .langs import detect

    print("detect:", detect("Привіт, як справи? Що нового?"), detect("Dzień dobry, jak się masz dzisiaj?"))
    tr = Translator(config.models_dir(), "offline")
    for a, b in (("en", "ru"), ("ru", "en")):
        if tr.can_offline(a, b):
            print(f"offline {a}->{b}:", tr.translate("Good morning, my friend." if a == "en" else "Доброе утро, друг.",
                                                     a, b)["out"])
    try:
        on = Translator(config.models_dir(), "online").online.translate("Good morning, my friend.", "en", "ru")
        print("online:", on["engine"], on["out"])
    except Exception as e:
        print("online: недоступно —", e)
    print("voices:", speech.voices())
    try:
        data, ext = speech.synthesize("Hello", "en")
        print("tts:", ext, len(data), "bytes")
    except Exception as e:
        print("tts: нет —", e)
    print("hotkey parse:", winapi.parse_hotkey("Ctrl+Alt+R"), winapi.parse_hotkey("Ctrl+Alt+L"))
    import numpy as np

    from . import lens, video

    try:
        exe = video.ffmpeg_exe()
        import subprocess

        ver = subprocess.run([exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             **video._quiet()).stdout.decode(errors="replace").split("\n")[0]
        print("ffmpeg:", os.path.basename(exe), ver[:40])
    except Exception as e:
        print("ffmpeg: нет —", e)
        return 1
    from . import asr, audio

    print("asr:", asr.features(np.zeros(16000, np.float32)).shape, "models:",
          [sz for sz in asr.SIZES if asr.installed(sz)])
    try:
        import soundcard  # noqa: F401
        import tokenizers  # noqa: F401

        print("audio:", audio.devices())
    except Exception as e:
        print("audio: нет —", e)
        return 1
    try:
        import docx  # noqa: F401
        import pymupdf  # noqa: F401

        print("docs: ok")
    except Exception as e:
        print("docs: нет —", e)
        return 1
    blk = lens.group([ocr.Line("Hello", 10, 10, 80, 20)])
    print("lens:", len(blk), lens.paint(QImage(120, 40, QImage.Format.Format_ARGB32), blk, ["Привет"]).size().toTuple())
    print("selftest ok")
    return 0


def main():
    # обновление первым: после --then идут аргументы для новой версии (там может быть и --selftest)
    if "--update-from" in sys.argv:
        return updater.cli(sys.argv)
    if "--finish-update" in sys.argv:
        return updater.finish(sys.argv)
    if "--selftest" in sys.argv:
        return selftest()
    hidden = "--tray" in sys.argv
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Babylon.Translator")
    app = QApplication(sys.argv)
    app.setApplicationName("Вавилон")
    app.setQuitOnLastWindowClosed(False)

    # уже запущен: просим открыть окно и выходим
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return 0

    theme.load_fonts()
    theme.set_accent(config.Settings().get("accent", theme.DEFAULT_ACCENT))
    app.setFont(theme.font(10))
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    os.makedirs(config.models_dir(), exist_ok=True)
    QTimer.singleShot(8000, updater.cleanup_staging)  # копия после обновления к этому времени уже закрылась
    t = Babylon(app, hidden)
    app._babylon = t  # держим ссылку
    return app.exec()
