"""Turns a planner save + machines.json + recipes.json into machine instances and pipe nets.

Rates, products and port ids come from planner.py (a port of the web app's solver, including the
special recipes). Port inference is only used for recipes that are neither in recipes.json nor
ported in special.py.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import planner as plan
from .shapes import Port, Rect, Shape, machine_shape, modular_turbine, tree_farm

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
    # pipe networks to build as a valve manifold (net keys from a first even-split check)
    "valve_nets": [],
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
    connected: float | None = None   # planner flow on this slot (all machines of the node), /s
    self_feed: float = 0.0           # part of `connected` that loops back into the same machine
    temperature: float | None = None


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
    recipe: dict | None = None                  # resolved recipe (planner port)
    settings: dict = field(default_factory=dict)
    special: bool = False
    result: object = None                       # planner.NodeResult

    @property
    def node_id_short(self):
        return self.id

    @property
    def util(self):
        return self.machine_count / self.count if self.count else 0.0


@dataclass
class Terminal:
    inst: int          # global instance index
    ports: tuple       # candidate port ids (pipe may attach to any one of them)
    direction: str = "input"   # "input" (machine takes from the pipe) | "output" (machine feeds it)
    rate: float | None = None  # planned flow through this terminal, /s
    capacity: float | None = None  # what this machine takes/gives at 100 %, /s
    slot: tuple = ()           # (node index, direction, slot index)


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
    key: str = ""        # stable id of this pipe network across rebuilds (for valve requests)
    product_name: str = "?"
    temperature: float | None = None


@dataclass
class Problem:
    nodes: list
    instances: list      # (node index, local index)
    nets: list
    warnings: list
    notes: list
    spacing: dict = field(default_factory=dict)
    spacing_measure: str = "edge"
    plan: object = None          # planner.PlanResult
    products: dict = field(default_factory=dict)
    machines: dict = field(default_factory=dict)
    self_feeds: list = field(default_factory=list)   # (node index, output idx, input idx, flow)
    valves: list = field(default_factory=list)       # valve controls built into the layout

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


ADAPTER_SIZE = 8


def valve_shape(kind: str) -> Shape:
    """3x1 fluid / item valve control: in at the left end, straight out at the right end,
    side out of the middle tile (bottom)."""
    ports = {"valve_in": Port("valve_in", kind, "input", "left", ((0, 0),), 1),
             "valve_straight": Port("valve_straight", kind, "output", "right", ((2, 0),), 1),
             "valve_side": Port("valve_side", kind, "output", "bottom", ((1, 0),), 1)}
    sid = f"valve_{kind.lower()}"
    name = "Fluid Valve Control" if kind == "Fluid" else "Item Valve Control"
    return Shape(sid, name, 3, 1, [Rect(0, 0, 3, 1, "Valve", sid)], ports, "Logistics")


def adapter_shape(small_to_large: bool) -> Shape:
    """8x8 small <-> large fluid pipe adapter. Port positions are an assumption (not in machines.json):
    the 2-wide large port is centred on the left side, the 1-wide small port centred on the right."""
    n = ADAPTER_SIZE
    mid = n // 2
    ld, sd = ("output", "input") if small_to_large else ("input", "output")
    ports = {"adapter_large": Port("adapter_large", "Fluid", ld, "left", ((0, mid - 1), (0, mid)), 2),
             "adapter_small": Port("adapter_small", "Fluid", sd, "right", ((n - 1, mid),), 1)}
    sid = "pipe_adapter_s2l" if small_to_large else "pipe_adapter_l2s"
    return Shape(sid, "Pipe Adapter", n, n, [Rect(0, 0, n, n, "Adapter", sid)], ports, "Logistics")


def load_problem(save_path, machines_path, recipes_path, cfg_overrides=None) -> Problem:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in (cfg_overrides or {}).items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v

    machines, recipes, products = plan.load_data(machines_path, recipes_path, cfg.get("products_path"))
    with open(save_path, encoding="utf-8") as f:
        save = json.load(f)
    data = save.get("data", save)
    planned = plan.Planner(save, machines, recipes, products).solve()

    shapes = {mid: machine_shape(m) for mid, m in machines.items()}
    port_kind = {p["id"]: p.get("product_type") for m in machines.values() for p in m.get("ports", [])}

    warnings, notes = list(planned.warnings), []
    if not planned.converged:
        warnings.append("planner temperature propagation did not settle - rates of temperature dependent "
                        "machines may be off")
    nodes: list[Node] = []
    node_index = {}

    edges = data.get("edges", [])
    used_slots = defaultdict(set)
    for e in edges:
        used_slots[e["source"]].add(("output", e["sourceIndex"]))
        used_slots[e["target"]].add(("input", e["targetIndex"]))

    def composite_ports(shape, recipe_ports):
        """Recipe port ids -> ports of a composite footprint ("<id>#<n>")."""
        out = []
        for rp in recipe_ports:
            out += [pid for pid in shape.ports if pid == rp or pid.startswith(rp + "#")]
        return out

    for n in data["nodes"]:
        if n.get("type") != "recipe":
            warnings.append(f"Skipping node {n['id']} of type {n.get('type')}")
            continue
        mc = float(n.get("machineCount", 0) or 0)
        if mc <= 0:
            warnings.append(f"Skipping node {n['id']} ({n['recipeId']}): machine count 0")
            continue
        count = max(1, plan.ceil_count(mc))
        rid = n["recipeId"]
        settings = n.get("settings", {}) or {}
        nres = planned.nodes.get(n["id"])
        recipe = nres.recipe if nres else None
        slots = {}
        known = recipe is not None
        if rid.startswith("r_modular_turbine"):
            shape = modular_turbine(shapes, int(settings.get("lpt_count", 5)), int(settings.get("hpt_count", 1)))
            notes.append(f"{rid}: built modular turbine (input, {settings.get('lpt_count', 5)} LPT, 1 IPT, "
                         f"{settings.get('hpt_count', 1)} HPT, generator, output) = {shape.w}x{shape.h}")
        elif rid.startswith("r_tree_farm"):
            shape = tree_farm(shapes, settings, cfg["trees_per_sprinkler"])
            notes.append(f"{rid}: built tree farm from guide layout = {shape.w}x{shape.h}")
        elif recipe is not None:
            shape = shapes[recipe["machine_id"]]
        else:
            mid = _machine_for(rid, machines, cfg)
            if mid is None:
                warnings.append(f"Recipe {rid} not found and no machine matches its name - node skipped")
                continue
            shape = shapes[mid]
        name = (recipe or {}).get("name") or shape.name
        if shape.name not in name:
            name = f"{shape.name}: {name}"

        if recipe is not None:
            for direction, key in (("input", "inputs"), ("output", "outputs")):
                flows = nres.inputs if direction == "input" else nres.outputs
                for i, io in enumerate(recipe[key]):
                    if shape.id.startswith("tree_farm"):
                        want = "input" if direction == "input" else "output"
                        ports = [pid for pid, pp in shape.ports.items() if pp.direction == want]
                        req_all = True
                    elif shape.id.startswith("modular_turbine"):
                        ports, req_all = composite_ports(shape, io.get("port_ids", [])), False
                    else:
                        ports = [pp for pp in io.get("port_ids", []) if pp in shape.ports]
                        req_all = False
                    kinds = {shape.ports[pp].kind for pp in ports} or \
                            ({products.get(io["product_id"], {}).get("type")} - {None})
                    kind = kinds.pop() if len(kinds) == 1 else None
                    slots[(direction, i)] = Slot(i, direction, io["product_id"], plan.rate_of(io, recipe), kind,
                                                 ports, require_all=req_all, connected=flows[i].connected,
                                                 temperature=flows[i].temperature)
                    if not ports and (n["id"], direction, i) in {(k, d, j) for k, v in used_slots.items()
                                                                  for d, j in v}:
                        warnings.append(f"{rid}: {direction} #{i} ({pretty(io['product_id'])}) lists no port of "
                                        f"{shape.id} - ports will be inferred")
                        slots[(direction, i)].inferred = True
        else:
            n_in = max([len(n.get("inputOrder", []))] + [i + 1 for d, i in used_slots[n["id"]] if d == "input"])
            n_out = max([len(n.get("outputOrder", []))] + [i + 1 for d, i in used_slots[n["id"]] if d == "output"])
            for i in range(n_in):
                slots[("input", i)] = Slot(i, "input", inferred=True)
            for i in range(n_out):
                slots[("output", i)] = Slot(i, "output", inferred=True)
            notes.append(f"{rid}: not in recipes.json and not a ported special recipe -> assumed machine "
                         f"{shape.id}; ports and rates inferred")

        # explicit overrides from the config file
        po = cfg["port_overrides"].get(rid, {})
        for direction, key in (("input", "inputs"), ("output", "outputs")):
            for si, plist in po.get(key, {}).items():
                s_ = slots.setdefault((direction, int(si)), Slot(int(si), direction))
                s_.ports, s_.inferred = list(plist), False
                s_.kind = s_.kind or next((port_kind.get(pp) for pp in plist if port_kind.get(pp)), None)
            for si, rate in cfg["rate_overrides"].get(rid, {}).get(key, {}).items():
                s_ = slots.setdefault((direction, int(si)), Slot(int(si), direction))
                s_.rate, s_.connected = float(rate), float(rate) * mc

        node_index[n["id"]] = len(nodes)
        nodes.append(Node(n["id"], rid, name, shape, mc, count, known, slots, recipe, settings,
                          bool(nres and nres.special), nres))

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
            self_loops.append((a, b, planned.edge_flows.get(e["id"], 0.0)))
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
    for a, b, _f in self_loops:
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

    # ---- self feeds: an output that loops back into the same machine needs no pipe
    self_feeds = []
    for a, b, f in self_loops:
        slot(a).self_feed += f
        slot(b).self_feed += f
        self_feeds.append((a[0], a[2], b[2], f))
        notes.append(f"self feed on {nodes[a[0]].recipe_id}: output #{a[2]} -> input #{b[2]} "
                     f"({pretty(slot(a).product)}, {f:.2f}/s) handled inside the machine, no pipe")

    # ---- instances
    instances, inst_base = [], []
    for ni, node in enumerate(nodes):
        inst_base.append(len(instances))
        instances.extend((ni, i) for i in range(node.count))

    cap = cfg["pipe_capacity"]
    nets: list[Net] = []

    def external(key):
        s_ = slot(key)
        if s_.connected is None:
            return None
        return max(0.0, s_.connected - s_.self_feed)

    def slot_terminals(ni, key, s_: Slot, inst_ids):
        node = nodes[ni]
        ext = external(key)
        per = None if ext is None else ext / node.count
        out = []
        for i in inst_ids:
            g = inst_base[ni] + i
            if s_.require_all:
                k = max(1, len(s_.ports))
                out.extend(Terminal(g, (pp,), s_.direction, None if per is None else per / k,
                                    None if s_.rate is None else s_.rate / k, key) for pp in s_.ports)
            else:
                out.append(Terminal(g, tuple(s_.ports), s_.direction, per, s_.rate, key))
        return out

    adapters = []   # (small_to_large, large net index, small net index, flow /s)
    valve_keys = set(cfg.get("valve_nets") or [])
    problem_valves = []
    valve_jobs = []   # (net key, kind, product name, product, temperature, chain outlets)
    for root, members in comps.items():
        if len(members) < 2:
            continue
        members.sort()
        ss = [slot(k) for k in members]
        if any(not s_.ports for s_ in ss):
            warnings.append(f"Net {[(nodes[k[0]].recipe_id, k[1], k[2]) for k in members]} has slots without "
                            f"ports - skipped")
            continue
        kind = next((s_.kind for s_ in ss if s_.kind), "Item")
        is_wide = [all(nodes[k[0]].shape.ports[pp].width >= 2 for pp in s_.ports) for k, s_ in zip(members, ss)]
        large = kind == "Fluid" and all(is_wide)
        mixed = kind == "Fluid" and any(is_wide) and not all(is_wide)
        capacity = cap["LargeFluid"] if large else cap[kind]
        product = next((s_.product for s_ in ss if s_.product), None)
        temp = next((s_.temperature for k, s_ in zip(members, ss) if k[1] == "output" and s_.temperature is not None),
                    None)

        ext = [external(k) for k in members]
        side_flow = {}
        if any(v is None for v in ext):
            flow = None
        else:
            sup = sum(v for k, v in zip(members, ext) if k[1] == "output")
            dem = sum(v for k, v in zip(members, ext) if k[1] == "input")
            flow = max(sup, dem)
            for wide in (True, False):
                side_flow[wide] = sum((v if k[1] == "output" else -v) for k, v, w in zip(members, ext, is_wide)
                                      if w == wide)
        min_count = min(nodes[k[0]].count for k in members)
        if flow is None:
            k_split = min_count            # unknown rate: one pipe per machine group (max parallelism)
        else:
            need = flow / capacity
            if mixed:
                need = max(max(abs(side_flow[True]), 1e-9) / cap["LargeFluid"],
                           max(abs(side_flow[False]), 1e-9) / cap["Fluid"])
            k_split = max(1, math.ceil(need * (1 + cfg["flow_margin"]) - 1e-9))
            k_split = min(k_split, min_count)
            if not mixed and flow / k_split > capacity * 1.0001:
                warnings.append(f"{plan.product_name(products, product)}: {flow:.1f}/s over {k_split} pipe(s) "
                                f"exceeds pipe capacity {capacity:g}/s (limited by a group with {min_count} "
                                f"machine(s))")
        pname = plan.product_name(products, product)
        label_parts = sorted({nodes[k[0]].recipe_id for k in members})
        for j in range(k_split):
            parts = {True: [], False: []}
            for k, s_, w in zip(members, ss, is_wide):
                n_c = nodes[k[0]].count
                ids = [i for i in range(n_c) if (i * k_split) // n_c == j]
                parts[w].extend(slot_terminals(k[0], k, s_, ids))
            sfx = f" [{j + 1}/{k_split}]" if k_split > 1 else ""
            if not mixed:
                terms = parts[True] + parts[False]
                key = f"{pname}|{'+'.join(f'{nodes[k[0]].node_id_short}:{k[1][0]}{k[2]}' for k in members)}|{j}"
                if len(terms) >= 2:
                    if key in valve_keys and not large and flow is not None:
                        chain = _valve_chain(terms, nodes, instances)
                        if chain:
                            valve_jobs.append((key, kind, pname, product, temp, chain))
                            continue
                    nets.append(Net(len(nets), pname + sfx, product, kind, large,
                                    None if flow is None else flow / k_split, capacity, terms,
                                    product_name=pname, temperature=temp, key=key))
                continue
            # mixed widths: small pipe -> 8x8 adapter -> large pipe
            through = None if flow is None else side_flow[False] / k_split   # >0: small side feeds large side
            s2l = through is None or through >= 0
            amt = None if through is None else abs(through)
            adapters.append((s2l, len(nets), len(nets) + 1, amt))
            nets.append(Net(len(nets), pname + sfx + " (large side)", product, kind, True, None,
                            cap["LargeFluid"], parts[True], product_name=pname, temperature=temp))
            nets.append(Net(len(nets), pname + sfx + " (small side)", product, kind, False, None,
                            cap["Fluid"], parts[False], product_name=pname, temperature=temp))
            if amt is not None and amt > cap["Fluid"] * 1.0001:
                warnings.append(f"{pname}: {amt:.1f}/s through a small pipe adapter exceeds the small pipe "
                                f"capacity {cap['Fluid']:g}/s")
        if mixed:
            notes.append(f"net {pname}: mixes 1-wide and 2-wide fluid ports -> {k_split} pipe adapter(s) (8x8)")
        notes.append(f"net {pname} ({kind}{', large' if large else ''}): "
                     f"{'flow unknown' if flow is None else f'{flow:.2f}/s'} -> {k_split} pipe network(s); "
                     f"{' + '.join(label_parts)}")

    # ---- valve manifolds: sources -> valve 1 -> valve 2 -> ...; every valve's side outlet feeds one outlet
    for vkind in ("Item", "Fluid"):
        jobs = [jb for jb in valve_jobs if jb[1] == vkind]
        if not jobs:
            continue
        shape = valve_shape(vkind)
        ni = len(nodes)
        total = sum(len(jb[5][1]) - 1 for jb in jobs)
        nodes.append(Node(f"valves-{vkind.lower()}", shape.id, shape.name, shape, total, total, True, {}))
        inst_base.append(len(instances))
        local = 0
        for key, _k, pname, product, temp, (sources, outlets) in jobs:
            demand = [sum(t.rate or 0.0 for t in o) for o in outlets]
            n_v = len(outlets) - 1
            g0 = len(instances)
            for i in range(n_v):
                instances.append((ni, local))
                local += 1
            through = sum(demand)
            vcap = cap[vkind]

            def mk(label, terms, f):
                nets.append(Net(len(nets), label, product, vkind, False, f, vcap, terms, product_name=pname,
                                temperature=temp, key=key))
            mk(f"{pname} -> valve 1", sources + [Terminal(g0, ("valve_in",), "input", through, None,
                                                           (ni, "input", 0))], through)
            rest = through
            for i in range(n_v):
                g = g0 + i
                side_amt = demand[i]
                pct = 100.0 * side_amt / rest if rest > 0 else 0.0
                problem_valves.append({"inst": g, "key": key, "product": pname, "side_pct": pct,
                                       "straight_pct": 100.0 - pct, "flow": rest, "side_flow": side_amt,
                                       "index": i + 1, "of": n_v})
                mk(f"{pname} valve {i + 1} side ({pct:.1f}%)",
                   [Terminal(g, ("valve_side",), "output", side_amt, None, (ni, "output", 1))] + outlets[i], side_amt)
                rest -= side_amt
                nxt = ([Terminal(g + 1, ("valve_in",), "input", rest, None, (ni, "input", 0))] if i + 1 < n_v
                       else outlets[-1])
                mk(f"{pname} valve {i + 1} straight ({100 - pct:.1f}%)",
                   [Terminal(g, ("valve_straight",), "output", rest, None, (ni, "output", 0))] + nxt, rest)
            notes.append(f"{pname}: even splitting would starve machines -> {n_v} {shape.name}(s) in a manifold")

    # ---- adapters become placeable 8x8 pieces, one node per direction
    for s2l in (True, False):
        mine = [a for a in adapters if a[0] == s2l]
        if not mine:
            continue
        shape = adapter_shape(s2l)
        ni = len(nodes)
        nodes.append(Node(f"adapter-{'s2l' if s2l else 'l2s'}", shape.id,
                          "Pipe Adapter (small -> large)" if s2l else "Pipe Adapter (large -> small)",
                          shape, len(mine), len(mine), True, {}))
        inst_base.append(len(instances))
        for i, (_, li, si, amt) in enumerate(mine):
            g = len(instances)
            instances.append((ni, i))
            nets[li].terminals.append(Terminal(g, ("adapter_large",), "output" if s2l else "input", amt, None,
                                               (ni, "output" if s2l else "input", 0)))
            nets[si].terminals.append(Terminal(g, ("adapter_small",), "input" if s2l else "output", amt, None,
                                               (ni, "input" if s2l else "output", 0)))
        notes.append(f"{len(mine)} pipe adapter(s) {'small -> large' if s2l else 'large -> small'}; adapter port "
                     f"positions are assumed (large port left, small port right)")
        for _, li, si, _amt in mine:
            for net in (nets[li], nets[si]):
                if all(t.rate is not None for t in net.terminals):
                    net.flow = max(sum(t.rate for t in net.terminals if t.direction == "output"),
                                   sum(t.rate for t in net.terminals if t.direction == "input"))
    nets[:] = [n_ for n_ in nets if len(n_.terminals) >= 2]
    for i, n_ in enumerate(nets):
        n_.id = i

    spacing = {k: float(v) for k, v in cfg["min_spacing"].items() if v}
    for mid, d in spacing.items():
        n = sum(nd.count for nd in nodes if nd.shape.id == mid)
        if n > 1:
            notes.append(f"spacing rule: the {n} x {mid} must be at least {d:g} tiles apart "
                         f"({cfg['spacing_measure']} distance)")
    return Problem(nodes, instances, nets, warnings, notes, spacing, cfg["spacing_measure"], planned, products,
                   machines, self_feeds, problem_valves)


def _valve_chain(terms, nodes, instances):
    """Split a pipe network's terminals into (sources, outlets) for a valve manifold.

    Every outlet gets exactly its planned share. A consumer group whose machines have no other piped input
    shares one outlet (uneven sharing inside it loses nothing); other machines get an outlet each."""
    sources = [t for t in terms if t.direction == "output"]
    sinks = [t for t in terms if t.direction == "input"]
    if not sources or len(sinks) < 2:
        return None
    by_node = defaultdict(list)
    for t in sinks:
        by_node[instances[t.inst][0]].append(t)
    outlets = []
    for ni_, ts in sorted(by_node.items()):
        node = nodes[ni_]
        piped_inputs = [s_ for (d, _), s_ in node.slots.items()
                        if d == "input" and s_.ports and (s_.connected or 0) - s_.self_feed > 1e-9]
        if len(piped_inputs) <= 1:
            outlets.append(sorted(ts, key=lambda t: t.inst))
        else:
            per = defaultdict(list)
            for t in ts:
                per[t.inst].append(t)
            outlets.extend(per[i] for i in sorted(per))
    if len(outlets) < 2:
        return None
    return sources, outlets
