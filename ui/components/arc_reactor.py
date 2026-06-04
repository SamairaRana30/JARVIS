"""
ui/components/arc_reactor.py -- J.A.R.V.I.S arc reactor.

Dark mechanical outer rings, blue dot matrix, rotating blue segments,
orange accent arc, teal glowing core with J.A.R.V.I.S text.
Color palette: purple (#8B2BE2) + pink (#E91E8C) + teal (#00FFB3).
"""

import math
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import (QColor, QConicalGradient, QPainter, QPainterPath,
                          QPen, QRadialGradient, QFont, QBrush)
from PyQt6.QtWidgets import QWidget, QSizePolicy

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# Status colors
STATUS_COLORS = {
    "Listening":    QColor("#00FFB3"),    # teal
    "Processing":   QColor("#8B2BE2"),    # purple
    "Speaking":     QColor("#E91E8C"),    # pink
    "Recording":    QColor("#00FFB3"),
    "Paused":       QColor("#2A1450"),
    "Sleeping":     QColor("#0D0B1E"),
    "MEETING":      QColor("#E91E8C"),    # pink pulse
    "Error":        QColor("#FF2D55"),
    "Transcribing": QColor("#FF9800"),
    "Loading Whisper...": QColor("#FF9800"),
}

PURPLE   = QColor("#8B2BE2")
PINK     = QColor("#E91E8C")
TEAL     = QColor("#00FFB3")
CYAN     = QColor("#00AAFF")
DIM_BLUE = QColor("#003366")
DARK     = QColor("#050510")
SURFACE  = QColor("#0D0B1E")
MECH     = QColor("#1a1a2e")    # dark mechanical grey-blue


class ArcReactor(QWidget):
    """
    J.A.R.V.I.S arc reactor -- dark mechanical rings + teal core.
    Ring 1: Outer tick marks (dark mechanical)
    Ring 2: Blue dot matrix
    Ring 3: Mechanical segment arcs
    Ring 4: Rotating blue segments
    Ring 5: Counter-rotating dots
    Ring 6: Orange/pink accent arc
    Core:   Teal radial glow + J.A.R.V.I.S text
    """

    def __init__(self, parent=None, size: int = 280):
        super().__init__(parent)
        self._sz = size
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._status       = "Listening"
        self._ring4_angle  = 0.0    # rotating blue segments CW
        self._ring5_angle  = 0.0    # counter-rotating dots CCW
        self._ring6_angle  = 0.0    # accent arc CW (faster)
        self._pulse_alpha  = 255
        self._pulse_dir    = -3
        self._wave_bars: list[float] = [0.0] * 24
        self._speaking     = False
        self._wave_phase   = 0.0
        self._dot_blink    = [True] * 60   # dot matrix blink state

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)   # ~60 fps

        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().status_changed.connect(self.set_status)
            JarvisSignals.instance().jarvis_speaking.connect(self._on_speaking)
        except Exception:
            pass

    @pyqtSlot(str)
    def set_status(self, status: str) -> None:
        self._status   = status
        self._speaking = status == "Speaking"

    @pyqtSlot(str)
    def _on_speaking(self, _text: str) -> None:
        self._speaking = True
        QTimer.singleShot(3000, lambda: setattr(self, "_speaking", False))

    def _tick(self):
        speed = 2.5 if self._status == "Processing" else 1.0

        self._ring4_angle = (self._ring4_angle + 0.6 * speed) % 360
        self._ring5_angle = (self._ring5_angle - 0.4 * speed) % 360
        self._ring6_angle = (self._ring6_angle + 1.2 * speed) % 360

        self._pulse_alpha = max(60, min(255, self._pulse_alpha + self._pulse_dir * 3))
        if self._pulse_alpha <= 60 or self._pulse_alpha >= 255:
            self._pulse_dir *= -1

        # Dot matrix blink
        import random
        for i in range(len(self._dot_blink)):
            if random.random() < 0.01:
                self._dot_blink[i] = not self._dot_blink[i]

        # Voice waveform
        self._wave_phase += 0.15
        if self._speaking:
            for i in range(len(self._wave_bars)):
                angle = (i / len(self._wave_bars)) * math.tau
                self._wave_bars[i] = 0.3 + 0.7 * abs(
                    math.sin(self._wave_phase + angle * 1.5))
        else:
            for i in range(len(self._wave_bars)):
                self._wave_bars[i] = max(0.0, self._wave_bars[i] - 0.06)

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = cy = self._sz / 2

        # ── Background circle ─────────────────────────────────────────────────
        p.setBrush(QBrush(DARK))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(cx - cx + 2), int(cy - cy + 2),
                      int(self._sz - 4), int(self._sz - 4))

        # ── Voice waveform ────────────────────────────────────────────────────
        if self._speaking:
            bar_inner = cx * 0.83
            bar_outer = cx * 0.95
            for i, amp in enumerate(self._wave_bars):
                angle = (i / len(self._wave_bars)) * math.tau - math.pi / 2
                ri = bar_inner
                ro = bar_inner + (bar_outer - bar_inner) * amp
                x1 = cx + ri * math.cos(angle)
                y1 = cy + ri * math.sin(angle)
                x2 = cx + ro * math.cos(angle)
                y2 = cy + ro * math.sin(angle)
                alpha = int(160 * amp)
                col = QColor(233, 30, 140, alpha)   # pink waveform
                p.setPen(QPen(col, 2.0))
                p.drawLine(int(x1), int(y1), int(x2), int(y2))

        # ── Ring 1: Outer dark mechanical ring + tick marks ───────────────────
        r1 = cx * 0.92
        p.setPen(QPen(MECH, 6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(cx - r1), int(cy - r1), int(r1 * 2), int(r1 * 2))

        n_ticks = 120
        for i in range(n_ticks):
            angle   = (i / n_ticks) * math.tau
            major   = i % 10 == 0
            r_inner = r1 - (7 if major else 4)
            r_outer = r1 + 2
            x1 = cx + r_inner * math.cos(angle)
            y1 = cy + r_inner * math.sin(angle)
            x2 = cx + r_outer * math.cos(angle)
            y2 = cy + r_outer * math.sin(angle)
            col = QColor("#4444AA") if major else QColor("#222244")
            p.setPen(QPen(col, 2 if major else 1))
            p.drawLine(int(x1), int(y1), int(x2), int(y2))

        # ── Ring 2: Blue dot matrix ────────────────────────────────────────────
        r2 = cx * 0.78
        for i in range(60):
            angle  = (i / 60) * math.tau
            active = self._dot_blink[i]
            radius = 2.5 if active else 1.5
            alpha  = 220 if active else 80
            col    = QColor(0, 170, 255, alpha)
            p.setBrush(QBrush(col))
            p.setPen(Qt.PenStyle.NoPen)
            x = cx + r2 * math.cos(angle)
            y = cy + r2 * math.sin(angle)
            p.drawEllipse(int(x - radius), int(y - radius),
                          int(radius * 2), int(radius * 2))

        # ── Ring 3: Dark mechanical segment arcs ──────────────────────────────
        r3 = cx * 0.65
        for i in range(12):
            start_deg = i * 30 - 2
            span_deg  = 20
            pen = QPen(QColor("#1a3a5c"), 10, Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect_x = int(cx - r3)
            rect_y = int(cy - r3)
            rect_w = int(r3 * 2)
            p.drawArc(rect_x, rect_y, rect_w, rect_w,
                      int(start_deg * 16), int(span_deg * 16))

        # ── Ring 4: Rotating blue segments ────────────────────────────────────
        r4 = cx * 0.55
        p.save()
        p.translate(int(cx), int(cy))
        p.rotate(self._ring4_angle)
        pen4 = QPen(QColor(0, 102, 204, 200), 5, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        p.setPen(pen4)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(8):
            start_deg = i * 45 - 5
            span_deg  = 28
            p.drawArc(int(-r4), int(-r4), int(r4 * 2), int(r4 * 2),
                      int(start_deg * 16), int(span_deg * 16))
        p.restore()

        # ── Ring 5: Counter-rotating purple/pink dots ─────────────────────────
        r5 = cx * 0.42
        for i in range(16):
            angle = ((i / 16) * math.tau +
                     math.radians(self._ring5_angle))
            col = PURPLE if i % 2 == 0 else PINK
            col = QColor(col.red(), col.green(), col.blue(), 150)
            p.setBrush(QBrush(col))
            p.setPen(Qt.PenStyle.NoPen)
            x = cx + r5 * math.cos(angle)
            y = cy + r5 * math.sin(angle)
            p.drawEllipse(int(x - 3), int(y - 3), 6, 6)

        # ── Ring 6: Orange/pink accent arc ────────────────────────────────────
        r6 = cx * 0.35
        p.save()
        p.translate(int(cx), int(cy))
        p.rotate(self._ring6_angle)
        pen6 = QPen(QColor("#E91E8C"), 3, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        p.setPen(pen6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(int(-r6), int(-r6), int(r6 * 2), int(r6 * 2),
                  0 * 16, int(72 * 16))   # 72 degrees
        p.restore()

        # ── Core glow ─────────────────────────────────────────────────────────
        core_r = cx * 0.26
        status_color = STATUS_COLORS.get(self._status, TEAL)

        # Outer glow
        glow = QRadialGradient(cx, cy, core_r * 2.5)
        gc = QColor(status_color.red(), status_color.green(),
                    status_color.blue(), self._pulse_alpha // 4)
        glow.setColorAt(0, gc)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(int(cx - core_r * 2.5), int(cy - core_r * 2.5),
                      int(core_r * 5), int(core_r * 5))

        # Core fill — teal radial gradient
        core_fill = QRadialGradient(cx, cy, core_r)
        c1 = QColor(status_color.red(), status_color.green(),
                    status_color.blue(), self._pulse_alpha)
        c2 = QColor(0, 51, 102, 220)
        core_fill.setColorAt(0, c1)
        core_fill.setColorAt(0.5, QColor(0, 170, 200, 180))
        core_fill.setColorAt(1, c2)
        p.setBrush(QBrush(core_fill))
        pen_core = QPen(TEAL, 1)
        p.setPen(pen_core)
        p.drawEllipse(int(cx - core_r), int(cy - core_r),
                      int(core_r * 2), int(core_r * 2))

        # ── J.A.R.V.I.S text ──────────────────────────────────────────────────
        font_main = QFont("Orbitron", max(7, int(core_r * 0.32)))
        font_main.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        font_sub  = QFont("Share Tech Mono", max(5, int(core_r * 0.22)))

        p.setPen(QPen(QColor("#003344"), 1))
        p.setFont(font_main)
        p.drawText(int(cx - core_r), int(cy - 6),
                   int(core_r * 2), 14, Qt.AlignmentFlag.AlignCenter, "J.A.R.V.I.S")

        p.setPen(QPen(QColor("#005566"), 1))
        p.setFont(font_sub)
        p.drawText(int(cx - core_r), int(cy + 6),
                   int(core_r * 2), 10, Qt.AlignmentFlag.AlignCenter, "SYSTEM ONLINE")

        p.drawText(int(cx - core_r), int(cy + 14),
                   int(core_r * 2), 8, Qt.AlignmentFlag.AlignCenter, "MARK 7")

        # ── Status text below reactor ─────────────────────────────────────────
        p.setPen(QPen(QColor(199, 125, 255, 120), 1))
        sfont = QFont("Share Tech Mono", 9)
        sfont.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        p.setFont(sfont)
        status_txt = self._status.upper()
        p.drawText(0, int(cy + core_r + 6), self._sz, 16,
                   Qt.AlignmentFlag.AlignCenter, status_txt)

        p.end()
