#!/usr/bin/env python3
"""Desktop viewer for optimized Industrialist layouts (the *_layout.json that layout.py writes).

    python viewer.py "output/8CPP-final_(Imported)_save_layout.json"

Mouse wheel zooms, drag pans, hover any tile for the pipes / machine under it, click a machine or pipe
for its details (connected pipes are highlighted), Esc clears the selection, F fits the view.
The panel on the left mirrors the web app's dashboard (power, pollution, cost, space, model count,
shortages / excesses) plus the layout checks (routing, even-split bottlenecks, valves).

Requires PySide6 (pip install PySide6).
"""
from __future__ import annotations

import colorsys
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from html import escape

try:
    from PySide6.QtCore import QPointF, QRectF, Qt, Signal
    from PySide6.QtGui import (QAction, QBrush, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen,
                               QPolygonF)
    from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QFileDialog, QFrame,
                                   QGraphicsPathItem, QGraphicsRectItem, QGraphicsScene,
                                   QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem, QMainWindow, QScrollArea, QSizePolicy,
                                   QTextBrowser, QToolBar, QToolButton, QToolTip, QVBoxLayout, QWidget)
except ImportError:  # pragma: no cover - friendly message instead of a traceback
    sys.stderr.write("The viewer needs PySide6:  pip install PySide6\n")
    raise SystemExit(1)

# ----------------------------------------------------------------------------- theme (web app colours)
BG = "#0a0a0a"
PANEL = "#1a1a1a"
PANEL2 = "#2b2b35"
GOLD = "#d4a637"
GOLD_TEXT = "#f5d56a"
TEXT = "#e0e0e0"
DIM = "#999999"
BORDER = "#333333"
GREEN = "#22c55e"
RED = "#ef4444"
FLUID = "#60a5fa"

STYLE = f"""
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; font-size: 12px; }}
QDockWidget {{ color: {GOLD_TEXT}; }}
QDockWidget::title {{ background: {PANEL}; padding: 6px; border-bottom: 1px solid {BORDER}; }}
QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; spacing: 6px; padding: 3px; }}
QToolButton {{ color: {TEXT}; background: transparent; border: 1px solid transparent; padding: 3px 6px; }}
QToolButton:hover {{ border: 1px solid {GOLD}; }}
QToolButton:checked {{ color: {GOLD_TEXT}; border: 1px solid {GOLD}; }}
QComboBox, QLineEdit {{ background: {PANEL2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 3px 6px; }}
QListWidget, QTextBrowser {{ background: {PANEL}; color: {TEXT}; border: none; }}
QListWidget::item:selected {{ background: {PANEL2}; color: {GOLD_TEXT}; }}
QScrollArea {{ border: none; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {GOLD}; padding: 4px; }}
"""


def hue(key, sat=0.55, light=0.55):
    h = int(hashlib.md5((key or "?").encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


# ----------------------------------------------------------------------------- number formatting
def with_prefix(value, limit, prefixes, suffix, unit="", decimals=2):
    """Port of the web app's formatWithPrefix."""
    if value is None:
        return "?"
    if not math.isfinite(value):
        return ("-" if value < 0 else "") + unit + "∞"
    neg, v = value < 0, abs(value)
    if v < limit:
        if v >= 1000:
            txt = f"{v:,.{decimals}f}".rstrip("0").rstrip(".")
        else:
            txt = f"{round(v, decimals):g}"
        out = f"{unit}{txt}{suffix}"
    else:
        tier = 0
        while v >= 1000 and tier < len(prefixes) - 1:
            v /= 1000
            tier += 1
        out = f"{unit}{round(v, decimals):g}{prefixes[tier]}{suffix}"
    return "-" + out if neg else out


def fmt_power(v):
    return with_prefix(v, 1000, ["", "k", "M", "G", "T", "P", "E"], "MF/s")


def fmt_pollution(v):
    return with_prefix(v, 1000, ["", "k", "M", "G", "T", "P", "E"], "%/hr", decimals=3)


def fmt_money(v):
    return with_prefix(v, 10000, ["", "k", "M", "B", "T", "Qa", "Qi"], "", "$")


RATE_MODES = {"/s": 1, "/min": 60, "/h": 3600}


class Fmt:
    mode = "/s"

    @classmethod
    def rate(cls, v):
        if v is None:
            return "?"
        v = v * RATE_MODES[cls.mode]
        a = abs(v)
        if a == 0:
            txt = "0"
        elif a >= 1000:
            txt = f"{v:,.0f}"
        elif a >= 10:
            txt = f"{v:.1f}"
        elif a >= 0.01:
            txt = f"{v:.3f}".rstrip("0").rstrip(".")
        else:
            txt = f"{v:.2e}"
        return txt + cls.mode


def pct(v):
    return "?" if v is None else f"{100 * v:.0f}%"


# ----------------------------------------------------------------------------- data
class Layout:
    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            self.d = json.load(f)
        self.path = path
        d = self.d
        if d.get("version", 1) < 2:
            raise ValueError("This layout file is from an older layout.py - re-run layout.py to get flows, "
                             "stats and valves for the viewer.")
        self.machines = d["machines"]
        self.pipes = d["pipes"]
        self.groups = d["groups"]
        self.machine_at = {}                      # tile -> machine index
        for mi, m in enumerate(self.machines):
            for x, y, w, h, _ in m["rects"]:
                for yy in range(y, y + h):
                    for xx in range(x, x + w):
                        self.machine_at[(xx, yy)] = mi
        self.port_at = {}                         # tile -> (machine index, port)
        for mi, m in enumerate(self.machines):
            for p in m["ports"]:
                for c in p["cells"]:
                    self.port_at[tuple(c)] = (mi, p)
        self.pipe_at = defaultdict(list)          # tile -> [(pipe index, graph node)]
        self.node_flow = []                       # per pipe: node -> {"in": [(from, f...)], "out": [...]}
        self.junction_at = []                     # per pipe: node -> junction dict
        self.term_at = []                         # per pipe: node -> [terminal]
        self.pipes_of_inst = defaultdict(set)
        for pi, p in enumerate(self.pipes):
            big = p["large"]
            for x, y in p["nodes"]:
                cells = [(x, y)] if not big else [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
                for c in cells:
                    self.pipe_at[c].append((pi, (x, y)))
            nfl = defaultdict(lambda: {"in": [], "out": []})
            for s in p["segments"]:
                a, b = (s[0], s[1]), (s[2], s[3])
                vals = s[4:7] if len(s) >= 7 else [None, None, None]
                nfl[a]["out"].append((b, vals))
                nfl[b]["in"].append((a, vals))
            self.node_flow.append(nfl)
            self.junction_at.append({tuple(j["at"]): j for j in p["junctions"]})
            ta = defaultdict(list)
            for t in p["terminals"]:
                if t["at"]:
                    ta[tuple(t["at"])].append(t)
                self.pipes_of_inst[t["inst"]].add(pi)
            self.term_at.append(ta)
        self.inst_index = {m["inst"]: mi for mi, m in enumerate(self.machines)}
        # a large pipe's 2x2 anchors overlap: keep one entry per pipe and tile (prefer a junction / terminal)
        for tile, lst in self.pipe_at.items():
            best = {}
            for pi, node in lst:
                score = (node in self.junction_at[pi] or node in self.term_at[pi], node == tile)
                if pi not in best or score > best[pi][0]:
                    best[pi] = (score, node)
            self.pipe_at[tile] = [(pi, v[1]) for pi, v in best.items()]


FLOW_MODES = [("planned", "Planned flows", 0), ("built", "As built (with valves)", 2),
              ("even", "Plain even splits (no valves)", 1)]


def _dir_arrow(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) >= abs(dy):
        return "→" if dx > 0 else "←"
    return "↓" if dy > 0 else "↑"


# ----------------------------------------------------------------------------- canvas
class MachineItem(QGraphicsRectItem):
    def __init__(self, rect, mi):
        super().__init__(rect)
        self.mi = mi


class PipeItem(QGraphicsPathItem):
    def __init__(self, path, pi):
        super().__init__(path)
        self.pi = pi


class View(QGraphicsView):
    hovered = Signal(object, object)   # tile, global pos
    clicked = Signal(object)           # ("machine", idx) | ("pipe", idx) | None

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setBackgroundBrush(QColor(BG))
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self._press = None
        self.grid_rect = QRectF()

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        s = self.transform().m11()
        if 0.3 < s * f < 400:
            self.scale(f, f)
            self.scene().zoom_changed(s * f)

    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(BG))
        s = self.transform().m11()
        r = rect.intersected(self.grid_rect)
        if r.isEmpty():
            return
        p.fillRect(self.grid_rect, QColor("#111111"))
        for step, col in ((1, "#1b1b1b"), (10, "#2a2a2a")):
            if step * s < 4:
                continue
            pen = QPen(QColor(col))
            pen.setCosmetic(True)
            p.setPen(pen)
            x = math.floor(r.left() / step) * step
            while x <= r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
            y = math.floor(r.top() / step) * step
            while y <= r.bottom():
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                y += step
        pen = QPen(QColor(GOLD), 0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.drawRect(self.grid_rect)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        sp = self.mapToScene(e.position().toPoint())
        self.hovered.emit((math.floor(sp.x()), math.floor(sp.y())), e.globalPosition().toPoint())

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self._press is not None and (e.position().toPoint() - self._press).manhattanLength() < 4:
            sp = self.mapToScene(e.position().toPoint())
            self.clicked.emit((math.floor(sp.x()), math.floor(sp.y())))
        self._press = None

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)


class Scene(QGraphicsScene):
    def __init__(self, lay: Layout):
        super().__init__()
        self.lay = lay
        self.machine_items, self.pipe_items, self.arrow_items, self.marker_items = [], [], [], []
        self.labels = []
        self.highlight = []
        self.show_arrows = self.show_markers = self.show_labels = True
        self.build()

    def build(self):
        lay = self.lay
        w, h = lay.d["footprint"]["width"], lay.d["footprint"]["height"]
        self.setSceneRect(QRectF(-20, -20, w + 40, h + 40))
        # machines
        for mi, m in enumerate(lay.machines):
            is_valve = m.get("valve") is not None
            base = QColor("#8a6d1f") if is_valve else hue(m["recipe"], 0.35, 0.28)
            for x, y, rw, rh, label in m["rects"]:
                it = MachineItem(QRectF(x, y, rw, rh), mi)
                it.setBrush(QBrush(base))
                pen = QPen(QColor(GOLD if not is_valve else GOLD_TEXT), 0)
                pen.setCosmetic(True)
                it.setPen(pen)
                it.setZValue(1)
                self.addItem(it)
                self.machine_items.append(it)
            x, y = m["x"], m["y"]
            title = f"{m['valve']['side_pct']:.0f}%" if is_valve else m["machine"]
            big = max((r for r in m["rects"]), key=lambda r: r[2] * r[3])
            self._label(title, big, f"#{m['index']}" if not is_valve and m["w"] * m["h"] >= 30 else None,
                        GOLD_TEXT if not is_valve else "#0a0a0a")
            for p in m["ports"]:
                col = QColor(GREEN if p["direction"] == "input" else RED)
                if p["kind"] == "Fluid":
                    col = col.lighter(115)
                for cx, cy in p["cells"]:
                    pr = QGraphicsRectItem(QRectF(cx + 0.15, cy + 0.15, 0.7, 0.7))
                    col2 = QColor(col)
                    col2.setAlphaF(1.0 if p["net"] is not None else 0.25)
                    pr.setBrush(QBrush(col2))
                    if p["net"] is not None:
                        pen = QPen(QColor("#ffffff"), 0)
                        pen.setCosmetic(True)
                        pr.setPen(pen)
                    else:
                        pr.setPen(QPen(Qt.NoPen))
                    pr.setZValue(2)
                    pr.setAcceptHoverEvents(False)
                    self.addItem(pr)
        # pipes (large first, below the small ones)
        order = sorted(range(len(lay.pipes)), key=lambda i: not lay.pipes[i]["large"])
        for pi in order:
            p = lay.pipes[pi]
            off = 1.0 if p["large"] else 0.5
            path = QPainterPath()
            for s in p["segments"]:
                path.moveTo(s[0] + off, s[1] + off)
                path.lineTo(s[2] + off, s[3] + off)
            col = hue(p["product"], 0.6, 0.55)
            it = PipeItem(path, pi)
            pen = QPen(col, 1.7 if p["large"] else 0.42)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            it.setPen(pen)
            it.setZValue(3 if p["large"] else 4)
            it.setData(0, col)
            self.addItem(it)
            self.pipe_items.append(it)
            self.arrow_items.append(self._arrows(p, off))
            self.marker_items.append(self._markers(p, off, col))
        # valves that still need placing
        for pi, p in enumerate(lay.pipes):
            for j in p["junctions"]:
                v = j.get("valve")
                if v and not v.get("ok"):
                    x, y = j["at"]
                    path = QPainterPath()
                    path.addEllipse(QPointF(x + 0.5, y + 0.5), 1.3, 1.3)
                    it = QGraphicsPathItem(path)
                    pen = QPen(QColor(RED), 0.3)
                    it.setPen(pen)
                    it.setZValue(8)
                    self.addItem(it)
        self.zoom_changed(1.0)

    def _label(self, text, rect, sub, color):
        x, y, w, h = rect[0], rect[1], rect[2], rect[3]
        t = QGraphicsSimpleTextItem(text)
        f = QFont("Segoe UI", 12)
        f.setBold(True)
        t.setFont(f)
        t.setBrush(QColor(color))
        br = t.boundingRect()
        k = min(0.8 * w / max(br.width(), 1), (0.35 if sub else 0.6) * h / max(br.height(), 1))
        t.setScale(k)
        t.setPos(x + (w - br.width() * k) / 2, y + h / 2 - br.height() * k * (1.0 if sub else 0.5))
        t.setZValue(5)
        self.addItem(t)
        self.labels.append(t)
        if sub:
            s = QGraphicsSimpleTextItem(sub)
            s.setFont(QFont("Segoe UI", 10))
            s.setBrush(QColor(DIM))
            sb = s.boundingRect()
            s.setScale(k * 0.7)
            s.setPos(x + (w - sb.width() * k * 0.7) / 2, y + h / 2 + 0.1)
            s.setZValue(5)
            self.addItem(s)
            self.labels.append(s)

    def _arrows(self, p, off):
        """Arrowheads every ~8 tiles along straight runs, pointing with the planned flow."""
        segs = {(s[0], s[1]): (s[2], s[3]) for s in p["segments"]
                if abs(s[0] - s[2]) + abs(s[1] - s[3]) == 1 and (len(s) < 5 or (s[4] or 0) > 0)}
        incoming = defaultdict(list)
        for a, b in segs.items():
            incoming[b].append(a)
        path = QPainterPath()
        size = 0.9 if p["large"] else 0.38
        counted = 0
        for a, b in segs.items():
            d = (b[0] - a[0], b[1] - a[1])
            prev = (a[0] - d[0], a[1] - d[1])
            if segs.get(prev) == a:
                continue      # not the start of a straight run
            run = [a]
            cur = a
            while cur in segs and (segs[cur][0] - cur[0], segs[cur][1] - cur[1]) == d:
                cur = segs[cur]
                run.append(cur)
            n = len(run) - 1
            for k in range(max(1, n // 8)):
                t = (k + 0.5) * n / max(1, n // 8)
                cx, cy = run[0][0] + off + d[0] * t, run[0][1] + off + d[1] * t
                px, py = -d[1], d[0]
                poly = QPolygonF([QPointF(cx + d[0] * size, cy + d[1] * size),
                                  QPointF(cx - d[0] * size + px * size * 0.8, cy - d[1] * size + py * size * 0.8),
                                  QPointF(cx - d[0] * size - px * size * 0.8, cy - d[1] * size - py * size * 0.8)])
                path.addPolygon(poly)
                path.closeSubpath()
                counted += 1
        it = QGraphicsPathItem(path)
        it.setBrush(QBrush(QColor(0, 0, 0, 200)))
        it.setPen(QPen(Qt.NoPen))
        it.setZValue(6)
        self.addItem(it)
        return it

    def _markers(self, p, off, col):
        """Port connections (green = into a machine, orange = out of one), splits (ring), merges (square)."""
        it = QGraphicsPathItem()
        it.setZValue(7)
        self.addItem(it)
        paths = {"in": QPainterPath(), "out": QPainterPath(), "split": QPainterPath(), "merge": QPainterPath(),
                 "bad": QPainterPath()}
        r = 0.75 if p["large"] else 0.34
        term_nodes = set()
        for t in p["terminals"]:
            if not t["at"] or not t["port"]:
                continue
            term_nodes.add(tuple(t["at"]))
            px = sum(c[0] for c in t["port"]) / len(t["port"]) + 0.5
            py = sum(c[1] for c in t["port"]) / len(t["port"]) + 0.5
            nx, ny = t["at"][0] + off, t["at"][1] + off
            dx, dy = px - nx, py - ny
            n = math.hypot(dx, dy) or 1
            dx, dy = dx / n, dy / n
            if t["direction"] == "output":
                dx, dy = -dx, -dy
            cx, cy = (nx + px) / 2, (ny + py) / 2
            s = 0.36
            poly = QPolygonF([QPointF(cx + dx * s, cy + dy * s), QPointF(cx - dx * s - dy * s, cy - dy * s + dx * s),
                              QPointF(cx - dx * s + dy * s, cy - dy * s - dx * s)])
            key = "in" if t["direction"] == "input" else "out"
            paths[key].addPolygon(poly)
            paths[key].closeSubpath()
        for j in p["junctions"]:
            at = tuple(j["at"])
            if at in term_nodes:
                continue
            cx, cy = at[0] + off, at[1] + off
            if j["kind"] in ("split", "mix"):
                bad = not j["even_ok"] and not (j.get("valve") or {}).get("ok")
                (paths["bad"] if bad else paths["split"]).addEllipse(QPointF(cx, cy), r, r)
            elif j["kind"] == "merge":
                paths["merge"].addRect(QRectF(cx - r * 0.8, cy - r * 0.8, r * 1.6, r * 1.6))
        group = []
        for key, fill, stroke in (("in", GREEN, "#ffffff"), ("out", "#e8590c", "#ffffff"),
                                  ("split", "#ffffff", "#000000"), ("merge", "#000000", "#ffffff"),
                                  ("bad", RED, "#ffffff")):
            if paths[key].isEmpty():
                continue
            sub = QGraphicsPathItem(paths[key], it)
            sub.setBrush(QBrush(QColor(fill)))
            pen = QPen(QColor(stroke), 0.08)
            sub.setPen(pen)
            group.append(sub)
        return it

    def zoom_changed(self, scale):
        for t in self.labels:
            t.setVisible(self.show_labels and scale * t.scale() * 12 > 5)
        for it in self.arrow_items:
            it.setVisible(self.show_arrows and scale > 2.0)
        for it in self.marker_items:
            it.setVisible(self.show_markers and scale > 1.5)

    def set_highlight(self, pipes=None, machines=None):
        """Dim everything except the given pipes / machines (None = no highlight)."""
        active = pipes is not None or machines is not None
        pipes, machines = set(pipes or ()), set(machines or ())
        for it in self.pipe_items:
            on = not active or it.pi in pipes
            it.setOpacity(1.0 if on else 0.12)
            self.arrow_items[it.pi].setOpacity(1.0 if on else 0.1)
            self.marker_items[it.pi].setOpacity(1.0 if on else 0.1)
            it.setZValue((10 if on and active else 0) + (3 if self.lay.pipes[it.pi]["large"] else 4))
        for it in self.machine_items:
            on = not active or it.mi in machines
            it.setOpacity(1.0 if on else 0.35)
            pen = it.pen()
            pen.setColor(QColor("#ffffff") if active and it.mi in machines else QColor(GOLD))
            pen.setWidthF(0)
            it.setPen(pen)


# ----------------------------------------------------------------------------- left dashboard
class Panel(QWidget):
    """Collapsible panel styled like the web app's dashboard panels."""

    def __init__(self, title, body: QWidget, open_=True):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.btn = QToolButton()
        self.btn.setText(title.upper())
        self.btn.setCheckable(True)
        self.btn.setChecked(open_)
        self.btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn.setStyleSheet(f"QToolButton {{ background: {PANEL}; color: {GOLD_TEXT}; font-weight: bold; "
                               f"font-size: 11px; letter-spacing: 1px; text-align: left; padding: 8px 12px; "
                               f"border: none; border-bottom: 1px solid {BORDER}; }}")
        self.body = body
        body.setVisible(open_)
        self.btn.toggled.connect(body.setVisible)
        lay.addWidget(self.btn)
        lay.addWidget(body)


def stat_rows(rows):
    """rows: [(label, value, colour or None)] -> widget."""
    w = QWidget()
    w.setStyleSheet(f"background: {PANEL};")
    v = QVBoxLayout(w)
    v.setContentsMargins(12, 6, 12, 8)
    v.setSpacing(3)
    for label, value, colour in rows:
        h = QHBoxLayout()
        a = QLabel(label)
        a.setStyleSheet(f"color: {DIM}; font-size: 11px;")
        b = QLabel(value)
        b.setStyleSheet(f"color: {colour or TEXT}; font-size: 11px; font-weight: 600;")
        b.setAlignment(Qt.AlignRight)
        h.addWidget(a)
        h.addStretch(1)
        h.addWidget(b)
        v.addLayout(h)
    return w


def clickable_list(items, on_click, height=None):
    """items: [(text, colour, payload)]"""
    lw = QListWidget()
    for text, colour, payload in items:
        it = QListWidgetItem(text)
        if colour:
            it.setForeground(QColor(colour))
        it.setData(Qt.UserRole, payload)
        lw.addItem(it)
    lw.itemClicked.connect(lambda it: on_click(it.data(Qt.UserRole)))
    lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lw.setTextElideMode(Qt.ElideMiddle)
    rows = max(1, len(items))
    lw.setFixedHeight(height or min(220, 20 * rows + 6))
    return lw


# ----------------------------------------------------------------------------- main window
class Viewer(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.setWindowTitle("Industrialist Layout Viewer")
        self.resize(1500, 950)
        self.setStyleSheet(STYLE)
        self.flow_col = 0
        self.lay = None
        self.view = None
        self._build_toolbar()
        self.left = QDockWidget("Dashboard", self)
        self.left.setFeatures(QDockWidget.DockWidgetMovable)
        self.left.setMinimumWidth(270)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left)
        self.right = QDockWidget("Details", self)
        self.right.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable)
        self.details = QTextBrowser()
        self.details.setOpenLinks(False)
        self.details.anchorClicked.connect(self._link)
        self.details.setMinimumWidth(330)
        self.right.setWidget(self.details)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right)
        self.right.hide()
        self.status = QLabel("Open a *_layout.json written by layout.py")
        self.status.setStyleSheet(f"color: {DIM}; padding: 2px 8px;")
        self.statusBar().addWidget(self.status, 1)
        self.statusBar().setStyleSheet(f"background: {PANEL};")
        if path:
            self.load(path)

    # ---------------------------------------------------------------- toolbar
    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)
        act = QAction("Open…", self)
        act.setShortcut(QKeySequence.Open)
        act.triggered.connect(self.open_dialog)
        tb.addAction(act)
        act = QAction("Fit", self)
        act.setShortcut("F")
        act.triggered.connect(self.fit)
        tb.addAction(act)
        tb.addSeparator()
        tb.addWidget(QLabel(" Flows: "))
        self.mode = QComboBox()
        for _, label, _c in FLOW_MODES:
            self.mode.addItem(label)
        self.mode.currentIndexChanged.connect(self._mode)
        tb.addWidget(self.mode)
        self.rate = QComboBox()
        self.rate.addItems(list(RATE_MODES))
        self.rate.currentTextChanged.connect(self._rate)
        tb.addWidget(self.rate)
        tb.addSeparator()
        self.toggles = {}
        for key, label in (("arrows", "Arrows"), ("markers", "Connections"), ("labels", "Labels")):
            a = QAction(label, self)
            a.setCheckable(True)
            a.setChecked(True)
            a.toggled.connect(lambda on, k=key: self._toggle(k, on))
            tb.addAction(a)
            self.toggles[key] = a
        tb.addSeparator()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find machine or product…")
        self.search.setFixedWidth(220)
        self.search.returnPressed.connect(self._find)
        tb.addWidget(self.search)
        esc = QAction("Clear", self)
        esc.setShortcut(Qt.Key_Escape)
        esc.triggered.connect(self.clear_selection)
        tb.addAction(esc)

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open layout", os.getcwd(), "Layout JSON (*_layout.json *.json)")
        if path:
            self.load(path)

    def load(self, path):
        try:
            self.lay = Layout(path)
        except (OSError, ValueError, KeyError) as e:
            self.status.setText(f"Could not open {path}: {e}")
            return
        self.scene = Scene(self.lay)
        self.view = View(self.scene)
        fp = self.lay.d["footprint"]
        self.view.grid_rect = QRectF(0, 0, fp["width"], fp["height"])
        self.view.hovered.connect(self._hover)
        self.view.clicked.connect(self._click)
        self.setCentralWidget(self.view)
        self.setWindowTitle(f"{self.lay.d.get('title') or os.path.basename(path)} - Industrialist Layout Viewer")
        self._dashboard()
        self.fit()
        ls = self.lay.d["layout_stats"]
        self.status.setText(f"{os.path.basename(path)} · {fp['width']} x {fp['height']} = {fp['area']:,} tiles · "
                            f"{ls['machines']} machines · {ls['pipe_networks']} pipe networks · hover a tile, "
                            f"click a machine or pipe")

    def fit(self):
        if self.view:
            self.view.fitInView(self.view.grid_rect.adjusted(-5, -5, 5, 5), Qt.KeepAspectRatio)
            self.scene.zoom_changed(self.view.transform().m11())

    def _toggle(self, key, on):
        if not self.view:
            return
        setattr(self.scene, f"show_{key}", on)
        self.scene.zoom_changed(self.view.transform().m11())

    def _mode(self, i):
        self.flow_col = FLOW_MODES[i][2]

    def _rate(self, mode):
        Fmt.mode = mode
        if self.lay:
            self._dashboard()

    # ---------------------------------------------------------------- dashboard
    def _dashboard(self):
        d = self.lay.d
        st, ls = d.get("stats", {}), d["layout_stats"]
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        pol = st.get("net_pollution", 0)
        rows = [("⚡ MV Power Use", fmt_power(st.get("mv_use", 0)), None)]
        if abs(st.get("hv_use", 0)) > 1e-4:
            rows.append(("⚡ HV Power Use", fmt_power(st["hv_use"]), None))
        rows.append(("⚡ MV Power Output", fmt_power(st.get("mv_output", 0)), None))
        if abs(st.get("hv_output", 0)) > 1e-4:
            rows.append(("⚡ HV Power Output", fmt_power(st["hv_output"]), None))
        rows += [("⚠ Net Pollution", fmt_pollution(pol), GREEN if pol < -1e-4 else RED if pol > 1e-4 else DIM),
                 ("$ Profit", f"({st.get('profit_multiplier', 0):+.2f}%) {fmt_money(st.get('profit', 0))}"
                  f"{Fmt.mode if Fmt.mode != '/s' else '/s'}", None),
                 ("◎ Machine Cost", fmt_money(st.get("machine_cost", 0)), None),
                 ("▦ Machine Space", f"{st.get('machine_space', 0):,.0f} squares", None),
                 ("▣ Machine Model Count", f"{st.get('model_count', 0):,.0f}", None)]
        v.addWidget(Panel("Production Stats", stat_rows(rows)))
        fp = d["footprint"]
        lrows = [("Footprint", f"{fp['width']} x {fp['height']}", None),
                 ("Area", f"{fp['area']:,} tiles", None),
                 ("Machine tiles", f"{ls['machine_tiles']:,} ({100 * ls['machine_tiles'] / max(1, fp['area']):.0f}%)",
                  None),
                 ("Routing", "complete" if d["fully_routed"] else "NOT complete", GREEN if d["fully_routed"] else RED),
                 ("Overfull tiles", str(ls["overfull_tiles"]), RED if ls["overfull_tiles"] else None),
                 ("Pipe networks", str(ls["pipe_networks"]), None),
                 ("Pipe tiles", f"{ls['pipe_tiles']:,}", None),
                 ("Valve controls", str(ls["valves"]), None)]
        if ls.get("valves_needed_unplaced"):
            lrows.append(("Valves to place by hand", str(ls["valves_needed_unplaced"]), RED))
        v.addWidget(Panel("Layout", stat_rows(lrows)))
        # even split check
        short = [g for g in d["groups"] if g.get("with_valves") is not None
                 and g["with_valves"] < g["planned"] * 0.995]
        items = [(f"{g['name'][:34]}  {100 * g['with_valves'] / max(g['planned'], 1e-9):.0f}%", RED,
                  ("group", g["index"])) for g in short]
        todo = [(pi, j) for pi, p in enumerate(self.lay.pipes) for j in p["junctions"]
                if j.get("valve") and not j["valve"].get("ok")]
        items += [(f"valve needed: {self.lay.pipes[pi]['product']} at {tuple(j['at'])}", "#e8590c",
                   ("tile", tuple(j["at"]), pi)) for pi, j in todo]
        if items:
            body = clickable_list(items, self._goto)
        else:
            body = stat_rows([("All machine groups reach their plan", "✓", GREEN)])
        v.addWidget(Panel("Even-split check", body))
        # shortages / excess (planner)
        de = [(f"{x['product']}  {Fmt.rate(x['rate'])}", RED, ("product", x["product"])) for x in d["deficiencies"]]
        ex = [(f"{x['product']}  {Fmt.rate(x['rate'])}", GREEN, ("product", x["product"])) for x in d["excesses"]]
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        for title, lst in (("Deficiencies (Shortages)", de), ("Excesses", ex)):
            lab = QLabel(title)
            lab.setStyleSheet(f"color: {GOLD_TEXT}; font-size: 10px; padding: 6px 12px 2px;")
            wl.addWidget(lab)
            if lst:
                wl.addWidget(clickable_list(lst, self._goto, min(140, 20 * len(lst) + 6)))
            else:
                e = QLabel("none")
                e.setStyleSheet(f"color: {DIM}; font-size: 11px; padding: 0 12px 6px;")
                wl.addWidget(e)
        v.addWidget(Panel("More Stats", w, open_=False))
        # machine groups
        gl = [(f"{g['count']} x {g['name'][:38]}", None if g["known"] else "#e8590c", ("group", g["index"]))
              for g in d["groups"]]
        v.addWidget(Panel("Machines", clickable_list(gl, self._goto, 220), open_=False))
        if d.get("warnings"):
            tw = QTextBrowser()
            tw.setHtml("<br>".join(escape(x) for x in d["warnings"]))
            tw.setFixedHeight(120)
            v.addWidget(Panel("Warnings", tw, open_=False))
        v.addStretch(1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(col)
        self.left.setWidget(sc)

    # ---------------------------------------------------------------- navigation
    def _goto(self, payload):
        kind = payload[0]
        if kind == "group":
            mis = [mi for mi, m in enumerate(self.lay.machines) if m["group"] == payload[1]]
            if not mis:
                return
            pipes = set()
            for mi in mis:
                pipes |= self.lay.pipes_of_inst[self.lay.machines[mi]["inst"]]
            self.scene.set_highlight(pipes, mis)
            self._zoom_to([self.lay.machines[mi] for mi in mis])
            self._show_group(payload[1])
        elif kind == "tile":
            x, y = payload[1]
            self.view.fitInView(QRectF(x - 12, y - 12, 24, 24), Qt.KeepAspectRatio)
            self.scene.zoom_changed(self.view.transform().m11())
            self.scene.set_highlight([payload[2]], [])
            self._show_pipe(payload[2])
        elif kind == "product":
            pipes = [pi for pi, p in enumerate(self.lay.pipes) if p["product"] == payload[1]]
            self.scene.set_highlight(pipes, [])

    def _zoom_to(self, ms):
        x0 = min(m["x"] for m in ms)
        y0 = min(m["y"] for m in ms)
        x1 = max(m["x"] + m["w"] for m in ms)
        y1 = max(m["y"] + m["h"] for m in ms)
        self.view.fitInView(QRectF(x0 - 6, y0 - 6, x1 - x0 + 12, y1 - y0 + 12), Qt.KeepAspectRatio)
        self.scene.zoom_changed(self.view.transform().m11())

    def _find(self):
        q = self.search.text().strip().lower()
        if not q or not self.lay:
            return
        mis = [mi for mi, m in enumerate(self.lay.machines) if q in m["name"].lower() or q in m["recipe"].lower()]
        pipes = [pi for pi, p in enumerate(self.lay.pipes) if q in (p["product"] or "").lower()]
        self.scene.set_highlight(pipes, mis)
        if mis:
            self._zoom_to([self.lay.machines[mi] for mi in mis])
        self.status.setText(f"'{q}': {len(mis)} machine(s), {len(pipes)} pipe network(s)")

    def clear_selection(self):
        if self.view:
            self.scene.set_highlight(None, None)
        self.right.hide()

    def _link(self, url):
        s = url.toString()
        kind, _, val = s.partition(":")
        if kind == "machine":
            self._select_machine(int(val))
        elif kind == "pipe":
            self._select_pipe(int(val))
        elif kind == "group":
            self._goto(("group", int(val)))

    # ---------------------------------------------------------------- hover
    def _hover(self, tile, gpos):
        html = self.tile_html(tile)
        if html:
            QToolTip.showText(gpos, html, self.view)
        else:
            QToolTip.hideText()
        self.status.setText(f"tile ({tile[0]}, {tile[1]})")

    def _flow_txt(self, vals):
        v = vals[self.flow_col] if vals and len(vals) > self.flow_col else None
        return Fmt.rate(v)

    def tile_html(self, tile):
        lay = self.lay
        if lay is None:
            return ""
        parts = []
        pm = lay.port_at.get(tile)
        mi = lay.machine_at.get(tile)
        if mi is not None:
            m = lay.machines[mi]
            parts.append(f"<b style='color:{GOLD_TEXT}'>{escape(m['name'])}</b> #{m['index']}/{m['count']}")
            if m.get("valve"):
                vv = m["valve"]
                parts.append(f"valve {vv['index']}/{vv['of']}: side outlet <b>{vv['side_pct']:.1f}%</b>, straight "
                             f"{vv['straight_pct']:.1f}% of {Fmt.rate(vv['flow'])}")
            r = m["run"]
            parts.append(f"runs: planned {pct(r['planned'])} · as built {pct(r['built'])}")
            if pm:
                p = pm[1]
                net = lay.pipes[p["net"]]["label"] if p["net"] is not None else "not connected"
                parts.append(f"port <b>{escape(p['id'])}</b>: {p['direction']} {p['kind']}"
                             f"{' (large)' if p['width'] > 1 else ''} → {escape(net)}"
                             + (f" · {Fmt.rate(p['rate'])}" if p["rate"] is not None else ""))
            parts.append(f"<span style='color:{DIM}'>click for details</span>")
        on = lay.pipe_at.get(tile, [])
        if len(on) >= 2:
            names = ", ".join(escape(lay.pipes[pi]["product"] or "?") for pi, _ in on)
            parts.append(f"<b style='color:{GOLD_TEXT}'>{len(on)} pipes on this tile</b> "
                         f"({'intersection' if len({lay.pipes[pi]['large'] for pi, _ in on}) == 1 else 'mixed'}): "
                         f"{names}")
        for pi, node in on:
            p = lay.pipes[pi]
            nfl = lay.node_flow[pi].get(node, {"in": [], "out": []})
            kind = "large fluid pipe" if p["large"] else ("fluid pipe" if p["kind"] == "Fluid" else "conveyor")
            head = (f"<b style='color:{hue(p['product']).name()}'>{escape(p['product'] or '?')}</b> "
                    f"<span style='color:{DIM}'>{escape(p['label'])} · {kind}"
                    + (f" · {p['temperature']:.0f}°C" if p.get("temperature") is not None else "") + "</span>")
            lines = [head]
            j = lay.junction_at[pi].get(node)
            if j and j["kind"] in ("split", "merge", "mix"):
                lines.append(f"<b>{j['kind'].upper()}</b>"
                             + ("" if j["even_ok"] or j["kind"] == "merge" else
                                " - <span style='color:%s'>uneven planned split</span>" % RED))
                for lbl, f in j["ins"]:
                    lines.append(f"&nbsp;in&nbsp; {escape(lbl)}: {Fmt.rate(f)}")
                for lbl, f in j["outs"]:
                    lines.append(f"&nbsp;out {escape(lbl)}: {Fmt.rate(f)}")
                v = j.get("valve")
                if v:
                    if v.get("ok"):
                        lines.append(f"valve here: side {v['side_pct']:.1f}% / straight {v['straight_pct']:.1f}%")
                    else:
                        lines.append(f"<span style='color:{RED}'>valve needed: {escape(v.get('why') or '')}</span>")
                        for lbl, pc in v.get("split", []):
                            lines.append(f"&nbsp;&nbsp;set {escape(lbl)} → {pc:.1f}%")
            else:
                for a, vals in nfl["in"]:
                    lines.append(f"flow {_dir_arrow(a, node)} {self._flow_txt(vals)}")
                if not nfl["in"]:
                    for b, vals in nfl["out"]:
                        lines.append(f"flow {_dir_arrow(node, b)} {self._flow_txt(vals)}")
            for t in lay.term_at[pi].get(node, []):
                arrow = "pipe → " if t["direction"] == "input" else ""
                arrow2 = " → pipe" if t["direction"] == "output" else ""
                lines.append(f"<span style='color:{GREEN if t['direction'] == 'input' else '#e8590c'}'>"
                             f"{arrow}{escape(t['machine'])}{arrow2}: {Fmt.rate(t['rate'])}</span>")
            parts.append("<br>".join(lines))
        if not parts:
            return ""
        return (f"<div style='font-size:11px'><span style='color:{DIM}'>tile ({tile[0]}, {tile[1]}) · "
                f"{FLOW_MODES[self.mode.currentIndex()][1].lower()}</span><br>" + "<hr>".join(parts) + "</div>")

    # ---------------------------------------------------------------- click / details
    def _click(self, tile):
        lay = self.lay
        if lay is None:
            return
        mi = lay.machine_at.get(tile)
        if mi is not None:
            self._select_machine(mi)
            return
        on = lay.pipe_at.get(tile, [])
        if on:
            self._select_pipe(on[0][0])
            return
        self.clear_selection()

    def _select_machine(self, mi):
        m = self.lay.machines[mi]
        pipes = self.lay.pipes_of_inst[m["inst"]]
        self.scene.set_highlight(pipes, [mi])
        self._show_machine(mi)

    def _select_pipe(self, pi):
        p = self.lay.pipes[pi]
        mis = [self.lay.inst_index[t["inst"]] for t in p["terminals"] if t["inst"] in self.lay.inst_index]
        self.scene.set_highlight([pi], mis)
        self._show_pipe(pi)

    def _card(self, html):
        self.details.setHtml(f"<div style='color:{TEXT}; font-size:12px'>{html}</div>")
        self.right.show()

    def _show_machine(self, mi):
        m = self.lay.machines[mi]
        g = self.lay.groups[m["group"]]
        h = [f"<h3 style='color:{GOLD_TEXT}'>{escape(m['name'])}</h3>",
             f"<span style='color:{DIM}'>{escape(m['recipe'])} · machine {m['index']} of {m['count']} "
             f"(planner {g['planned']:.3f}) · {m['w']}x{m['h']} at ({m['x']}, {m['y']}), rotated {m['rotation']}°"
             f"</span>"]
        if m.get("valve"):
            v = m["valve"]
            h.append(f"<p><b>Valve {v['index']}/{v['of']} on {escape(v['product'])}</b><br>side outlet "
                     f"<b>{v['side_pct']:.2f}%</b> ({Fmt.rate(v['side_flow'])}) · straight {v['straight_pct']:.2f}% "
                     f"of {Fmt.rate(v['flow'])}</p>")
        r = m["run"]
        h.append(f"<p>Runs at <b>{pct(r['planned'])}</b> planned · <b>{pct(r['built'])}</b> in this layout"
                 f" · {pct(r['even_split'])} with plain even splits</p>")
        if g.get("power") is not None:
            pw = g["power"] * (r["planned"] or 0)
            h.append(f"<p>Power {'output' if pw < 0 else 'use'} {fmt_power(abs(pw))} {g.get('power_type') or ''}"
                     f" · pollution {fmt_pollution((g.get('pollution') or 0) * (r['planned'] or 0))}</p>")
        for key, title, colour, bg in (("inputs", "Inputs", GREEN, "#1a3a2a"), ("outputs", "Outputs", RED, "#3a1a1a")):
            rows = m["io"][key]
            if not rows:
                continue
            h.append(f"<p style='color:{colour}'><b>{title}</b></p><table width='100%' cellspacing='0' "
                     f"cellpadding='3' style='background:{bg}'>")
            for io in rows:
                t = io.get("temperature")
                extra = f" · {t:.1f}°C" if isinstance(t, (int, float)) else ""
                if io.get("self_feed"):
                    extra += f" · {Fmt.rate(io['self_feed'])} fed by itself (no pipe)"
                h.append(f"<tr><td>{escape(io['product'])}</td><td align='right'>{Fmt.rate(io['planned_rate'])}"
                         f" <span style='color:{DIM}'>(max {Fmt.rate(io['max_rate'])})</span>{extra}</td></tr>")
            h.append("</table>")
        h.append(f"<p style='color:{GOLD_TEXT}'><b>Ports</b></p>")
        for p in m["ports"]:
            if p["net"] is not None:
                net = self.lay.pipes[p["net"]]
                h.append(f"<div>{escape(p['id'])} ({p['direction']} {p['kind']}) → "
                         f"<a href='pipe:{p['net']}' style='color:{GOLD}'>{escape(net['label'])}</a> "
                         f"{Fmt.rate(p['rate'])}</div>")
            else:
                h.append(f"<div style='color:{DIM}'>{escape(p['id'])} ({p['direction']} {p['kind']}) - unused</div>")
        h.append(f"<p><a href='group:{m['group']}' style='color:{GOLD}'>show all {g['count']} of this group</a></p>")
        self._card("".join(h))

    def _show_pipe(self, pi):
        p = self.lay.pipes[pi]
        kind = "Large fluid pipe (2x2)" if p["large"] else ("Fluid pipe" if p["kind"] == "Fluid" else "Conveyor")
        h = [f"<h3 style='color:{hue(p['product']).name()}'>{escape(p['label'])}</h3>",
             f"<span style='color:{DIM}'>{kind} · flow {Fmt.rate(p['flow'])} · capacity {Fmt.rate(p['capacity'])}"
             + (f" · {p['temperature']:.1f}°C" if p.get("temperature") is not None else "")
             + f" · {len(p['nodes'])} tiles{'' if p['routed'] else ' · NOT ROUTED'}</span>"]
        if p.get("note"):
            h.append(f"<p style='color:#e8590c'>{escape(p['note'])}</p>")
        h.append(f"<p style='color:{GOLD_TEXT}'><b>Connections</b></p><table width='100%' cellpadding='2'>")
        for t in sorted(p["terminals"], key=lambda t: (t["direction"], t["machine"])):
            mi = self.lay.inst_index.get(t["inst"])
            col = GREEN if t["direction"] == "input" else "#e8590c"
            lbl = "takes" if t["direction"] == "input" else "gives"
            link = f"<a href='machine:{mi}' style='color:{col}'>{escape(t['machine'])}</a>" if mi is not None else \
                escape(t["machine"])
            h.append(f"<tr><td>{link}</td><td>{lbl}</td><td align='right'>{Fmt.rate(t['rate'])}</td></tr>")
        h.append("</table>")
        js = [j for j in p["junctions"] if j["kind"] in ("split", "merge", "mix")]
        if js:
            h.append(f"<p style='color:{GOLD_TEXT}'><b>Splits and joins</b> ({len(js)})</p>")
            for j in js[:60]:
                bad = j["kind"] != "merge" and not j["even_ok"]
                v = j.get("valve")
                tag = ""
                if v:
                    tag = (f" - valve {v['side_pct']:.1f}% side" if v.get("ok") else
                           f" - <span style='color:{RED}'>valve needed</span>")
                h.append(f"<div>{j['kind']} at {tuple(j['at'])}: in "
                         + ", ".join(Fmt.rate(f) for _, f in j["ins"]) + " → out "
                         + ", ".join(Fmt.rate(f) for _, f in j["outs"])
                         + (f" <span style='color:{RED}'>(uneven)</span>" if bad and not v else "") + tag + "</div>")
        self._card("".join(h))

    def _show_group(self, gi):
        g = self.lay.groups[gi]
        ev, vv = g.get("even_split"), g.get("with_valves")
        h = [f"<h3 style='color:{GOLD_TEXT}'>{g['count']} x {escape(g['name'])}</h3>",
             f"<span style='color:{DIM}'>{escape(g['recipe'])} · planner count {g['planned']:.4f}</span>"]
        if vv is not None:
            h.append(f"<p>Group output: <b>{100 * vv / max(g['planned'], 1e-9):.1f}%</b> of plan as built · "
                     f"{100 * ev / max(g['planned'], 1e-9):.1f}% with plain even splits</p>")
        for mi, m in enumerate(self.lay.machines):
            if m["group"] == gi:
                h.append(f"<div><a href='machine:{mi}' style='color:{GOLD}'>#{m['index']}</a> at ({m['x']}, {m['y']})"
                         f" · runs {pct(m['run']['built'])}</div>")
        self._card("".join(h))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = Viewer(argv[0] if argv else None)
    w.show()
    if not argv:
        w.open_dialog()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
