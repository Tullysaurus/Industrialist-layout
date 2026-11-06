"""A block = all machines of one recipe node arranged as a grid array with pipe corridors."""
from __future__ import annotations

import math
from collections import defaultdict

from .shapes import SIDES, rotate_side


def _lanes(small: float, large: float) -> int:
    """Corridor width (tiles) for pipes leaving one side; 2 pipes may share a tile."""
    return math.ceil(small / 2 - 1e-9) + 2 * math.ceil(large / 2 - 1e-9)


class Block:
    initial_slack = 1      # extra tiles of corridor on every side to start from
    def __init__(self, idx, node_idx, node, inst_ids, nets):
        self.idx = idx
        self.node_idx = node_idx
        self.node = node
        self.shape = node.shape
        self.inst_ids = inst_ids          # global instance ids, local index = position in list
        self.n = len(inst_ids)
        self.ext_int = 0                  # extra corridor width inside the block
        s0 = Block.initial_slack
        self.ext_side = {"left": s0, "top": s0, "right": s0, "bottom": s0}   # extra corridor per side
        self.acc = 0.75                   # how much pipe demand accumulates along a shared corridor
        self._cache = {}

        # per-side pipe demand of one machine (unrotated frame)
        local = {g: i for i, g in enumerate(inst_ids)}
        per_inst = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        for net in nets:
            for t in net.terminals:
                if t.inst not in local:
                    continue
                sides = {self.shape.ports[p].side for p in t.ports}
                for s in sides:
                    per_inst[t.inst][s][1 if net.large else 0] += 1.0 / len(sides)
        self.demand = {s: [0.0, 0.0] for s in SIDES}
        for d in per_inst.values():
            for s in SIDES:
                for k in (0, 1):
                    self.demand[s][k] = max(self.demand[s][k], d[s][k])
        self.base_lanes = {s: _lanes(*self.demand[s]) for s in SIDES}

    def lanes(self, rot, mult=1, acc=1.0):
        """Corridor width needed on each side after rotating by rot quarter turns, for a
        corridor shared by `mult` machines (pipes accumulate along the corridor)."""
        m = 1 + (mult - 1) * acc
        return {rotate_side(s, rot): (_lanes(v[0] * m, v[1] * m) if (v[0] or v[1]) else 0)
                for s, v in self.demand.items()}

    def options(self):
        """All (rot, cols, alt) arrangements worth trying."""
        rots = [0, 1, 2, 3]
        out = []
        for rot in rots:
            for cols in range(1, self.n + 1):
                rows = math.ceil(self.n / cols)
                if cols > 1 and math.ceil(self.n / (cols - 1)) == rows:
                    continue  # same rows with fewer columns: wasteful
                out.append((rot, cols, False))
                if rows > 1:
                    out.append((rot, cols, True))
        return out

    def default_option(self):
        best, best_score = None, None
        for opt in self.options():
            g = self.geometry(opt)
            score = max(g.w, g.h) * 4 + g.w * g.h / max(1, min(g.w, g.h))
            if best is None or score < best_score:
                best, best_score = opt, score
        return best

    def geometry(self, opt):
        key = (opt, self.ext_int, tuple(self.ext_side.values()), self.acc)
        g = self._cache.get(key)
        if g is None:
            g = BlockGeometry(self, *opt)
            self._cache[key] = g
        return g

    def clear_cache(self):
        self._cache.clear()

    def get_state(self):
        return (self.ext_int, dict(self.ext_side))

    def set_state(self, st):
        self.ext_int, self.ext_side = st[0], dict(st[1])
        self.clear_cache()


class BlockGeometry:
    def __init__(self, block: Block, rot: int, cols: int, alt: bool):
        n = block.n
        cols = min(cols, n)
        rows = math.ceil(n / cols)
        shapes = [block.shape.rot(rot), block.shape.rot(rot + 2)]
        acc = block.acc
        lr = [block.lanes(rot, cols, acc), block.lanes(rot + 2, cols, acc)]   # corridors along rows
        lc = [block.lanes(rot, rows, acc), block.lanes(rot + 2, rows, acc)]   # corridors along columns
        rowt = [(r % 2 if alt else 0) for r in range(rows)]
        types = set(rowt)
        W, H = shapes[0].w, shapes[0].h
        ei, es = block.ext_int, block.ext_side
        colgap = max(lc[t]["right"] + lc[t]["left"] for t in types) + ei if cols > 1 else 0
        rowgaps = [max(0, lr[rowt[r]]["bottom"] + lr[rowt[r + 1]]["top"] + ei) for r in range(rows - 1)]
        colgap = max(0, colgap)
        padL = max(0, max(lc[t]["left"] for t in types) + es["left"])
        padR = max(0, max(lc[t]["right"] for t in types) + es["right"])
        padT = max(0, lr[rowt[0]]["top"] + es["top"])
        padB = max(0, lr[rowt[-1]]["bottom"] + es["bottom"])
        if rows > 1 and n % cols:
            # machines in the second-to-last row with no machine below them expose their bottom side
            padB = max(padB, lr[rowt[-2]]["bottom"] + es["bottom"] - (H + rowgaps[-1]))
        self.rot, self.cols, self.rows, self.alt = rot, cols, rows, alt
        self.pad = (padL, padT, padR, padB)
        self.w = padL + cols * W + (cols - 1) * colgap + padR
        self.h = padT + rows * H + sum(rowgaps) + padB
        self.core = (padL, padT, self.w - padR, self.h - padB)
        self.items = []                 # (dx, dy, rotated shape, rotation)
        ys, y = [], padT
        for r in range(rows):
            ys.append(y)
            y += H + (rowgaps[r] if r < rows - 1 else 0)
        for i in range(n):
            r, c = divmod(i, cols)
            t = rowt[r]
            self.items.append((padL + c * (W + colgap), ys[r], shapes[t], (rot + 2 * t) % 4))
        self._tp = {}

    def term_pos(self, local_i, ports):
        key = (local_i, ports)
        v = self._tp.get(key)
        if v is None:
            dx, dy, sh, _ = self.items[local_i]
            xs, ys = [], []
            for p in ports:
                for (x, y) in sh.ports[p].access_cells():
                    xs.append(x)
                    ys.append(y)
            v = (dx + sum(xs) / len(xs) + 0.5, dy + sum(ys) / len(ys) + 0.5)
            self._tp[key] = v
        return v
