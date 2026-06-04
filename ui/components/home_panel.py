"""ui/components/home_panel.py — Dashboard home with overview cards."""

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


class OverviewCard(QFrame):
    """A single home-screen card."""
    def __init__(self, title: str, on_click=None):
        super().__init__()
        self.setObjectName("card")
        self.setStyleSheet(
            "QFrame#card{background:#1A1A1A;border:1px solid #2A2A2A;"
            "border-radius:12px;padding:16px;}"
            "QFrame#card:hover{border-color:#6C63FF;cursor:pointer;}"
        )
        self.setMinimumHeight(160)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("section_title")
        layout.addWidget(title_lbl)

        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        layout.addLayout(self._body)
        layout.addStretch()

        if on_click:
            self.mousePressEvent = lambda e: on_click()

    def set_body_text(self, text: str, color: str = "#FFFFFF"):
        while self._body.count():
            item = self._body.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        for line in text.strip().splitlines():
            lbl = QLabel(line)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(f"color:{color};")
            lbl.setWordWrap(True)
            self._body.addWidget(lbl)

    def add_row(self, text: str, color: str = "#FFFFFF"):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{color};font-size:12px;")
        lbl.setWordWrap(True)
        self._body.addWidget(lbl)

    def add_progress(self, label: str, value: int):
        row_w = QWidget()
        rl = QVBoxLayout(row_w)
        rl.setSpacing(2)
        rl.setContentsMargins(0, 0, 0, 0)
        lbl_row = QHBoxLayout()
        lbl_row.addWidget(QLabel(label))
        lbl_row.addStretch()
        pct_lbl = QLabel(f"{value}%")
        pct_lbl.setObjectName("accent")
        lbl_row.addWidget(pct_lbl)
        rl.addLayout(lbl_row)
        bar = QProgressBar()
        bar.setMaximum(100)
        bar.setValue(value)
        bar.setFixedHeight(6)
        rl.addWidget(bar)
        self._body.addWidget(row_w)


class HomePanel(QWidget):
    """Default home panel with overview cards."""

    # nav_requested is emitted with a panel key when a card is clicked
    from PyQt6.QtCore import pyqtSignal
    nav_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, OverviewCard] = {}
        self._setup_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(60_000)
        # Signal-based refreshes
        try:
            from ui.signals import JarvisSignals
            sig = JarvisSignals.instance()
            sig.tasks_updated.connect(self._refresh)
            sig.fridge_updated.connect(self._refresh)
            sig.goals_updated.connect(self._refresh)
        except Exception:
            pass

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        # Greeting row
        now = datetime.now()
        hour = now.hour
        greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
        try:
            cfg = _load_cfg()
            mem = json.loads((ROOT / cfg["paths"]["memory"]).read_text())
            name = mem.get("name", "Samaira").split()[0]
        except Exception:
            name = "Samaira"

        greet_lbl = QLabel(f"{greeting}, {name}! 👋")
        greet_lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        layout.addWidget(greet_lbl)

        date_lbl = QLabel(now.strftime("%A, %d %B %Y"))
        date_lbl.setObjectName("secondary")
        layout.addWidget(date_lbl)
        layout.addSpacing(16)

        # Card grid
        grid = QGridLayout()
        grid.setSpacing(12)

        def _card(title, key):
            c = OverviewCard(title, on_click=lambda k=key: self.nav_requested.emit(k))
            self._cards[key] = c
            return c

        grid.addWidget(_card("TODAY'S TASKS",  "tasks"),    0, 0)
        grid.addWidget(_card("GOALS PROGRESS", "tasks"),    0, 1)
        grid.addWidget(_card("FRIDGE ALERTS",  "fridge"),   1, 0)
        grid.addWidget(_card("OPEN FOLLOW-UPS","chat"),     1, 1)

        layout.addLayout(grid, 1)

    @pyqtSlot()
    def _refresh(self):
        try:
            cfg = _load_cfg()
            self._refresh_tasks(cfg)
            self._refresh_goals(cfg)
            self._refresh_fridge(cfg)
            self._refresh_followups(cfg)
        except Exception:
            pass

    def _refresh_tasks(self, cfg):
        card = self._cards.get("tasks")
        if not card: return
        try:
            tasks = json.loads((ROOT / cfg["paths"]["tasks"]).read_text())
            today = date.today().isoformat()
            pending = [t for t in tasks if not t.get("done")]
            pending.sort(key=lambda t: (
                {"high": 0, "medium": 1, "low": 2}.get(t.get("priority"), 1),
                t.get("deadline", "9999")
            ))
            while card._body.count():
                item = card._body.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            if not pending:
                card.add_row("🎉 All done!", "#4CAF50")
            else:
                for t in pending[:4]:
                    p = t.get("priority", "medium")
                    dot = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(p, "🟡")
                    dl = f"  · due {t['deadline'][:10]}" if t.get("deadline") else ""
                    card.add_row(f"{dot} {t['title'][:30]}{dl}")
                if len(pending) > 4:
                    card.add_row(f"  +{len(pending) - 4} more...", "#888888")
        except Exception:
            pass

    def _refresh_goals(self, cfg):
        card = self._cards.get("tasks")  # goals go in the second card slot
        # We use a separate card for goals
        goals_card = None
        # Find the goals card by position - it's the second in row 0
        for k, c in self._cards.items():
            if "GOALS" in c.findChild(QLabel).text() if c.findChild(QLabel) else "":
                goals_card = c
                break
        # Simple approach: directly find the second card
        try:
            cfg2 = _load_cfg()
            progress = json.loads((ROOT / cfg2["paths"]["progress"]).read_text())
            goals = progress.get("goals", [])
            # Find the goals card (second card added)
            cards_list = list(self._cards.values())
            if len(cards_list) < 2: return
            goals_card = cards_list[1]
            while goals_card._body.count():
                item = goals_card._body.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            if not goals:
                # Fall back to goals.json
                g_data = json.loads((ROOT / cfg["paths"]["goals"]).read_text())
                for g in (g_data.get("long_term", []) + g_data.get("short_term", []))[:2]:
                    goals_card.add_progress(g["goal"][:25], g.get("progress", 0))
            else:
                for g in goals[:3]:
                    snaps = g.get("snapshots", [])
                    pct = snaps[-1]["progress_percent"] if snaps else 0
                    goals_card.add_progress(g["goal"][:25], pct)
        except Exception:
            pass

    def _refresh_fridge(self, cfg):
        card = self._cards.get("fridge")
        if not card: return
        try:
            fridge = json.loads((ROOT / cfg["paths"]["fridge"]).read_text())
            cutoff = (date.today() + timedelta(days=3)).isoformat()
            expiring = sorted(
                [i for i in fridge.get("items", []) if i.get("expires") and i["expires"] <= cutoff],
                key=lambda i: i["expires"]
            )
            while card._body.count():
                item = card._body.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            if not expiring:
                card.add_row("✅ Nothing expiring soon", "#4CAF50")
            else:
                for item in expiring[:4]:
                    days = (date.fromisoformat(item["expires"]) - date.today()).days
                    when = "today!" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
                    color = "#F44336" if days <= 1 else "#FF9800"
                    card.add_row(f"⚠️ {item['name']} — expires {when}", color)
        except Exception:
            pass

    def _refresh_followups(self, cfg):
        card = self._cards.get("chat")
        if not card: return
        try:
            fups = json.loads((ROOT / cfg["paths"]["followups"]).read_text())
            open_fups = [f for f in fups if not f.get("done")]
            while card._body.count():
                item = card._body.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            if not open_fups:
                card.add_row("✅ No open follow-ups", "#4CAF50")
            else:
                for f in open_fups[:4]:
                    card.add_row(f"• {f.get('note', f.get('topic', '?'))[:40]}", "#888888")
        except Exception:
            pass
