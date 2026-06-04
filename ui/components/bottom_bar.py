"""ui/components/bottom_bar.py — HUD bottom bar: system stats + quick commands."""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton,
                              QProgressBar, QWidget)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _bar_style(pct: int) -> str:
    if pct > 85:
        chunk = "#FF6B35"
    elif pct > 65:
        chunk = "#FFAA00"
    else:
        chunk = "#00D4FF"
    return (
        f"QProgressBar{{background:#001220;border:1px solid rgba(0,212,255,0.2);"
        f"border-radius:0;height:6px;text-align:center;color:transparent;}}"
        f"QProgressBar::chunk{{background:{chunk};}}"
    )


class MiniStat(QWidget):
    """Label + progress bar for one system metric."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._lbl = QLabel(f"{label}:")
        self._lbl.setStyleSheet("color:#004455;font-size:9px;letter-spacing:1px;")
        self._lbl.setFixedWidth(36)
        layout.addWidget(self._lbl)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedWidth(70)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        self._val = QLabel("0%")
        self._val.setStyleSheet("color:#00D4FF;font-size:9px;min-width:28px;")
        layout.addWidget(self._val)

    def update_value(self, pct: int, extra: str = ""):
        self._bar.setValue(pct)
        self._bar.setStyleSheet(_bar_style(pct))
        self._val.setText(f"{pct}%{' ' + extra if extra else ''}")


class BottomBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("bottom_bar")
        self.setFixedHeight(40)
        self._setup_ui()
        t = QTimer(self)
        t.timeout.connect(self._update_stats)
        t.start(5000)
        self._update_stats()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(16)

        # System metrics
        self._cpu  = MiniStat("CPU")
        self._ram  = MiniStat("RAM")
        self._disk = QLabel()
        self._disk.setStyleSheet("color:#004455;font-size:9px;letter-spacing:1px;")
        layout.addWidget(self._cpu)
        layout.addWidget(self._ram)
        layout.addWidget(self._disk)
        layout.addStretch()

        # Quick commands
        sep = QLabel("◄ QUICK COMMANDS ►")
        sep.setStyleSheet("color:#004455;font-size:9px;letter-spacing:2px;")
        layout.addWidget(sep)

        for label, slot in [
            ("STUDY MODE", "_cmd_study"),
            ("SLEEP",      "_cmd_sleep"),
            ("DIAGNOSE",   "_cmd_diag"),
            ("BACKUP",     "_cmd_backup"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setStyleSheet(
                "QPushButton{background:transparent;border:1px solid rgba(0,212,255,0.25);"
                "color:#004455;font-family:'Share Tech Mono';font-size:9px;"
                "letter-spacing:1px;padding:0 8px;}"
                "QPushButton:hover{border-color:#00D4FF;color:#00D4FF;"
                "background:rgba(0,212,255,0.07);}"
            )
            btn.clicked.connect(getattr(self, slot))
            layout.addWidget(btn)

        layout.addStretch()

        # Battery
        self._battery = QLabel()
        self._battery.setStyleSheet("color:#00D4FF;font-size:9px;letter-spacing:1px;")
        layout.addWidget(self._battery)

    def _update_stats(self):
        try:
            import psutil
            cpu  = int(psutil.cpu_percent(interval=0))
            ram  = int(psutil.virtual_memory().percent)
            disk = psutil.disk_usage("/")
            free_gb = disk.free // (1024 ** 3)
            self._cpu.update_value(cpu)
            self._ram.update_value(ram)
            self._disk.setText(f"DISK: {free_gb}GB FREE")

            bat = psutil.sensors_battery()
            if bat:
                charging = "⚡" if bat.power_plugged else ""
                self._battery.setText(f"BATT: {int(bat.percent)}% {charging}")
            else:
                self._battery.setText("BATT: N/A")
        except Exception:
            pass

    def _cmd_study(self):
        self._send("start study mode")

    def _cmd_sleep(self):
        self._send("go to sleep")

    def _cmd_diag(self):
        self._send("run diagnostics")

    def _cmd_backup(self):
        self._send("back up everything")

    def _send(self, cmd: str):
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().user_typed.emit(cmd)
        except Exception:
            pass
