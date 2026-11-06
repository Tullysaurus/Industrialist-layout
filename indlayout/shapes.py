"""Machine footprints, ports and rotation (90 degree steps, no mirroring)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

ROT_SIDE = {"top": "right", "right": "bottom", "bottom": "left", "left": "top"}
OUTWARD = {"top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0)}
SIDES = ("top", "right", "bottom", "left")


def rotate_side(side: str, k: int) -> str:
    for _ in range(k % 4):
        side = ROT_SIDE[side]
    return side


@dataclass(frozen=True)
class Port:
    id: str
    kind: str          # "Item" | "Fluid"
    direction: str     # "input" | "output"
    side: str
    cells: tuple       # tiles of the machine (local coords) the port occupies
    width: int

    def rotated(self, w: int, h: int) -> "Port":
        """Rotate 90 degrees clockwise inside a w x h footprint."""
        cells = tuple(sorted((h - 1 - y, x) for x, y in self.cells))
        return Port(self.id, self.kind, self.direction, ROT_SIDE[self.side], cells, self.width)

    def shifted(self, dx: int, dy: int, new_id: str | None = None) -> "Port":
        return Port(new_id or self.id, self.kind, self.direction, self.side,
                    tuple((x + dx, y + dy) for x, y in self.cells), self.width)

    def access_cells(self):
        """Tiles directly outside the port where a normal pipe can attach."""
        dx, dy = OUTWARD[self.side]
        return [(x + dx, y + dy) for x, y in self.cells]

    def large_anchor(self):
        """Top-left tile of the 2x2 large pipe that attaches to this port."""
        x0 = min(c[0] for c in self.cells)
        y0 = min(c[1] for c in self.cells)
        return {"top": (x0, y0 - 2), "bottom": (x0, y0 + 1),
                "left": (x0 - 2, y0), "right": (x0 + 1, y0)}[self.side]


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int
    label: str
    machine_id: str


@dataclass
class Shape:
    id: str
    name: str
    w: int
    h: int
    rects: list
    ports: dict           # port id -> Port
    category: str = ""
    _rot: dict = field(default_factory=dict, repr=False)

    def rotated_once(self) -> "Shape":
        w, h = self.w, self.h
        rects = [Rect(h - r.y - r.h, r.x, r.h, r.w, r.label, r.machine_id) for r in self.rects]
        ports = {pid: p.rotated(w, h) for pid, p in self.ports.items()}
        return Shape(self.id, self.name, h, w, rects, ports, self.category)

    def rot(self, k: int) -> "Shape":
        k %= 4
        if k == 0:
            return self
        if k not in self._rot:
            s = self
            for _ in range(k):
                s = s.rotated_once()
            self._rot[k] = s
        return self._rot[k]

    def occupied(self):
        for r in self.rects:
            for yy in range(r.y, r.y + r.h):
                for xx in range(r.x, r.x + r.w):
                    yield xx, yy


def port_cells(p: dict):
    x, y, w = int(p["x"]), int(p["y"]), int(p.get("width", 1))
    if p["side"] in ("top", "bottom"):
        return tuple((x + i, y) for i in range(w))
    return tuple((x, y + i) for i in range(w))


def machine_shape(m: dict) -> Shape:
    w, h = int(m["size"]["x"]), int(m["size"]["y"])
    ports = {}
    for p in m.get("ports", []):
        if p.get("type") != "product" or "side" not in p:
            continue  # power/data ports are ignored (no pole data available)
        ports[p["id"]] = Port(p["id"], p.get("product_type", "Item"), p["direction"], p["side"],
                              port_cells(p), int(p.get("width", 1)))
    return Shape(m["id"], m["name"], w, h, [Rect(0, 0, w, h, m["name"], m["id"])], ports,
                 m.get("category", ""))


class Composite:
    """Helper that assembles several machine shapes into one footprint."""

    def __init__(self, sid: str, name: str):
        self.sid, self.name = sid, name
        self.rects: list[Rect] = []
        self.ports: dict[str, Port] = {}
        self._count: dict[str, int] = {}

    def add(self, shape: Shape, x: int, y: int, keep_ports=True):
        for r in shape.rects:
            self.rects.append(Rect(r.x + x, r.y + y, r.w, r.h, r.label, r.machine_id))
        if keep_ports:
            for pid, p in shape.ports.items():
                n = self._count.get(pid, 0)
                self._count[pid] = n + 1
                self.ports[f"{pid}#{n}"] = p.shifted(x, y, f"{pid}#{n}")

    def build(self, category="Composite") -> Shape:
        minx = min(r.x for r in self.rects)
        miny = min(r.y for r in self.rects)
        maxx = max(r.x + r.w for r in self.rects)
        maxy = max(r.y + r.h for r in self.rects)
        rects = [Rect(r.x - minx, r.y - miny, r.w, r.h, r.label, r.machine_id) for r in self.rects]
        ports = {pid: p.shifted(-minx, -miny) for pid, p in self.ports.items()}
        return Shape(self.sid, self.name, maxx - minx, maxy - miny, rects, ports, category)


def modular_turbine(shapes: dict, n_lpt: int, n_hpt: int) -> Shape:
    """turbine input, n LPT, 1 IPT, n HPT, generator, turbine output, laid end to end."""
    parts = (["m_turbine_input"] + ["m_low_pressure_turbine"] * n_lpt
             + ["m_intermediate_pressure_turbine"] + ["m_high_pressure_turbine"] * n_hpt
             + ["m_turbine_generator", "m_turbine_output"])
    c = Composite(f"modular_turbine_{n_lpt}l_{n_hpt}h", f"Modular Turbine ({n_lpt} LPT, {n_hpt} HPT)")
    height = max(shapes[p].h for p in parts)
    x = 0
    for p in parts:
        s = shapes[p]
        c.add(s, x, (height - s.h) // 2, keep_ports=p in ("m_turbine_input", "m_turbine_output"))
        x += s.w
    return c.build()


def tree_farm(shapes: dict, settings: dict, trees_per_sprinkler: int = 44) -> Shape:
    """Tree farm following the wiki guide: a 7x7 block of tree cells (corners cut) around
    each sprinkler, harvesters on the outer corners, outputs in the cut corners between
    the squares, controller + water tanks in a strip above the farm."""
    T = int(settings.get("tree_count", 88))
    H = int(settings.get("harvester_count", 4))
    S_req = int(settings.get("sprinkler_count", 2))
    O = max(1, int(settings.get("outputs_count", 1)))
    tree = shapes[settings.get("tree_id", "m_tree")]
    ctrl = shapes[settings.get("controller_id", "m_tree_farm_controller")]
    spr = shapes["m_tree_farm_sprinkler"]
    harv = shapes["m_farm_harvester"]
    out = shapes["m_tree_farm_output"]
    tank = shapes["m_tree_farm_water_tank"]
    c = tree.w  # cell size (4 tiles)

    S = max(1, math.ceil(T / trees_per_sprinkler))
    comp = Composite("tree_farm", f"Tree Farm ({T} trees)")
    sprinklers = [(7 * s + 3, 3) for s in range(S)]
    corners = {(7 * s + a, b) for s in range(S) for a in (0, 6) for b in (0, 6)}
    slots = [(x, y) for y in range(7) for x in range(7 * S)
             if (x, y) not in corners and (x, y) not in sprinklers]

    def dist(cell):
        return min(max(abs(cell[0] - sx), abs(cell[1] - sy)) + 0.01 * math.hypot(cell[0] - sx, cell[1] - sy)
                   for sx, sy in sprinklers)

    slots.sort(key=dist)
    tree_cells, spare = slots[:T], slots[T:]
    for cx, cy in tree_cells:
        comp.add(tree, cx * c, cy * c)
    for cx, cy in sprinklers:
        comp.add(spr, cx * c, cy * c)

    bottom_seams = [(7 * s + a, 6) for s in range(S - 1) for a in (6, 7)]
    top_seams = [(7 * s + a, 0) for s in range(S - 1) for a in (6, 7)]
    bottom_free = bottom_seams + [cl for cl in spare if cl[1] == 6]
    other_free = top_seams + [cl for cl in spare if cl[1] != 6]

    # outputs need their (bottom) port to face open space -> bottom seams first
    overflow_bottom = []
    for i in range(O):
        if bottom_free:
            cx, cy = bottom_free.pop(0)
            comp.add(out, cx * c, cy * c)
        else:
            overflow_bottom.append(out)
    extra_spr = max(0, S_req - S)
    free = other_free + bottom_free
    for _ in range(extra_spr):
        if free:
            cx, cy = free.pop(0)
            comp.add(spr, cx * c, cy * c)
        else:
            overflow_bottom.append(spr)

    # harvesters (2x2 cells) covering the outer cut corners
    hpos = [(-1, -1), (7 * S - 1, -1), (-1, 6), (7 * S - 1, 6)]
    for i in range(H):
        if i < 4:
            hx, hy = hpos[i]
        else:  # extras above the farm
            hx, hy = 1 + 2 * (i - 4), -3
        comp.add(harv, hx * c, hy * c)

    # strip above: water tanks (1 per 3 sprinklers) + controller, ports face up/out
    n_tanks = max(1, math.ceil(max(S, S_req) / 3))
    items = [tank] * n_tanks + [ctrl]
    x0, x1 = c, (7 * S - 1) * c
    x, row = x0, 0
    for it in items:
        if x + it.w > x1:
            row += 1
            x, x1 = -c, (7 * S + 1) * c
        y = -c * (row + 1) - row - (it.h - c)   # 1-tile gap between strips for pipes
        comp.add(it, x, y)
        x += it.w
    # anything that did not fit in the cut corners goes in a row under the farm
    x = c
    for it in overflow_bottom:
        comp.add(it, x, 7 * c)
        x += it.w + 1
    return comp.build()
