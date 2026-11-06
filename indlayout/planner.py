"""Python port of the planner's flow pipeline (Industrialist-Production-Calculator/src/solver).

Given a planner save it resolves every node's recipe (recipes.json or a ported special recipe),
allocates product flows over the save's edges (max flow per product component, like the planner's
Dinic pass), propagates temperatures (flow weighted mixing, then re-computes temperature dependent
special recipes until settled) and finally collects the dashboard numbers the web app shows on the
left: power, pollution, machine cost / space / model count, shortages and excesses.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field

from . import special

EPS = 1e-9


def load_data(machines_path, recipes_path, products_path=None):
    with open(machines_path, encoding="utf-8") as f:
        machines = {m["id"]: m for m in json.load(f)}
    with open(recipes_path, encoding="utf-8") as f:
        recipes = {r["id"]: r for r in json.load(f)}
    products = {}
    if products_path is None:
        products_path = os.path.join(os.path.dirname(os.path.abspath(machines_path)), "products.json")
    if os.path.exists(products_path):
        with open(products_path, encoding="utf-8") as f:
            products = {p["id"]: p for p in json.load(f)}
    special.MACHINES = machines
    return machines, recipes, products


def product_name(products, pid):
    if not pid:
        return "?"
    p = products.get(pid)
    if p:
        return p["name"]
    return pid.removeprefix("p_").replace("_", " ").title()


@dataclass
class HandleFlow:
    rate: float              # required (input) / produced (output) per second, all machines of the node
    connected: float = 0.0   # what the edges actually deliver / take
    temperature: float | None = None

    @property
    def deficit(self):
        return max(0.0, self.rate - self.connected)

    @property
    def excess(self):
        return max(0.0, self.rate - self.connected)


@dataclass
class NodeResult:
    id: str
    recipe_id: str
    machine_count: float
    settings: dict
    recipe: dict | None
    special: bool
    inputs: list = field(default_factory=list)    # HandleFlow per recipe input
    outputs: list = field(default_factory=list)   # HandleFlow per recipe output


@dataclass
class PlanResult:
    nodes: dict                 # node id -> NodeResult
    edge_flows: dict            # edge id -> flow /s
    edge_temps: dict            # edge id -> °C
    stats: dict
    deficiencies: list          # (product, total, [(node id, rate)])
    excesses: list
    warnings: list
    converged: bool


def rate_of(io, recipe):
    ct = recipe.get("cycle_time") or 1
    return float(io.get("quantity", 0)) / ct


class Planner:
    def __init__(self, save_data, machines, recipes, products):
        self.data = save_data.get("data", save_data)
        self.machines, self.recipes, self.products = machines, recipes, products
        self.globals = self.data.get("globalSettings", {}) or {}
        self.nodes = [n for n in self.data.get("nodes", []) if n.get("type") == "recipe"]
        self.by_id = {n["id"]: n for n in self.nodes}
        self.edges = [e for e in self.data.get("edges", [])
                      if e["source"] in self.by_id and e["target"] in self.by_id]
        self.connected = set()
        for e in self.edges:
            self.connected.add((e["source"], "output", e["sourceIndex"]))
            self.connected.add((e["target"], "input", e["targetIndex"]))
        self.warnings = []

    # ---------------------------------------------------------------- recipe resolution
    def resolve(self, node, temp_overrides=None):
        rid = node["recipeId"]
        sp = special.get_special(rid)
        if sp:
            settings = sp.settings(node.get("settings"))
            if temp_overrides:
                for idx, key in sp.input_temp_settings.items():
                    if idx in temp_overrides and (node["id"], "input", idx) in self.connected:
                        settings[key] = temp_overrides[idx]
            helpers = special.Helpers(lambda side, i, nid=node["id"]: (nid, side, i) in self.connected)
            return sp.compute(settings, self.globals, helpers), True
        r = self.recipes.get(rid)
        return (json.loads(json.dumps(r)) if r else None), False

    # ---------------------------------------------------------------- flows
    def allocate(self, recipes):
        """Max flow per product component over the save's edges (like the planner's Dinic pass)."""
        supply, demand = {}, {}
        for n in self.nodes:
            r = recipes.get(n["id"])
            if not r:
                continue
            mc = float(n.get("machineCount", 0) or 0)
            for i, o in enumerate(r["outputs"]):
                supply[(n["id"], i)] = rate_of(o, r) * mc
            for i, inp in enumerate(r["inputs"]):
                demand[(n["id"], i)] = rate_of(inp, r) * mc
        # components of edges sharing an output or input handle
        parent = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for e in self.edges:
            a, b = ("o", e["source"], e["sourceIndex"]), ("i", e["target"], e["targetIndex"])
            parent[find(a)] = find(b)
        comps = defaultdict(list)
        for e in self.edges:
            comps[find(("o", e["source"], e["sourceIndex"]))].append(e)
        flows = {}
        for es in comps.values():
            flows.update(_maxflow(es, supply, demand))
        return flows

    # ---------------------------------------------------------------- pipeline
    def solve(self, max_passes=8, max_temp_iter=80):
        temp_over = {}
        recipes, flows, converged = {}, {}, False
        for _ in range(max_passes):
            recipes = {}
            for n in self.nodes:
                r, _sp = self.resolve(n, temp_over.get(n["id"]))
                if r is not None:
                    recipes[n["id"]] = r
            flows = self.allocate(recipes)
            new_over, edge_t, it_ok = self.propagate(flows, temp_over, max_temp_iter)
            if _same(new_over, temp_over):
                converged = it_ok
                temp_over = new_over
                break
            temp_over = new_over
        # final resolve with the settled temperatures
        results = {}
        recipes = {}
        for n in self.nodes:
            r, is_sp = self.resolve(n, temp_over.get(n["id"]))
            mc = float(n.get("machineCount", 0) or 0)
            nr = NodeResult(n["id"], n["recipeId"], mc, n.get("settings") or {}, r, is_sp)
            if r is None:
                self.warnings.append(f"{n['recipeId']}: recipe not in recipes.json and not ported as a special "
                                     f"recipe - rates unknown")
            else:
                recipes[n["id"]] = r
                nr.inputs = [HandleFlow(rate_of(i, r) * mc) for i in r["inputs"]]
                nr.outputs = [HandleFlow(rate_of(o, r) * mc, temperature=o.get("temperature", 18))
                              for o in r["outputs"]]
            results[n["id"]] = nr
        flows = self.allocate(recipes)
        _, edge_t, _ = self.propagate(flows, temp_over, 1)
        for e in self.edges:
            f = flows.get(e["id"], 0.0)
            s, t = results[e["source"]], results[e["target"]]
            if e["sourceIndex"] < len(s.outputs):
                s.outputs[e["sourceIndex"]].connected += f
            if e["targetIndex"] < len(t.inputs):
                t.inputs[e["targetIndex"]].connected += f
        for nid, over in temp_over.items():
            for idx, tv in over.items():
                if idx < len(results[nid].inputs):
                    results[nid].inputs[idx].temperature = tv
        stats, defs, excs = self.dashboard(results)
        return PlanResult(results, flows, edge_t, stats, defs, excs, self.warnings, converged)

    def propagate(self, flows, temp_over, max_iter):
        """Flow weighted input temperatures; returns per-node {input idx: °C} for connected inputs."""
        incoming = defaultdict(list)
        for e in self.edges:
            incoming[(e["target"], e["targetIndex"])].append(e)
        cur = {nid: dict(v) for nid, v in temp_over.items()}
        out_t = {}
        edge_t = {}
        ok = False
        for _ in range(max(1, max_iter)):
            for n in self.nodes:
                r, _sp = self.resolve(n, cur.get(n["id"]))
                out_t[n["id"]] = [o.get("temperature", 18) for o in r["outputs"]] if r else []
            for e in self.edges:
                ts = out_t.get(e["source"], [])
                edge_t[e["id"]] = ts[e["sourceIndex"]] if flows.get(e["id"], 0) > EPS and e["sourceIndex"] < len(ts) else 18
            nxt = {}
            for (nid, idx), es in incoming.items():
                tot = sum(flows.get(e["id"], 0) for e in es)
                if tot > EPS:
                    nxt.setdefault(nid, {})[idx] = sum(flows.get(e["id"], 0) * edge_t[e["id"]] for e in es) / tot
            if _same(nxt, cur, 1e-6):
                ok = True
                cur = nxt
                break
            cur = nxt
        return cur, edge_t, ok

    # ---------------------------------------------------------------- dashboard
    def dashboard(self, results):
        st = {"mv_use": 0.0, "mv_output": 0.0, "hv_use": 0.0, "hv_output": 0.0, "net_pollution": 0.0,
              "machine_cost": 0.0, "machine_space": 0.0, "model_count": 0.0, "profit": 0.0}
        defs, excs = defaultdict(list), defaultdict(list)
        for n in self.nodes:
            nr = results[n["id"]]
            r = nr.recipe
            if not r:
                continue
            mc = nr.machine_count
            whole = ceil_count(mc)
            sp = special.get_special(r["id"])
            settings = sp.settings(n.get("settings")) if sp else (n.get("settings") or {})
            machine = self.machines.get(r["machine_id"])
            if machine:
                cost = sp.machine_cost(settings, self.globals, self.machines) if sp and sp.machine_cost else machine["cost"]
                space = (sp.machine_space(settings, self.globals, self.machines) if sp and sp.machine_space
                         else machine["size"]["x"] * machine["size"]["y"])
                st["machine_cost"] += cost * whole
                st["machine_space"] += space * whole
                if machine.get("subcategory") == "Depot":
                    for i, inp in enumerate(r["inputs"]):
                        p = self.products.get(inp["product_id"])
                        if p and i < len(nr.inputs):
                            st["profit"] += nr.inputs[i].connected * p.get("sell_price", 0)
            models = (sp.model_count(settings, self.globals, self.machines) if sp and sp.model_count
                      else 1 + 2 * len(r["inputs"]) + 2 * len(r["outputs"]) + _power_models(r))
            st["model_count"] += models * whole
            p = float(r.get("power_use", 0)) * (1 if r.get("powerIndependentOfMachineCount") else mc)
            hv = r.get("power_type") == "HV"
            if p > 0:
                st["hv_use" if hv else "mv_use"] += p
            elif p < 0:
                st["hv_output" if hv else "mv_output"] += -p
            pol_mult = 1 if (r.get("pollutionIndependentOfMachineCount") or (sp and sp.pollution_independent)) else mc
            st["net_pollution"] += float(r.get("pollution", 0)) * pol_mult
            name = machine["name"] if machine else r["machine_id"]
            for i, inp in enumerate(r["inputs"]):
                hf = nr.inputs[i]
                if not inp.get("variable") and meaningful(hf.rate, hf.connected):
                    defs[inp["product_id"]].append((n["id"], name, hf.deficit))
            for i, out in enumerate(r["outputs"]):
                hf = nr.outputs[i]
                if not out.get("variable") and meaningful(hf.rate, hf.connected):
                    excs[out["product_id"]].append((n["id"], name, hf.excess, bool(out.get("voidable"))))
        x = float(self.globals.get("global_pollution", 0) or 0)
        diff = self.globals.get("difficulty") or "normal"
        if diff == "hard":
            y = clamp(-77 * x / 290, -2800 / 29, 200 / 29)
        elif diff == "impossible":
            y = clamp(-(x * x) / 290, -2800 / 29, 0)
        elif diff == "impossible2":
            y = clamp(-x / 2, -2850 / 29, 200 / 29)
        else:
            y = clamp(-5 * x / 29, -2800 / 29, 200 / 29)
        st["profit_multiplier"] = y
        st["profit"] *= 1 + y / 100
        d_list = sorted(((pid, sum(v[2] for v in vs), vs) for pid, vs in defs.items()), key=lambda t: -t[1])
        e_list = sorted(((pid, sum(v[2] for v in vs), vs) for pid, vs in excs.items()), key=lambda t: -t[1])
        return st, d_list, e_list


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def meaningful(a, b):
    return abs(a - b) > max(1e-6, max(abs(a), abs(b)) * 1e-12)


def ceil_count(v):
    if not math.isfinite(v) or v <= 1e-12:
        return 0
    r = round(v)
    if r > 0 and abs(v - r) <= abs(v) * 2.220446049250313e-16 * 8:
        return r
    return math.ceil(v)


def _power_models(r):
    pu = float(r.get("power_use", 0))
    if pu == 0:
        return 0
    if r.get("power_type") == "HV":
        return 2
    return math.ceil(abs(pu) / 1500000) * 2


def _same(a, b, tol=1e-6):
    if a.keys() != b.keys():
        return False
    for k in a:
        if a[k].keys() != b[k].keys():
            return False
        for j in a[k]:
            if abs(a[k][j] - b[k][j]) > tol:
                return False
    return True


def _maxflow(edges, supply, demand):
    """Dinic-free Edmonds-Karp on a tiny bipartite network: S -> outputs -> inputs -> T."""
    outs = sorted({(e["source"], e["sourceIndex"]) for e in edges})
    ins = sorted({(e["target"], e["targetIndex"]) for e in edges})
    idx = {("S",): 0, ("T",): 1}
    for o in outs:
        idx[("o",) + o] = len(idx)
    for i in ins:
        idx[("i",) + i] = len(idx)
    n = len(idx)
    cap = defaultdict(float)
    adj = defaultdict(set)

    def add(u, v, c):
        cap[(u, v)] += c
        adj[u].add(v)
        adj[v].add(u)

    for o in outs:
        add(0, idx[("o",) + o], supply.get(o, 0.0))
    for i in ins:
        add(idx[("i",) + i], 1, demand.get(i, 0.0))
    big = sum(supply.get(o, 0.0) for o in outs) + 1.0
    for e in edges:
        add(idx[("o", e["source"], e["sourceIndex"])], idx[("i", e["target"], e["targetIndex"])], big)
    flow = defaultdict(float)
    for _ in range(4 * n * n + 10):
        prev = {0: None}
        q = deque([0])
        while q and 1 not in prev:
            u = q.popleft()
            for v in adj[u]:
                if v not in prev and cap[(u, v)] - flow[(u, v)] > EPS:
                    prev[v] = u
                    q.append(v)
        if 1 not in prev:
            break
        b, v = math.inf, 1
        while prev[v] is not None:
            u = prev[v]
            b = min(b, cap[(u, v)] - flow[(u, v)])
            v = u
        v = 1
        while prev[v] is not None:
            u = prev[v]
            flow[(u, v)] += b
            flow[(v, u)] -= b
            v = u
    res = {}
    for e in edges:
        u, v = idx[("o", e["source"], e["sourceIndex"])], idx[("i", e["target"], e["targetIndex"])]
        res[e["id"]] = max(0.0, flow[(u, v)])
    return res


def solve_save(save_path, machines_path, recipes_path, products_path=None):
    machines, recipes, products = load_data(machines_path, recipes_path, products_path)
    with open(save_path, encoding="utf-8") as f:
        save = json.load(f)
    return Planner(save, machines, recipes, products).solve(), (machines, recipes, products)
