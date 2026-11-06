"""Place fluid / item valve controls (3x1) where even splitting would starve machines.

A valve is three tiles in a straight line [A, M, E]: the pipe enters A from the end, leaves E straight
through, and leaves the middle tile M out of its side. Only normal (small) pipes have valves.

For every split that flows.Analysis marked as needing a valve:
  1. if the routed pipe already runs straight through the junction (and the tiles are not shared with
     another pipe) the valve simply goes there;
  2. otherwise the junction is rebuilt locally: the valve is laid in line with the incoming pipe and the
     two branches are re-connected from its outlets with a short path search;
  3. if neither works the junction is reported (with the percentage) so it can be placed by hand.
"""
from __future__ import annotations

import heapq
from collections import defaultdict

DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _add(a, d, k=1):
    return (a[0] + d[0] * k, a[1] + d[1] * k)


def _adj(edges):
    g = defaultdict(set)
    for a, b in edges:
        g[a].add(b)
        g[b].add(a)
    return g


class ValvePlacer:
    def __init__(self, problem, sol, analysis, radius=14, max_path=40):
        self.p, self.sol, self.an = problem, sol, analysis
        self.radius, self.max_path = radius, max_path
        self.reserved = set()      # tiles used by placed valves (exclusive)
        self.placed, self.failed = [], []

    # ------------------------------------------------------------------ helpers
    def occ(self, c):
        return self.sol.occ_s.get(c, 0) + self.sol.occ_l.get(c, 0)

    def free(self, c, ni):
        """A tile a new piece of net ni may use."""
        if c in self.sol.blocked or c in self.reserved:
            return False
        if self.sol.occ_l.get(c, 0):
            return False
        own = c in self.sol.net_nodes[ni]
        return self.sol.occ_s.get(c, 0) - (1 if own else 0) < 2

    def term_nodes(self, nf):
        return {ti.node for ti in nf.terms if ti.node is not None}

    def straight_ok(self, ni, nf, A, M, E, d):
        """Existing pipe already forms A -> M -> E with a side outlet at M."""
        g = nf.adj
        tn = self.term_nodes(nf)
        if any(c in tn for c in (A, M, E)):
            return False
        if any(self.occ(c) > 1 or c in self.reserved for c in (A, M, E)):
            return False
        prev, nxt = _add(A, d, -1), _add(E, d)
        return (g.get(A) == {prev, M} and g.get(E) == {M, nxt} and len(g.get(M, ())) == 3
                and nf.edge_flow.get((prev, A), 0) > 0 and nf.edge_flow.get((E, nxt), 0) > 0)

    # ------------------------------------------------------------------ main
    def run(self):
        for nf in self.an.nets:
            if nf.ni not in self.an.valve_nets or self.p.nets[nf.ni].large:
                continue
            todo = [n for n, j in nf.junctions.items() if j.kind == "split" and not j.even_ok]
            for J in todo:
                self.place(nf.ni, J)
        return self.placed, self.failed

    def place(self, ni, J):
        nf = self.an.nets[ni]
        j = nf.junctions[J]
        tot_in = sum(f for _, f in j.ins) or 1.0
        split = [(lbl, 100.0 * f / tot_in) for lbl, f in j.outs]
        rec = {"net": ni, "label": self.p.nets[ni].label, "node": J, "split": split}
        if len(j.outs) != 2 or len(j.ins) != 1:
            rec["why"] = (f"{len(j.ins)} in / {len(j.outs)} out at {J}: a valve has 1 input and 2 outputs - "
                          f"chain two valves or move one branch")
            self.failed.append(rec)
            return
        in_nb = [v for v in nf.adj[J] if nf.edge_flow.get((v, J), 0) > 0]
        out_nb = [v for v in nf.adj[J] if nf.edge_flow.get((J, v), 0) > 0]
        term_here = [k for k, ti in enumerate(nf.terms) if ti.node == J]
        if term_here or len(in_nb) != 1 or len(out_nb) != 2:
            rec["why"] = "a machine port attaches at the split tile - move the split one tile along the pipe"
            self.failed.append(rec)
            return
        a = in_nb[0]
        d = (J[0] - a[0], J[1] - a[1])
        if abs(d[0]) + abs(d[1]) != 1:
            rec["why"] = "the pipe reaches the split through a quantum hop"
            self.failed.append(rec)
            return
        # 1. valve fits on the existing pipe (J is the middle tile)
        E = _add(J, d)
        if self.straight_ok(ni, nf, a, J, E, d):
            side = next(v for v in out_nb if v != E)
            self._record(ni, nf, [a, J, E], d, E, side, rec)
            return
        # 2. rebuild: valve [J, J+d, J+2d] in line with the inflow, reconnect both branches
        res = self.rebuild(ni, nf, J, a, d, out_nb)
        if res is None:
            rec["why"] = "no room for a 3x1 valve in line with the incoming pipe - place it by hand"
            self.failed.append(rec)
            return
        tiles, straight_tile, side_tile = res
        self._record(ni, nf, tiles, d, straight_tile, side_tile, rec, rebuilt=True)

    def _record(self, ni, nf, tiles, d, straight_nb, side_nb, rec, rebuilt=False):
        self.reserved.update(tiles)
        rec.update(tiles=tiles, dir=d, straight=straight_nb, side=side_nb, rebuilt=rebuilt)
        self.placed.append(rec)

    def rebuild(self, ni, nf, J, a, d, out_nb):
        M, E = _add(J, d), _add(J, d, 2)
        if a != _add(J, d, -1):
            return None
        for c in (M, E):
            if c in self.sol.blocked or self.occ(c) > 0 or c in self.reserved:
                return None
        if self.occ(J) > 1:
            return None
        # branch targets: the sub-trees hanging off J (without J)
        g = _adj(self.sol.net_edges[ni])
        branches = []
        for b in out_nb:
            seen, st = {b}, [b]
            while st:
                u = st.pop()
                for w in g[u]:
                    if w != J and w not in seen:
                        seen.add(w)
                        st.append(w)
            branches.append(seen)
        S = _add(E, d)
        perp = [(d[1], d[0]), (-d[1], -d[0])]
        best = None
        for order in ((0, 1), (1, 0)):
            for pd in perp:
                side_start = _add(M, pd)
                p1 = self.path(ni, S, branches[order[0]], {J, M, E})
                if p1 is None:
                    continue
                p2 = self.path(ni, side_start, branches[order[1]], {J, M, E} | set(p1))
                if p2 is None:
                    continue
                cost = len(p1) + len(p2)
                if best is None or cost < best[0]:
                    best = (cost, p1, p2, side_start)
        if best is None:
            return None
        _, p1, p2, side_start = best
        edges = [e for e in self.sol.net_edges[ni] if J not in e or a in e]
        edges += [(J, M), (M, E), (E, p1[0])] + list(zip(p1, p1[1:]))
        edges += [(M, p2[0])] + list(zip(p2, p2[1:]))
        nodes = {c for e in edges for c in e}
        nodes, edges = self.prune(nf, nodes, edges, keep={J, M, E} | set(p1) | set(p2))
        self.sol.net_nodes[ni] = nodes
        self.sol.net_edges[ni] = edges
        self.sol.refresh()
        return [J, M, E], p1[0], p2[0]

    def path(self, ni, start, targets, avoid):
        """Shortest free path from start to any tile of `targets` (inclusive)."""
        if start in avoid or not self.free(start, ni) and start not in targets:
            return None
        if start in targets:
            return [start]
        r = self.radius
        x0, y0 = start
        dist = {start: 0}
        prev = {start: None}
        h = [(0, start)]
        while h:
            dcur, u = heapq.heappop(h)
            if dcur > dist[u]:
                continue
            if dcur > self.max_path:
                break
            for dx, dy in DIRS:
                v = (u[0] + dx, u[1] + dy)
                if abs(v[0] - x0) > r or abs(v[1] - y0) > r or v in avoid or v in dist:
                    continue
                if v in targets:
                    path = [v, u]
                    while prev[u] is not None:
                        u = prev[u]
                        path.append(u)
                    return path[::-1]
                if not self.free(v, ni):
                    continue
                cost = dcur + 1 + (0.6 if self.occ(v) else 0)
                dist[v] = cost
                prev[v] = u
                heapq.heappush(h, (cost, v))
        return None

    def prune(self, nf, nodes, edges, keep):
        """Remove dangling pipe ends that no longer lead to a machine port."""
        tn = self.term_nodes(nf) | keep
        g = _adj(edges)
        changed = True
        while changed:
            changed = False
            for n in list(g):
                if n not in tn and len(g[n]) <= 1:
                    for m in g[n]:
                        g[m].discard(n)
                    del g[n]
                    changed = True
        edges = [(a, b) for a, b in edges if a in g and b in g]
        return set(g), edges


def place_valves(problem, sol, analysis):
    vp = ValvePlacer(problem, sol, analysis)
    placed, failed = vp.run()
    return placed, failed
