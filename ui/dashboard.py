"""
ui/dashboard.py — Main Jarvis dashboard window.

Startup: python ui/dashboard.py  (standalone)
Or wired into tray_icon.py which launches it in the main thread.

PyQt6 must run on the main thread. Voice engine threads communicate
via JarvisSignals (queued connections, thread-safe).
"""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSlot, QSettings
from PyQt6.QtGui import QIcon, QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout,
    QMainWindow, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from ui.components.sidebar    import SidebarWidget
from ui.components.header     import HeaderWidget
from ui.components.home_panel import HomePanel
from ui.components.chat_panel import ChatPanel
from ui.components.tasks_panel    import TasksPanel
from ui.components.notes_panel    import NotesPanel
from ui.components.fridge_panel   import FridgePanel
from ui.components.wellbeing_panel import WellbeingPanel
from ui.components.stylist_panel  import StylistPanel
from ui.components.budget_panel   import BudgetPanel
from ui.components.sites_panel    import SitesPanel
from ui.components.schedule_panel import SchedulePanel
from ui.components.settings_panel import SettingsPanel


def _load_stylesheet() -> str:
    qss_path = ROOT / "ui" / "styles" / "dark.qss"
    try:
        return qss_path.read_text(encoding="utf-8")
    except Exception:
        return ""


class JarvisDashboard(QMainWindow):
    """Main dashboard window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Jarvis")
        self.setMinimumSize(900, 600)
        self._settings = QSettings("Jarvis", "Dashboard")
        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._restore_geometry()
        self._start_weather_timer()

    # ── Setup ──────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(Qt.WindowType.Window)
        # Closing minimizes to tray rather than quitting
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        self._header = HeaderWidget()
        main_layout.addWidget(self._header)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#2A2A2A;")
        main_layout.addWidget(sep)

        # Body: sidebar + content
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = SidebarWidget()
        self._sidebar.page_changed.connect(self._switch_panel)
        body.addWidget(self._sidebar)

        # Content area
        self._stack = QStackedWidget()
        self._panels: dict[str, QWidget] = {}

        def _add(key: str, widget: QWidget):
            self._panels[key] = widget
            self._stack.addWidget(widget)

        self._home_panel = HomePanel()
        self._home_panel.nav_requested.connect(self._sidebar.select)
        _add("home",      self._home_panel)
        _add("chat",      ChatPanel())
        _add("tasks",     TasksPanel())
        _add("notes",     NotesPanel())
        _add("fridge",    FridgePanel())
        _add("wellbeing", WellbeingPanel())
        _add("stylist",   StylistPanel())
        _add("budget",    BudgetPanel())
        _add("sites",     SitesPanel())
        _add("schedule",  SchedulePanel())
        _add("settings",  SettingsPanel())

        body.addWidget(self._stack, 1)
        main_layout.addLayout(body, 1)

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.status_changed.connect(self._header.set_status)
            # User typed in chat → process as Jarvis command
            sig.user_typed.connect(self._handle_typed_command)
            sig.profile_changed.connect(self._handle_profile_change)
        except Exception:
            pass

    def _start_weather_timer(self):
        self._update_weather()
        timer = QTimer(self)
        timer.timeout.connect(self._update_weather)
        timer.start(30 * 60 * 1000)   # every 30 min

    # ── Panel switching ────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _switch_panel(self, key: str):
        panel = self._panels.get(key)
        if panel:
            self._stack.setCurrentWidget(panel)

    # ── Close → minimize to tray ───────────────────────────────────────────

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ── Geometry persistence ───────────────────────────────────────────────

    def _restore_geometry(self):
        geom = self._settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.resize(1200, 800)
            screen = QApplication.primaryScreen().geometry()
            self.move(
                (screen.width()  - 1200) // 2,
                (screen.height() - 800)  // 2,
            )

    def _save_geometry(self):
        self._settings.setValue("geometry", self.saveGeometry())

    def moveEvent(self, e):
        self._save_geometry()
        super().moveEvent(e)

    def resizeEvent(self, e):
        self._save_geometry()
        super().resizeEvent(e)

    # ── Weather ───────────────────────────────────────────────────────────

    def _update_weather(self):
        try:
            import yaml
            with open(ROOT / "config.yaml") as f:
                cfg = yaml.safe_load(f)
            city = cfg.get("weather", {}).get("default_location", "Berlin")
            import requests
            resp = requests.get(
                f"https://wttr.in/{city}?format=3",
                timeout=5, headers={"User-Agent": "Jarvis/1.0"}
            )
            text = resp.text.strip()
            # Strip emoji for cleaner display
            import re, unicodedata
            clean = "".join(c for c in text
                            if unicodedata.category(c) not in ("So",) and ord(c) < 0x1F600)
            self._header.set_weather(clean.strip())
        except Exception:
            pass

    # ── Voice integration ─────────────────────────────────────────────────

    @pyqtSlot(str)
    def _handle_typed_command(self, text: str):
        """Process a message typed in the chat panel as a Jarvis command."""
        try:
            import jarvis
            import threading
            threading.Thread(
                target=jarvis.process_command,
                args=(text,),
                daemon=True
            ).start()
        except Exception:
            pass

    @pyqtSlot(str)
    def _handle_profile_change(self, profile: str):
        try:
            import tools
            tools.switch_profile(profile)
        except Exception:
            pass


# ── Wire signals from jarvis.py ────────────────────────────────────────────

def wire_jarvis_signals():
    """
    Call once after jarvis.py is imported.
    Patches jarvis.speak_async and status updates to emit PyQt signals.
    """
    try:
        from ui.signals import JarvisSignals
        import tts as _tts

        sig = JarvisSignals.instance()

        # Patch speak_async so every utterance emits jarvis_speaking
        _orig_speak_async = _tts.speak_async

        def _patched_speak_async(text, voice=None, rate=None):
            if text and text.strip():
                sig.jarvis_speaking.emit(text)
            _orig_speak_async(text, voice=voice, rate=rate)

        _tts.speak_async = _patched_speak_async

        # Patch jarvis._set_status (called from tray and wake word thread)
        try:
            import jarvis as _j
            _orig_set = _j._sleep_status_callback

            def _status_callback(state: str):
                sig.status_changed.emit(state)
                if callable(_orig_set):
                    _orig_set(state)

            _j.set_sleep_status_callback(_status_callback)
        except Exception:
            pass

    except Exception as e:
        print(f"Could not wire Jarvis signals: {e}")


# ── Watchdog file watcher ──────────────────────────────────────────────────

def start_file_watcher():
    """Watch data files for changes and emit refresh signals."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        from ui.signals import JarvisSignals
        import yaml

        with open(ROOT / "config.yaml") as f:
            cfg = yaml.safe_load(f)

        FILE_SIGNAL_MAP = {
            cfg["paths"]["tasks"]:      "tasks_updated",
            cfg["paths"]["fridge"]:     "fridge_updated",
            cfg["paths"]["notes_index"]:"notes_updated",
            cfg["paths"]["progress"]:   "goals_updated",
            cfg["paths"]["wellbeing"]:  "wellbeing_updated",
            cfg["paths"]["sites"]:      "sites_updated",
            cfg["paths"]["reminders"]:  "reminders_updated",
            cfg["paths"].get("closet", "data/closet.json"):  "fridge_updated",  # reuse signal
        }

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event):
                rel = str(Path(event.src_path).relative_to(ROOT)).replace("\\", "/")
                for file_rel, signal_name in FILE_SIGNAL_MAP.items():
                    if rel.endswith(file_rel.replace("\\", "/")):
                        sig = JarvisSignals.instance()
                        emit_fn = getattr(sig, signal_name, None)
                        if emit_fn:
                            emit_fn.emit()
                        break

        observer = Observer()
        observer.schedule(_Handler(), str(ROOT / "data"),   recursive=False)
        observer.schedule(_Handler(), str(ROOT / "memory"), recursive=False)
        observer.start()
        return observer
    except Exception as e:
        print(f"File watcher could not start: {e}")
        return None


# ── Standalone entry point ─────────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    app.setStyleSheet(_load_stylesheet())
    app.setFont(QFont("Segoe UI", 11))

    window = JarvisDashboard()
    window.show()

    wire_jarvis_signals()
    _watcher = start_file_watcher()

    sys.exit(app.exec())
