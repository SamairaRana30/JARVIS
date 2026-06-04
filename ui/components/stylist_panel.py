"""ui/components/stylist_panel.py — Wardrobe manager and AI stylist panel."""

import json
import sys
from datetime import date
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap, QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QStackedWidget, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget
)

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT))

PHOTO_SIZE = 100   # thumbnail px
CARD_W     = 130


def _load_cfg():
    import yaml
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _make_placeholder_pixmap(color: str = "#2A2A2A", size: int = PHOTO_SIZE) -> QPixmap:
    """Generate a solid-color placeholder pixmap."""
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    return pm


def _load_photo(photo_rel: str | None, size: int = PHOTO_SIZE) -> QPixmap:
    """Load a clothing photo, or return placeholder."""
    if photo_rel:
        abs_path = ROOT / photo_rel
        if abs_path.exists():
            pm = QPixmap(str(abs_path))
            if not pm.isNull():
                return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                  Qt.TransformationMode.SmoothTransformation)
    return _make_placeholder_pixmap()


# ---------------------------------------------------------------------------
# Add Item dialog
# ---------------------------------------------------------------------------

class AddItemDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Clothing Item")
        self.setMinimumWidth(420)
        self._photo_path: str | None = None
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit     = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. White oversized tee")
        self.category_box  = QComboBox()
        self.category_box.addItems(["tops","bottoms","shoes","outerwear","accessories","dresses"])
        self.color_edit    = QLineEdit()
        self.color_edit.setPlaceholderText("white, navy  (comma separated)")
        self.brand_edit    = QLineEdit()
        self.size_edit     = QLineEdit()
        self.cost_edit     = QLineEdit()
        self.cost_edit.setPlaceholderText("19.99")
        self.occasion_edit = QLineEdit()
        self.occasion_edit.setPlaceholderText("casual, study  (comma separated)")
        self.season_edit   = QLineEdit()
        self.season_edit.setPlaceholderText("spring, summer, autumn, winter")

        form.addRow("Name:",     self.name_edit)
        form.addRow("Category:", self.category_box)
        form.addRow("Colors:",   self.color_edit)
        form.addRow("Brand:",    self.brand_edit)
        form.addRow("Size:",     self.size_edit)
        form.addRow("Cost (€):", self.cost_edit)
        form.addRow("Occasions:",self.occasion_edit)
        form.addRow("Season:",   self.season_edit)
        layout.addLayout(form)

        # Photo picker
        photo_row = QHBoxLayout()
        self._photo_lbl = QLabel("No photo selected")
        self._photo_lbl.setObjectName("muted")
        photo_btn = QPushButton("📷 Choose Photo")
        photo_btn.clicked.connect(self._pick_photo)
        photo_row.addWidget(self._photo_lbl, 1)
        photo_row.addWidget(photo_btn)
        layout.addLayout(photo_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _pick_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Photo", "", "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if path:
            self._photo_path = path
            self._photo_lbl.setText(Path(path).name)

    def get_data(self) -> dict:
        def _list(s):
            return [x.strip() for x in s.split(",") if x.strip()]
        return {
            "name":     self.name_edit.text().strip(),
            "category": self.category_box.currentText(),
            "colors":   _list(self.color_edit.text()),
            "brand":    self.brand_edit.text().strip(),
            "size":     self.size_edit.text().strip(),
            "cost":     float(self.cost_edit.text()) if self.cost_edit.text() else None,
            "occasion": _list(self.occasion_edit.text()) or ["casual"],
            "season":   _list(self.season_edit.text()) or ["spring", "summer", "autumn", "winter"],
            "photo_path": self._photo_path,
        }


# ---------------------------------------------------------------------------
# Item card (thumbnail grid)
# ---------------------------------------------------------------------------

class ItemCard(QFrame):
    def __init__(self, item: dict, on_click, on_wear, on_fav):
        super().__init__()
        self.item = item
        self.setFixedWidth(CARD_W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QFrame{background:#1A1A1A;border:1px solid #2A2A2A;"
            "border-radius:8px;padding:4px;}"
            "QFrame:hover{border-color:#6C63FF;}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # Thumbnail
        thumb = QLabel()
        thumb.setFixedSize(PHOTO_SIZE, PHOTO_SIZE)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = _load_photo(item.get("photo"))
        thumb.setPixmap(pm)
        thumb.mousePressEvent = lambda e, i=item: on_click(i)
        layout.addWidget(thumb)

        # Name
        name = QLabel(item["name"][:18])
        name.setFont(QFont("Segoe UI", 9))
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)

        # Action row
        row = QHBoxLayout()
        row.setSpacing(2)
        wear_btn = QPushButton("✓")
        wear_btn.setFixedSize(26, 22)
        wear_btn.setToolTip("Log worn today")
        wear_btn.setStyleSheet("font-size:11px;")
        wear_btn.clicked.connect(lambda: on_wear(item))
        row.addWidget(wear_btn)

        fav_btn = QPushButton("★" if item.get("favorite") else "☆")
        fav_btn.setFixedSize(26, 22)
        fav_btn.setStyleSheet(
            f"color:{'#FFD700' if item.get('favorite') else '#888888'};font-size:13px;"
        )
        fav_btn.clicked.connect(lambda: on_fav(item))
        row.addWidget(fav_btn)
        layout.addLayout(row)


# ---------------------------------------------------------------------------
# Item detail view
# ---------------------------------------------------------------------------

class ItemDetailView(QWidget):
    def __init__(self, item: dict, on_back, on_wear, on_delete, on_photo):
        super().__init__()
        self.item = item
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Back button
        back_btn = QPushButton("← Back")
        back_btn.clicked.connect(on_back)
        back_btn.setFixedWidth(80)
        layout.addWidget(back_btn)

        # Main content
        content = QHBoxLayout()

        # Left: photo
        left = QVBoxLayout()
        self._photo_lbl = QLabel()
        pm = _load_photo(item.get("photo"), size=220)
        self._photo_lbl.setPixmap(pm)
        self._photo_lbl.setFixedSize(220, 220)
        self._photo_lbl.setStyleSheet("border:1px solid #2A2A2A;border-radius:8px;")
        left.addWidget(self._photo_lbl)

        change_photo_btn = QPushButton("📷 Change Photo")
        change_photo_btn.clicked.connect(lambda: on_photo(item))
        left.addWidget(change_photo_btn)
        left.addStretch()
        content.addLayout(left)

        # Right: details
        right = QVBoxLayout()
        right.setSpacing(8)

        name_row = QHBoxLayout()
        name_lbl = QLabel(item["name"])
        name_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        name_row.addWidget(name_lbl)
        name_row.addStretch()
        fav_lbl = QLabel("❤️" if item.get("favorite") else "🤍")
        fav_lbl.setFont(QFont("Segoe UI", 18))
        name_row.addWidget(fav_lbl)
        right.addLayout(name_row)

        def _detail_row(label, value):
            if not value:
                return
            lbl = QLabel(f"<b>{label}</b>  {value}")
            lbl.setFont(QFont("Segoe UI", 12))
            right.addWidget(lbl)

        _detail_row("Brand:", item.get("brand") or "—")
        _detail_row("Size:",  item.get("size") or "—")
        _detail_row("Colors:", ", ".join(item.get("colors", [])))
        _detail_row("Season:", ", ".join(item.get("season", [])))
        _detail_row("Occasions:", ", ".join(item.get("occasion", [])))
        _detail_row("Worn:", f"{item.get('times_worn', 0)} times")
        _detail_row("Last worn:", item.get("last_worn") or "Never")
        if item.get("cost"):
            cost = item["cost"]
            worn = item.get("times_worn", 1) or 1
            cpp  = float(cost) / worn
            _detail_row("Cost:", f"€{cost:.2f}  (€{cpp:.2f}/wear)")

        right.addStretch()

        btn_row = QHBoxLayout()
        wear_btn = QPushButton("✓ Wore today")
        wear_btn.setObjectName("success_btn")
        wear_btn.clicked.connect(lambda: on_wear(item))
        btn_row.addWidget(wear_btn)

        del_btn = QPushButton("🗑 Remove")
        del_btn.setObjectName("danger_btn")
        del_btn.clicked.connect(lambda: on_delete(item))
        btn_row.addWidget(del_btn)
        right.addLayout(btn_row)

        content.addLayout(right, 1)
        layout.addLayout(content)


# ---------------------------------------------------------------------------
# Main Stylist Panel
# ---------------------------------------------------------------------------

class StylistPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []
        self._filtered: list[dict] = []
        self._setup_ui()
        self._refresh()
        QTimer(self, timeout=self._refresh, interval=60_000).start()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        header = QHBoxLayout()
        title = QLabel("👗  Stylist")
        title.setObjectName("panel_title")
        header.addWidget(title)
        layout.addLayout(header)
        layout.addSpacing(8)

        # Tabs
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        # Tab 1: Today's Outfit
        self._outfit_tab = self._build_outfit_tab()
        self._tabs.addTab(self._outfit_tab, "Today's Outfit")

        # Tab 2: My Closet (stacked: grid vs detail)
        self._closet_stack = QStackedWidget()
        self._closet_grid_widget = self._build_closet_tab()
        self._closet_stack.addWidget(self._closet_grid_widget)
        self._tabs.addTab(self._closet_stack, "My Closet")

        # Tab 3: Stats
        self._stats_tab = self._build_stats_tab()
        self._tabs.addTab(self._stats_tab, "Stats")

        layout.addWidget(self._tabs, 1)

    # ── Today's Outfit tab ────────────────────────────────────────────────

    def _build_outfit_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        # Context bar
        self._context_lbl = QLabel("Loading weather and schedule...")
        self._context_lbl.setObjectName("secondary")
        layout.addWidget(self._context_lbl)
        layout.addSpacing(8)

        # Outfit suggestion area
        self._outfit_suggestion_lbl = QLabel("Click 'Suggest' to get today's outfit.")
        self._outfit_suggestion_lbl.setWordWrap(True)
        self._outfit_suggestion_lbl.setFont(QFont("Segoe UI", 13))
        self._outfit_suggestion_lbl.setStyleSheet(
            "background:#1A1A1A;border:1px solid #2A2A2A;border-radius:8px;padding:12px;"
        )
        layout.addWidget(self._outfit_suggestion_lbl)

        # Item thumbnails row
        self._outfit_items_row = QHBoxLayout()
        self._outfit_items_row.setSpacing(8)
        layout.addLayout(self._outfit_items_row)
        layout.addSpacing(8)

        # Buttons
        btn_row = QHBoxLayout()
        suggest_btn = QPushButton("🔄  Suggest Outfit")
        suggest_btn.setObjectName("accent_btn")
        suggest_btn.clicked.connect(self._suggest_outfit)
        btn_row.addWidget(suggest_btn)

        wear_btn = QPushButton("✓  Wearing This")
        wear_btn.setObjectName("success_btn")
        wear_btn.clicked.connect(self._log_today_outfit)
        btn_row.addWidget(wear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addStretch()

        return w

    def _suggest_outfit(self):
        self._outfit_suggestion_lbl.setText("Thinking... ⏳")
        QTimer.singleShot(100, self._do_suggest)

    def _do_suggest(self):
        try:
            from closet_tool import suggest_daily
            suggestion = suggest_daily()
            self._outfit_suggestion_lbl.setText(suggestion)
            self._update_context()
        except Exception as e:
            self._outfit_suggestion_lbl.setText(f"Stylist unavailable: {e}")

    def _update_context(self):
        try:
            import yaml
            with open(ROOT / "config.yaml") as f:
                cfg = yaml.safe_load(f)
            city = cfg.get("weather", {}).get("default_location", "Berlin")
            import requests
            resp = requests.get(f"https://wttr.in/{city}?format=3", timeout=5,
                                headers={"User-Agent": "Jarvis/1.0"})
            import re, unicodedata
            text = "".join(c for c in resp.text.strip() if unicodedata.category(c) != "So")
            self._context_lbl.setText(text.strip())
        except Exception:
            self._context_lbl.setText("")

    def _log_today_outfit(self):
        try:
            from closet_tool import log_worn
            for item in self._items[:3]:
                log_worn(item["name"])
        except Exception:
            pass

    # ── My Closet tab ─────────────────────────────────────────────────────

    def _build_closet_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)

        # Toolbar
        toolbar = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Search items...")
        self._search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_edit, 1)

        self._cat_filter = QComboBox()
        self._cat_filter.addItems(["All categories", "tops", "bottoms", "shoes",
                                    "outerwear", "accessories", "dresses"])
        self._cat_filter.currentTextChanged.connect(self._apply_filter)
        toolbar.addWidget(self._cat_filter)

        add_btn = QPushButton("＋ Add Item")
        add_btn.setObjectName("accent_btn")
        add_btn.clicked.connect(self._add_item)
        toolbar.addWidget(add_btn)
        layout.addLayout(toolbar)
        layout.addSpacing(8)

        # Item count
        self._count_lbl = QLabel()
        self._count_lbl.setObjectName("muted")
        layout.addWidget(self._count_lbl)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(8)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self._grid_container)
        layout.addWidget(scroll, 1)

        return w

    def _apply_filter(self):
        query = self._search_edit.text().lower()
        cat   = self._cat_filter.currentText()
        self._filtered = [
            i for i in self._items
            if (not query or query in i.get("name", "").lower() or
                any(query in c for c in i.get("colors", [])))
            and (cat == "All categories" or i.get("category") == cat)
        ]
        self._rebuild_grid()

    def _rebuild_grid(self):
        # Clear
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._count_lbl.setText(f"{len(self._filtered)} items")
        cols = max(1, min(6, (self._grid_container.width() or 700) // (CARD_W + 10)))

        for idx, item in enumerate(self._filtered):
            card = ItemCard(
                item,
                on_click=self._show_item_detail,
                on_wear=lambda i: self._log_item(i),
                on_fav=lambda i: self._toggle_fav(i),
            )
            self._grid_layout.addWidget(card, idx // cols, idx % cols)

    def _show_item_detail(self, item: dict):
        detail = ItemDetailView(
            item,
            on_back=lambda: self._closet_stack.setCurrentIndex(0),
            on_wear=lambda i: self._log_item(i),
            on_delete=lambda i: self._delete_item(i),
            on_photo=lambda i: self._change_photo(i),
        )
        if self._closet_stack.count() > 1:
            self._closet_stack.removeWidget(self._closet_stack.widget(1))
        self._closet_stack.addWidget(detail)
        self._closet_stack.setCurrentIndex(1)

    def _add_item(self):
        dlg = AddItemDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        data = dlg.get_data()
        if not data["name"]:
            return
        try:
            from closet_tool import add_item, attach_photo
            result = add_item(
                data["name"], data["category"], data["colors"],
                data["occasion"], data["season"],
                data["brand"], data["size"], data["cost"]
            )
            if data.get("photo_path"):
                # Find the newly added item by name
                from closet_tool import get_all_items
                for i in get_all_items():
                    if i["name"] == data["name"]:
                        attach_photo(i["id"], data["photo_path"])
                        break
            self._refresh()
        except Exception as e:
            print(f"Add item error: {e}")

    def _log_item(self, item: dict):
        try:
            from closet_tool import log_worn
            log_worn(item["name"])
            self._refresh()
        except Exception as e:
            print(f"Log worn error: {e}")

    def _toggle_fav(self, item: dict):
        try:
            from closet_tool import toggle_favorite
            toggle_favorite(item["id"])
            self._refresh()
        except Exception as e:
            print(f"Toggle fav error: {e}")

    def _delete_item(self, item: dict):
        try:
            from closet_tool import delete_item
            delete_item(item["id"])
            self._closet_stack.setCurrentIndex(0)
            self._refresh()
        except Exception as e:
            print(f"Delete item error: {e}")

    def _change_photo(self, item: dict):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Photo", "", "Images (*.jpg *.jpeg *.png *.webp)"
        )
        if not path:
            return
        try:
            from closet_tool import attach_photo
            attach_photo(item["id"], path)
            self._refresh()
        except Exception as e:
            print(f"Change photo error: {e}")

    # ── Stats tab ─────────────────────────────────────────────────────────

    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)
        self._stats_lbl = QLabel("Loading...")
        self._stats_lbl.setFont(QFont("Segoe UI", 12))
        self._stats_lbl.setWordWrap(True)
        self._stats_lbl.setStyleSheet(
            "background:#1A1A1A;border:1px solid #2A2A2A;border-radius:8px;padding:16px;"
        )
        layout.addWidget(self._stats_lbl)

        # Most worn list
        sec = QLabel("MOST WORN")
        sec.setObjectName("section_title")
        layout.addWidget(sec)
        self._most_worn_layout = QVBoxLayout()
        layout.addLayout(self._most_worn_layout)

        # Unworn list
        sec2 = QLabel("NEVER / RARELY WORN (30+ days)")
        sec2.setObjectName("section_title")
        layout.addWidget(sec2)
        self._unworn_layout = QVBoxLayout()
        layout.addLayout(self._unworn_layout)

        layout.addStretch()
        return w

    def _refresh_stats(self):
        try:
            from closet_tool import get_stats, get_all_items
            items = get_all_items()
            total = len(items)
            total_val = sum(float(i.get("cost") or 0) for i in items)

            self._stats_lbl.setText(
                f"Total items: {total}   ·   Estimated value: €{total_val:.0f}"
            )

            by_worn = sorted(items, key=lambda i: i.get("times_worn", 0), reverse=True)
            while self._most_worn_layout.count():
                item = self._most_worn_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            for i in by_worn[:5]:
                worn = i.get("times_worn", 0)
                cost = float(i.get("cost") or 0)
                cpp  = f"  ·  €{cost/worn:.2f}/wear" if worn and cost else ""
                lbl = QLabel(f"• {i['name']} — {worn} times{cpp}")
                lbl.setFont(QFont("Segoe UI", 12))
                self._most_worn_layout.addWidget(lbl)

            from closet_tool import unworn as _unworn, _days_since_worn
            while self._unworn_layout.count():
                item = self._unworn_layout.takeAt(0)
                if item.widget(): item.widget().deleteLater()
            neglected = [i for i in items if _days_since_worn(i) >= 30]
            neglected.sort(key=_days_since_worn, reverse=True)
            for i in neglected[:5]:
                days = _days_since_worn(i)
                worn = i.get("times_worn", 0)
                lbl = QLabel(f"• {i['name']} — {worn}x, "
                             f"{'never worn' if days == 9999 else f'{days} days ago'}")
                lbl.setFont(QFont("Segoe UI", 12))
                lbl.setStyleSheet("color:#FF9800;")
                self._unworn_layout.addWidget(lbl)
        except Exception as e:
            self._stats_lbl.setText(f"Stats unavailable: {e}")

    # ── Data refresh ──────────────────────────────────────────────────────

    @pyqtSlot()
    def _refresh(self):
        try:
            from closet_tool import get_all_items
            self._items    = get_all_items()
            self._filtered = list(self._items)
        except Exception:
            self._items = self._filtered = []

        self._rebuild_grid()
        self._refresh_stats()
        self._update_context()
