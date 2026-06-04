"""ui/components/header.py — Top bar with clock, status, weather, profile."""

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class StatusDot(QLabel):
    """Animated colored dot showing Jarvis state."""
    COLORS = {
        "Listening":    "#4CAF50",
        "Processing":   "#FF9800",
        "Speaking":     "#6C63FF",
        "Recording":    "#FF6B6B",
        "Paused":       "#F44336",
        "Sleeping":     "#444444",
        "Transcribing": "#FF9800",
        "Loading Whisper...": "#FF9800",
    }

    def __init__(self):
        super().__init__("●")
        self.setFont(QFont("Segoe UI", 14))
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink)
        self._visible = True
        self.set_state("Listening")

    def set_state(self, state: str) -> None:
        self._state = state
        color = self.COLORS.get(state, "#888888")
        self.setStyleSheet(f"color: {color}; padding: 0 4px;")
        # Blink when processing or speaking
        if state in ("Processing", "Speaking", "Recording", "Transcribing"):
            self._blink_timer.start(400)
        else:
            self._blink_timer.stop()
            self._visible = True
            self.setVisible(True)

    def _blink(self):
        self._visible = not self._visible
        self.setVisible(self._visible)


class HeaderWidget(QWidget):
    """Top bar: logo | time+date | status | weather | profile | buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(64)
        self._weather_text = ""
        self._current_profile = "study"
        self._setup_ui()
        self._connect_signals()
        self._start_clock()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(24)

        # ── Left: Logo + time ──────────────────────────────────────────────
        logo = QLabel("J")
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "background:#6C63FF; border-radius:18px; color:white; "
            "font-size:18px; font-weight:bold;"
        )
        layout.addWidget(logo)

        time_col = QVBoxLayout()
        time_col.setSpacing(0)
        self._time_lbl = QLabel()
        self._time_lbl.setObjectName("header_time")
        self._date_lbl = QLabel()
        self._date_lbl.setObjectName("header_date")
        time_col.addWidget(self._time_lbl)
        time_col.addWidget(self._date_lbl)
        layout.addLayout(time_col)

        layout.addStretch()

        # ── Center: Status ─────────────────────────────────────────────────
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        self._dot = StatusDot()
        self._status_lbl = QLabel("Listening")
        self._status_lbl.setObjectName("secondary")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._status_lbl)
        layout.addLayout(status_row)

        layout.addStretch()

        # ── Right: Weather | Profile | Settings ────────────────────────────
        self._weather_lbl = QLabel()
        self._weather_lbl.setObjectName("secondary")
        layout.addWidget(self._weather_lbl)

        self._profile_btn = QPushButton("Study")
        self._profile_btn.setObjectName("status_badge")
        self._profile_btn.setFixedHeight(28)
        self._profile_btn.setStyleSheet(
            "QPushButton#status_badge {"
            "background:#1E1A3A; border:1px solid #6C63FF; "
            "border-radius:14px; color:#6C63FF; padding:0 12px; font-size:12px;}"
            "QPushButton#status_badge:hover{background:#6C63FF;color:white;}"
        )
        self._profile_btn.clicked.connect(self._cycle_profile)
        layout.addWidget(self._profile_btn)

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.status_changed.connect(self.set_status)
        except Exception:
            pass

    def _start_clock(self):
        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)
        self._update_clock()

    def _update_clock(self):
        now = datetime.now()
        self._time_lbl.setText(now.strftime("%H:%M:%S"))
        self._date_lbl.setText(now.strftime("%A, %d %B %Y"))

    @pyqtSlot(str)
    def set_status(self, state: str):
        self._dot.set_state(state)
        self._status_lbl.setText(state)

    def set_weather(self, text: str):
        self._weather_lbl.setText(text)

    def _cycle_profile(self):
        profiles = ["study", "work", "chill"]
        idx = profiles.index(self._current_profile) if self._current_profile in profiles else 0
        self._current_profile = profiles[(idx + 1) % len(profiles)]
        self._profile_btn.setText(self._current_profile.title())
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().profile_changed.emit(self._current_profile)
        except Exception:
            pass
