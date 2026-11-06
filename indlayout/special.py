"""Python port of the planner's "special recipes" (recipes whose rates are computed from settings).

Ported from Industrialist-Production-Calculator/src/data/special_recipes/*.ts. Each entry returns a
recipe dict shaped like recipes.json:

    {"id", "name", "machine_id", "cycle_time", "power_use", "power_type", "pollution",
     "inputs": [{"product_id", "quantity", "port_ids"}],
     "outputs": [{"product_id", "quantity", "port_ids", "temperature", "voidable"}]}

Only the recipes used by real saves so far are ported. Anything else falls back to the old port
inference in model.py (and is flagged in the report), so add a port here when a save needs one.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Callable

_DATA = os.path.join(os.path.dirname(__file__), "data")
AMBIENT = 18.0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _num(settings, key, default):
    v = settings.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else float(default)


def _io(pid, qty, ports, temp=None, voidable=False):
    d = {"product_id": pid, "quantity": qty, "port_ids": list(ports)}
    if temp is not None:
        d["temperature"] = temp
    if voidable:
        d["voidable"] = True
    return d


def _recipe(rid, name, mid, power, ptype, inputs, outputs, pollution=0.0, **extra):
    r = {"id": rid, "name": name, "machine_id": mid, "cycle_time": 1, "power_use": power,
         "power_type": ptype, "pollution": pollution, "inputs": inputs, "outputs": outputs}
    r.update(extra)
    return r


@dataclass
class Helpers:
    """What a special recipe may ask about its node (mirrors the TS helpers object)."""
    has_connection: Callable[[str, int], bool] = lambda side, idx: False


@dataclass
class Special:
    id: str
    machine_id: str
    defaults: dict
    compute: Callable                      # (settings, global_settings, helpers) -> recipe dict
    input_temp_settings: dict = field(default_factory=dict)   # input index -> setting key
    machine_cost: Callable | None = None   # (settings, global_settings, machines) -> cost
    model_count: Callable | None = None
    machine_space: Callable | None = None
    pollution_independent: bool = False

    def settings(self, node_settings):
        s = dict(self.defaults)
        s.update(node_settings or {})
        return s


REGISTRY: dict[str, Special] = {}


def register(sp: Special):
    REGISTRY[sp.id] = sp
    return sp


def get_special(recipe_id: str) -> Special | None:
    return REGISTRY.get(recipe_id)


# --------------------------------------------------------------------------- simple ones

register(Special(
    "r_polisher_01", "m_polisher", {"condensate_temp": 18},
    lambda s, g, h: _recipe(
        "r_polisher_01", "Condensate Purification", "m_polisher", 500000, "MV",
        [_io("p_condensate", 400, ["m_polisher_port_3"]),
         _io("p_hydrochloric_acid", 1, ["m_polisher_port_1"]),
         _io("p_sodium_hydroxide_solution", 1, ["m_polisher_port_2"])],
        [_io("p_distilled_water", 400, ["m_polisher_port_4"], _num(s, "condensate_temp", 18) * 0.9)]),
    {0: "condensate_temp"}))

register(Special(
    "r_cooling_tower_01", "m_cooling_tower", {"distilled_water_temp": 320},
    lambda s, g, h: _recipe(
        "r_cooling_tower_01", "Distilled Water Cooling", "m_cooling_tower", 0, "MV",
        [_io("p_distilled_water", 800, ["m_cooling_tower_port_2"])],
        [_io("p_distilled_water", 800, ["m_cooling_tower_port_1"],
             max(_num(s, "distilled_water_temp", 100) / 3, 21))]),
    {0: "distilled_water_temp"}))


def _asu(s, g, h):
    residue = clamp(float((g or {}).get("global_pollution", 10)) / 10, 1, 20)
    return _recipe("r_air_separation_unit_01", "Air Separation", "m_air_separation_unit", 20000000, "HV", [],
                   [_io("p_liquid_nitrogen", 60, ["m_air_separation_unit_port_2"], -205, True),
                    _io("p_liquid_oxygen", 15, ["m_air_separation_unit_port_3"], -190, True),
                    _io("p_liquid_argon", 3, ["m_air_separation_unit_port_4"], -195, True),
                    _io("p_residue", residue, ["m_air_separation_unit_port_1"], 18)])


register(Special("r_air_separation_unit_01", "m_air_separation_unit", {}, _asu))


# --------------------------------------------------------------------------- chemical plant

def chem_multipliers(speed, eff):
    speed = clamp(speed, 50, 200)
    eff = clamp(eff, 80, 120)
    ss = (speed - 100) / 5
    io_speed, pw_speed = 1.0, 1.0
    if speed < 100:
        io_speed, pw_speed = 1 + ss * 0.05, 1 + ss * (1 / 15)
    elif speed > 100:
        io_speed, pw_speed = 1 + ss * 0.05, 1 + ss * 0.1
    es = (eff - 100) / 5
    in_eff, pw_eff = 1.0, 1.0
    if eff < 100:
        in_eff, pw_eff = 1 + es * -0.0625, 1 + es * 0.05
    elif eff > 100:
        in_eff, pw_eff = 1 + es * (-1 / 24), 1 + es * 0.25
    return io_speed * in_eff, io_speed, pw_speed + pw_eff - 1


def _chem(base):
    def compute(s, g, h):
        im, om, pm = chem_multipliers(_num(s, "speed_factor", 100), _num(s, "efficiency_factor", 100))
        r = json.loads(json.dumps(base))
        r["power_use"] = base["power_use"] * pm
        for i in r["inputs"]:
            i["quantity"] *= im
        for o in r["outputs"]:
            o["quantity"] *= om
        return r
    return compute


with open(os.path.join(_DATA, "chemical_plant.json"), encoding="utf-8") as _f:
    for _base in json.load(_f):
        register(Special(_base["id"], "m_chemical_plant", {"speed_factor": 100, "efficiency_factor": 100},
                         _chem(_base)))


# --------------------------------------------------------------------------- vertical heat exchanger

_K = 2 / 15
_KC = 2.2 * _K


def vhe_steady_state(tc, tw):
    hx = (2.2 * (1 - _K) * tc + tw) / (3.2 - 2.2 * _K)
    hxp = hx + (tc - hx) * _KC
    cout = tc - (tc - hx) * 2.2 - hxp * 0.25
    return max(18, hx), max(18, cout), max(18, hxp), max(18, hx) >= 100


def _vhe(rid, name, coolant):
    def compute(s, g, h):
        tw = _num(s, "water_temp", 18)
        tc = _num(s, "coolant_temp", 330)
        loss = _num(s, "heat_loss", 1)
        hx, cout, steam, boiling = vhe_steady_state(tc, tw)
        connected = any(h.has_connection(side, i) for side in ("input", "output") for i in (0, 1))
        steam_qty = 12000 if boiling else (0 if connected else 12000)
        return _recipe(rid, name, "m_vertical_heat_exchanger", 0, "MV",
                       [_io("p_distilled_water", 400, ["m_vertical_heat_exchanger_port_4"]),
                        _io(coolant, 400, ["m_vertical_heat_exchanger_port_3"])],
                       [_io(coolant, 400, ["m_vertical_heat_exchanger_port_1"], max(18, round(cout - loss, 2))),
                        _io("p_high_pressure_steam", steam_qty, ["m_vertical_heat_exchanger_port_2"],
                            max(18, round(steam - loss, 2)))],
                       runtime={"hxTemp": round(hx, 1)})
    return Special(rid, "m_vertical_heat_exchanger", {"water_temp": 18, "coolant_temp": 330, "heat_loss": 1},
                   compute, {0: "water_temp", 1: "coolant_temp"})


register(_vhe("r_vertical_heat_exchanger_01", "Steam Generation (Distilled Coolant)", "p_distilled_water"))
register(_vhe("r_vertical_heat_exchanger_02", "Steam Generation (Contaminated Coolant)", "p_contaminated_water"))


# --------------------------------------------------------------------------- steam condenser

def condenser_steady_state(coolant_temp, steam_temp, steam_flow):
    f = 800.0
    q = clamp(steam_flow, 0, 24000) if math.isfinite(steam_flow) else 0.0
    a, b = f / 3000, q / 360000
    D = a + b - a * b
    threshold = max(40, min(100, steam_temp / 2))
    res = {"coolant_flow": f, "steam_flow": 0.0, "condensate": 0.0, "t_coolant_out": coolant_temp,
           "t_condensate": steam_temp, "condensing": False}
    if D > 0:
        hyp = (a * (1 - b) * coolant_temp + b * steam_temp) / D
        if hyp < threshold:
            res.update(steam_flow=q, condensate=q / 30, t_coolant_out=hyp, t_condensate=hyp, condensing=True)
    return res


def _condenser(s, g, h):
    r = condenser_steady_state(_num(s, "coolant_temp", 21), _num(s, "steam_temp", 198), _num(s, "steam_flow", 24000))
    return _recipe("r_steam_condenser_01", "Steam Condensation", "m_steam_condenser", 500000, "MV",
                   [_io("p_distilled_water", r["coolant_flow"], ["m_steam_condenser_port_2", "m_steam_condenser_port_1"]),
                    _io("p_low_pressure_steam", r["steam_flow"], ["m_steam_condenser_port_4", "m_steam_condenser_port_3"])],
                   [_io("p_distilled_water", r["coolant_flow"], ["m_steam_condenser_port_7", "m_steam_condenser_port_6"],
                        r["t_coolant_out"]),
                    _io("p_condensate", r["condensate"], ["m_steam_condenser_port_5"], r["t_condensate"])])


register(Special("r_steam_condenser_01", "m_steam_condenser",
                 {"coolant_temp": 21, "steam_temp": 198, "steam_flow": 24000}, _condenser,
                 {0: "coolant_temp", 1: "steam_temp"}))


# --------------------------------------------------------------------------- modular turbine

def turbine_steady_state(inp, temp, hpt, lpt, bypass, clutch, grid_max=500000000.0, grid_buffer=0.0, rpm=3600.0):
    steam = min(inp, 24000)
    flow = steam * (1 - bypass)
    rem_f, rem_t = flow, temp
    hpt_torque, eff_h = 0.0, 0
    for _ in range(int(hpt)):
        if rem_t < 150:
            break
        p = rem_f * 0.04 * (rem_t + 273) / 24000
        if p > 11.1:
            hpt_torque += 5 * p ** 1.8
        elif p > 10:
            hpt_torque += 5 * p ** (20 / p)
        else:
            hpt_torque += 5 * p ** 2
        rem_f *= 0.7
        rem_t *= 0.9
        eff_h += 1
    if lpt > 0 and rem_f * 0.04 * (rem_t + 273) / 48000 > 2:
        rem_f = 96000 / (0.04 * (rem_t + 273))
    lpt_torque, eff_l = 0.0, 0
    for _ in range(int(lpt)):
        if rem_t < 150:
            break
        lpt_torque += (rem_f * 0.04 * (rem_t + 273) / 48000 * 10) ** 2
        rem_f *= 0.8
        rem_t *= 0.9
        eff_l += 1
    raw = (hpt_torque + lpt_torque) * 240
    synced = min(raw * rpm / 10, grid_max - grid_buffer + 0.1) * clutch
    inertia = max(1, 2000 + 700 + 1500 * max(0, hpt) + 1000 * max(0, lpt))
    drive = raw / inertia
    drag = max(0.002 * 2.5 * (rpm / 60) ** 2, 4) * (synced / 120000000 + 1)
    aero = math.exp(-0.001 * rpm) * 0.7 * raw / inertia
    change = drive - drag - aero
    power = synced * (steam / 6000 if steam < 6000 else 1) * 1.1
    return {"steam": steam, "power": power, "can_sync": abs(change) <= 5, "rpm_change": change,
            "final_temp": temp * 0.6, "eff_hpt": eff_h, "eff_lpt": eff_l}


def _turbine(s, g, h):
    hpt, lpt = _num(s, "hpt_count", 1), _num(s, "lpt_count", 5)
    r = turbine_steady_state(_num(s, "input_flow", 6000), _num(s, "input_temp", 330), hpt, lpt,
                             _num(s, "steam_bypass", 0) / 100, _num(s, "generator_engagement", 100) / 100)
    return _recipe("r_modular_turbine_01",
                   f"{int(hpt)} HPT - {int(lpt)} LPT Turbine" if r["can_sync"] else "Unsynced",
                   "m_modular_turbine", -math.floor(r["power"]) if r["can_sync"] else 0, "HV",
                   [_io("p_high_pressure_steam", round(r["steam"], 1), ["m_turbine_input_port_1", "m_turbine_input_port_2"])],
                   [_io("p_low_pressure_steam", round(r["steam"], 1),
                        ["m_turbine_output_port_1", "m_turbine_output_port_2"], r["final_temp"])])


def _turbine_parts(s):
    return {"m_turbine_input": 1, "m_intermediate_pressure_turbine": 1,
            "m_low_pressure_turbine": max(1, int(_num(s, "lpt_count", 5))), "m_turbine_generator": 1,
            "m_turbine_output": 1, "m_high_pressure_turbine": max(0, int(_num(s, "hpt_count", 1)))}


register(Special(
    "r_modular_turbine_01", "m_modular_turbine",
    {"input_flow": 6000, "input_temp": 330, "hpt_count": 1, "lpt_count": 5, "steam_bypass": 0,
     "generator_engagement": 100},
    _turbine, {0: "input_temp"},
    machine_cost=lambda s, g, m: sum(m.get(k, {}).get("cost", 0) * n for k, n in _turbine_parts(s).items()),
    model_count=lambda s, g, m: (_num(s, "hpt_count", 1) + _num(s, "lpt_count", 5) + 1
                                 + (6 if _num(s, "input_flow", 6000) > 12000 else 4) + 2),
    machine_space=lambda s, g, m: sum(_area(m, k) * n for k, n in _turbine_parts(s).items())))


def _area(machines, mid):
    m = machines.get(mid)
    return m["size"]["x"] * m["size"]["y"] if m else 0


# --------------------------------------------------------------------------- mineshaft drill

_HEADS = {
    "copper": (lambda d: d / 150, "p_copper_drill_head"),
    "iron": (lambda d: 0.04 * d ** 0.25, "p_iron_drill_head"),
    "steel": (lambda d: 0.02 * d ** 0.25, "p_steel_drill_head"),
    "tungsten": (lambda d: 0.005 * d ** 0.25, "p_tungsten_carbide_drill_head"),
}
_ACIDS = {
    "none": (lambda d: d ** 2 / 900e3, 0, None),
    "water": (lambda d: d ** 2 / 1875e3, 10, "p_water"),
    "acetic": (lambda d: d ** 0.8 / 450, 3, "p_acetic_acid"),
    "sulfuric": (lambda d: 0.09 * d ** 0.25, 1, "p_sulfuric_acid"),
    "hydrochloric": (lambda d: (0.000013 * d ** (1.5 - 0.00005 * d) + 4.3875 * 10 ** -13.3 * d ** 3)
                     if d < 6000 else 0.09 * d ** 0.25, 1.5, "p_hydrochloric_acid"),
}
with open(os.path.join(_DATA, "mineshaft_depths.json"), encoding="utf-8") as _f:
    DEPTH_YIELDS = {int(k): v for k, v in json.load(_f).items()}


def _mineshaft(s, g, h):
    depth = int(_num(s, "depth", 9000))
    head = _HEADS.get(s.get("drill_head"), _HEADS["tungsten"])
    acid = _ACIDS.get(s.get("acid_type"), _ACIDS["sulfuric"])
    oil = s.get("has_machine_oil") == "Yes"
    eff_depth = 300 if depth == 100 else depth
    oil_mult = 1.1 if oil else 1.0
    deterioration = 0.5 * head[0](eff_depth) * acid[0](eff_depth) * oil_mult
    life = math.ceil(100 / deterioration)
    travel = 2 * depth / (100 if oil else 50)
    replace = 12
    cycle = life + travel + replace
    drilling = life / cycle
    power = (0.1 * replace + 0.5 * travel + 2 * life) / cycle * 1000000
    inputs = [_io(head[1], 1 / cycle, ["m_mineshaft_drill_port_4"])]
    if acid[2]:
        inputs.append(_io(acid[2], acid[1] * drilling, ["m_mineshaft_drill_port_1"]))
    if oil:
        inputs.append(_io("p_machine_oil", 2 * (1 - 12 / cycle), ["m_mineshaft_drill_port_2"]))
    outputs = [_io(o["product_id"], o["amount"] * oil_mult * drilling, [f"m_mineshaft_drill_port_{i + 5}"], 18, True)
               for i, o in enumerate(DEPTH_YIELDS.get(depth, []))]
    return _recipe("r_mineshaft_drill_01", f"{depth}m Mineshaft Drill", "m_mineshaft_drill", power, "HV",
                   inputs, outputs)


register(Special("r_mineshaft_drill_01", "m_mineshaft_drill",
                 {"depth": 6000, "drill_head": "steel", "acid_type": "hydrochloric", "has_machine_oil": "No"},
                 _mineshaft))


# --------------------------------------------------------------------------- tree farm

def _growth_time(pollution, tree_id="m_tree"):
    if pollution > 0:
        gm = 1 + 0.005 * pollution - 0.0001 * pollution * pollution
    elif pollution < -60:
        gm = 0.005 * pollution + 1.25
    else:
        gm = 1.0
    gm = max(0.5, min(1.2, gm))
    need = math.ceil(4500 / (gm * 100))
    exp = [0.0] * (need + 1)
    for u in range(1, need + 1):
        c = 1.0
        for pg in range(7, 12):
            c += exp[max(0, u - pg)] / 5
        exp[u] = c
    t = 2 * (1000 / 30) * exp[need]
    return t / 1.2 if tree_id == "m_candy_cane_tree" else t


MACHINES: dict = {}   # filled by planner.load_data(); needed for variant / limited checks


def _option_allowed(mid, g):
    m = MACHINES.get(mid)
    if m is None:
        return not MACHINES   # no data loaded: accept as-is
    variant = m.get("variant") not in (None, "", "none")
    return (not variant and not m.get("limited")) or bool((g or {}).get("showVariantLimited"))


def _tree_ids(s, g):
    ctrl = s.get("controller_id")
    if ctrl not in ("m_tree_farm_controller", "m_igloo_farm_controller") or not _option_allowed(ctrl, g):
        ctrl = "m_tree_farm_controller"
    tree = s.get("tree_id")
    if tree not in ("m_tree", "m_classic_tree", "m_christmas_tree", "m_candy_cane_tree") or not _option_allowed(tree, g):
        tree = "m_tree"
    return ctrl, tree


def _tree_farm(s, g, h):
    trees, harv, spr = _num(s, "tree_count", 600), _num(s, "harvester_count", 20), _num(s, "sprinkler_count", 24)
    pollution = float((g or {}).get("global_pollution", 10))
    ctrl, tree = _tree_ids(s, g)
    rate = min(trees / _growth_time(pollution, tree), harv / 11)
    winter = (g or {}).get("current_month") in ("December", "January", "February")
    logs = 2 * (1.5 if ctrl == "m_igloo_farm_controller" and tree != "m_candy_cane_tree"
                and (g or {}).get("showVariantLimited") and winter else 1)
    return _recipe("r_tree_farm_01", f"{int(trees)} Tree Farm", "m_tree_farm", round(rate * 200000, 6), "MV",
                   [_io("p_water", spr * (33 / (100 / 3)), ["m_tree_farm_water_input_port_1"])],
                   [_io("p_oak_log", rate * logs, ["m_tree_farm_output_port_1"], 18, True)])


def _tree_parts(s, g):
    ctrl, tree = _tree_ids(s, g)
    spr = int(_num(s, "sprinkler_count", 24))
    return {ctrl: 1, tree: int(_num(s, "tree_count", 600)), "m_farm_harvester": int(_num(s, "harvester_count", 20)),
            "m_tree_farm_sprinkler": spr, "m_tree_farm_water_tank": math.ceil(spr / 3),
            "m_tree_farm_output": int(_num(s, "outputs_count", 8))}


def _tree_models(s, g, m):
    p = _tree_parts(s, g)
    _, tree = _tree_ids(s, g)
    rate = min(_num(s, "tree_count", 600) / _growth_time(float((g or {}).get("global_pollution", 10)), tree),
               _num(s, "harvester_count", 20) / 11)
    return (_num(s, "tree_count", 600) + _num(s, "harvester_count", 20) + 1 + _num(s, "sprinkler_count", 24)
            + p["m_tree_farm_water_tank"] * 2 + p["m_tree_farm_output"] * 2 + math.ceil(rate * 200000 / 1500000))


register(Special(
    "r_tree_farm_01", "m_tree_farm",
    {"controller_id": "m_tree_farm_controller", "tree_id": "m_tree", "tree_count": 600, "harvester_count": 20,
     "sprinkler_count": 24, "outputs_count": 8},
    _tree_farm,
    machine_cost=lambda s, g, m: sum(m.get(k, {}).get("cost", 0) * n for k, n in _tree_parts(s, g).items()),
    model_count=_tree_models,
    machine_space=lambda s, g, m: sum(_area(m, k) * n for k, n in _tree_parts(s, g).items())))


# --------------------------------------------------------------------------- coal power plant

_WATER_FLOW = 400.0
_OUT_PRESSURE = 4 * 7
_SAFE_TEMP_MAX, _SAFE_PRESSURE_MAX = 500, 12
_LIM = 1e100


def _fin(v):
    return math.isfinite(v) and abs(v) < _LIM


def _san(st):
    return (clamp(st[0], AMBIENT, 2000), clamp(st[1], 1e-9, 1e8), clamp(st[2], 1e-9, 1e8), clamp(st[3], 0, 1000))


def _crit_pressure(temp):
    return max(0.0, max(0.0, temp) ** 0.75 * 0.4 - 12.6413) + 0.1013


def _cpp_eval(raw, ctl, water_t):
    temp, air_s, exh_s, fbp = _san(raw)
    feed, air, exh = ctl[0] / 25, ctl[1] / 25, ctl[2] / 50
    comb = max(math.sqrt(max(0, temp)) / 10 + fbp, 1e-9)
    exh_out = clamp(clamp(comb * exh / 2 * 1000, -1, exh_s + air_s), 0, math.inf)
    air_in = (1 / comb) * air / 4 * 3500 * 5
    total = exh_s * 3 + air_s
    frac = exh_s * 3 / total if total > 0 else 0
    exh_rm = clamp(exh_out * frac, 0, exh_s / 3)
    air_rm = clamp(exh_out * (1 - frac), 0, air_s / 3)
    exh_a = max(0, exh_s - exh_rm)
    air_a = max(0, air_s - air_rm) + air_in
    t_a = (temp * comb * 100000 + AMBIENT * air_in) / (air_in + comb * 100000)
    next_fbp = (exh_a * 2 + air_a) * t_a * 0.0036 / 100000
    spl = max(math.sqrt(max(0, t_a)) / 10 + next_fbp, 1e-9)
    ratio = air_a * 4 / exh_a if exh_a > 0 else 40
    nominal = spl / 2 * clamp(ratio, 0.025, 40) * 1.6 * 1.6
    cap = max(0, min(nominal, air_a / 6.25))
    burn = min(feed * 40, cap)
    air_b = max(0, air_a - burn * 6.25)
    exh_b = exh_a + burn * 25 * 0.625
    t_b = t_a + 800 / max(t_a, 1e-9) * (burn / 350) * 12.5
    pf = clamp(_OUT_PRESSURE / 14, 0.5, 2)
    heat = (t_b - water_t) * 0.9 * clamp(spl / 16, 0.1, 0.5) * pf
    t_w = (t_b * 100000 * spl - _WATER_FLOW * heat * _OUT_PRESSURE) / (100000 * spl)
    out_t = water_t + heat
    nxt = _san((clamp(t_w - (0.5 + t_w * t_w / 1000000), AMBIENT, math.inf), air_b, exh_b, next_fbp))
    power = (100000 + feed * 100000 + comb * 250000 * air + exh * 10000
             + abs(_OUT_PRESSURE - _crit_pressure(water_t)) ** 1.1 * _WATER_FLOW * 500 + _WATER_FLOW * 1000)
    finite = all(_fin(v) for v in (*nxt, burn, exh_out, power, out_t, comb, spl))
    return {"next": nxt, "burn": burn, "exhaust": exh_out, "power": power, "out_temp": out_t,
            "pressure": comb, "finite": finite}


def _cpp_res(st, ctl, wt):
    n = _cpp_eval(st, ctl, wt)["next"]
    return [n[i] - st[i] for i in range(4)]


def _cpp_norm(st, ctl, wt):
    r = _cpp_res(st, ctl, wt)
    return math.sqrt(r[0] ** 2 + (r[1] / 50) ** 2 + (r[2] / 50) ** 2 + (r[3] / 0.01) ** 2)


def _solve4(m):
    for col in range(4):
        piv = max(range(col, 4), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            return None
        m[piv], m[col] = m[col], m[piv]
        d = m[col][col]
        for k in range(col, 5):
            m[col][k] /= d
        for r in range(4):
            if r != col:
                f = m[r][col]
                for k in range(col, 5):
                    m[r][k] -= f * m[col][k]
    return [m[i][4] for i in range(4)]


def _add(st, d, sc):
    return _san(tuple(st[i] + d[i] * sc for i in range(4)))


def _newton(seed, ctl, wt):
    st = _san(seed)
    try:
        norm = _cpp_norm(st, ctl, wt)
    except (OverflowError, ValueError, ZeroDivisionError):
        return None
    for _ in range(80):
        if not all(_fin(v) for v in st) or not math.isfinite(norm):
            return None
        if norm < 1e-7:
            return st
        base = _cpp_res(st, ctl, wt)
        mins = (1e-3, 1e-2, 1e-2, 1e-5)
        aug = [[0.0] * 5 for _ in range(4)]
        for v in range(4):
            hh = max(abs(st[v]) * 1e-5, mins[v])
            stp = list(st)
            stp[v] += hh
            r2 = _cpp_res(_san(tuple(stp)), ctl, wt)
            for row in range(4):
                aug[row][v] = (r2[row] - base[row]) / hh
        for row in range(4):
            aug[row][4] = -base[row]
        delta = _solve4(aug) or base
        accepted = False
        sc = 1.0
        while sc >= 1 / 1024:
            cand = _add(st, delta, sc)
            cn = _cpp_norm(cand, ctl, wt)
            if math.isfinite(cn) and cn < norm:
                st, norm, accepted = cand, cn, True
                break
            sc *= 0.5
        if not accepted:
            st = _add(st, _cpp_res(st, ctl, wt), 0.15)
            norm = _cpp_norm(st, ctl, wt)
    return st if norm < 1e-5 else None


def _relaxed(seed, ctl, wt):
    st = _san(seed)
    alpha = 0.12
    best, best_n = st, _cpp_norm(st, ctl, wt)
    since = 0
    for it in range(1600):
        ev = _cpp_eval(st, ctl, wt)
        if not ev["finite"]:
            return None
        st = _add(st, [ev["next"][i] - st[i] for i in range(4)], alpha)
        n = _cpp_norm(st, ctl, wt)
        if math.isfinite(n) and n < best_n - 1e-7:
            best, best_n, since = st, n, 0
        else:
            since += 1
        if best_n < 1e-5:
            return best
        if since >= 200:
            break
        if it % 400 == 399:
            alpha = max(0.02, alpha * 0.8)
    return _newton(best, ctl, wt) or (best if best_n < 1e-4 else None)


def _silo_temp(ret, silo):
    ret = max(0, ret)
    ex = _WATER_FLOW / max(_WATER_FLOW, silo)
    dlt = ret - AMBIENT
    if dlt <= 0 or ex >= 1:
        return ret
    p = 1 - ex
    disc = (1600 * ex) ** 2 + 4 * p * 1600 * ex * dlt
    mixed = (-1600 * ex + math.sqrt(max(0, disc))) / (2 * p)
    return clamp(AMBIENT + mixed - mixed * mixed / 1600, min(AMBIENT, ret), max(AMBIENT, ret))


_CPP_CACHE: dict = {}


def cpp_steady_state(ctl, water_t, silo):
    key = (round(ctl[0], 4), round(ctl[1], 4), round(ctl[2], 4), round(water_t, 4), round(silo, 2))
    if key in _CPP_CACHE:
        return _CPP_CACHE[key]
    silo_t = _silo_temp(water_t, silo)
    state = None
    if min(ctl) > 0:
        seeds = [(max(180, silo_t + 180), 900, 900, 1), (260, 1200, 1400, 3), (360, 1800, 2600, 6),
                 (470, 2600, 4800, 9), (120, 700, 700, 0.8)]
        best, best_n = None, math.inf
        for sd in seeds:
            s2 = _newton(sd, ctl, silo_t)
            if s2 is None:
                continue
            n = _cpp_norm(s2, ctl, silo_t)
            if n < 1e-7:
                best, best_n = s2, n
                break
            if n < best_n:
                best, best_n = s2, n
        if best is None or best_n >= 1e-4:
            for sd in seeds[:2]:
                s2 = _relaxed(sd, ctl, silo_t)
                if s2 is None:
                    continue
                n = _cpp_norm(s2, ctl, silo_t)
                if n < best_n:
                    best, best_n = s2, n
        state = best if best is not None and best_n < 1e-4 else None
    if state is None:
        st = _san((max(AMBIENT, silo_t), 1, 1, 0))
        res = {"state": st, "eval": _cpp_eval(st, ctl, silo_t), "silo_t": silo_t, "working": False}
    else:
        ev = _cpp_eval(state, ctl, silo_t)
        working = (ev["finite"] and ev["burn"] > 1e-6 and ev["exhaust"] > 1e-6 and 150 <= state[0] <= _SAFE_TEMP_MAX
                   and ev["pressure"] <= _SAFE_PRESSURE_MAX and _crit_pressure(ev["out_temp"]) <= _OUT_PRESSURE + 0.05)
        res = {"state": state, "eval": ev, "silo_t": silo_t, "working": working}
    _CPP_CACHE[key] = res
    return res


def _cpp(s, g, h):
    ctl = (clamp(_num(s, "coal_feed", 60), 0, 100), clamp(_num(s, "air", 92.5), 0, 100),
           clamp(_num(s, "exhaust", 20), 0, 100))
    silo = clamp(_num(s, "silo_water", 200000), 20000, 400000)
    r = cpp_steady_state(ctl, _num(s, "distilled_water_temp", AMBIENT), silo)
    ev, ok = r["eval"], r["working"]

    def fmt(v):
        return f"{v:g}"
    return _recipe("r_coal_power_plant_01",
                   f"{fmt(ctl[0])}% C, {fmt(ctl[1])}% A, {fmt(ctl[2])}% E" if ok else "Tripped",
                   "m_coal_power_plant", round(ev["power"], 6), "HV",
                   [_io("p_coal", round(ev["burn"] if ok else 0, 6), ["m_coal_power_plant_port_7", "m_coal_power_plant_port_6"]),
                    _io("p_distilled_water", _WATER_FLOW, ["m_coal_power_plant_port_5"])],
                   [_io("p_distilled_water", _WATER_FLOW, ["m_coal_power_plant_port_4"],
                        round(ev["out_temp"] if ok else r["silo_t"], 6)),
                    _io("p_exhaust", round(ev["exhaust"] if ok else 0, 6), ["m_coal_power_plant_port_3"], AMBIENT)],
                   runtime={"boilerTemp": round(r["state"][0], 1), "working": ok})


register(Special("r_coal_power_plant_01", "m_coal_power_plant",
                 {"coal_feed": 60, "air": 92.5, "exhaust": 20, "distilled_water_temp": AMBIENT, "silo_water": 200000},
                 _cpp, {1: "distilled_water_temp"}))
