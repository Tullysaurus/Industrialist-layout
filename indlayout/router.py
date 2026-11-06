"""Grid pipe router: A* Steiner trees + PathFinder negotiated congestion.

Tile rules:
  * pipes never pass through machines
  * a tile holds at most 2 normal pipes (crossing via intersection or side by side),
    items and fluids may share
  * large fluid pipes are 2x2 tiles; a tile holds at most 2 large pipes and never
    mixes large with normal pipes
"""
from __future__ import annotations

import heapq
import time

INF = float("inf")


class Router:
    def __init__(self, gw, gh, blocked, nets, share_cost=0.35, bend_cost=0.25, h_weight=1.25,
                 mixed_crossing=False, jump=3, jump_cost=3.0):
        """nets: list of dicts {large: bool, stub: bool, terms: [set(cell or anchor idx)]}"""
        self.gw, self.gh = gw, gh
        self.N = gw * gh
        self.blocked = blocked
        bl = bytearray(self.N)
        for y in range(gh):
            row = y * gw
            for x in range(gw):
                c = row + x
                if (x >= gw - 1 or y >= gh - 1 or blocked[c] or blocked[c + 1]
                        or blocked[c + gw] or blocked[c + gw + 1]):
                    bl[c] = 1
        self.blocked_l = bl
        self.nets = nets
        self.occ_s = [0] * self.N
        self.occ_l = [0] * self.N
        self.hist = [0.0] * self.N
        self.cells = [set() for _ in nets]      # tiles occupied by each net
        self.tree = [set() for _ in nets]       # anchors (tiles or 2x2 anchors) of each net
        self.edges = [[] for _ in nets]
        self.failed = set()
        self.share_cost, self.bend_cost, self.h_weight = share_cost, bend_cost, h_weight
        self.pres = 0.5
        self.mix = 0 if mixed_crossing else 1   # 1: normal and large pipes may not share a tile
        self.nb = ((1, 0, 1), (-1, 0, -1), (0, 1, gw), (0, -1, -gw))
        # quantum piping: a pipe may hop straight over other pipes to a bore up to `jump` tiles away
        self.jump, self.jump_cost = max(1, int(jump or 1)), jump_cost

    # ------------------------------------------------------------------ helpers
    def fp(self, a):
        g = self.gw
        return (a, a + 1, a + g, a + g + 1)

    def over_amount(self, c):
        s, l = self.occ_s[c], self.occ_l[c]
        if self.mix:
            return max(0, s - 2) + max(0, l - 2) + (min(s, l) if s and l else 0)
        return max(0, s + l - 2)

    def ripup(self, ni):
        for c in self.cells[ni]:
            if self.nets[ni]["large"]:
                self.occ_l[c] -= 1
            else:
                self.occ_s[c] -= 1
        self.cells[ni] = set()
        self.tree[ni] = set()
        self.edges[ni] = []

    def commit(self, ni, tree, edges):
        large = self.nets[ni]["large"]
        cells = set()
        if large:
            for a in tree:
                cells.update(self.fp(a))
            for c in cells:
                self.occ_l[c] += 1
        else:
            cells = set(tree)
            for c in cells:
                self.occ_s[c] += 1
        self.cells[ni], self.tree[ni], self.edges[ni] = cells, set(tree), edges

    def cell_cost_small(self, c):
        s, l = self.occ_s[c], self.occ_l[c]
        over = ((s - 1 if s >= 2 else 0) + l) if self.mix else max(0, s + l - 1)
        return (1.0 + self.hist[c]) * (1.0 + self.pres * over) + self.share_cost * (s + l)

    def anchor_cost_large(self, a, own_cells):
        tot = 0.0
        for c in self.fp(a):
            if c in own_cells:
                continue
            s, l = self.occ_s[c], self.occ_l[c]
            over = ((l - 1 if l >= 2 else 0) + s) if self.mix else max(0, s + l - 1)
            tot += (1.0 + self.hist[c]) * (1.0 + self.pres * over) + self.share_cost * (s + l)
        return tot * 0.5

    # ------------------------------------------------------------------ A*
    def astar(self, sources, targets, large, own, own_cells, window):
        gw = self.gw
        x0, y0, x1, y1 = window
        if large:
            x1 = min(x1, gw - 2)
            y1 = min(y1, self.gh - 2)
        txs = [t % gw for t in targets]
        tys = [t // gw for t in targets]
        tx0, tx1, ty0, ty1 = min(txs), max(txs), min(tys), max(tys)
        hw = self.h_weight
        blocked = self.blocked_l if large else self.blocked
        occ_s, occ_l, hist = self.occ_s, self.occ_l, self.hist
        pres, share, bend, mix = self.pres, self.share_cost, self.bend_cost, self.mix
        jump, jcost = self.jump, self.jump_cost
        g = {}
        came = {}
        dirc = {}
        heap = []
        for s in sources:
            g[s] = 0.0
            came[s] = -1
            dirc[s] = -1
            sx, sy = s % gw, s // gw
            h = (tx0 - sx if sx < tx0 else (sx - tx1 if sx > tx1 else 0)) + \
                (ty0 - sy if sy < ty0 else (sy - ty1 if sy > ty1 else 0))
            heap.append((h * hw, 0.0, s))
        heapq.heapify(heap)
        nb = self.nb
        found = -1
        while heap:
            f, gc, c = heapq.heappop(heap)
            if gc > g[c]:
                continue
            if c in targets:
                found = c
                break
            cx, cy = c % gw, c // gw
            dc = dirc[c]
            for d in range(4):
                ddx, ddy, off = nb[d]
                nx, ny = cx + ddx, cy + ddy
                if nx < x0 or nx > x1 or ny < y0 or ny > y1:
                    continue
                n = c + off
                if blocked[n]:
                    continue
                if n in own:
                    step = 0.0
                elif large:
                    step = self.anchor_cost_large(n, own_cells)
                else:
                    s_, l_ = occ_s[n], occ_l[n]
                    ov = ((s_ - 1 if s_ >= 2 else 0) + l_) if mix else (s_ + l_ - 1 if s_ + l_ >= 2 else 0)
                    step = (1.0 + hist[n]) * (1.0 + pres * ov) + share * (s_ + l_)
                if dc >= 0 and d != dc:
                    step += bend
                ng = gc + step
                if ng < g.get(n, INF):
                    g[n] = ng
                    came[n] = c
                    dirc[n] = d
                    h = (tx0 - nx if nx < tx0 else (nx - tx1 if nx > tx1 else 0)) + \
                        (ty0 - ny if ny < ty0 else (ny - ty1 if ny > ty1 else 0))
                    heapq.heappush(heap, (ng + hw * h, ng, n))
                if jump > 1 and n not in own:
                    # quantum piping: hop over the pipe(s) in front (never over machines)
                    if large:
                        foreign = any(occ_s[q] or occ_l[q] >= 2 for q in self.fp(n))
                    else:
                        foreign = occ_l[n] > 0 if mix else occ_s[n] + occ_l[n] >= 2
                    if not foreign:
                        continue
                    for k in range(2, jump + 1):
                        jx, jy = cx + ddx * k, cy + ddy * k
                        if jx < x0 or jx > x1 or jy < y0 or jy > y1:
                            break
                        m = c + off * k
                        if blocked[m]:
                            break
                        if m in own:
                            step = 0.0
                        elif large:
                            step = self.anchor_cost_large(m, own_cells)
                        else:
                            s_, l_ = occ_s[m], occ_l[m]
                            ov = ((s_ - 1 if s_ >= 2 else 0) + l_) if mix else (s_ + l_ - 1 if s_ + l_ >= 2 else 0)
                            step = (1.0 + hist[m]) * (1.0 + pres * ov) + share * (s_ + l_)
                        ng = gc + step + (k - 1) + jcost + (bend if dc >= 0 and d != dc else 0.0)
                        if ng < g.get(m, INF):
                            g[m] = ng
                            came[m] = c
                            dirc[m] = d
                            h = (tx0 - jx if jx < tx0 else (jx - tx1 if jx > tx1 else 0)) + \
                                (ty0 - jy if jy < ty0 else (jy - ty1 if jy > ty1 else 0))
                            heapq.heappush(heap, (ng + hw * h, ng, m))
        if found < 0:
            return None
        path = [found]
        while came[path[-1]] != -1:
            path.append(came[path[-1]])
        path.reverse()
        return path

    def _bbox(self, cells, pad):
        gw = self.gw
        xs = [c % gw for c in cells]
        ys = [c // gw for c in cells]
        return (max(0, min(xs) - pad), max(0, min(ys) - pad),
                min(gw - 1, max(xs) + pad), min(self.gh - 1, max(ys) + pad))

    def route_net(self, ni):
        net = self.nets[ni]
        large = net["large"]
        terms = [t for t in net["terms"] if t]
        if len(terms) < len(net["terms"]):
            return False
        if net["stub"]:
            if large:
                best = min(terms[0], key=lambda a: self.anchor_cost_large(a, ()))
            else:
                best = min(terms[0], key=self.cell_cost_small)
            self.commit(ni, {best}, [])
            return True
        gw = self.gw
        tree = set()
        own_cells = set()
        edges = []
        remaining = list(range(1, len(terms)))
        srcs = terms[0]
        cent = [(sum(c % gw for c in t) / len(t), sum(c // gw for c in t) / len(t)) for t in terms]
        while remaining:
            base = tree or srcs
            bx0, by0, bx1, by1 = self._bbox(base, 0)

            def dist(j):
                x, y = cent[j]
                return max(bx0 - x, 0, x - bx1) + max(by0 - y, 0, y - by1)

            j = min(remaining, key=dist)
            remaining.remove(j)
            if tree & terms[j]:
                continue
            path = None
            for pad in (12, 40, None):
                if pad is None:
                    window = (0, 0, gw - 1, self.gh - 1)
                else:
                    window = self._bbox(list(base) + list(terms[j]), pad)
                path = self.astar(base, terms[j], large, tree, own_cells, window)
                if path is not None:
                    break
            if path is None:
                self.commit(ni, tree, edges)
                return False
            for a, b in zip(path, path[1:]):
                edges.append((a, b))
            tree.update(path)
            if large:
                for a in path:
                    own_cells.update(self.fp(a))
        self.commit(ni, tree, edges)
        return True

    # ------------------------------------------------------------------ PathFinder
    def run(self, time_limit=60.0, max_iters=40, log=None):
        t0 = time.time()
        order = sorted(range(len(self.nets)), key=lambda i: (self.nets[i]["stub"], -self._span(i)))
        todo = order
        self.pres = 0.5
        best_over, stall = None, 0
        for it in range(max_iters):
            tp = time.time()
            self.failed = set()
            for ni in todo:
                self.ripup(ni)
            for ni in todo:
                if time.time() - t0 > time_limit:
                    self.failed.add(ni)     # out of time: leave unrouted
                    continue
                if not self.route_net(ni):
                    self.failed.add(ni)
            over = self.overused_cells()
            if log:
                log(f"    routing pass {it + 1}: {len(todo)} nets rerouted, {len(over)} overfull tiles, "
                    f"{len(self.failed)} unroutable ({time.time() - tp:.1f}s)")
            if not over and not self.failed:
                return True
            if time.time() - t0 > time_limit * 0.85:
                break
            score = len(over) + 50 * len(self.failed)
            if best_over is None or score < best_over:
                best_over, stall = score, 0
            else:
                stall += 1
                if stall >= 8:
                    break
            for c in over:
                self.hist[c] += 0.6 * self.over_amount(c)
            self.pres = min(self.pres * 1.6, 12.0)
            over_set = set(over)
            todo = [ni for ni in order if self.cells[ni] & over_set or ni in self.failed]
        return False

    def _span(self, ni):
        allc = [c for t in self.nets[ni]["terms"] for c in t]
        if not allc:
            return 0
        x0, y0, x1, y1 = self._bbox(allc, 0)
        return (x1 - x0) + (y1 - y0)

    def overused_cells(self):
        occ_s, occ_l = self.occ_s, self.occ_l
        out = []
        if self.mix:
            for c in range(self.N):
                s = occ_s[c]
                l = occ_l[c]
                if s > 2 or l > 2 or (s and l):
                    out.append(c)
        else:
            for c in range(self.N):
                if occ_s[c] + occ_l[c] > 2:
                    out.append(c)
        return out
