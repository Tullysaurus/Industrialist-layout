"""Turns a planner save + machines.json + recipes.json into machine instances and pipe nets."""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .shapes import Shape, machine_shape, modular_turbine, tree_farm

DEFAULT_CONFIG = {
    "pipe_capacity": {"Item": 120.0, "Fluid": 120.0, "LargeFluid": 12000.0},
    "flow_margin": 0.0,             # extra headroom when splitting nets by pipe speed
    "machine_overrides": {},        # recipe id -> machine id
    "port_overrides": {},           # recipe id -> {"inputs": {"0": [port ids]}, "outputs": {...}}
    "rate_overrides": {},           # recipe id -> {"inputs": {"0": per-machine rate/s}, ...}
    "trees_per_sprinkler": 44,
    # minimum distance between two machines of the same type (machine id -> tiles)
    "min_spacing": {"m_mineshaft_drill": 48},
    # "edge": empty tiles between footprints along x or y (strictest, default)
    # "center": straight-line distance between machine centres
    "spacing_measure": "edge",
}


def pretty(pid: str | None) -> str:
    if not pid:
        return "?"
    return re.sub(r"^p_", "", pid).replace("_", " ").title()


@dataclass
class Slot:
    idx: int
    direction: str              # "input" | "output"
    product: str | None = None
    rate: float | None = None   # units/s for one machine running at 100%
    kind: str | None = None     # "Item" | "Fluid"
    ports: list = field(default_factory=list)
    require_all: bool = False   # every listed port needs its own connection
    inferred: bool = False


@dataclass
class Node:
    id: str
    recipe_id: str
    name: str
    shape: Shape
    machine_count: float
    count: int
    known: bool
    slots: dict = field(default_factory=dict)   # (direction, idx) -> Slot

    @property
    def util(self):
        return self.machine_count / self.count if self.count else 0.0


@dataclass
class Terminal:
    inst: int          # global instance index
    ports: tuple       # candidate port ids (pipe may attach to any one of them)


@dataclass
class Net:
    id: int
    label: str
    product: str | None
    kind: str
    large: bool
    flow: float | None
    capacity: float
    terminals: list
    stub: bool = False   # same-machine (quantum) connection: only a pipe stub at the port


@dataclass
class Problem:
    nodes: list
    instances: list      # (node index, local index)
    nets: list
    warnings: list
    notes: list
    spacing: dict = field(default_factory=dict)
    spacing_measure: str = "edge"

    def spacing_of(self, inst):
        return self.spacing.get(self.nodes[self.instances[inst][0]].shape.id)


def _machine_for(recipe_id: str, machines: dict, cfg: dict) -> str | None:
    if recipe_id in cfg["machine_overrides"]:
        return cfg["machine_overrides"][recipe_id]
    base = re.sub(r"_\d+$", "", re.sub(r"^r_", "", recipe_id)).lower()
    parts = base.split("_")
    for n in range(len(parts), 0, -1):
        mid = "m_" + "_".join(parts[:n])
        if mid in machines:
            return mid
    return None


def load_problem(save_path, machines_path, recipes_path, cfg_overrides=None) -> Problem:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in (cfg_overrides or {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v

    with open(machines_path, encoding="utf-8") as f:
        mlist = json.load(f)
    with open(recipes_path, encoding="utf-8") as f:
        rlist = json.load(f)
    with open(save_path, encoding="utf-8") as f:
        save = json.load(f)
    data = save.get("data", save)

    machines = {m["id"]: m for m in mlist}
    shapes = {mid: machine_shape(m) for mid, m in machines.items()}
    recipes = {r["id"]: r for r in rlist}
    port_kind = {p["id"]: p.get("product_type") for m in mlist for p in m.get("ports", [])}

    warnings, notes = [], []
    nodes: list[Node] = []
    node_index = {}

    edges = data.get("edges", [])
    used_slots = defaultdict(set)
    for e in edges:
        used_slots[e["source"]].add(("output", e["sourceIndex"]))
        used_slots[e["target"]].add(("input", e["targetIndex"]))

    for n in data["nodes"]:
        if n.get("type") != "recipe":
            warnings.append(f"Skipping node {n['id']} of type {n.get('type')}")
            continue
        mc = float(n.get("machineCount", 0) or 0)
        if mc <= 0:
            warnings.append(f"Skipping node {n['id']} ({n['recipeId']}): machine count 0")
            continue
        count = max(1, math.ceil(mc - 1e-9))
        rid = n["recipeId"]
        settings = n.get("settings", {}) or {}
        slots = {}
        known = rid in recipes
        if known:
            r = recipes[rid]
            shape = shapes[r["machine_id"]]
            name = r["name"]
            for direction, key in (("input", "inputs"), ("output", "outputs")):
                for i, io in enumerate(r[key]):
                    kinds = {port_kind.get(p) for p in io["port_ids"]} - {None}
                    slots[(direction, i)] = Slot(i, direction, io["product_id"],
                                                 io["quantity"] / r["cycle_time"],
                                                 kinds.pop() if len(kinds) == 1 else None,
                                                 list(io["port_ids"]))
        elif rid.startswith("r_modular_turbine"):
            shape = modular_turbine(shapes, int(settings.get("lpt_count", 0)), int(settings.get("hpt_count", 0)))
            name = shape.name
            ins = [p for p, v in shape.ports.items() if v.direction == "input"]
            outs = [p for p, v in shape.ports.items() if v.direction == "output"]
            slots[("input", 0)] = Slot(0, "input", None, None, "Fluid", ins)
            slots[("output", 0)] = Slot(0, "output", None, None, "Fluid", outs)
            notes.append(f"{rid}: built modular turbine (input, {settings.get('lpt_count', 0)} LPT, 1 IPT, "
                         f"{settings.get('hpt_count', 0)} HPT, generator, output) = {shape.w}x{shape.h}")
        elif rid.startswith("r_tree_farm"):
            shape = tree_farm(shapes, settings, cfg["trees_per_sprinkler"])
            name = shape.name
            ins = [p for p, v in shape.ports.items() if v.direction == "input"]
            outs = [p for p, v in shape.ports.items() if v.direction == "output"]
            slots[("input", 0)] = Slot(0, "input", "p_water", None, "Fluid", ins, require_all=True)
            slots[("output", 0)] = Slot(0, "output", "p_oak_log", None, "Item", outs, require_all=True)
            notes.append(f"{rid}: built tree farm from guide layout = {shape.w}x{shape.h} "
                         f"({len(ins)} water tank(s), {len(outs)} output(s))")
        else:
            mid = _machine_for(rid, machines, cfg)
            if mid is None:
                warnings.append(f"Recipe {rid} not found and no machine matches its name - node skipped")
                continue
            shape = shapes[mid]
            name = f"{shape.name} [{rid}]"
            n_in = max([len(n.get("inputOrder", []))] + [i + 1 for d, i in used_slots[n["id"]] if d == "input"])
            n_out = max([len(n.get("outputOrder", []))] + [i + 1 for d, i in used_slots[n["id"]] if d == "output"])
            for i in range(n_in):
                slots[("input", i)] = Slot(i, "input", inferred=True)
            for i in range(n_out):
                slots[("output", i)] = Slot(i, "output", inferred=True)
            notes.append(f"{rid}: not in recipes.json -> assumed machine {mid}; ports inferred")

        # explicit overrides from the config file
        po = cfg["port_overrides"].get(rid, {})
        for direction, key in (("input", "inputs"), ("output", "outputs")):
            for si, plist in po.get(key, {}).items():
                s = slots.setdefault((direction, int(si)), Slot(int(si), direction))
                s.ports, s.inferred = list(plist), False
                s.kind = s.kind or next((port_kind.get(p) for p in plist if port_kind.get(p)), None)
            for si, rate in cfg["rate_overrides"].get(rid, {}).get(key, {}).items():
                slots.setdefault((direction, int(si)), Slot(int(si), direction)).rate = float(rate)

        node_index[n["id"]] = len(nodes)
        nodes.append(Node(n["id"], rid, name, shape, mc, count, known, slots))

    # ---- group slots into nets (union find over edges; self loops handled separately)
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    self_loops = []
    for e in edges:
        if e["source"] not in node_index or e["target"] not in node_index:
            continue
        a = (node_index[e["source"]], "output", e["sourceIndex"])
        b = (node_index[e["target"]], "input", e["targetIndex"])
        for ni, d, i in (a, b):
            nodes[ni].slots.setdefault((d, i), Slot(i, d, inferred=True))
        if e["source"] == e["target"]:
            self_loops.append((a, b))
            find(a), find(b)
        else:
            union(a, b)

    comps = defaultdict(list)
    for key in list(parent):
        comps[find(key)].append(key)

    # ---- infer product / kind for unknown slots by propagating through nets
    def slot(key):
        return nodes[key[0]].slots[(key[1], key[2])]

    loop_pairs = defaultdict(list)
    for a, b in self_loops:
        loop_pairs[find(a)].append(find(b))
        loop_pairs[find(b)].append(find(a))
    changed = True
    while changed:
        changed = False
        for root, members in comps.items():
            kinds = {slot(k).kind for k in members} - {None}
            prods = {slot(k).product for k in members} - {None}
            for other in loop_pairs.get(root, []):   # self loops carry the same product
                kinds |= {slot(k).kind for k in comps[other]} - {None}
                prods |= {slot(k).product for k in comps[other]} - {None}
            for k in members:
                s = slot(k)
                if s.kind is None and len(kinds) == 1:
                    s.kind, changed = next(iter(kinds)), True
                if s.product is None and len(prods) == 1:
                    s.product, changed = next(iter(prods)), True
        # per machine: a slot whose kind is unknown can only be a kind that still has
        # a free port after every known-kind slot has taken one
        for node in nodes:
            for direction in ("input", "output"):
                group = [s for (d, _), s in node.slots.items() if d == direction]
                unknown = [s for s in group if s.kind is None and s.inferred]
                if not unknown:
                    continue
                count = defaultdict(int)
                for p in node.shape.ports.values():
                    if p.direction == direction:
                        count[p.kind] += 1
                for s in group:
                    if s.kind:
                        count[s.kind] -= 1
                possible = [k for k, c in count.items() if c >= 1]
                if len(possible) == 1:
                    for s in unknown:
                        s.kind, changed = possible[0], True

    # ---- assign ports to inferred slots
    for ni, node in enumerate(nodes):
        for direction in ("input", "output"):
            inferred = sorted((s for (d, _), s in node.slots.items() if d == direction and s.inferred and not s.ports),
                              key=lambda s: s.idx)
            if not inferred:
                continue
            taken = {p for (d, _), s in node.slots.items() if d == direction for p in s.ports}
            ports = [p for p in sorted(node.shape.ports.values(),
                                       key=lambda p: int(re.sub(r"\D", "", p.id.split("_port_")[-1]) or 0))
                     if p.direction == direction and p.id not in taken]
            for kind in ("Item", "Fluid", None):
                group = [s for s in inferred if s.kind == kind]
                if not group:
                    continue
                cand = [p.id for p in ports if kind is None or p.kind == kind]
                if not cand:
                    warnings.append(f"{node.recipe_id}: no free {kind or ''} {direction} port for "
                                    f"slot(s) {[s.idx for s in group]}")
                    continue
                n_s, n_p = len(group), len(cand)
                for j, s in enumerate(group):
                    s.ports = cand[j * n_p // n_s:(j + 1) * n_p // n_s] if n_s <= n_p else [cand[j % n_p]]
                    if s.kind is None:
                        s.kind = node.shape.ports[s.ports[0]].kind
                ports = [p for p in ports if p.id not in {q for s in group for q in s.ports}]
            for s in inferred:
                notes.append(f"  {node.recipe_id} {direction} #{s.idx} ({pretty(s.product)}, {s.kind}) -> "
                             f"{', '.join(s.ports) or 'NONE'}")

    # ---- slots of one machine that share candidate ports must get distinct ports
    for node in nodes:
        for direction in ("input", "output"):
            group = sorted((s for (d, _), s in node.slots.items() if d == direction and s.ports),
                           key=lambda s: s.idx)
            seen, overlap = set(), False
            for s in group:
                if seen & set(s.ports):
                    overlap = True
                seen |= set(s.ports)
            if not overlap:
                continue
            used = set()
            for s in sorted(group, key=lambda s: (len(s.ports), s.idx)):
                free = [p for p in s.ports if p not in used]
                s.ports = [free[0] if free else s.ports[0]]
                used.add(s.ports[0])

    # ---- instances
    instances, inst_base = [], []
    for ni, node in enumerate(nodes):
        inst_base.append(len(instances))
        instances.extend((ni, i) for i in range(node.count))

    cap = cfg["pipe_capacity"]
    nets: list[Net] = []

    def slot_terminals(ni, s: Slot, inst_ids):
        out = []
        for i in inst_ids:
            g = inst_base[ni] + i
            if s.require_all:
                out.extend(Terminal(g, (p,)) for p in s.ports)
            else:
                out.append(Terminal(g, tuple(s.ports)))
        return out

    for root, members in comps.items():
        if len(members) < 2:
            continue
        members.sort()
        ss = [slot(k) for k in members]
        if any(not s.ports for s in ss):
            warnings.append(f"Net {[(nodes[k[0]].recipe_id, k[1], k[2]) for k in members]} has slots without ports - skipped")
            continue
        kind = next((s.kind for s in ss if s.kind), "Item")
        widths = [nodes[k[0]].shape.ports[p].width for k, s in zip(members, ss) for p in s.ports]
        large = kind == "Fluid" and all(w >= 2 for w in widths)
        capacity = cap["LargeFluid"] if large else cap[kind]
        product = next((s.product for s in ss if s.product), None)

        sup = dem = 0.0
        unknown = False
        for k, s in zip(members, ss):
            node = nodes[k[0]]
            if s.rate is None:
                unknown = True
                continue
            total = s.rate * node.machine_count
            if k[1] == "output":
                sup += total
            else:
                dem += total
        flow = None if unknown else max(sup, dem)
        min_count = min(nodes[k[0]].count for k in members)
        if flow is None:
            k_split = min_count            # unknown rate: one pipe per machine group (max parallelism)
        else:
            k_split = max(1, math.ceil(flow * (1 + cfg["flow_margin"]) / capacity - 1e-9))
            k_split = min(k_split, min_count)
            if flow / k_split > capacity * 1.0001:
                warnings.append(f"{pretty(product)}: {flow:.1f}/s over {k_split} pipe(s) exceeds pipe "
                                f"capacity {capacity:g}/s (limited by a group with {min_count} machine(s))")
        label_parts = sorted({nodes[k[0]].recipe_id for k in members})
        for j in range(k_split):
            terms = []
            for k, s in zip(members, ss):
                n_c = nodes[k[0]].count
                ids = [i for i in range(n_c) if (i * k_split) // n_c == j]
                terms.extend(slot_terminals(k[0], s, ids))
            if len(terms) < 2:
                continue
            nets.append(Net(len(nets), pretty(product) + (f" [{j + 1}/{k_split}]" if k_split > 1 else ""),
                            product, kind, large, None if flow is None else flow / k_split, capacity, terms))
        notes.append(f"net {pretty(product)} ({kind}{', large' if large else ''}): "
                     f"{'flow unknown' if flow is None else f'{flow:.2f}/s'} -> {k_split} pipe network(s); "
                     f"{' + '.join(label_parts)}")

    # ---- self loops: a pipe stub on each port of the same machine (quantum piping)
    ported = {(t.inst, t.ports) for n in nets for t in n.terminals}
    for a, b in self_loops:
        sa, sb = slot(a), slot(b)
        node = nodes[a[0]]
        for i in range(node.count):
            g = inst_base[a[0]] + i
            for s in (sa, sb):
                if (g, tuple(s.ports)) in ported or not s.ports:
                    continue
                large = s.kind == "Fluid" and all(node.shape.ports[p].width >= 2 for p in s.ports)
                nets.append(Net(len(nets), f"{pretty(s.product)} (self-feed stub)", s.product, s.kind or "Fluid",
                                large, None, 0, [Terminal(g, tuple(s.ports))], stub=True))
        notes.append(f"self loop on {node.recipe_id}: output #{a[2]} -> input #{b[2]} uses same-machine "
                     f"(quantum) connection, only pipe stubs reserved")

    spacing = {k: float(v) for k, v in cfg["min_spacing"].items() if v}
    for mid, d in spacing.items():
        n = sum(nd.count for nd in nodes if nd.shape.id == mid)
        if n > 1:
            notes.append(f"spacing rule: the {n} x {mid} must be at least {d:g} tiles apart "
                         f"({cfg['spacing_measure']} distance)")
    return Problem(nodes, instances, nets, warnings, notes, spacing, cfg["spacing_measure"])
