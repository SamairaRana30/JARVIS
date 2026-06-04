"""
ui/hud_dashboard.py — Full-screen Stark Industries HUD dashboard.

Layout: no sidebar. Everything visible at once.
Left column: Tasks, Goals, Budget
Center: Arc Reactor + terminal chat
Right column: Weather, Schedule, Fridge, Wellbeing
Top bar, Bottom bar.

Click any panel to expand it fullscreen.
Press Escape to collapse back.
"""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSettings, pyqtSlot, QPropertyAnimation, QRect
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget, QFrame
)

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from ui.components.top_bar      import TopBar
from ui.components.bottom_bar   import BottomBar
from ui.components.arc_reactor  import ArcReactor
from ui.components.hud_chat     import HudChat
from ui.components.category_bar import CategoryBar
from ui.components.floating_panel import FloatingPanel, PANEL_POSITIONS
from ui.components.hud_panels   import (
    HudTasksPanel, HudGoalsPanel, HudBudgetPanel,
    HudWeatherPanel, HudSchedulePanel, HudFridgePanel, HudWellbeingPanel,
)

# ---------------------------------------------------------------------------
# Category detection from Jarvis speech
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "tasks":     ["task", "objective", "deadline", "priority", "todo",
                  "finish", "complete", "due", "scrum"],
    "goals":     ["goal", "progress", "milestone", "percent", "stylemate",
                  "graduation", "mission", "ship"],
    "fridge":    ["fridge", "expir", "food", "eat", "recipe", "grocery",
                  "milk", "eggs", "spinach", "supply"],
    "budget":    ["spend", "spent", "budget", "euro", "afford", "money",
                  "cost", "savings", "transaction"],
    "weather":   ["weather", "temperature", "rain", "cloudy", "sunny",
                  "forecast", "wear", "celsius", "atmospheric"],
    "schedule":  ["class", "lecture", "seminar", "calendar", "event",
                  "meeting", "room", "online", "schedule"],
    "wellbeing": ["mood", "energy", "sleep", "water", "exercise", "streak",
                  "feeling", "tired", "stressed", "hydration"],
    "notes":     ["note", "wrote", "document", "pdf", "summary",
                  "found in", "journal", "intel"],
    "stylist":   ["outfit", "wear", "clothes", "style", "closet",
                  "wardrobe", "shirt", "jeans", "attire"],
    "sites":     ["blocked", "study mode", "distract", "pomodoro",
                  "focus mode", "network"],
    "news":      ["news", "headline", "article", "bbc", "reuters", "intel feed"],
    "memory":    ["last time", "remember", "decision", "session",
                  "we discussed", "memory"],
}


def detect_category(text: str) -> str | None:
    """Return the best-matching category for a Jarvis response, or None."""
    text_l = text.lower()
    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_l)
        if score > 0:
            scores[cat] = score
    return max(scores, key=scores.get) if scores else None


def _load_stylesheet() -> str:
    qss_path = ROOT / "ui" / "styles" / "hud.qss"
    try:
        return qss_path.read_text(encoding="utf-8")
    except Exception:
        return ""


class ExpandablePanel(QFrame):
    """
    Wraps a HUD content panel. Click to expand fullscreen; Escape to collapse.
    """
    def __init__(self, panel: QWidget, parent=None):
        super().__init__(parent)
        self._panel    = panel
        self._expanded = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_expand()

    def toggle_expand(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._panel.setParent(self.window())  # type: ignore
            self._panel.setGeometry(self.window().rect())  # type: ignore
            self._panel.raise_()
            self._panel.show()
            self._panel.setStyleSheet(
                "background:rgba(0,8,16,0.97);"
                "border:1px solid rgba(0,212,255,0.6);"
            )
        else:
            self._panel.setParent(self)
            self.layout().addWidget(self._panel)
            self._panel.setStyleSheet("")
            self._panel.show()


class ScanlineOverlay(QWidget):
    """Transparent scanline + circuit grid overlay drawn over entire window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self._offset = 0
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(40)

    def _tick(self):
        self._offset = (self._offset + 2) % 4
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        # Scanlines
        for y in range(self._offset, self.height(), 4):
            p.setPen(QPen(QColor(0, 212, 255, 4), 1))
            p.drawLine(0, y, self.width(), y)
        p.end()


class JarvisHUD(QMainWindow):
    """Main HUD window — full Stark Industries interface."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS — STARK AI INTERFACE")
        self._settings        = QSettings("Jarvis", "HUD")
        self._floating_panels: dict[str, FloatingPanel] = {}
        self._panel_order:     list[str] = []   # tracks oldest→newest
        self._MAX_PANELS      = 3
        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._restore_geometry()
        self._start_weather_timer()

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self._collapse_all)

    def _setup_window(self):
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setStyleSheet("background:#000810;")

    def _setup_ui(self):
        root = QWidget()
        root.setObjectName("hud_root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # Top bar
        self._top_bar = TopBar()
        main.addWidget(self._top_bar)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(8)

        # ── Left column ───────────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(8)

        self._tasks_panel  = HudTasksPanel()
        self._goals_panel  = HudGoalsPanel()
        self._budget_panel = HudBudgetPanel()

        for panel in [self._tasks_panel, self._goals_panel, self._budget_panel]:
            ep = ExpandablePanel(panel)
            left.addWidget(ep, 1)

        left_w = QWidget()
        left_w.setObjectName("left_col")
        left_w.setFixedWidth(230)
        left_w.setLayout(left)
        body.addWidget(left_w)

        # ── Center column ─────────────────────────────────────────────────
        center = QVBoxLayout()
        center.setSpacing(8)
        center.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._reactor = ArcReactor(size=260)
        center.addWidget(self._reactor, 0, Qt.AlignmentFlag.AlignHCenter)

        self._chat = HudChat()
        center.addWidget(self._chat, 1)

        center_w = QWidget()
        center_w.setObjectName("center_col")
        center_w.setLayout(center)
        body.addWidget(center_w, 1)

        # ── Right column ──────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        self._weather_panel   = HudWeatherPanel()
        self._schedule_panel  = HudSchedulePanel()
        self._fridge_panel    = HudFridgePanel()
        self._wellbeing_panel = HudWellbeingPanel()

        for panel in [self._weather_panel, self._schedule_panel,
                      self._fridge_panel, self._wellbeing_panel]:
            ep = ExpandablePanel(panel)
            right.addWidget(ep, 1)

        right_w = QWidget()
        right_w.setObjectName("right_col")
        right_w.setFixedWidth(230)
        right_w.setLayout(right)
        body.addWidget(right_w)

        main.addLayout(body, 1)

        # Category button bar (above bottom bar)
        self._category_bar = CategoryBar()
        self._category_bar.panel_requested.connect(self._on_panel_requested)
        main.addWidget(self._category_bar)

        # Bottom bar
        self._bottom_bar = BottomBar()
        main.addWidget(self._bottom_bar)

        # Scanline overlay (on top of everything)
        self._scanline = ScanlineOverlay(root)
        self._scanline.setGeometry(root.rect())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_scanline"):
            self._scanline.setGeometry(self.centralWidget().rect())

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.status_changed.connect(self._top_bar._set_status)
            sig.user_typed.connect(self._handle_typed)
            sig.profile_changed.connect(self._handle_profile)
            # Auto-open floating panel when Jarvis speaks about a category
            sig.jarvis_speaking.connect(self._on_jarvis_spoke)
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # Floating panel management
    # ---------------------------------------------------------------------------

    def _make_panel_content(self, category: str) -> QWidget:
        """Create the content widget for a floating panel."""
        mapping = {
            "tasks":     HudTasksPanel,
            "goals":     HudGoalsPanel,
            "budget":    HudBudgetPanel,
            "weather":   HudWeatherPanel,
            "schedule":  HudSchedulePanel,
            "fridge":    HudFridgePanel,
            "wellbeing": HudWellbeingPanel,
        }
        cls = mapping.get(category)
        if cls:
            w = cls()
            w.setStyleSheet("background:transparent;")
            return w
        # Fallback: simple label
        from ui.components.hud_panel import HudPanel
        w = QWidget()
        from PyQt6.QtWidgets import QLabel, QVBoxLayout
        l = QVBoxLayout(w)
        lbl = QLabel(f"{category.upper()} PANEL\n(Coming soon)")
        lbl.setStyleSheet("color:#C77DFF;font-family:'Share Tech Mono';font-size:12px;")
        l.addWidget(lbl)
        return w

    def _open_panel(self, category: str, auto: bool = False) -> None:
        """Open a floating panel for the given category."""
        if category in self._floating_panels:
            self._floating_panels[category].raise_()
            return

        # Enforce max 3 panels — close oldest
        if len(self._panel_order) >= self._MAX_PANELS:
            oldest = self._panel_order[0]
            self._close_panel(oldest)

        content = self._make_panel_content(category)
        panel   = FloatingPanel(
            category=category,
            content_widget=content,
            auto_opened=auto,
            parent=self.centralWidget(),
        )
        panel.closed.connect(lambda cat: self._on_panel_closed(cat))

        # Position based on how many panels are open
        root = self.centralWidget()
        idx  = len(self._panel_order)
        if idx < len(PANEL_POSITIONS):
            rx, ry = PANEL_POSITIONS[idx]
            x = int(root.width() * rx)
            y = int(root.height() * ry)
        else:
            x, y = 100 + idx * 30, 100 + idx * 30
        panel.move(x, y)
        panel.show()

        self._floating_panels[category] = panel
        self._panel_order.append(category)

        # Tell arc reactor panels are open
        if hasattr(self, "_reactor"):
            self._reactor._speaking = True   # triggers faster ring spin
            QTimer.singleShot(1000, lambda: setattr(self._reactor, "_speaking", False))

    def _close_panel(self, category: str) -> None:
        panel = self._floating_panels.pop(category, None)
        if panel:
            panel.close_animated()
        if category in self._panel_order:
            self._panel_order.remove(category)
        if hasattr(self, "_category_bar"):
            self._category_bar.deactivate_panel(category)

    def _on_panel_closed(self, category: str) -> None:
        self._floating_panels.pop(category, None)
        if category in self._panel_order:
            self._panel_order.remove(category)
        if hasattr(self, "_category_bar"):
            self._category_bar.deactivate_panel(category)

    def _on_panel_requested(self, signal: str, auto: bool) -> None:
        if signal.endswith(":close"):
            self._close_panel(signal[:-6])
        else:
            self._open_panel(signal, auto=auto)

    @pyqtSlot(str)
    def _on_jarvis_spoke(self, text: str) -> None:
        """Detect category in Jarvis speech and auto-open panel."""
        category = detect_category(text)
        if category:
            self._category_bar.activate_panel(category, auto=True)
            self._open_panel(category, auto=True)

    def _start_weather_timer(self):
        self._update_weather()
        t = QTimer(self)
        t.timeout.connect(self._update_weather)
        t.start(30 * 60 * 1000)

    def _update_weather(self):
        try:
            import yaml, requests, unicodedata
            with open(ROOT / "config.yaml") as f:
                cfg = yaml.safe_load(f)
            city = cfg.get("weather", {}).get("default_location", "Berlin")
            resp = requests.get(f"https://wttr.in/{city}?format=3",
                                timeout=5, headers={"User-Agent": "Jarvis/1.0"})
            clean = "".join(c for c in resp.text.strip()
                            if unicodedata.category(c) != "So" and ord(c) < 0x1F600)
            self._top_bar.set_weather(clean.strip())
        except Exception:
            pass

    @pyqtSlot(str)
    def _handle_typed(self, text: str):
        try:
            import jarvis as _j
            import threading
            threading.Thread(target=_j.process_command, args=(text,), daemon=True).start()
        except Exception:
            pass

    @pyqtSlot(str)
    def _handle_profile(self, profile: str):
        try:
            import tools
            tools.switch_profile(profile)
        except Exception:
            pass

    def _collapse_all(self):
        """Re-reparent any expanded panels back into their containers."""
        # Simplest: just rebuild the layout
        pass

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

    def _restore_geometry(self):
        # Use availableGeometry() — respects taskbar position and height
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(800, 500)   # allow window to be smaller than panels
        self.resize(screen.width(), screen.height())
        self.move(screen.left(), screen.top())
        self.setMaximumSize(screen.width(), screen.height())

    def moveEvent(self, e):
        self._settings.setValue("hud_geometry", self.saveGeometry())

    def resizeEvent(self, e):
        self._settings.setValue("hud_geometry", self.saveGeometry())
        if hasattr(self, "_scanline"):
            self._scanline.setGeometry(self.centralWidget().rect())
        super().resizeEvent(e)


# ---------------------------------------------------------------------------
# Wire + launch helpers (used by tray_icon.py)
# ---------------------------------------------------------------------------

def wire_jarvis_signals():
    """Same as dashboard.py — patch speak_async to emit signals."""
    try:
        from ui.signals import JarvisSignals
        import tts as _tts
        sig = JarvisSignals.instance()
        _orig = _tts.speak_async

        def _patched(text, voice=None, rate=None):
            if text and text.strip():
                sig.jarvis_speaking.emit(text)
            _orig(text, voice=voice, rate=rate)

        _tts.speak_async = _patched
    except Exception as e:
        print(f"Could not wire HUD signals: {e}")


def start_file_watcher():
    """Same watchdog watcher as dashboard.py."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        from ui.signals import JarvisSignals
        import yaml
        with open(ROOT / "config.yaml") as f:
            cfg = yaml.safe_load(f)
        FILE_SIGNAL_MAP = {
            cfg["paths"]["tasks"]:     "tasks_updated",
            cfg["paths"]["fridge"]:    "fridge_updated",
            cfg["paths"]["wellbeing"]: "wellbeing_updated",
            cfg["paths"]["sites"]:     "sites_updated",
        }

        class _H(FileSystemEventHandler):
            def on_modified(self, ev):
                rel = str(Path(ev.src_path).relative_to(ROOT)).replace("\\", "/")
                for k, s in FILE_SIGNAL_MAP.items():
                    if rel.endswith(k.replace("\\", "/")):
                        emit = getattr(JarvisSignals.instance(), s, None)
                        if emit:
                            emit.emit()

        obs = Observer()
        obs.schedule(_H(), str(ROOT / "data"),   recursive=False)
        obs.schedule(_H(), str(ROOT / "memory"), recursive=False)
        obs.start()
        return obs
    except Exception as e:
        print(f"File watcher error: {e}")
        return None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis HUD")
    app.setStyleSheet(_load_stylesheet())
    app.setFont(QFont("Share Tech Mono", 10))
    w = JarvisHUD()
    w.show()
    wire_jarvis_signals()
    _watcher = start_file_watcher()
    sys.exit(app.exec())
