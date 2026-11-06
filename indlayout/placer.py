"""Simulated annealing over a sequence-pair floorplan of blocks."""
from __future__ import annotations

import math
import random
import time

from .spacing import violations


def pack(seq_a, seq_b, ws, hs):
    n = len(seq_a)
    pos_b = [0] * n
    for k, b in enumerate(seq_b):
        pos_b[b] = k
    xs = [0] * n
    ys = [0] * n
    for idx, j in enumerate(seq_a):
        xj = yj = 0
        pj = pos_b[j]
        for t in range(idx):
            i = seq_a[t]
            if pos_b[i] < pj:          # i before j in both sequences: i is left of j
                v = xs[i] + ws[i]
                if v > xj:
                    xj = v
            else:                      # i before j in A, after in B: i is above j
                v = ys[i] + hs[i]
                if v > yj:
                    yj = v
        xs[j], ys[j] = xj, yj
    W = max(xs[i] + ws[i] for i in range(n))
    H = max(ys[i] + hs[i] for i in range(n))
    return xs, ys, W, H


class State:
    __slots__ = ("a", "b", "opt")

    def __init__(self, a, b, opt):
        self.a, self.b, self.opt = a, b, opt

    def copy(self):
        return State(self.a[:], self.b[:], self.opt[:])


class Placer:
    def __init__(self, blocks, nets, inst_block, wire_weight=1.0, seed=0, spaced=None, measure="edge",
                 spacing_weight=4000.0):
        """spaced: list of (machine id, instance id, min distance) that must keep their distance."""
        self.blocks = blocks
        self.measure = measure
        self.spacing_weight = spacing_weight
        self.spaced = [(mid, inst_block[g][0], inst_block[g][1], d) for mid, g, d in (spaced or [])
                       if g in inst_block]
        self.rng = random.Random(seed)
        self.wire_weight = wire_weight
        self.options = [b.options() for b in blocks]
        # nets as lists of (block, local index, ports)
        self.nets = []
        for net in nets:
            if net.stub:
                continue
            terms = [(inst_block[t.inst][0], inst_block[t.inst][1], t.ports) for t in net.terminals]
            if len({t[0] for t in terms}) < 1:
                continue
            self.nets.append((terms, 2.0 if net.large else 1.0))

    def initial(self):
        order = sorted(range(len(self.blocks)), key=lambda i: -self.blocks[i].geometry(
            self.blocks[i].default_option()).w * self.blocks[i].geometry(self.blocks[i].default_option()).h)
        a = order[:]
        b = order[:]
        return State(a, b, [blk.default_option() for blk in self.blocks])

    def evaluate(self, st: State):
        geos = [blk.geometry(st.opt[i]) for i, blk in enumerate(self.blocks)]
        xs, ys, W, H = pack(st.a, st.b, [g.w for g in geos], [g.h for g in geos])
        wl = 0.0
        for terms, wgt in self.nets:
            minx = miny = 1e18
            maxx = maxy = -1e18
            for b, li, ports in terms:
                px, py = geos[b].term_pos(li, ports)
                px += xs[b]
                py += ys[b]
                if px < minx: minx = px
                if px > maxx: maxx = px
                if py < miny: miny = py
                if py > maxy: maxy = py
            wl += wgt * ((maxx - minx) + (maxy - miny))
        viol = 0.0
        if self.spaced:
            rects = []
            for mid, b, li, d in self.spaced:
                dx, dy, sh, _ = geos[b].items[li]
                rects.append(((mid,), (xs[b] + dx, ys[b] + dy, sh.w, sh.h), d))
            for _, _, dist, req in violations(rects, self.measure):
                viol += req - dist
        cost = W * H + self.wire_weight * wl + self.spacing_weight * viol
        self.last_violation = viol
        return cost, (xs, ys, W, H, geos, wl, viol)

    def neighbor(self, st: State):
        s = st.copy()
        n = len(s.a)
        r = self.rng.random()
        if n >= 2 and r < 0.30:
            i, j = self.rng.sample(range(n), 2)
            s.a[i], s.a[j] = s.a[j], s.a[i]
        elif n >= 2 and r < 0.60:
            i, j = self.rng.sample(range(n), 2)
            s.b[i], s.b[j] = s.b[j], s.b[i]
        elif n >= 2 and r < 0.75:
            x, y = self.rng.sample(range(n), 2)
            ia, ja = s.a.index(x), s.a.index(y)
            ib, jb = s.b.index(x), s.b.index(y)
            s.a[ia], s.a[ja] = s.a[ja], s.a[ia]
            s.b[ib], s.b[jb] = s.b[jb], s.b[ib]
        elif n >= 2 and r < 0.82:
            # move one block to a new position in both sequences
            x = self.rng.randrange(n)
            s.a.remove(x)
            s.a.insert(self.rng.randrange(n), x)
            s.b.remove(x)
            s.b.insert(self.rng.randrange(n), x)
        else:
            k = self.rng.randrange(n)
            opts = self.options[k]
            if len(opts) > 1:
                cur = s.opt[k]
                rr = self.rng.random()
                if rr < 0.5:
                    # nudge: same rotation/alt, neighbouring column count
                    same = [o for o in opts if o[0] == cur[0] and o[2] == cur[2]]
                    same.sort(key=lambda o: o[1])
                    if cur in same:
                        i = same.index(cur) + self.rng.choice((-1, 1))
                        if 0 <= i < len(same):
                            s.opt[k] = same[i]
                    else:
                        s.opt[k] = self.rng.choice(opts)
                elif rr < 0.8:
                    s.opt[k] = ((cur[0] + self.rng.choice((1, 2, 3))) % 4, cur[1], cur[2])
                    if s.opt[k] not in opts:
                        s.opt[k] = self.rng.choice(opts)
                else:
                    s.opt[k] = self.rng.choice(opts)
        return s

    def anneal(self, state: State | None, seconds: float, t_start=None, t_end_frac=1e-4, log=None, t_scale=1.0):
        st = state.copy() if state else self.initial()
        cost, info = self.evaluate(st)
        best, best_cost, best_info = st.copy(), cost, info
        # estimate temperature from random move deltas
        if t_start is None:
            deltas = []
            for _ in range(60):
                c2, _ = self.evaluate(self.neighbor(st))
                deltas.append(abs(c2 - cost))
            t_start = (sum(deltas) / len(deltas)) * 0.5 * t_scale + 1e-9
        t_end = max(t_start * t_end_frac, 1e-6)
        t0 = time.time()
        it = 0
        T = t_start
        while True:
            it += 1
            if it % 64 == 0:
                frac = (time.time() - t0) / seconds
                if frac >= 1:
                    break
                T = t_start * (t_end / t_start) ** frac
            cand = self.neighbor(st)
            c2, inf2 = self.evaluate(cand)
            d = c2 - cost
            if d <= 0 or self.rng.random() < math.exp(-d / T):
                st, cost, info = cand, c2, inf2
                if cost < best_cost:
                    best, best_cost, best_info = st.copy(), cost, info
        if log:
            log(f"  placement: {it} iterations, bbox {best_info[2]}x{best_info[3]} = "
                f"{best_info[2] * best_info[3]} tiles, est. pipe length {best_info[5]:.0f}"
                + (f", SPACING SHORT BY {best_info[6]:.0f} tiles" if best_info[6] > 0 else ""))
        return best, best_cost, best_info
