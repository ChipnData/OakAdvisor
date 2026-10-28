"""Windows UI: the advisor panel (for your second monitor) and the in-game overlay."""
from __future__ import annotations
import ctypes
import sys
import threading
import time
import traceback

import cv2
import numpy as np
from PySide6.QtCore import Qt, QRect, Signal, QObject, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QCompleter, QScrollArea)

from . import capture, config
from . import layout as L
from .advisor import advise, Advice, RunTracker
from .icons import IconLibrary
from .vision import Reader, GameState, parse_tooltip

STYLE = """
* { font-family: 'Segoe UI'; color: #ece4d6; }
QMainWindow, QDialog, QWidget#root { background: #1d1813; }
QPushButton { background: #3a2c20; border: 1px solid #6b4f33; border-radius: 6px; padding: 7px 12px; font-weight: 600; }
QPushButton:hover { background: #4a3828; }
QPushButton#primary { background: #4f7a3a; border-color: #79a85c; }
QPushButton#primary:hover { background: #5d8c45; }
QFrame#card { background: #2a221b; border: 1px solid #45362a; border-radius: 8px; }
QFrame#card[act="buy"] { border: 2px solid #7fd35c; background: #24301c; }
QFrame#card[act="freeze"] { border: 2px solid #5cc8e0; background: #1c2a30; }
QLabel#head { font-size: 20px; font-weight: 700; color: #ffe39a; }
QLabel#muted { color: #a8998a; }
QLabel#stat { font-size: 15px; font-weight: 600; }
QTextEdit, QLineEdit, QComboBox, QSpinBox, QTableWidget { background: #2a221b; border: 1px solid #45362a; border-radius: 4px; }
QHeaderView::section { background: #3a2c20; padding: 4px; border: none; }
"""

ACT_COLORS = {"buy": QColor(127, 211, 92), "freeze": QColor(92, 200, 224)}


def to_pixmap(img: np.ndarray | None, size=96) -> QPixmap:
    if img is None or img.size == 0:
        return QPixmap()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    q = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(q).scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def exclude_from_capture(widget: QWidget):
    """Keep the overlay out of our own screenshots (Windows 10 2004+)."""
    if sys.platform != "win32":
        return False
    try:
        WDA_EXCLUDEFROMCAPTURE = 0x11
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(int(widget.winId()), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


def phys_to_logical(rect: QRect) -> QRect:
    """Physical screen pixels (what Win32/mss use) -> Qt logical pixels."""
    for scr in QGuiApplication.screens():
        g = scr.geometry()
        dpr = scr.devicePixelRatio()
        phys = QRect(g.x(), g.y(), int(g.width() * dpr), int(g.height() * dpr))
        if phys.contains(rect.center()):
            return QRect(g.x() + int((rect.x() - g.x()) / dpr), g.y() + int((rect.y() - g.y()) / dpr),
                         int(rect.width() / dpr), int(rect.height() / dpr))
    return rect


# --------------------------------------------------------------------------- overlay
class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.advice: Advice | None = None
        self.state: GameState | None = None
        self.message = ""
        self.excluded = False

    def place(self, area):
        self.setGeometry(phys_to_logical(QRect(area.x, area.y, area.w, area.h)))

    def showEvent(self, e):
        super().showEvent(e)
        self.excluded = exclude_from_capture(self)

    def set_content(self, state, advice, message=""):
        self.state, self.advice, self.message = state, advice, message
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sx = self.width() / L.FRAME_W
        sy = self.height() / L.FRAME_H

        def r(box):
            x0, y0, x1, y1 = box
            return QRect(int(x0 * sx), int(y0 * sy), int((x1 - x0) * sx), int((y1 - y0) * sy))

        if self.advice and self.state:
            for idx, a in self.advice.slots.items():
                col = ACT_COLORS.get(a.action)
                if not col:
                    continue
                p.setPen(QPen(col, max(3, int(5 * sx))))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r(L.SHOP_ICON[idx]).adjusted(-6, -6, 6, 6), 10, 10)
                tag = QRect(r(L.SHOP_ICON[idx]).x(), r(L.SHOP_ICON[idx]).y() - int(34 * sy), int(130 * sx), int(30 * sy))
                p.fillRect(tag, col)
                p.setPen(QColor(10, 10, 10))
                f = QFont("Segoe UI", max(8, int(15 * sy)), QFont.Bold)
                p.setFont(f)
                p.drawText(tag, Qt.AlignCenter, a.action.upper())
            steps = self.advice.steps
        else:
            steps = []
        lines = ([self.message] if self.message else []) + [x.split("  (")[0] for x in steps[:4]]
        if not lines:
            return
        # advice box sits over the empty strip right of the player banner
        box = QRect(int(1040 * sx), int(105 * sy), int(1080 * sx), int(40 * sy * (len(lines)) + 16 * sy))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 12, 9, 215))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QColor(255, 227, 154))
        p.setFont(QFont("Segoe UI", max(8, int(17 * sy)), QFont.Bold))
        y = box.y() + int(8 * sy)
        for i, line in enumerate(lines):
            if i == 1:
                p.setPen(QColor(236, 228, 214))
                p.setFont(QFont("Segoe UI", max(8, int(15 * sy))))
            p.drawText(QRect(box.x() + int(14 * sx), y, box.width() - int(28 * sx), int(40 * sy)),
                       Qt.AlignVCenter | Qt.TextSingleLine, line)
            y += int(40 * sy)


# --------------------------------------------------------------------------- dialogs
class NameDialog(QDialog):
    """Name an item by hand (when no tooltip was open)."""
    def __init__(self, parent, crop, lib: IconLibrary, packs=None, guess=""):
        super().__init__(parent)
        self.setWindowTitle("Name this item")
        lay = QFormLayout(self)
        pic = QLabel()
        pic.setPixmap(to_pixmap(crop, 140))
        lay.addRow(pic)
        self.name = QLineEdit(guess)
        comp = QCompleter(sorted(lib.items))
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.name.setCompleter(comp)
        lay.addRow("Item name", self.name)
        self.packs = QLineEdit(", ".join(packs or []))
        lay.addRow("Packs", self.packs)
        self.rating = QComboBox()
        self.rating.addItems(["", "S", "A", "B", "C", "D"])
        lay.addRow("Your rating", self.rating)
        self.consumable = QCheckBox("Potion / consumable")
        lay.addRow(self.consumable)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)


class LibraryDialog(QDialog):
    COLS = ["", "Name", "Packs", "Rarity", "Rating", "Type", "Cooldown", "Damage", "Effects", "Potion", "Notes"]

    def __init__(self, parent, lib: IconLibrary):
        super().__init__(parent)
        self.lib = lib
        self.setWindowTitle(f"Item library — {len(lib.items)} items")
        self.resize(1200, 700)
        v = QVBoxLayout(self)
        tip = QLabel("Set a Rating (S best … D worst) for items you know are good or bad — the advisor leans on it. "
                     "Edit any cell; renaming merges into an existing item of that name.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(56)
        v.addWidget(self.table)
        row = QHBoxLayout()
        dele = QPushButton("Delete selected")
        dele.clicked.connect(self.delete)
        save = QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        row.addWidget(dele)
        row.addStretch()
        row.addWidget(save)
        v.addLayout(row)
        self.fill()

    def fill(self):
        self.table.setRowCount(0)
        thumbs = {}
        for t in self.lib.templates:
            thumbs.setdefault(t.item, t.path)
        for it in sorted(self.lib.items.values(), key=lambda i: i.name.lower()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            pic = QLabel()
            if it.name in thumbs:
                pic.setPixmap(to_pixmap(cv2.imread(thumbs[it.name]), 50))
            self.table.setCellWidget(r, 0, pic)
            vals = [it.name, ", ".join(it.packs), it.rarity, None, it.type, it.cooldown, it.damage, it.effects, None, it.notes]
            for c, val in enumerate(vals, start=1):
                if c == 4:
                    cb = QComboBox()
                    cb.addItems(["", "S", "A", "B", "C", "D"])
                    cb.setCurrentText(it.rating)
                    self.table.setCellWidget(r, c, cb)
                elif c == 9:
                    ch = QCheckBox()
                    ch.setChecked(it.consumable)
                    self.table.setCellWidget(r, c, ch)
                else:
                    item = QTableWidgetItem(val or "")
                    if c == 1:
                        item.setData(Qt.UserRole, it.name)
                    self.table.setItem(r, c, item)

    def save(self):
        for r in range(self.table.rowCount()):
            old = self.table.item(r, 1).data(Qt.UserRole)
            new = self.table.item(r, 1).text().strip() or old
            it = self.lib.items.get(old)
            if not it:
                continue
            it.packs = [p.strip() for p in self.table.item(r, 2).text().split(",") if p.strip()]
            it.rarity = self.table.item(r, 3).text().strip()
            it.rating = self.table.cellWidget(r, 4).currentText()
            it.type = self.table.item(r, 5).text().strip()
            it.cooldown = self.table.item(r, 6).text().strip()
            it.damage = self.table.item(r, 7).text().strip()
            it.effects = self.table.item(r, 8).text().strip()
            it.consumable = self.table.cellWidget(r, 9).isChecked()
            it.notes = self.table.item(r, 10).text().strip()
            if new != old:
                self.lib.save()
                self.lib.rename(old, new)
        self.lib.save()
        self.accept()

    def delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            return
        names = [self.table.item(r, 1).data(Qt.UserRole) for r in rows]
        if QMessageBox.question(self, "Delete", f"Delete {', '.join(names)}?") == QMessageBox.Yes:
            for n in names:
                self.lib.delete(n)
            self.fill()


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg, adv):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.cfg, self.adv = cfg, adv
        f = QFormLayout(self)
        self.packs = {}
        packrow = QGridLayout()
        for i, p in enumerate(L.PACKS):
            cb = QCheckBox(p)
            cb.setChecked(p in adv.favorite_packs)
            self.packs[p] = cb
            packrow.addWidget(cb, i // 5, i % 5)
        w = QWidget()
        w.setLayout(packrow)
        f.addRow("Packs you like", w)
        self.buy = QSpinBox(); self.buy.setRange(0, 100); self.buy.setValue(adv.buy_threshold)
        self.frz = QSpinBox(); self.frz.setRange(0, 100); self.frz.setValue(adv.freeze_threshold)
        self.safe = QSpinBox(); self.safe.setRange(1, 10); self.safe.setValue(adv.safe_hearts)
        f.addRow("Buy if score ≥", self.buy)
        f.addRow("Freeze if score ≥", self.frz)
        f.addRow("Greedy (level up) at hearts ≥", self.safe)
        self.keys = {}
        for act in ("scan", "learn", "overlay"):
            cb = QComboBox()
            cb.addItems([f"F{i}" for i in range(1, 13)])
            cb.setCurrentText(cfg["hotkeys"].get(act, "F8"))
            self.keys[act] = cb
            f.addRow(f"Hotkey: {act}", cb)
        self.title = QLineEdit(cfg["window_title"])
        f.addRow("Game window title", self.title)
        self.mon = QSpinBox(); self.mon.setRange(1, 6); self.mon.setValue(int(cfg["monitor"]))
        f.addRow("Game monitor (if window not found)", self.mon)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def ok(self):
        self.adv.favorite_packs = [p for p, cb in self.packs.items() if cb.isChecked()]
        self.adv.buy_threshold = self.buy.value()
        self.adv.freeze_threshold = self.frz.value()
        self.adv.safe_hearts = self.safe.value()
        self.cfg["hotkeys"] = {a: cb.currentText() for a, cb in self.keys.items()}
        self.cfg["window_title"] = self.title.text().strip() or "Oaken Tower"
        self.cfg["monitor"] = self.mon.value()
        config.save(self.cfg, self.adv)
        self.accept()


# --------------------------------------------------------------------------- main window
class Bridge(QObject):
    done = Signal(object)


class Card(QFrame):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        self.pic = QLabel(alignment=Qt.AlignCenter)
        self.pic.setFixedHeight(90)
        self.title = QLabel(wordWrap=True, alignment=Qt.AlignCenter)
        self.title.setStyleSheet("font-weight:700")
        self.sub = QLabel(wordWrap=True, alignment=Qt.AlignCenter)
        self.sub.setObjectName("muted")
        for w in (self.pic, self.title, self.sub):
            v.addWidget(w)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def set(self, crop, title, sub, act=""):
        self.pic.setPixmap(to_pixmap(crop, 86))
        self.title.setText(title)
        self.sub.setText(sub)
        self.setProperty("act", act)
        self.style().unpolish(self)
        self.style().polish(self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oak Advisor")
        self.resize(980, 900)
        self.cfg, self.adv = config.load()
        root = config.data_dir()
        config.seed_library(root)
        self.lib = IconLibrary(root)
        self.reader = Reader(self.lib)
        self.tracker = RunTracker()
        self.state: GameState | None = None
        self.frame = None
        self.area = None
        self.busy = False
        self.bridge = Bridge()
        self.bridge.done.connect(self._on_result)

        self.overlay = Overlay()

        w = QWidget(objectName="root")
        self.setCentralWidget(w)
        v = QVBoxLayout(w)

        bar = QHBoxLayout()
        hk = self.cfg["hotkeys"]
        self.scan_btn = QPushButton(f"Scan shop  ({hk['scan']})")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self.scan)
        learn = QPushButton(f"Learn hovered item  ({hk['learn']})")
        learn.clicked.connect(self.learn)
        self.ov_btn = QPushButton(f"Overlay  ({hk['overlay']})")
        self.ov_btn.setCheckable(True)
        self.ov_btn.setChecked(self.cfg.get("overlay_on", True))
        self.ov_btn.clicked.connect(self.toggle_overlay)
        libb = QPushButton("Item library")
        libb.clicked.connect(self.open_library)
        newrun = QPushButton("New run")
        newrun.setToolTip("Forget this run's purchases (happens automatically when a new run starts)")
        newrun.clicked.connect(lambda: (self.tracker.reset(), self.head.setText("New run — good luck!")))
        bar.addWidget(newrun)
        setb = QPushButton("Settings")
        setb.clicked.connect(self.open_settings)
        for b in (self.scan_btn, learn, self.ov_btn):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(libb)
        bar.addWidget(setb)
        v.addLayout(bar)

        self.stats = QLabel("Press Scan while the shop is open.", objectName="stat")
        v.addWidget(self.stats)
        self.head = QLabel("", objectName="head", wordWrap=True)
        v.addWidget(self.head)
        self.steps = QLabel("", wordWrap=True)
        self.steps.setStyleSheet("font-size:15px")
        v.addWidget(self.steps)
        self.direction = QLabel("", objectName="muted")
        v.addWidget(self.direction)

        v.addWidget(QLabel("<b>Shop</b>  <span style='color:#a8998a'>(click an unrecognised item to name it)</span>"))
        grid = QGridLayout()
        self.shop_cards = []
        for i in range(7):
            c = Card()
            c.clicked.connect(lambda i=i: self.name_target("shop", i))
            self.shop_cards.append(c)
            grid.addWidget(c, 0 if i < 4 else 1, i if i < 4 else i - 4)
        v.addLayout(grid)

        v.addWidget(QLabel("<b>Your tower & storage</b>"))
        self.owned_wrap = QWidget(objectName="root")
        self.owned_grid = QGridLayout(self.owned_wrap)
        self.owned_grid.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setStyleSheet("QScrollArea { background: #1d1813; }")
        sc.setWidgetResizable(False)
        sc.setWidget(self.owned_wrap)
        sc.setMinimumHeight(180)
        sc.setFrameShape(QFrame.NoFrame)
        v.addWidget(sc)

        self.notes = QLabel("", objectName="muted", wordWrap=True)
        v.addWidget(self.notes)

        self.hot = None
        self.start_hotkeys()
        QShortcut(QKeySequence("F5"), self, activated=self.scan)

    # ---------------- hotkeys
    def start_hotkeys(self):
        from .hotkeys import HotkeyThread
        if self.hot:
            self.hot.stop()
        self.hot = HotkeyThread(dict(self.cfg["hotkeys"]))
        self.hot.pressed.connect(self._hotkey)
        self.hot.failed.connect(lambda m: self.notes.setText(f"Hotkey problem: {m} — change it in Settings."))
        self.hot.start()

    def _hotkey(self, action):
        {"scan": self.scan, "learn": self.learn, "overlay": lambda: (self.ov_btn.toggle(), self.toggle_overlay())}[action]()

    def closeEvent(self, e):
        if self.hot:
            self.hot.stop()
        self.overlay.close()
        self.lib.save()
        super().closeEvent(e)

    # ---------------- capture + work in background
    def _grab(self):
        self.area = capture.locate(self.cfg)
        if self.area is None:
            raise RuntimeError("Couldn't find the game. Is Oaken Tower running?")
        hide = self.overlay.isVisible() and not self.overlay.excluded
        if hide:
            self.overlay.hide()
            QApplication.processEvents()
            time.sleep(0.06)
        img = capture.grab(self.area)
        if hide:
            self.overlay.show()
        if float(img.mean()) < 3:
            raise RuntimeError("The capture came back black — set the game to Borderless Windowed "
                               "(exclusive fullscreen can't be captured).")
        return img

    def scan(self):
        if self.busy:
            return
        try:
            img = self._grab()
        except Exception as e:
            self.head.setText(str(e))
            return
        self._run("scan", img, None)

    def learn(self):
        if self.busy:
            return
        try:
            img = self._grab()
            cur = capture.cursor_pos()
        except Exception as e:
            self.head.setText(str(e))
            return
        pt = capture.to_frame_coords(self.area, *cur) if cur else None
        self._run("learn", img, pt)

    def _run(self, kind, img, pt):
        self.busy = True
        self.scan_btn.setEnabled(False)
        self.head.setText("Reading the shop…" if kind == "scan" else "Reading the tooltip…")
        self.overlay.set_content(self.state, None, "Thinking…")

        def work():
            try:
                frame = Reader.to_frame(img)
                if kind == "scan":
                    st = self.reader.read(frame)
                    self.tracker.update(st)
                    adv = advise(st, self.lib, self.adv, self.tracker)
                    self.lib.save()
                    self.bridge.done.emit(("scan", frame, st, adv, None))
                else:
                    st = self.reader.read(frame, identify=False)
                    kind2, target = self.reader.target_at(st, *pt) if pt else (None, None)
                    tip = parse_tooltip(frame, near=pt) if target is not None else None
                    self.bridge.done.emit(("learn", frame, st, (kind2, target), tip))
            except Exception:
                self.bridge.done.emit(("error", None, None, traceback.format_exc(), None))

        threading.Thread(target=work, daemon=True).start()

    def _on_result(self, res):
        kind, frame, st, payload, tip = res
        self.busy = False
        self.scan_btn.setEnabled(True)
        if kind == "error":
            self.head.setText("Something went wrong reading the screen.")
            self.notes.setText(payload[-800:])
            self.overlay.set_content(None, None, "")
            return
        if kind == "scan":
            self.frame, self.state = frame, st
            self.show_state(st, payload)
            return
        # learn
        where, target = payload
        if target is None:
            self.head.setText("Point the mouse at an item (shop, tower or storage), then press Learn.")
            self.overlay.set_content(self.state, None, "Hover an item, then press Learn")
            return
        packs = getattr(target, "packs", []) if where == "shop" else []
        if tip and tip.get("name"):
            it = self.lib.upsert(tip["name"], packs=packs, rarity=tip["rarity"], type=tip["type"],
                                 cooldown=tip["cooldown"], damage=tip["damage"], effects=tip["effects"])
            self.lib.add_template(it.name, where, target.crop)
            self.lib.save()
            msg = f"Learned {it.name} ({it.rarity or '?'})"
        else:
            dlg = NameDialog(self, target.crop, self.lib, packs)
            if dlg.exec() != QDialog.Accepted or not dlg.name.text().strip():
                self.head.setText("Learn cancelled.")
                return
            self._save_named(dlg, where, target)
            msg = f"Learned {dlg.name.text().strip()}"
        self.head.setText(msg)
        self.overlay.set_content(self.state, None, msg)
        if self.cfg.get("auto_rescan_after_learn", True):
            QTimer.singleShot(150, self.scan)

    def _save_named(self, dlg, where, target):
        name = dlg.name.text().strip()
        packs = [p.strip() for p in dlg.packs.text().split(",") if p.strip()]
        it = self.lib.upsert(name, packs=packs, rating=dlg.rating.currentText())
        it.consumable = dlg.consumable.isChecked() or it.consumable
        self.lib.add_template(name, where, target.crop)
        self.lib.save()

    def name_target(self, where, idx):
        if not self.state:
            return
        if where == "shop":
            if idx >= len(self.state.shop) or self.state.shop[idx].empty:
                return
            target = self.state.shop[idx]
            packs = target.packs
        else:
            target = idx
            packs = []
        dlg = NameDialog(self, target.crop, self.lib, packs, target.name or "")
        if dlg.exec() == QDialog.Accepted and dlg.name.text().strip():
            self._save_named(dlg, where if where == "shop" else target.where, target)
            self.reader.identify_all(self.state)
            self.show_state(self.state, advise(self.state, self.lib, self.adv, self.tracker))

    # ---------------- display
    def show_state(self, st: GameState, a: Advice):
        def v(x):
            return "?" if x is None else x
        self.stats.setText(
            f"Day {v(st.day)}   🏆 {v(st.wins)}/10   ❤ {v(st.hearts)}/{v(st.hearts_max)}   "
            f"💰 {v(st.gold)} (+{v(st.income)})   Lv {v(st.level)}  XP {v(st.xp)}/{v(st.xp_need)}   "
            f"refresh {v(st.reroll_cost)}g · XP {v(st.level_cost)}g")
        self.head.setText(a.headline.split("  (")[0])
        self.steps.setText("<br>".join(f"{i}. {s}" for i, s in enumerate(a.steps, 1)))
        real = [(p, w) for p, w in a.direction if w >= 1.5]
        self.direction.setText("Build direction: " + (", ".join(f"{p} ({w})" for p, w in real)
                               or "open — not enough info yet (learn your tower items or keep scanning each shop)"))
        for i, card in enumerate(self.shop_cards):
            s = st.shop[i] if i < len(st.shop) else None
            if not s or s.empty:
                card.set(None, "—", "", "")
                continue
            sa = a.slots.get(i)
            title = s.name or "Unknown — click to name"
            sale = " SALE" if s.sale else ""
            up = " ⬆ combines" if s.upgrade_glow else ""
            sub = f"{'/'.join(s.packs) or '?'} · {s.price}g{sale}{up}"
            if sa:
                sub += f"\nscore {sa.score}" + (f": {', '.join(sa.reasons[:3])}" if sa.reasons else "")
            card.set(s.crop, title, sub, sa.action if sa else "")
        # owned
        while self.owned_grid.count():
            it = self.owned_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for n, o in enumerate(st.tower + st.storage):
            c = Card()
            stars = {1: "", 2: " ★", 3: " ★★"}[o.tier]
            c.set(o.crop, (o.name or "Unknown — click") + stars, "tower" if o.where == "tower" else "storage")
            c.setFixedSize(124, 160)
            c.clicked.connect(lambda o=o: self.name_target("owned", o))
            self.owned_grid.addWidget(c, n // 7, n % 7)
            c.show()
        self.owned_wrap.adjustSize()
        self.notes.setText("<br>".join(a.notes))
        if self.area:
            self.overlay.place(self.area)
        self.overlay.set_content(st, a)
        if self.ov_btn.isChecked():
            self.overlay.show()

    def toggle_overlay(self):
        on = self.ov_btn.isChecked()
        self.cfg["overlay_on"] = on
        config.save(self.cfg, self.adv)
        if on:
            if self.area:
                self.overlay.place(self.area)
            self.overlay.show()
        else:
            self.overlay.hide()

    def open_library(self):
        LibraryDialog(self, self.lib).exec()
        if self.state:
            self.reader.identify_all(self.state)
            self.show_state(self.state, advise(self.state, self.lib, self.adv, self.tracker))

    def open_settings(self):
        if SettingsDialog(self, self.cfg, self.adv).exec() == QDialog.Accepted:
            self.start_hotkeys()
            if self.state:
                self.show_state(self.state, advise(self.state, self.lib, self.adv, self.tracker))


def run():
    # Qt makes the process per-monitor DPI aware itself, so Win32 calls see real pixels
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = MainWindow()
    win.show()
    # warm up the text reader in the background so the first scan is quick
    threading.Thread(target=lambda: __import__("oakadvisor.ocr", fromlist=["engine"]).engine(), daemon=True).start()
    sys.exit(app.exec())
