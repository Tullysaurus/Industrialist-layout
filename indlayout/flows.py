"""Flow on every routed pipe segment, junction types, and the even-split bottleneck check.

Game rules modelled here
  * a split (1 in, 2 or 3 out) shares its inflow evenly between the open directions; a direction that
    is full (everything behind it is saturated) gets nothing and its share goes to the others
  * a machine only runs as fast as its scarcest input (it needs the full amount of every input)
  * normal (small) pipes can be split with exact percentages by a fluid/item valve control, a 3x1 piece
    that sits on the junction: inflow at one end, one outflow straight through, one out of the side of
    the middle tile. Large pipes have no valve.

Planned flows come from the planner port (each terminal carries its share of the planner's rates);
directions of the segments follow those planned flows. The simulation then replays the layout with
even splitting and reports which machine groups would fall short of the plan, and which junctions need
a valve (with the percentage to set) to prevent that.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

EPS = 1e-9
BUFFER_TOLERANCE = 0.01   # shortfalls below 1 % of an input are treated as absorbed by its buffer


@dataclass
class TermInfo:
    t: object            # model.Terminal
    node: tuple | None   # net graph node the terminal attaches to
    port_cells: tuple    # tiles of the machine port (absolute)
    machine: dict | None


@dataclass
class Junction:
    node: tuple
    kind: str            # split | merge | mix | pass | end
    ins: list            # [(label, flow)]
    outs: list
    even_ok: bool = True
    valve: dict | None = None   # {"tiles": [...], "side_pct": .., "straight_pct": .., "ok": bool, "why": str}


@dataclass
class NetFlow:
    ni: int
    adj: dict                    # node -> set(node)
    terms: list                  # TermInfo
    edge_flow: dict = field(default_factory=dict)    # (a, b) directed a->b -> planned flow
    sim_flow: dict = field(default_factory=dict)     # (a, b) -> simulated even-split flow (as built)
    valve_flow: dict = field(default_factory=dict)   # (a, b) -> simulated flow with the proposed valves
    junctions: dict = field(default_factory=dict)    # node -> Junction
    balanced_note: str = ""
    cyclic: bool = False
    radj: dict = field(default_factory=dict)       # reduced graph: junction / terminal nodes only
    rflow: dict = field(default_factory=dict)      # (u, v) -> planned flow on the chain u..v
    chains: dict = field(default_factory=dict)     # (u, v) -> [u, ..., v] graph nodes
    rorder: list = field(default_factory=list)     # reduced nodes, parents before children
    rparent: dict = field(default_factory=dict)


def _graph(nodes, edges):
    adj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    for n in nodes:
        adj.setdefault(n, set())
    return adj


def _spanning(adj):
    """Drop edges that close cycles (BFS tree); returns (tree adj, had_cycle)."""
    tree = defaultdict(set)
    seen = set()
    cyc = False
    for start in adj:
        if start in seen:
            continue
        seen.add(start)
        q = deque([start])
        while q:
            u = q.popleft()
            for v in sorted(adj[u]):
                if v not in seen:
                    seen.add(v)
                    tree[u].add(v)
                    tree[v].add(u)
                    q.append(v)
                elif v not in tree[u]:
                    cyc = True
        tree.setdefault(start, set())
    return tree, cyc


class Analysis:
    def __init__(self, problem, sol):
        self.problem, self.sol = problem, sol
        self.inst_m = {m["inst"]: m for m in sol.machines}
        self.nets: list[NetFlow] = []
        for ni, net in enumerate(problem.nets):
            self.nets.append(self._net(ni, net))
        self.planned_run = {}
        for g, (ni_, li) in enumerate(problem.instances):
            node = problem.nodes[ni_]
            self.planned_run[g] = node.util
        self.run_even = self.run_valve = None
        self.valve_nets = set()      # nets that need valves to reach the plan
        self.valve_nodes = {}        # net -> graph nodes holding a valve (simulated with exact split)
        self.placed, self.unplaced = [], []
        self.groups = []

    # ---------------------------------------------------------------- per net graph
    def _net(self, ni, net):
        nodes = self.sol.net_nodes[ni]
        adj, cyc = _spanning(_graph(nodes, self.sol.net_edges[ni]))
        terms = []
        for t in net.terminals:
            m = self.inst_m.get(t.inst)
            at, cells = None, ()
            if m is not None:
                for pid in t.ports:
                    acc = self.sol.access(m, pid, net.large) & nodes
                    if acc:
                        at = min(acc)
                        p = m["shape"].ports[pid]
                        cells = tuple((m["x"] + x, m["y"] + y) for x, y in p.cells)
                        break
            terms.append(TermInfo(t, at, cells, m))
        nf = NetFlow(ni, adj, terms, cyclic=cyc)
        self._planned(nf)
        self._reduce(nf)
        return nf

    def _reduce(self, nf):
        adj = nf.adj
        key = {n for n in adj if len(adj[n]) != 2} | {ti.node for ti in nf.terms if ti.node is not None}
        if not key and adj:
            key = {next(iter(adj))}
        radj = defaultdict(set)
        for k in key:
            radj.setdefault(k, set())
            for nb in adj[k]:
                path, prev, cur = [k], k, nb
                while cur not in key:
                    path.append(cur)
                    nxt = [w for w in adj[cur] if w != prev]
                    if not nxt:
                        break
                    prev, cur = cur, nxt[0]
                path.append(cur)
                end = path[-1]
                if end == k or (k, end) in nf.chains:
                    continue
                nf.chains[(k, end)] = path
                nf.chains[(end, k)] = path[::-1]
                radj[k].add(end)
                radj[end].add(k)
                a, b = path[0], path[1]
                if nf.edge_flow.get((a, b), 0) > EPS:
                    nf.rflow[(k, end)] = nf.edge_flow[(a, b)]
                elif nf.edge_flow.get((b, a), 0) > EPS:
                    nf.rflow[(end, k)] = nf.edge_flow[(b, a)]
        nf.radj = radj
        seen = set()
        for r in sorted(radj):
            if r in seen:
                continue
            seen.add(r)
            nf.rparent[r] = None
            st = [r]
            while st:
                u = st.pop()
                nf.rorder.append(u)
                for v in radj[u]:
                    if v not in seen:
                        seen.add(v)
                        nf.rparent[v] = u
                        st.append(v)

    def expand(self, nf, rflows):
        """Reduced-edge flows -> per tile-edge flows."""
        out = {}
        for (u, v), f in rflows.items():
            path = nf.chains.get((u, v))
            if path:
                for a, b in zip(path, path[1:]):
                    out[(a, b)] = f
        return out

    def _inject(self, nf, supply, demand):
        """node -> (sources [(term idx, amount)], sinks [(term idx, cap)])."""
        loc = defaultdict(lambda: ([], []))
        for k, ti in enumerate(nf.terms):
            if ti.node is None:
                continue
            if ti.t.direction == "output":
                loc[ti.node][0].append((k, supply[k]))
            else:
                loc[ti.node][1].append((k, demand[k]))
        return loc

    def _planned(self, nf):
        """Tree-cut flows from the planned terminal rates (supply and demand balanced first)."""
        sup = [(ti.t.rate or 0.0) if ti.t.direction == "output" else 0.0 for ti in nf.terms]
        dem = [(ti.t.rate or 0.0) if ti.t.direction == "input" else 0.0 for ti in nf.terms]
        S, D = sum(sup), sum(dem)
        if S > D + EPS:
            sup = [v * D / S for v in sup] if S > 0 else sup
            nf.balanced_note = f"supply {S:.2f}/s > demand {D:.2f}/s: the excess backs up in the pipe"
        elif D > S + EPS:
            dem = [v * S / D for v in dem] if D > 0 else dem
            nf.balanced_note = f"demand {D:.2f}/s > supply {S:.2f}/s: shortage"
        loc = self._inject(nf, sup, dem)
        b = defaultdict(float)
        for n, (srcs, snks) in loc.items():
            b[n] += sum(a for _, a in srcs) - sum(c for _, c in snks)
        flows = {}
        for comp_root in list(nf.adj):
            if any((comp_root, v) in flows or (v, comp_root) in flows for v in nf.adj[comp_root]):
                continue
            order, parent = [], {comp_root: None}
            st = [comp_root]
            while st:
                u = st.pop()
                order.append(u)
                for v in nf.adj[u]:
                    if v not in parent:
                        parent[v] = u
                        st.append(v)
            sub = defaultdict(float)
            for u in reversed(order):
                sub[u] += b[u]
                p = parent[u]
                if p is not None:
                    sub[p] += sub[u]
                    f = sub[u]       # >0: flows from u towards its parent
                    if f >= 0:
                        flows[(u, p)] = f
                    else:
                        flows[(p, u)] = -f
        nf.edge_flow = flows
        # junctions
        for n in nf.adj:
            srcs, snks = loc.get(n, ([], []))
            ins = [(f"pipe {v}", flows[(v, n)]) for v in nf.adj[n] if flows.get((v, n), 0) > EPS]
            outs = [(f"pipe {v}", flows[(n, v)]) for v in nf.adj[n] if flows.get((n, v), 0) > EPS]
            ins += [(self._tlabel(nf.terms[k]), a) for k, a in srcs if a > EPS]
            outs += [(self._tlabel(nf.terms[k]), a) for k, a in snks if a > EPS]
            if len(ins) + len(outs) <= 1:
                kind = "end"
            elif len(ins) == 1 and len(outs) == 1:
                kind = "pass"
            elif len(ins) == 1:
                kind = "split"
            elif len(outs) == 1:
                kind = "merge"
            else:
                kind = "mix"
            nf.junctions[n] = Junction(n, kind, ins, outs)

    def _tlabel(self, ti):
        node = self.problem.nodes[self.problem.instances[ti.t.inst][0]]
        return f"{node.shape.name} #{self.problem.instances[ti.t.inst][1] + 1}"

    # ---------------------------------------------------------------- even split simulation
    def _simulate_net(self, nf, supply, cap, valves: bool):
        """Push supplies along the planned directions; returns (delivered per sink term, accepted ratio)."""
        loc = self._inject(nf, supply, cap)
        # acceptance of everything "behind" a directed edge u->v (the v side of the cut)
        node_sup = defaultdict(float)
        node_cap = defaultdict(float)
        for n, (srcs, snks) in loc.items():
            node_sup[n] = sum(a for _, a in srcs)
            node_cap[n] = sum(c for _, c in snks)
        indeg = defaultdict(int)
        out_e = defaultdict(list)
        in_e = defaultdict(list)
        for (u, v) in nf.rflow:
            indeg[v] += 1
            out_e[u].append(v)
            in_e[v].append(u)
        order = []
        deg = dict(indeg)
        q = deque([n for n in nf.radj if indeg[n] == 0])
        while q:
            u = q.popleft()
            order.append(u)
            for v in out_e[u]:
                deg[v] -= 1
                if deg[v] == 0:
                    q.append(v)
        # acceptance of each directed edge: start with everything downstream could take
        down = {}
        for u in reversed(order):
            down[u] = node_cap[u] + sum(down[v] for v in out_e[u])
        accept = {(u, v): down[v] for (u, v) in nf.rflow}
        vnodes = self.valve_nodes.get(nf.ni, ()) if valves else ()
        flow, delivered = {}, [0.0] * len(nf.terms)
        for _round in range(30):
            inflow = defaultdict(float)
            flow = {}
            delivered = [0.0] * len(nf.terms)
            for u in order:
                srcs, snks = loc.get(u, ([], []))
                total = inflow[u] + sum(a for _, a in srcs)
                dirs = [("t", k, c) for k, c in snks] + [("e", v, accept[(u, v)]) for v in out_e[u]]
                if not dirs:
                    continue
                if u in vnodes and len(dirs) >= 2:
                    # valve: split in planned proportions; what a full branch cannot take goes to the others
                    want = [(nf.rflow[(u, d[1])] if d[0] == "e" else self._planned_sink(nf, d[1])) for d in dirs]
                    tw = sum(want) or 1.0
                    amounts = [min(d[2], total * w / tw) for d, w in zip(dirs, want)]
                    rest = total - sum(amounts)
                    if rest > EPS:
                        amounts = _water_fill(rest, [d[2] - x for d, x in zip(dirs, amounts)], amounts)
                else:
                    amounts = _water_fill(total, [d[2] for d in dirs], [0.0] * len(dirs))
                for d, x in zip(dirs, amounts):
                    if d[0] == "t":
                        delivered[d[1]] += x
                    else:
                        flow[(u, d[1])] = x
                        inflow[d[1]] += x
            # a node that cannot pass on everything it receives backs up: its feeders get less next round
            changed = False
            for v in order:
                srcs, snks = loc.get(v, ([], []))
                got = inflow[v] + sum(a for _, a in srcs)
                passed = sum(flow.get((v, w), 0.0) for w in out_e[v]) + sum(delivered[k] for k, _ in snks)
                if got > passed + 1e-9 * max(1.0, got) and inflow[v] > EPS:
                    keep = passed / got      # feeders and local sources back up in proportion
                    for u in in_e[v]:
                        new = flow.get((u, v), 0.0) * keep
                        if new < accept[(u, v)] - 1e-9 * max(1.0, accept[(u, v)]):
                            accept[(u, v)] = new
                            changed = True
            if not changed:
                break
        tot_sup = sum(supply[k] for k, ti in enumerate(nf.terms) if ti.t.direction == "output")
        acc = (sum(delivered) / tot_sup) if tot_sup > EPS else 1.0
        return delivered, min(1.0, acc), flow

    def _planned_sink(self, nf, k):
        return nf.terms[k].t.rate or 0.0

    def simulate(self, valves=False, iters=80):
        """Steady state of the whole layout: machine run fractions (1 = 100 %)."""
        P = self.problem
        n_inst = len(P.instances)
        has_in = defaultdict(list)    # inst -> [(net, term idx)]
        has_out = defaultdict(list)
        for nf in self.nets:
            for k, ti in enumerate(nf.terms):
                (has_in if ti.t.direction == "input" else has_out)[ti.t.inst].append((nf.ni, k))
        run = {g: self.planned_run[g] for g in range(n_inst)}
        frac = {}            # (inst, net, term) -> delivered / needed at 100 %
        flows = {}

        def others(g, key):
            """How fast machine g could run judged by all its piped inputs except `key`."""
            v = [frac.get((g, n_, k_), 1.0) for n_, k_ in has_in[g] if (n_, k_) != key]
            return min([1.0] + v)

        for _ in range(iters):
            new_frac = {}
            for nf in self.nets:
                sup, cap = [], []
                for k, ti in enumerate(nf.terms):
                    g, r = ti.t.inst, ti.t.rate or 0.0
                    full = r / max(self.planned_run[g], EPS)   # this terminal's flow at 100 %
                    if ti.t.direction == "output":
                        sup.append(full * run[g])
                        cap.append(0.0)
                    else:
                        sup.append(0.0)
                        # an input buffer only keeps taking what the machine can use (its other inputs)
                        cap.append(full * others(g, (nf.ni, k)))
                deliv, _acc, fl = self._simulate_net(nf, sup, cap, valves)
                flows[nf.ni] = fl
                for k, ti in enumerate(nf.terms):
                    if ti.t.direction == "input":
                        full = (ti.t.rate or 0.0) / max(self.planned_run[ti.t.inst], EPS)
                        f = min(1.0, deliv[k] / full) if full > EPS else 1.0
                        # input buffers absorb tiny imbalances (and the planner's own rounding)
                        new_frac[(ti.t.inst, nf.ni, k)] = 1.0 if f >= 1.0 - BUFFER_TOLERANCE else f
            frac = new_frac
            # a machine runs as fast as its scarcest piped input; raw sources produce exactly the plan.
            # Outputs are assumed to drain (excess backs up in the pipe but does not slow the machine here).
            new = {g: (min([1.0] + [frac[(g, n_, k_)] for n_, k_ in has_in[g]]) if has_in[g]
                       else self.planned_run[g]) for g in range(n_inst)}
            delta = max(abs(new[g] - run[g]) for g in range(n_inst)) if n_inst else 0
            run = new
            if delta < 1e-7:
                break
        return run, flows

    def _voidable(self, ti):
        ni, d, si = ti.t.slot if ti.t.slot else (None, None, None)
        if ni is None:
            return True
        node = self.problem.nodes[ni]
        if not node.recipe:
            return True
        ios = node.recipe["outputs"] if d == "output" else node.recipe["inputs"]
        return bool(ios[si].get("voidable")) if si < len(ios) else True

    # ---------------------------------------------------------------- groups & valves
    def group_throughput(self, run):
        P = self.problem
        out = []
        for ni_, node in enumerate(P.nodes):
            insts = [g for g, (a, _) in enumerate(P.instances) if a == ni_]
            actual = sum(run[g] for g in insts)
            out.append((ni_, node.machine_count, actual))
        return out

    def loss(self, run):
        return sum(max(0.0, plan - act) / max(plan, EPS) for _, plan, act in self.group_throughput(run))

    def _hypothetical(self, nets):
        return {ni: {n for n, j in self.nets[ni].junctions.items() if j.kind in ("split", "mix")} for ni in nets}

    def analyse(self, placed=None, needed=None, unplaced=()):
        """placed: valves already in the layout (valves.place_valves output); needed: nets known to need them."""
        run, flows = self.simulate(valves=False)
        self.run_even = run
        for nf in self.nets:
            nf.sim_flow = self.expand(nf, flows.get(nf.ni, {}))
        if needed is not None:
            self.valve_nets = set(needed)
        else:
            base = self.loss(run)
            cand = [nf.ni for nf in self.nets if not self.problem.nets[nf.ni].large
                    and any(j.kind in ("split", "mix") for j in nf.junctions.values())]
            self.valve_nets = set()
            if base > 1e-3 and cand:
                self.valve_nets = set(cand)
                self.valve_nodes = self._hypothetical(self.valve_nets)
                best = self.loss(self.simulate(valves=True)[0])
                # keep valves only on nets where they help
                for ni in sorted(cand, key=lambda i: len(self.nets[i].terms)):
                    self.valve_nets.discard(ni)
                    self.valve_nodes = self._hypothetical(self.valve_nets)
                    l2 = self.loss(self.simulate(valves=True)[0])
                    if l2 > best + 1e-4:
                        self.valve_nets.add(ni)
                    else:
                        best = min(best, l2)
        if placed is None:
            self.valve_nodes = self._hypothetical(self.valve_nets)
        else:
            self.placed, self.unplaced = placed, list(unplaced)
            self.valve_nodes = defaultdict(set)
            for v in placed:
                self.valve_nodes[v["net"]].add(v["tiles"][1])
        run_v, flows_v = self.simulate(valves=True)
        self.run_valve = run_v
        for nf in self.nets:
            nf.valve_flow = self.expand(nf, flows_v.get(nf.ni, {}))
            self._junction_checks(nf)
        self.groups = [(ni_, plan, act, av) for (ni_, plan, act), (_, _, av)
                       in zip(self.group_throughput(run), self.group_throughput(run_v))]
        return self

    def _junction_checks(self, nf):
        placed = {v["tiles"][1]: v for v in self.placed if v["net"] == nf.ni}
        unplaced = {v["node"]: v for v in self.unplaced if v["net"] == nf.ni}
        for n, j in nf.junctions.items():
            if j.kind not in ("split", "mix"):
                continue
            outs = [f for _, f in j.outs]
            tot = sum(outs)
            j.even_ok = tot <= EPS or max(outs) - min(outs) <= max(1e-6, tot * 0.01)
            if n in placed:
                v = placed[n]
                tot_in = sum(f for _, f in j.ins) or 1.0
                st = nf.edge_flow.get((n, v["straight"]), 0.0)
                j.valve = {"ok": True, "tiles": v["tiles"], "rebuilt": v.get("rebuilt", False),
                           "straight_pct": 100.0 * st / tot_in, "side_pct": 100.0 * (1 - st / tot_in),
                           "split": [(lbl, 100.0 * f / tot_in) for lbl, f in j.outs], "why": ""}
            elif n in unplaced:
                j.valve = {"ok": False, "tiles": [], "why": unplaced[n]["why"], "split": unplaced[n]["split"]}
            elif nf.ni in self.valve_nets and not j.even_ok and not self.placed:
                j.valve = self._place_valve(nf, n, j, self.problem.nets[nf.ni])

    def _place_valve(self, nf, n, j, net):
        tot_in = sum(f for _, f in j.ins) or 1.0
        info = {"node": n, "tiles": [], "ok": False, "why": "",
                "split": [(lbl, 100.0 * f / tot_in) for lbl, f in j.outs]}
        if net.large:
            info["why"] = "large pipes have no valve - give these consumers their own pipe"
            return info
        if len(j.outs) > 2 or len(j.ins) > 1:
            info["why"] = (f"{len(j.ins)} in / {len(j.outs)} out: a valve has 1 input and 2 outputs - chain two "
                           f"valves or move one branch")
            return info
        nbrs = list(nf.adj[n])
        in_nb = [v for v in nbrs if nf.edge_flow.get((v, n), 0) > EPS]
        out_nb = [v for v in nbrs if nf.edge_flow.get((n, v), 0) > EPS]
        if len(in_nb) == 1:
            a = in_nb[0]
            straight = (2 * n[0] - a[0], 2 * n[1] - a[1])
            if abs(a[0] - n[0]) + abs(a[1] - n[1]) != 1:
                info["why"] = "inflow arrives through a quantum hop - needs a straight 3-tile run"
                return info
            if straight in out_nb:
                tiles = [a, n, straight]
                if max(self.sol.occ_s.get(c, 0) + self.sol.occ_l.get(c, 0) for c in tiles) > 1:
                    info["why"] = "another pipe shares the valve tiles - re-route that pipe"
                    return info
                info["tiles"], info["ok"] = tiles, True
                info["straight_pct"] = 100.0 * nf.edge_flow[(n, straight)] / tot_in
                info["side_pct"] = 100.0 - info["straight_pct"]
                return info
        info["why"] = "inflow does not run straight through the junction - re-route so it enters at one end"
        return info

    # ---------------------------------------------------------------- lookups for renderers
    def tile_index(self):
        """tile -> list of (net index, graph node) for hover lookups."""
        idx = defaultdict(list)
        for nf in self.nets:
            large = self.problem.nets[nf.ni].large
            for n in nf.adj:
                cells = [n] if not large else [n, (n[0] + 1, n[1]), (n[0], n[1] + 1), (n[0] + 1, n[1] + 1)]
                for c in cells:
                    idx[c].append((nf.ni, n))
        return idx

    def node_flow(self, nf, n, which="planned"):
        """Flow passing through graph node n (max of in/out)."""
        fl = {"planned": nf.edge_flow, "even": nf.sim_flow, "valve": nf.valve_flow}[which]
        fin = sum(f for (a, b), f in fl.items() if b == n)
        fout = sum(f for (a, b), f in fl.items() if a == n)
        j = nf.junctions.get(n)
        if which == "planned" and j:
            fin = max(fin, sum(f for _, f in j.ins))
            fout = max(fout, sum(f for _, f in j.outs))
        return max(fin, fout)


def _water_fill(total, caps, base):
    """Split `total` evenly over the directions; full ones (cap reached) drop out."""
    amounts = list(base)
    room = [max(0.0, c) for c in caps]
    open_ = [i for i, r in enumerate(room) if r > EPS]
    rest = total
    while rest > EPS and open_:
        share = rest / len(open_)
        tight = [i for i in open_ if room[i] <= share + EPS]
        if not tight:
            for i in open_:
                amounts[i] += share
                room[i] -= share
            rest = 0.0
            break
        for i in tight:
            amounts[i] += room[i]
            rest -= room[i]
            room[i] = 0.0
        open_ = [i for i in open_ if room[i] > EPS]
    return amounts


def analyse(problem, sol, valves=True):
    """Full check: find where even splits starve machines, place valves there, re-check as built."""
    first = Analysis(problem, sol).analyse()
    if not valves or not first.valve_nets:
        first.placed, first.unplaced = [], []
        return first
    from .valves import place_valves
    placed, unplaced = place_valves(problem, sol, first)
    sol.valves = placed
    return Analysis(problem, sol).analyse(placed=placed, needed=first.valve_nets, unplaced=unplaced)
