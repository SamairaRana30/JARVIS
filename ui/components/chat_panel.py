"""ui/components/chat_panel.py — Conversation UI like a messaging app."""

import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QKeySequence
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class MessageBubble(QFrame):
    """A single chat message bubble."""

    def __init__(self, text: str, role: str, timestamp: str = ""):
        super().__init__()
        is_user = role == "user"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)

        bubble = QFrame()
        bubble.setMaximumWidth(520)
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(2)

        msg = QLabel(text)
        msg.setWordWrap(True)
        msg.setFont(QFont("Segoe UI", 13))

        ts_lbl = QLabel(timestamp)
        ts_lbl.setObjectName("muted")
        ts_lbl.setFont(QFont("Segoe UI", 9))

        bl.addWidget(msg)
        bl.addWidget(ts_lbl)

        if is_user:
            bubble.setObjectName("user_bubble")
            bubble.setStyleSheet(
                "QFrame#user_bubble{background:#6C63FF;border-radius:16px 16px 4px 16px;}"
                "QLabel{color:white;}"
            )
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            avatar = QLabel("J")
            avatar.setFixedSize(32, 32)
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setStyleSheet(
                "background:#1E1A3A;border-radius:16px;color:#6C63FF;"
                "font-weight:bold;font-size:14px;"
            )
            bubble.setObjectName("jarvis_bubble")
            bubble.setStyleSheet(
                "QFrame#jarvis_bubble{background:#1A1A1A;border:1px solid #2A2A2A;"
                "border-radius:4px 16px 16px 16px;}"
                "QLabel{color:#FFFFFF;}"
            )
            layout.addWidget(avatar)
            layout.addWidget(bubble)
            layout.addStretch()


class TypingIndicator(QWidget):
    """Animated "..." indicator while Jarvis processes."""

    def __init__(self):
        super().__init__()
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(48, 4, 0, 4)

        frame = QFrame()
        frame.setStyleSheet(
            "background:#1A1A1A;border:1px solid #2A2A2A;"
            "border-radius:4px 16px 16px 16px;padding:12px 16px;"
        )
        fl = QHBoxLayout(frame)
        fl.setSpacing(4)
        self._dots = []
        for _ in range(3):
            d = QLabel("●")
            d.setStyleSheet("color:#6C63FF;font-size:10px;")
            fl.addWidget(d)
            self._dots.append(d)
        layout.addWidget(frame)
        layout.addStretch()

        self._anim_idx = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(300)

    def _animate(self):
        for i, d in enumerate(self._dots):
            d.setStyleSheet(
                f"color:{'#6C63FF' if i == self._anim_idx else '#2A2A2A'};font-size:10px;"
            )
        self._anim_idx = (self._anim_idx + 1) % 3


class ChatPanel(QWidget):
    """Full conversation panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(56)
        tb_lay = QHBoxLayout(title_bar)
        tb_lay.setContentsMargins(20, 0, 20, 0)
        title = QLabel("💬  Conversation")
        title.setObjectName("panel_title")
        tb_lay.addWidget(title)
        tb_lay.addStretch()
        clear_btn = QPushButton("Clear session")
        clear_btn.clicked.connect(self._clear_session)
        tb_lay.addWidget(clear_btn)
        layout.addWidget(title_bar)

        # Messages area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._msg_container = QWidget()
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(16, 8, 16, 8)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()
        scroll.setWidget(self._msg_container)
        self._scroll = scroll
        layout.addWidget(scroll, 1)

        # Typing indicator
        self._typing = TypingIndicator()
        layout.addWidget(self._typing)

        # Input bar
        input_bar = QFrame()
        input_bar.setFixedHeight(64)
        input_bar.setStyleSheet("background:#111111;border-top:1px solid #2A2A2A;")
        ib_lay = QHBoxLayout(input_bar)
        ib_lay.setContentsMargins(16, 12, 16, 12)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message or press Ctrl+Shift+J to speak...")
        self._input.returnPressed.connect(self._send_typed)
        ib_lay.addWidget(self._input, 1)

        send_btn = QPushButton("Send")
        send_btn.setObjectName("accent_btn")
        send_btn.clicked.connect(self._send_typed)
        ib_lay.addWidget(send_btn)
        layout.addWidget(input_bar)

        # Load today's transcript
        QTimer.singleShot(500, self._load_transcript)

    def _connect_signals(self):
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.jarvis_speaking.connect(self._on_jarvis_spoke)
            sig.user_spoke.connect(self._on_user_spoke)
            sig.status_changed.connect(self._on_status)
        except Exception:
            pass

    def _load_transcript(self):
        """Load today's conversation from logs/conversations/."""
        try:
            import yaml
            cfg_path = ROOT / "config.yaml"
            with open(cfg_path) as f:
                import yaml
                cfg = yaml.safe_load(f)
            convo_dir = ROOT / cfg["paths"]["convos"]
            today = datetime.now().strftime("%Y-%m-%d")
            md_file = convo_dir / f"{today}.md"
            if not md_file.exists():
                self._add_system("No conversation today yet. Say 'Jarvis' to start.")
                return
            import re
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r"\[(\d\d:\d\d:\d\d)\]\s+(YOU|JARVIS):\s+(.+)", text):
                ts, role, msg = match.groups()
                self.add_message(msg, "user" if role == "YOU" else "jarvis", ts)
        except Exception:
            self._add_system("Could not load conversation history.")

    def _add_system(self, text: str):
        lbl = QLabel(text)
        lbl.setObjectName("muted")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, lbl)

    def add_message(self, text: str, role: str, timestamp: str = ""):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M")
        bubble = MessageBubble(text, role, timestamp)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    @pyqtSlot(str)
    def _on_jarvis_spoke(self, text: str):
        self._typing.setVisible(False)
        self.add_message(text, "jarvis")

    @pyqtSlot(str)
    def _on_user_spoke(self, text: str):
        self.add_message(text, "user")

    @pyqtSlot(str)
    def _on_status(self, state: str):
        self._typing.setVisible(state in ("Processing", "Transcribing"))

    def _send_typed(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.add_message(text, "user")
        self._typing.setVisible(True)
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().user_typed.emit(text)
        except Exception:
            pass

    def _clear_session(self):
        try:
            import jarvis as _j
            _j.start_new_session()
        except Exception:
            pass
        # Remove all message widgets except the stretch
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._add_system("Session cleared. Starting fresh.")
