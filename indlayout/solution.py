"""Coordinate-based finished layout: validation and row/column compaction."""
from __future__ import annotations

from collections import defaultdict

from .spacing import violations


class Solution:
    jump = 3   # max quantum-piping hop (tiles), set by the optimizer

    def __init__(self, problem, machines, net_nodes, net_edges, failed=()):
        self.problem = problem
        self.machines = machines            # dicts with x, y, shape, inst, node, rot, local
        self.net_nodes = net_nodes          # per net: set of (x, y)  (tiles, or 2x2 anchors for large)
        self.net_edges = net_edges          # per net: list of ((x, y), (x, y))
        self.failed = set(failed)
        self.refresh()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_router(cls, problem, machines, router):
        gw = router.gw
        nodes = [{(c % gw, c // gw) for c in t} for t in router.tree]
        edges = [[((a % gw, a // gw), (b % gw, b // gw)) for a, b in e] for e in router.edges]
        ms = [dict(m) for m in machines]
        return cls(problem, ms, nodes, edges, router.failed)

    def copy(self):
        return Solution(self.problem, [dict(m) for m in self.machines], [set(n) for n in self.net_nodes],
                        [list(e) for e in self.net_edges], self.failed)

    # ------------------------------------------------------------------ derived data
    def refresh(self):
        self.blocked = set()
        for m in self.machines:
            ox, oy = m["x"], m["y"]
            for x, y in m["shape"].occupied():
                self.blocked.add((ox + x, oy + y))
        self.cells = []
        self.occ_s = defaultdict(int)
        self.occ_l = defaultdict(int)
        for ni, nodes in enumerate(self.net_nodes):
            large = self.problem.nets[ni].large
            cells = set()
            for (x, y) in nodes:
                if large:
                    cells.update(((x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)))
                else:
                    cells.add((x, y))
            self.cells.append(cells)
            occ = self.occ_l if large else self.occ_s
            for c in cells:
                occ[c] += 1
        xs0, ys0, xs1, ys1 = [], [], [], []
        for m in self.machines:
            xs0.append(m["x"]); ys0.append(m["y"])
            xs1.append(m["x"] + m["shape"].w); ys1.append(m["y"] + m["shape"].h)
        for cells in self.cells:
            for x, y in cells:
                xs0.append(x); ys0.append(y); xs1.append(x + 1); ys1.append(y + 1)
        self.bbox = (min(xs0), min(ys0), max(xs1), max(ys1))

    @property
    def area(self):
        x0, y0, x1, y1 = self.bbox
        return (x1 - x0) * (y1 - y0)

    def overfull(self, mixed_crossing=False):
        out = []
        for c in set(self.occ_s) | set(self.occ_l):
            s, l = self.occ_s.get(c, 0), self.occ_l.get(c, 0)
            if mixed_crossing:
                bad = s + l > 2
            else:
                bad = s > 2 or l > 2 or (s and l)
            if bad:
                out.append(c)
        return out

    def access(self, m, pid, large):
        p = m["shape"].ports[pid]
        if large:
            ax, ay = p.large_anchor()
            return {(ax + m["x"], ay + m["y"])}
        return {(x + m["x"], y + m["y"]) for x, y in p.access_cells()}

    def validate(self, mixed_crossing=False, jump=None):
        """Return a list of rule violations (empty = valid)."""
        errs = []
        inst_m = {m["inst"]: m for m in self.machines}
        seen = {}
        for m in self.machines:
            for x, y in m["shape"].occupied():
                c = (m["x"] + x, m["y"] + y)
                if c in seen:
                    errs.append(f"machines overlap at {c}")
                    return errs
                seen[c] = m["inst"]
        for ni, net in enumerate(self.problem.nets):
            if ni in self.failed:
                continue
            cells = self.cells[ni]
            if cells & self.blocked:
                errs.append(f"{net.label}: pipe under a machine")
            nodes = self.net_nodes[ni]
            for t in net.terminals:
                m = inst_m[t.inst]
                if not any(self.access(m, p, net.large) & nodes for p in t.ports):
                    errs.append(f"{net.label}: terminal on {self.problem.nodes[m['node']].recipe_id} "
                                f"#{m['local'] + 1} not attached")
            if nodes:
                adj = defaultdict(set)
                jmax = self.jump if jump is None else jump
                for a, b in self.net_edges[ni]:
                    dist = abs(a[0] - b[0]) + abs(a[1] - b[1])
                    if (a[0] != b[0] and a[1] != b[1]) or dist < 1 or dist > max(1, jmax):
                        errs.append(f"{net.label}: broken pipe segment {a}-{b}")
                    elif dist > 1:
                        sx, sy = (b[0] - a[0]) // dist, (b[1] - a[1]) // dist
                        for i in range(1, dist):
                            q = (a[0] + sx * i, a[1] + sy * i)
                            span = [q] if not net.large else [q, (q[0] + 1, q[1]), (q[0], q[1] + 1),
                                                               (q[0] + 1, q[1] + 1)]
                            if any(t in self.blocked for t in span):
                                errs.append(f"{net.label}: quantum hop over a machine at {q}")
                    adj[a].add(b)
                    adj[b].add(a)
                start = next(iter(nodes))
                stack, vis = [start], {start}
                while stack:
                    c = stack.pop()
                    for d in adj[c]:
                        if d not in vis:
                            vis.add(d)
                            stack.append(d)
                if vis != nodes:
                    errs.append(f"{net.label}: pipe network not connected")
        rects = []
        for m in self.machines:
            d = self.problem.spacing_of(m["inst"])
            if d:
                rects.append(((m["shape"].id, m["inst"]), (m["x"], m["y"], m["shape"].w, m["shape"].h), d))
        for k1, k2, dist, req in violations(rects, self.problem.spacing_measure):
            errs.append(f"{k1[0]} #{k1[1]} and #{k2[1]} only {dist:.0f} tiles apart (need {req:g})")
        for c in self.overfull(mixed_crossing):
            errs.append(f"overfull tile {c}: {self.occ_s.get(c, 0)} normal + {self.occ_l.get(c, 0)} large")
        return errs

    # ------------------------------------------------------------------ compaction
    def _try_delete(self, axis, k, mixed_crossing):
        """Delete tile row (axis=1) or column (axis=0) k if every rule still holds."""
        def shift(c):
            return tuple(v - 1 if (i == axis and v > k) else v for i, v in enumerate(c))

        # quick rejects
        for m in self.machines:
            lo = m["y"] if axis == 1 else m["x"]
            size = m["shape"].h if axis == 1 else m["shape"].w
            if lo <= k < lo + size:
                return None
        new_nodes, new_edges = [], []
        for ni, nodes in enumerate(self.net_nodes):
            large = self.problem.nets[ni].large
            edges = self.net_edges[ni]
            on = {c for c in nodes if c[axis] == k}
            if not on:
                if large and any(c[axis] == k - 1 for c in nodes):
                    pass   # footprint touches k; checked by full validation below
                new_nodes.append({shift(c) for c in nodes})
                new_edges.append([(shift(a), shift(b)) for a, b in edges])
                continue
            # every node on line k must be a straight pass across the line (or a line-crossing end)
            ok = True
            for c in on:
                nbr = [b if a == c else a for a, b in edges if a == c or b == c]
                if not nbr:
                    ok = False
                    break
                if any(n[axis] == k for n in nbr):
                    ok = False
                    break
            if not ok:
                return None
            kept = {shift(c) for c in nodes if c[axis] != k}
            es = []
            for a, b in edges:
                if a[axis] == k or b[axis] == k:
                    continue
                es.append((shift(a), shift(b)))
            # reconnect across the removed line
            for c in on:
                nbr = [b if a == c else a for a, b in edges if a == c or b == c]
                lo = [n for n in nbr if n[axis] < k]
                hi = [n for n in nbr if n[axis] > k]
                if lo and hi:
                    es.append((shift(lo[0]), shift(hi[0])))
                elif hi and not lo:
                    # end of the pipe at the line: it attaches to a port on the low side
                    pass
                elif lo and not hi:
                    pass
            new_nodes.append(kept)
            new_edges.append(es)
        trial = Solution(self.problem, [dict(m) for m in self.machines], new_nodes, new_edges, self.failed)
        for m in trial.machines:
            if (m["y"] if axis == 1 else m["x"]) > k:
                m["y" if axis == 1 else "x"] -= 1
        trial.refresh()
        if trial.validate(mixed_crossing):
            return None
        return trial

    def compact(self, mixed_crossing=False, log=None):
        if self.validate(mixed_crossing):
            return self
        sol = self
        removed = [0, 0]
        changed = True
        while changed:
            changed = False
            for axis in (0, 1):
                x0, y0, x1, y1 = sol.bbox
                lo, hi = (x0, x1) if axis == 0 else (y0, y1)
                k = hi - 1
                while k >= lo:
                    t = sol._try_delete(axis, k, mixed_crossing)
                    if t is not None:
                        sol = t
                        removed[axis] += 1
                        changed = True
                    k -= 1
        if log:
            log(f"  compaction removed {removed[0]} columns and {removed[1]} rows")
        return sol
