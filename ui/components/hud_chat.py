"""ui/components/hud_chat.py — Terminal-style chat panel."""

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                              QPlainTextEdit, QVBoxLayout, QWidget)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from ui.components.hud_panel import HudPanel


class HudChat(HudPanel):
    """Terminal-style chat that mimics a command-line interface."""

    def __init__(self, parent=None):
        super().__init__("COMM CHANNEL", parent)
        self._setup_terminal()
        self._connect_signals()
        self._add_line("JARVIS", "SYSTEM ONLINE. AWAITING INPUT.")

    def _setup_terminal(self):
        layout = self.content_layout()

        # Terminal display
        self._terminal = QPlainTextEdit()
        self._terminal.setObjectName("hud_terminal")
        self._terminal.setReadOnly(True)
        self._terminal.setFont(QFont("Share Tech Mono", 10))
        self._terminal.setStyleSheet(
            "QPlainTextEdit#hud_terminal{"
            "background:#000810;border:none;"
            "color:#00D4FF;font-family:'Share Tech Mono','Courier New',monospace;"
            "font-size:10px;padding:4px;}"
            "QScrollBar:vertical{width:3px;background:#001220;}"
            "QScrollBar::handle:vertical{background:#00D4FF;}"
        )
        layout.addWidget(self._terminal, 1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(4)
        prompt = QLabel(">")
        prompt.setStyleSheet("color:#00FF9F;font-family:'Share Tech Mono';font-size:12px;")
        input_row.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setObjectName("hud_cmd_input")
        self._input.setPlaceholderText("ENTER COMMAND...")
        self._input.setStyleSheet(
            "QLineEdit#hud_cmd_input{"
            "background:#000810;border:none;"
            "border-top:1px solid rgba(0,212,255,0.2);"
            "color:#00FF9F;font-family:'Share Tech Mono';font-size:11px;padding:4px;}"
        )
        self._input.returnPressed.connect(self._send_command)
        input_row.addWidget(self._input, 1)
        layout.addLayout(input_row)

        # Blinking cursor simulation
        self._blink_state = True
        t = QTimer(self)
        t.timeout.connect(self._blink_cursor)
        t.start(500)

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.jarvis_speaking.connect(self._on_jarvis)
            sig.user_spoke.connect(self._on_user)
            sig.status_changed.connect(self._on_status)
        except Exception:
            pass

    def _add_line(self, role: str, text: str, color: str = "#00D4FF"):
        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)
        cursor.insertText(f"\n[{ts}] {role}: {text.upper()}")

        self._terminal.setTextCursor(cursor)
        self._terminal.ensureCursorVisible()

    @pyqtSlot(str)
    def _on_jarvis(self, text: str):
        self._add_line("JARVIS", text, "#00D4FF")

    @pyqtSlot(str)
    def _on_user(self, text: str):
        self._add_line("USER", text, "#00FF9F")

    @pyqtSlot(str)
    def _on_status(self, status: str):
        if status in ("Processing", "Transcribing"):
            self._add_line("SYSTEM", "PROCESSING...", "#FFAA00")

    def _send_command(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._add_line("USER", text, "#00FF9F")
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().user_typed.emit(text)
        except Exception:
            pass

    def _blink_cursor(self):
        self._blink_state = not self._blink_state
        # The placeholder text acts as cursor indicator
        self._input.setPlaceholderText(
            "ENTER COMMAND..._" if self._blink_state else "ENTER COMMAND... "
        )
