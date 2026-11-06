"""Group tightly connected machines (e.g. coal plant + its heat exchanger + turbines) into
modules ("macros") that are laid out once and placed as a unit."""
from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

from .blocks import Block
from .placer import Placer
from .shapes import rotate_side


def instance_clusters(problem, max_terms=8, max_members=26, area_frac=1 / 4, min_weight=0.15):
    nets = problem.nets
    area = {}
    for g, (ni, _) in enumerate(problem.instances):
        sh = problem.nodes[ni].shape
        area[g] = sum(r.w * r.h for r in sh.rects)
    total = sum(area.values())
    w = defaultdict(float)
    for net in nets:
        if net.stub:
            continue
        insts = sorted({t.inst for t in net.terminals})
        if not (2 <= len(insts) <= max_terms):
            continue
        val = (3.0 if net.large else 1.0) / (len(insts) - 1)
        for i in range(len(insts)):
            for j in range(i + 1, len(insts)):
                w[(insts[i], insts[j])] += val
    parent = {g: g for g in area}
    members = {g: [g] for g in area}
    carea = dict(area)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    # cluster-level weights, merged greedily strongest first
    while True:
        cw = defaultdict(float)
        for (a, b), v in w.items():
            ra, rb = find(a), find(b)
            if ra != rb:
                cw[(min(ra, rb), max(ra, rb))] += v
        best = None
        for (ra, rb), v in cw.items():
            if v < min_weight:
                continue
            biggest = max(max(area[g] for g in members[ra]), max(area[g] for g in members[rb]))
            limit = max(total * area_frac, biggest * 2.2)
            if carea[ra] + carea[rb] > limit or len(members[ra]) + len(members[rb]) > max_members:
                continue
            spaced = [problem.nodes[problem.instances[g][0]].shape.id for g in members[ra] + members[rb]
                      if problem.spacing_of(g)]
            if len(spaced) != len(set(spaced)):
                continue   # two machines that must be far apart cannot share a compact module
            # prefer strong links relative to the size they add
            score = v / (len(members[ra]) + len(members[rb])) ** 0.5
            if best is None or score > best[0]:
                best = (score, ra, rb)
        if best is None:
            break
        _, ra, rb = best
        parent[rb] = ra
        members[ra] += members.pop(rb)
        carea[ra] += carea.pop(rb)
    return [sorted(m, key=lambda g: (problem.instances[g][0], problem.instances[g][1]))
            for r, m in members.items() if find(r) == r]


def signature(problem, members):
    pos = {g: i for i, g in enumerate(members)}
    sig_nets = []
    for net in problem.nets:
        ts = tuple(sorted((pos[t.inst], t.ports) for t in net.terminals if t.inst in pos))
        if len(ts) >= (1 if net.stub else 2):
            sig_nets.append((net.large, net.stub, ts))
    return (tuple(problem.instances[g][0] for g in members), tuple(sorted(sig_nets)))


class MacroLayout:
    """Internal arrangement of one module type (shared by identical modules).

    The arrangement (sequence pair + rotations) is solved once; afterwards only the
    corridor widths of individual members change and the module is re-packed."""

    def __init__(self, problem, members, seconds=1.0, seed=0, wire_weight=1.0):
        self.problem = problem
        self.members = members        # instance ids of the representative module
        self.seconds, self.seed, self.wire_weight = seconds, seed, wire_weight
        self.cache = {}
        self.placer = None

    def _solve(self):
        pos = {g: i for i, g in enumerate(self.members)}
        sub_nets = []
        for net in self.problem.nets:
            ts = [t for t in net.terminals if t.inst in pos]
            if len(ts) >= (1 if net.stub else 2):
                sub_nets.append(SimpleNamespace(stub=net.stub, large=net.large, terminals=ts))
        blocks = []
        inst_block = {}
        for k, g in enumerate(self.members):
            ni = self.problem.instances[g][0]
            blocks.append(Block(k, ni, self.problem.nodes[ni], [g], self.problem.nets))
            inst_block[g] = (k, 0)
        self.placer = Placer(blocks, sub_nets, inst_block, wire_weight=self.wire_weight, seed=self.seed)
        self.state, _, _ = self.placer.anneal(None, self.seconds)

    @property
    def members_blocks(self):
        if self.placer is None:
            self._solve()
        return self.placer.blocks

    def key(self):
        return tuple(tuple(b.ext_side.values()) for b in self.members_blocks)

    def build(self):
        k = self.key()
        if k not in self.cache:
            xs, ys, W, H, geos = self.placer.evaluate(self.state)[1][:5]
            items = []
            for i in range(len(self.placer.blocks)):
                dx, dy, sh, rot = geos[i].items[0]
                items.append((xs[i] + dx, ys[i] + dy, sh, rot))
            self.cache[k] = (W, H, items)
        return self.cache[k]

    def get_state(self):
        return [dict(b.ext_side) for b in self.members_blocks]

    def set_state(self, st):
        for b, es in zip(self.members_blocks, st):
            b.ext_side = dict(es)
            b.clear_cache()


class MacroGeometry:
    def __init__(self, W, H, items, rot, pad):
        """pad = (left, top, right, bottom) extra corridor in the placed orientation."""
        for _ in range(rot % 4):
            items = [(H - dy - sh.h, dx, sh.rot(1), (r + 1) % 4) for dx, dy, sh, r in items]
            W, H = H, W
        pl, pt, pr, pb = pad
        self.items = [(dx + pl, dy + pt, sh, r) for dx, dy, sh, r in items]
        self.w, self.h = W + pl + pr, H + pt + pb
        self.pad = pad
        self.core = (pl, pt, self.w - pr, self.h - pb)
        self.rot, self.cols, self.rows, self.alt = rot, 1, 1, False
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


class Macro:
    """Placer-compatible block made of several different machines."""

    def __init__(self, idx, problem, members, layout: MacroLayout):
        self.idx = idx
        self.inst_ids = members
        self.n = len(members)
        self.node_idx = problem.instances[members[0]][0]
        self.node = problem.nodes[self.node_idx]
        names = defaultdict(int)
        for g in members:
            names[problem.nodes[problem.instances[g][0]].shape.name] += 1
        self.label = " + ".join(f"{c}x {n}" if c > 1 else n for n, c in names.items())
        self.layout = layout
        self.ext_side = {"left": 0, "top": 0, "right": 0, "bottom": 0}
        self._cache = {}

    def options(self):
        return [(r, 1, False) for r in range(4)]

    def default_option(self):
        return (0, 1, False)

    def geometry(self, opt):
        pad = tuple(max(0, self.ext_side[k]) for k in ("left", "top", "right", "bottom"))
        key = (opt, self.layout.key(), pad)
        g = self._cache.get(key)
        if g is None:
            W, H, items = self.layout.build()
            g = MacroGeometry(W, H, items, opt[0], pad)
            self._cache[key] = g
        return g

    def clear_cache(self):
        self._cache.clear()

    def get_state(self):
        return (dict(self.ext_side), self.layout.get_state())

    def set_state(self, st):
        self.ext_side = dict(st[0])
        self.layout.set_state(st[1])
        self.clear_cache()

    def widen_inner(self, points, geo, step=1):
        """Widen the corridor of the member machine(s) nearest to congested points
        (points in block-local coordinates of geometry geo)."""
        touched = {}
        for (x, y) in points:
            best = None
            for k, (dx, dy, sh, _) in enumerate(geo.items):
                ddx = max(dx - x, 0, x - (dx + sh.w - 1))
                ddy = max(dy - y, 0, y - (dy + sh.h - 1))
                d = ddx + ddy
                if best is None or d < best[0]:
                    if x < dx:
                        side = "left"
                    elif x >= dx + sh.w:
                        side = "right"
                    elif y < dy:
                        side = "top"
                    else:
                        side = "bottom"
                    best = (d, k, side)
            _, k, side = best
            base_side = rotate_side(side, (4 - geo.rot) % 4)   # back to the module frame
            touched[(k, base_side)] = touched.get((k, base_side), 0) + 1
        blocks = self.layout.members_blocks
        for (k, side), n in touched.items():
            blocks[k].ext_side[side] += step if n < 10 else step + 1
            blocks[k].clear_cache()
        self.clear_cache()
        return len(touched)
