"""
ui/components/floating_panel.py -- Draggable holographic floating panels.

Entry: rises from bottom with opacity fade.
Exit:  shrinks and fades out.
Drag:  click header and drag anywhere.
Max 3 panels open at once.
"""

import sys
from pathlib import Path

from PyQt6.QtCore import (Qt, QTimer, QPoint, QPropertyAnimation,
                           QEasingCurve, QRect, pyqtSignal)
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QCursor
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel,
                              QPushButton, QVBoxLayout, QWidget,
                              QGraphicsOpacityEffect, QScrollArea)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

PURPLE = QColor("#8B2BE2")
PINK   = QColor("#E91E8C")
TEAL   = QColor("#00FFB3")

PANEL_TITLES = {
    "tasks":     "ACTIVE OBJECTIVES",
    "goals":     "MISSION PROGRESS",
    "schedule":  "MISSION SCHEDULE",
    "weather":   "ATMOSPHERIC DATA",
    "fridge":    "SUPPLY STATUS",
    "budget":    "RESOURCE ALLOCATION",
    "stylist":   "RECOMMENDED ATTIRE",
    "wellbeing": "AGENT STATUS",
    "notes":     "INTELLIGENCE FILES",
    "sites":     "NETWORK CONTROL",
    "news":      "INTEL FEED",
    "chat":      "COMM CHANNEL",
    "settings":  "SYSTEM CONFIG",
    "memory":    "MEMORY CORE",
}

# Default positions for up to 3 panels
PANEL_POSITIONS = [
    (0.05, 0.12),   # top-left area
    (0.55, 0.12),   # top-right area
    (0.28, 0.50),   # center-bottom
]


class FloatingPanel(QFrame):
    """
    Draggable holographic floating panel with entry/exit animations.
    """

    closed = pyqtSignal(str)   # emits category when closed

    def __init__(self, category: str, content_widget: QWidget,
                 auto_opened: bool = False, parent=None):
        super().__init__(parent)
        self.category    = category
        self._auto       = auto_opened
        self._dragging   = False
        self._drag_start = QPoint()

        self.setFixedWidth(380)
        self.setMinimumHeight(200)
        self.setMaximumHeight(480)

        self.setStyleSheet("""
            QFrame {
                background: rgba(13, 11, 30, 0.93);
                border: 1px solid rgba(139, 43, 226, 0.45);
                border-radius: 4px;
            }
        """)

        self._setup_ui(content_widget)
        self._setup_opacity()
        self._scan_offset = 0
        self._scan_timer  = QTimer(self)
        self._scan_timer.timeout.connect(self._tick_scan)
        self._scan_timer.start(20)

    def _setup_ui(self, content_widget: QWidget):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header (drag handle) ──────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(36)
        header.setStyleSheet(
            "background:rgba(5,5,16,0.95);"
            "border-bottom:1px solid rgba(139,43,226,0.25);"
        )
        header.setCursor(Qt.CursorShape.SizeAllCursor)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)

        title = PANEL_TITLES.get(self.category, self.category.upper())
        title_lbl = QLabel(f"◄ {title} ►")
        title_lbl.setFont(QFont("Orbitron", 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color:#8B2BE2;letter-spacing:2px;")
        hl.addWidget(title_lbl)

        if self._auto:
            ai_lbl = QLabel(" AI")
            ai_lbl.setStyleSheet("color:#00FFB3;font-size:9px;font-family:Share Tech Mono;")
            hl.addWidget(ai_lbl)

        hl.addStretch()

        max_btn = QPushButton("[MAX]")
        max_btn.setFixedSize(36, 20)
        max_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid rgba(139,43,226,0.3);"
            "color:#3D1F6B;font-size:8px;font-family:Share Tech Mono;}"
            "QPushButton:hover{border-color:#8B2BE2;color:#C77DFF;}"
        )
        max_btn.clicked.connect(self._toggle_maximize)
        hl.addWidget(max_btn)

        close_btn = QPushButton("[X]")
        close_btn.setFixedSize(28, 20)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid rgba(233,30,140,0.3);"
            "color:#3D1F6B;font-size:8px;font-family:Share Tech Mono;}"
            "QPushButton:hover{border-color:#E91E8C;color:#E91E8C;}"
        )
        close_btn.clicked.connect(self.close_animated)
        hl.addWidget(close_btn)

        layout.addWidget(header)
        self._header = header

        # ── Content ───────────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollBar:vertical{width:3px;background:#0D0B1E;}"
            "QScrollBar::handle:vertical{background:#8B2BE2;}"
        )
        scroll.setWidget(content_widget)
        layout.addWidget(scroll, 1)

        # ── Bottom glow line ──────────────────────────────────────────────
        bottom = QWidget()
        bottom.setFixedHeight(2)
        bottom.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 transparent,stop:0.5 #8B2BE2,stop:1 transparent);"
        )
        layout.addWidget(bottom)

    def _setup_opacity(self):
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._anim.setDuration(400)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

        # Slide up animation via geometry
        QTimer.singleShot(0, self._slide_in)

    def _slide_in(self):
        target = self.geometry()
        start  = QRect(target.x(), target.y() + 60,
                       target.width(), target.height())
        self._pos_anim = QPropertyAnimation(self, b"geometry")
        self._pos_anim.setDuration(500)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._pos_anim.setStartValue(start)
        self._pos_anim.setEndValue(target)
        self._pos_anim.start()

    def close_animated(self):
        anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        anim.setDuration(250)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.setStartValue(self._opacity_effect.opacity())
        anim.setEndValue(0.0)
        anim.finished.connect(lambda: (self.closed.emit(self.category), self.hide(), self.deleteLater()))
        anim.start()
        self._close_anim = anim

    def _toggle_maximize(self):
        """Expand to fill parent window."""
        parent = self.parent()
        if not parent:
            return
        if self.width() < 600:
            self._original_geo = self.geometry()
            self.setFixedWidth(parent.width() - 40)
            self.setMaximumHeight(parent.height() - 100)
            self.move(20, 60)
            self.raise_()
        else:
            self.setFixedWidth(380)
            self.setMaximumHeight(480)
            self.setGeometry(self._original_geo)

    # ── Drag ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if self._header.geometry().contains(event.pos()):
            self._dragging   = True
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            new_pos = event.globalPosition().toPoint() - self._drag_start
            # Clamp within parent
            parent = self.parent()
            if parent:
                new_pos.setX(max(0, min(new_pos.x(), parent.width() - self.width())))
                new_pos.setY(max(0, min(new_pos.y(), parent.height() - self.height())))
            self.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        super().mouseReleaseEvent(event)

    # ── Scanning line effect ──────────────────────────────────────────────

    def _tick_scan(self):
        self._scan_offset = (self._scan_offset + 3) % max(1, self.width())
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        # Corner brackets: purple top-left, pink bottom-right
        br = 12
        p.setPen(QPen(PURPLE, 2))
        p.drawLine(0, 0, br, 0)
        p.drawLine(0, 0, 0, br)
        p.drawLine(self.width() - br, 0, self.width() - 1, 0)
        p.drawLine(self.width() - 1, 0, self.width() - 1, br)
        p.setPen(QPen(PINK, 2))
        p.drawLine(0, self.height() - br, 0, self.height() - 1)
        p.drawLine(0, self.height() - 1, br, self.height() - 1)
        p.drawLine(self.width() - br, self.height() - 1, self.width() - 1, self.height() - 1)
        p.drawLine(self.width() - 1, self.height() - br, self.width() - 1, self.height() - 1)
        # Scanning line
        w = 60
        for i in range(w):
            alpha = int(80 * (1 - abs(i - w // 2) / (w // 2)))
            p.setPen(QPen(QColor(139, 43, 226, alpha), 1))
            x = (self._scan_offset - w // 2 + i) % self.width()
            p.drawLine(x, 36, x, 37)
        p.end()
