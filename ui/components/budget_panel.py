"""ui/components/budget_panel.py — Spending tracker with category budgets."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QTabWidget, QVBoxLayout, QWidget, QProgressBar
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

CATEGORY_ICONS = {
    "food":          "🍕",
    "transport":     "🚌",
    "uni":           "📚",
    "clothes":       "👗",
    "health":        "💊",
    "entertainment": "🎬",
    "personal":      "💇",
    "tech":          "💻",
    "other":         "📦",
}

CATEGORIES = list(CATEGORY_ICONS.keys())


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


class AddTransactionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Transaction")
        self.setMinimumWidth(380)
        layout = QFormLayout(self)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, 99999)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setPrefix("€ ")

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("e.g. Coffee at uni")

        self.cat_box = QComboBox()
        self.cat_box.addItems(CATEGORIES)

        self.date_edit = QLineEdit(date.today().isoformat())

        self.payment_box = QComboBox()
        self.payment_box.addItems(["card", "cash", "transfer"])

        layout.addRow("Amount:", self.amount_spin)
        layout.addRow("Description:", self.desc_edit)
        layout.addRow("Category:", self.cat_box)
        layout.addRow("Date:", self.date_edit)
        layout.addRow("Payment:", self.payment_box)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)


class BudgetCategoryRow(QWidget):
    """One budget category: icon + name + progress bar + amounts."""

    def __init__(self, category: str, spent: float, limit: float, currency: str):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(3)

        icon = CATEGORY_ICONS.get(category, "📦")
        pct  = min(spent / limit, 1.5) if limit else 0
        pct_int = int((spent / limit * 100)) if limit else 0

        # Name row
        name_row = QHBoxLayout()
        name_lbl = QLabel(f"{icon}  {category.title()}")
        name_lbl.setFont(QFont("Segoe UI", 12))
        name_row.addWidget(name_lbl, 1)

        amounts = QLabel(f"{currency}{spent:.0f} / {currency}{limit:.0f}")
        amounts.setObjectName("secondary")
        name_row.addWidget(amounts)

        if pct_int > 100:
            status = QLabel("🔴")
            status_style = "color:#F44336;"
        elif pct_int >= 80:
            status = QLabel("⚠️")
            status_style = "color:#FF9800;"
        else:
            status = QLabel("✅")
            status_style = "color:#4CAF50;"
        status.setStyleSheet(status_style)
        name_row.addWidget(status)
        layout.addLayout(name_row)

        # Progress bar
        bar = QProgressBar()
        bar.setMaximum(100)
        bar.setValue(min(pct_int, 100))
        bar.setFixedHeight(6)
        bar.setTextVisible(False)
        if pct_int > 100:
            bar.setStyleSheet("QProgressBar::chunk{background:#F44336;border-radius:3px;}")
        elif pct_int >= 80:
            bar.setStyleSheet("QProgressBar::chunk{background:#FF9800;border-radius:3px;}")
        else:
            bar.setStyleSheet("QProgressBar::chunk{background:#6C63FF;border-radius:3px;}")
        layout.addWidget(bar)


class BudgetPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        # Header
        header = QHBoxLayout()
        now = date.today()
        self._title = QLabel(f"💰  Budget — {now.strftime('%B %Y')}")
        self._title.setObjectName("panel_title")
        header.addWidget(self._title)
        header.addStretch()

        add_btn = QPushButton("＋ Add")
        add_btn.setObjectName("accent_btn")
        add_btn.clicked.connect(self._add_transaction)
        header.addWidget(add_btn)
        layout.addLayout(header)

        # Summary bar
        self._summary_lbl = QLabel()
        self._summary_lbl.setObjectName("secondary")
        layout.addWidget(self._summary_lbl)
        layout.addSpacing(8)

        # Tabs
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        tabs.addTab(self._build_overview_tab(), "Overview")
        tabs.addTab(self._build_transactions_tab(), "Transactions")
        tabs.addTab(self._build_stats_tab(), "Stats")

        layout.addWidget(tabs, 1)

    # ── Overview tab ──────────────────────────────────────────────────────

    def _build_overview_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._categories_widget = QWidget()
        self._categories_layout = QVBoxLayout(self._categories_widget)
        self._categories_layout.setSpacing(8)
        self._categories_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._categories_widget)
        layout.addWidget(scroll, 1)

        # Savings section
        sav_frame = QFrame()
        sav_frame.setStyleSheet(
            "QFrame{background:#1A2A1A;border:1px solid #4CAF50;border-radius:8px;padding:12px;}"
        )
        sl = QVBoxLayout(sav_frame)
        self._savings_lbl = QLabel("Savings: Loading...")
        self._savings_lbl.setFont(QFont("Segoe UI", 12))
        sl.addWidget(self._savings_lbl)
        self._savings_bar = QProgressBar()
        self._savings_bar.setFixedHeight(6)
        self._savings_bar.setTextVisible(False)
        self._savings_bar.setStyleSheet("QProgressBar::chunk{background:#4CAF50;border-radius:3px;}")
        sl.addWidget(self._savings_bar)
        add_sav_btn = QPushButton("＋ Add to Savings")
        add_sav_btn.clicked.connect(self._add_savings)
        sl.addWidget(add_sav_btn)
        layout.addWidget(sav_frame)
        return w

    # ── Transactions tab ──────────────────────────────────────────────────

    def _build_transactions_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        toolbar = QHBoxLayout()
        self._txn_filter = QComboBox()
        self._txn_filter.addItems(["This month", "This week", "Today", "All time"])
        self._txn_filter.currentTextChanged.connect(self._refresh_transactions)
        toolbar.addWidget(self._txn_filter, 1)

        self._cat_filter = QComboBox()
        self._cat_filter.addItems(["All categories"] + CATEGORIES)
        self._cat_filter.currentTextChanged.connect(self._refresh_transactions)
        toolbar.addWidget(self._cat_filter)
        layout.addLayout(toolbar)
        layout.addSpacing(4)

        self._txn_list = QListWidget()
        self._txn_list.setAlternatingRowColors(True)
        layout.addWidget(self._txn_list, 1)

        add_btn = QPushButton("＋ Add transaction manually")
        add_btn.clicked.connect(self._add_transaction)
        layout.addWidget(add_btn)
        return w

    # ── Stats tab ─────────────────────────────────────────────────────────

    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        self._stats_lbl = QLabel("Loading stats...")
        self._stats_lbl.setFont(QFont("Segoe UI", 12))
        self._stats_lbl.setWordWrap(True)
        self._stats_lbl.setStyleSheet(
            "background:#1A1A1A;border:1px solid #2A2A2A;border-radius:8px;padding:16px;"
        )
        layout.addWidget(self._stats_lbl)
        layout.addStretch()
        return w

    # ── Data refresh ──────────────────────────────────────────────────────

    @pyqtSlot()
    def _refresh(self):
        try:
            from budget_tool import get_monthly_data
            data = get_monthly_data()
        except Exception as e:
            self._summary_lbl.setText(f"Budget tool unavailable: {e}")
            return

        budget   = data["budget"]
        by_cat   = data["by_category"]
        spent    = data["total_spent"]
        income   = float(budget.get("monthly_income", 0))
        cur      = budget.get("currency", "EUR")
        limits   = budget.get("limits", {})

        # Summary bar
        left = income - spent if income else 0
        self._summary_lbl.setText(
            f"Income: {cur}{income:.0f}  ·  Spent: {cur}{spent:.2f}  ·  Left: {cur}{left:.2f}"
        )

        # Category rows
        while self._categories_layout.count():
            item = self._categories_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        for cat in CATEGORIES:
            cat_spent = by_cat.get(cat, 0.0)
            cat_limit = float(limits.get(cat, 0))
            if cat_limit > 0 or cat_spent > 0:
                row = BudgetCategoryRow(cat, cat_spent, cat_limit, cur)
                self._categories_layout.addWidget(row)
        self._categories_layout.addStretch()

        # Savings
        sav_goal = float(budget.get("savings_goal", 0))
        sav_curr = float(budget.get("savings_current", 0))
        if sav_goal:
            pct = int(min(sav_curr / sav_goal * 100, 100))
            self._savings_lbl.setText(
                f"🏦 Savings: {cur}{sav_curr:.2f} / {cur}{sav_goal:.0f} goal  ({pct}%)"
            )
            self._savings_bar.setValue(pct)
        else:
            self._savings_lbl.setText(f"🏦 Savings: {cur}{sav_curr:.2f}")

        self._refresh_transactions()
        self._refresh_stats(data, cur)

    def _refresh_transactions(self):
        try:
            from budget_tool import _txn_path, _period_start
            txns_data = json.loads(_txn_path().read_text())
            txns = txns_data.get("transactions", [])
        except Exception:
            return

        period_map = {
            "This month": "month",
            "This week":  "week",
            "Today":      "today",
            "All time":   "year",
        }
        period = period_map.get(self._txn_filter.currentText(), "month")
        cat_f  = self._cat_filter.currentText()

        try:
            from budget_tool import _period_start
            cutoff = _period_start(period)
        except Exception:
            cutoff = ""

        filtered = [
            t for t in txns
            if t.get("date", "") >= cutoff
            and (cat_f == "All categories" or t.get("category") == cat_f)
        ]
        filtered.sort(key=lambda t: t.get("date", ""), reverse=True)

        self._txn_list.clear()
        cur = "EUR"
        prev_date = None
        for txn in filtered:
            d = txn.get("date", "")
            if d != prev_date:
                header_item = QListWidgetItem(
                    f"  {'Today' if d == date.today().isoformat() else d}"
                )
                header_item.setBackground(QColor("#0D0D0D"))
                header_item.setForeground(QColor("#888888"))
                header_item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._txn_list.addItem(header_item)
                prev_date = d

            icon = CATEGORY_ICONS.get(txn.get("category", "other"), "📦")
            cat  = txn.get("category", "other").title()[:8]
            item = QListWidgetItem(
                f"  {icon} {txn.get('description', '')[:30]:<30}  "
                f"{cat:<10}  -{cur}{txn.get('amount', 0):.2f}"
            )
            item.setFont(QFont("Consolas", 11))
            item.setData(Qt.ItemDataRole.UserRole, txn["id"])
            self._txn_list.addItem(item)

    def _refresh_stats(self, data: dict, cur: str):
        by_cat = data["by_category"]
        today  = date.today()
        month_txns = data["transactions"]
        total  = data["total_spent"]
        days_so_far = today.day

        if not month_txns:
            self._stats_lbl.setText("No transactions this month.")
            return

        top = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = "\n".join(
            f"{i+1}. {CATEGORY_ICONS.get(c,'')}{c.title()} — {cur}{v:.2f} ({int(v/total*100)}%)"
            for i, (c, v) in enumerate(top)
        )

        biggest = sorted(month_txns, key=lambda t: t.get("amount", 0), reverse=True)[:3]
        big_str = "\n".join(
            f"  {t.get('description','')[:30]:<32} {cur}{t.get('amount',0):.2f}"
            for t in biggest
        )

        daily_avg = total / days_so_far if days_so_far else 0
        from calendar import monthrange
        days_in_month = monthrange(today.year, today.month)[1]
        projected = daily_avg * days_in_month

        self._stats_lbl.setText(
            f"Top categories:\n{top_str}\n\n"
            f"Biggest expenses:\n{big_str}\n\n"
            f"Daily average: {cur}{daily_avg:.2f}\n"
            f"Projected month-end: {cur}{projected:.0f}"
        )

    # ── Actions ───────────────────────────────────────────────────────────

    def _add_transaction(self):
        dlg = AddTransactionDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        amount = dlg.amount_spin.value()
        desc   = dlg.desc_edit.text().strip()
        cat    = dlg.cat_box.currentText()
        txn_date = dlg.date_edit.text().strip() or date.today().isoformat()
        payment= dlg.payment_box.currentText()
        if not desc:
            return
        try:
            from budget_tool import log_transaction
            log_transaction(amount, desc, category=cat, payment_method=payment)
            self._refresh()
        except Exception as e:
            print(f"Add transaction error: {e}")

    def _add_savings(self):
        from PyQt6.QtWidgets import QInputDialog
        amount, ok = QInputDialog.getDouble(self, "Add to Savings", "Amount (€):", 0, 0, 99999, 2)
        if ok and amount > 0:
            try:
                from budget_tool import log_savings
                result = log_savings(amount)
                self._refresh()
            except Exception as e:
                print(f"Add savings error: {e}")
