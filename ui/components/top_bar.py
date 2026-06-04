"""ui/components/top_bar.py -- HUD top bar: logo, clock, status, voice toggle, weather."""

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# Purple/pink palette
PURPLE = "#8B2BE2"
PINK   = "#E91E8C"
TEAL   = "#00FFB3"
LAVENDER = "#C77DFF"


class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("top_bar")
        self.setFixedHeight(52)
        self._status       = "SYSTEM ONLINE"
        self._voice_on     = True
        self._lecture_mode = False
        self._setup_ui()
        self._connect_signals()
        t = QTimer(self)
        t.timeout.connect(self._update_clock)
        t.start(1000)
        self._update_clock()

    def _setup_ui(self):
        main = QHBoxLayout(self)
        main.setContentsMargins(16, 0, 16, 0)
        main.setSpacing(0)

        # Left: Logo
        logo_lbl = QLabel("◄ JARVIS AI ►")
        logo_lbl.setFont(QFont("Orbitron", 13, QFont.Weight.Bold))
        logo_lbl.setStyleSheet(
            f"color:{LAVENDER};"
            "font-family:'Orbitron','Arial Black',sans-serif;"
            "letter-spacing:4px;"
        )
        main.addWidget(logo_lbl)

        ver = QLabel("  v0.1.0")
        ver.setStyleSheet("color:#3D1F6B;font-size:10px;letter-spacing:1px;")
        main.addWidget(ver)
        main.addStretch()

        # Center: Status + clock
        center = QHBoxLayout()
        center.setSpacing(16)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color:{TEAL};font-size:14px;")
        center.addWidget(self._status_dot)

        self._status_lbl = QLabel("SYSTEM ONLINE")
        self._status_lbl.setStyleSheet(
            f"color:{TEAL};font-family:'Share Tech Mono',monospace;"
            "font-size:11px;letter-spacing:2px;"
        )
        center.addWidget(self._status_lbl)

        sep = QLabel("  ····  ")
        sep.setStyleSheet("color:#3D1F6B;")
        center.addWidget(sep)

        self._date_lbl = QLabel()
        self._date_lbl.setStyleSheet(f"color:{LAVENDER};font-size:10px;letter-spacing:1px;opacity:0.6;")
        center.addWidget(self._date_lbl)

        self._time_lbl = QLabel()
        self._time_lbl.setFont(QFont("Share Tech Mono", 14))
        self._time_lbl.setStyleSheet(f"color:{LAVENDER};letter-spacing:2px;")
        center.addWidget(self._time_lbl)

        main.addLayout(center)
        main.addStretch()

        # Right: Weather | Voice toggle | Profile
        self._weather_lbl = QLabel()
        self._weather_lbl.setStyleSheet(f"color:{LAVENDER};font-size:10px;letter-spacing:1px;opacity:0.7;")
        main.addWidget(self._weather_lbl)
        main.addSpacing(12)

        # Voice toggle button
        self._voice_btn = QPushButton("[MIC] VOICE ON")
        self._voice_btn.setFixedHeight(28)
        self._voice_btn.clicked.connect(self._toggle_voice)
        self._update_voice_btn()
        main.addWidget(self._voice_btn)
        main.addSpacing(8)

        self._profile_btn = QPushButton("[ STUDY ]")
        self._profile_btn.setFixedHeight(28)
        self._profile_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:1px solid rgba(139,43,226,0.35);"
            f"color:{LAVENDER};font-family:'Share Tech Mono';font-size:10px;letter-spacing:2px;"
            f"padding:0 10px;}}"
            f"QPushButton:hover{{border-color:{PURPLE};background:rgba(139,43,226,0.1);}}"
        )
        self._profile_btn.clicked.connect(self._cycle_profile)
        main.addWidget(self._profile_btn)

    def _update_voice_btn(self):
        if self._lecture_mode:
            label  = "[BOOK] LECTURE"
            border = "#FF6B6B"
            bg     = "rgba(255,50,50,0.15)"
            color  = "#FF6B6B"
        elif self._voice_on:
            label  = "[MIC] VOICE ON"
            border = TEAL
            bg     = "rgba(0,255,179,0.1)"
            color  = TEAL
        else:
            label  = "[MUTE] SILENT"
            border = "#FF9800"
            bg     = "rgba(255,152,0,0.1)"
            color  = "#FF9800"
        self._voice_btn.setText(label)
        self._voice_btn.setStyleSheet(
            f"QPushButton{{background:{bg};border:1px solid {border};"
            f"color:{color};font-family:'Share Tech Mono';font-size:10px;"
            f"letter-spacing:1px;padding:0 10px;}}"
            f"QPushButton:hover{{background:rgba(139,43,226,0.15);}}"
        )

    def _toggle_voice(self):
        try:
            from tts import set_voice_output, is_voice_on
            current = is_voice_on()
            set_voice_output(not current)
            self._voice_on = not current
            self._lecture_mode = False
            self._update_voice_btn()
        except Exception:
            pass

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().status_changed.connect(self._set_status)
        except Exception:
            pass

    def _update_clock(self):
        now = datetime.now()
        self._time_lbl.setText(now.strftime("%H:%M:%S"))
        self._date_lbl.setText(now.strftime("%A %d.%m.%Y").upper())

    @pyqtSlot(str)
    def _set_status(self, status: str):
        self._status = status.upper()
        self._status_lbl.setText(self._status)

        # Special: lecture mode
        if self._status == "LECTURE":
            self._lecture_mode = True
            self._voice_on     = False
            self._update_voice_btn()

        colors = {
            "LISTENING":   TEAL,
            "PROCESSING":  PURPLE,
            "SPEAKING":    PINK,
            "PAUSED":      "#FF6B35",
            "SLEEPING":    "#2A1450",
            "MEETING":     PINK,
            "LECTURE":     "#FF6B6B",
            "ERROR":       "#FF2D55",
        }
        color = colors.get(self._status, TEAL)
        self._status_dot.setStyleSheet(f"color:{color};font-size:14px;")
        self._status_lbl.setStyleSheet(
            f"color:{color};font-family:'Share Tech Mono',monospace;"
            "font-size:11px;letter-spacing:2px;"
        )

    def set_weather(self, text: str):
        self._weather_lbl.setText(text.upper() + "   ")

    def _cycle_profile(self):
        profiles = ["[ STUDY ]", "[ WORK ]", "[ CHILL ]"]
        cur = self._profile_btn.text()
        idx = profiles.index(cur) if cur in profiles else 0
        self._profile_btn.setText(profiles[(idx + 1) % len(profiles)])
        try:
            from ui.signals import JarvisSignals
            p = profiles[(idx + 1) % len(profiles)].strip("[] ").lower()
            JarvisSignals.instance().profile_changed.emit(p)
        except Exception:
            pass
