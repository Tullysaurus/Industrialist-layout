"""Place -> route -> grow congested corridors -> route ... then tighten and compact.

The block arrangement found by the initial annealing is kept fixed afterwards; only the
corridor widths around/inside blocks change, so every step is a small local edit."""
from __future__ import annotations

import time
from collections import defaultdict

from .blocks import Block
from .placer import Placer
from .router import Router
from .solution import Solution

MARGIN = 4   # free border around the placement so pipes can run around the outside
SIDES = ("left", "top", "right", "bottom")


def build_blocks(problem, use_modules=True, seed=0, log=None):
    """Modules of tightly connected machines + one grid block per recipe for the rest."""
    from .clusters import Macro, MacroLayout, instance_clusters, signature
    blocks, inst_block = [], {}
    clustered = set()
    if use_modules:
        layouts = {}
        for members in instance_clusters(problem):
            if len(members) < 2:
                continue
            sig = signature(problem, members)
            if sig not in layouts:
                layouts[sig] = MacroLayout(problem, members, seconds=1.5, seed=seed)
            m = Macro(len(blocks), problem, members, layouts[sig])
            for li, g in enumerate(members):
                inst_block[g] = (m.idx, li)
                clustered.add(g)
            blocks.append(m)
        if log and blocks:
            kinds = defaultdict(int)
            for b in blocks:
                kinds[b.label] += 1
            for lbl, c in kinds.items():
                log(f"  module x{c}: {lbl}")
    for ni, node in enumerate(problem.nodes):
        ids = [g for g, (n, _) in enumerate(problem.instances) if n == ni and g not in clustered]
        if not ids:
            continue
        groups = [[g] for g in ids] if problem.spacing.get(node.shape.id) else [ids]
        for grp in groups:
            b = Block(len(blocks), ni, node, grp, problem.nets)
            for li, g in enumerate(grp):
                inst_block[g] = (b.idx, li)
            blocks.append(b)
    return blocks, inst_block


def spaced_list(problem):
    return [(problem.nodes[n].shape.id, g, problem.spacing_of(g))
            for g, (n, _) in enumerate(problem.instances) if problem.spacing_of(g)]


def realize(problem, blocks, inst_block, info, router_kw=None):
    """Build the tile grid for a placement and set up the router."""
    xs, ys, W, H, geos = info[:5]
    gw, gh = W + 2 * MARGIN, H + 2 * MARGIN
    blocked = bytearray(gw * gh)
    machines = []
    inst_pos = {}
    for b, blk in enumerate(blocks):
        g = geos[b]
        for li, (dx, dy, shape, rot) in enumerate(g.items):
            ox, oy = MARGIN + xs[b] + dx, MARGIN + ys[b] + dy
            inst = blk.inst_ids[li]
            inst_pos[inst] = (ox, oy, shape)
            machines.append({"inst": inst, "node": problem.instances[inst][0], "x": ox, "y": oy, "shape": shape,
                             "rot": rot, "block": b, "local": problem.instances[inst][1]})
            for (cx, cy) in shape.occupied():
                blocked[(oy + cy) * gw + ox + cx] = 1
    rnets = []
    for net in problem.nets:
        terms = []
        for t in net.terminals:
            ox, oy, shape = inst_pos[t.inst]
            cells = set()
            for pid in t.ports:
                p = shape.ports[pid]
                if net.large:
                    ax, ay = p.large_anchor()
                    ax, ay = ax + ox, ay + oy
                    if 0 <= ax < gw - 1 and 0 <= ay < gh - 1:
                        cells.add(ay * gw + ax)
                else:
                    for (x, y) in p.access_cells():
                        x, y = x + ox, y + oy
                        if 0 <= x < gw and 0 <= y < gh and not blocked[y * gw + x]:
                            cells.add(y * gw + x)
            terms.append(cells)
        rnets.append({"large": net.large, "stub": net.stub, "terms": terms})
    router = Router(gw, gh, blocked, rnets, **(router_kw or {}))
    # drop large anchors whose 2x2 footprint is blocked
    for rn in rnets:
        if rn["large"]:
            rn["terms"] = [{a for a in t if not router.blocked_l[a]} for t in rn["terms"]]
    return gw, gh, machines, router


def classify(cells, gw, info, blocks):
    """For each problem tile: nearest block and which part of it (a side corridor or inside)."""
    xs, ys, W, H, geos = info[:5]
    hits = defaultdict(lambda: defaultdict(int))
    inner_pts = defaultdict(list)
    for c in cells:
        x, y = c % gw - MARGIN, c // gw - MARGIN
        best, bd = None, None
        for b in range(len(blocks)):
            g = geos[b]
            bx0, by0, bx1, by1 = xs[b], ys[b], xs[b] + g.w, ys[b] + g.h
            d = max(bx0 - x, 0, x - bx1 + 1) + max(by0 - y, 0, y - by1 + 1)
            if bd is None or d < bd:
                best, bd = b, d
        g = geos[best]
        rx, ry = x - xs[best], y - ys[best]
        cx0, cy0, cx1, cy1 = g.core
        if cx0 <= rx < cx1 and cy0 <= ry < cy1:
            part = "inner"
            inner_pts[best].append((rx, ry))
        else:
            dl, dr, dt, db = cx0 - rx, rx - (cx1 - 1), cy0 - ry, ry - (cy1 - 1)
            part = max((dl, "left"), (dt, "top"), (dr, "right"), (db, "bottom"))[1]
        hits[best][part] += 1
    return hits, inner_pts


def route_layout(problem, blocks, inst_block, info, router_kw, time_limit, log):
    gw, gh, machines, router = realize(problem, blocks, inst_block, info, router_kw)
    ok = router.run(time_limit=time_limit, max_iters=60, log=log)
    over = router.overused_cells()
    sol = Solution.from_router(problem, machines, router)
    sol.ok, sol.n_over = ok, len(over)
    mixed = bool((router_kw or {}).get("mixed_crossing"))
    if ok:
        errs = sol.validate(mixed)
        if errs:
            log(f"  validation failed: {errs[:3]}")
            sol.ok = False
    bad = list(over)
    for ni in router.failed:
        for t in router.nets[ni]["terms"]:
            bad.extend(list(t)[:1])
    return sol, router, bad, gw


def snapshot(blocks):
    return [b.get_state() for b in blocks]


def restore(blocks, snap):
    for b, st in zip(blocks, snap):
        b.set_state(st)
    for b in blocks:
        b.clear_cache()


def optimize(problem, time_budget=180.0, seed=0, wire_weight=1.0, router_kw=None, use_modules=True,
             slack=1, log=print):
    t_start = time.time()
    Block.initial_slack = slack
    mixed = bool((router_kw or {}).get("mixed_crossing"))
    Solution.jump = int((router_kw or {}).get("jump", 3) or 1)
    blocks, inst_block = build_blocks(problem, use_modules, seed, log)
    placer = Placer(blocks, problem.nets, inst_block, wire_weight=wire_weight, seed=seed,
                    spaced=spaced_list(problem), measure=problem.spacing_measure)

    def left():
        return time_budget - (time.time() - t_start)

    log(f"Placement ({len(blocks)} blocks, {len(problem.instances)} machines, {len(problem.nets)} nets)...")
    state, _, info = placer.anneal(None, max(5.0, min(60.0, time_budget * 0.2)), log=log)
    if info[6] > 0:
        log("  WARNING: placement could not satisfy the spacing rule; try a longer --time")

    best = None
    best_ext = None
    frozen = set()
    tried = []
    attempt = 0
    phase = "grow"
    while left() > 10:
        attempt += 1
        log(f"Attempt {attempt} ({phase}): time left {left():.0f}s")
        sol, router, bad, gw = route_layout(problem, blocks, inst_block, info, router_kw,
                                            max(5.0, min(left() - 5.0, 150.0)), log)
        if sol.ok:
            raw = sol.area
            sol = sol.compact(mixed, log=log, deadline=t_start + time_budget * 1.1 + 10)
            sol.ok, sol.n_over = True, 0
            log(f"  ROUTED. footprint {raw} -> {sol.area} tiles after compaction")
            if best is None or not best.ok or sol.area < best.area:
                best = sol
                best_ext = snapshot(blocks)
            else:
                frozen.update(tried)
                restore(blocks, best_ext)
            phase = "tighten"
            used = set()
            for cells in router.cells:
                used |= cells
            usage, _ = classify(used, gw, info, blocks)
            cand = []
            for b, blk in enumerate(blocks):
                g = info[4][b]
                for k, side in enumerate(SIDES):
                    if (b, side) in frozen or g.pad[k] <= 0:
                        continue
                    length = g.h if side in ("left", "right") else g.w
                    cand.append((usage[b][side] / max(1, length * g.pad[k]), b, side))
            cand.sort()
            tried = [(b, side) for _, b, side in cand[:max(2, len(blocks) // 4)]]
            if not tried:
                log("  nothing left to tighten")
                break
            for b, side in tried:
                blocks[b].ext_side[side] -= 1
                blocks[b].clear_cache()
        else:
            log(f"  {sol.n_over} overfull tiles, {len(router.failed)} unrouted nets")
            if best is None or (not best.ok and sol.n_over + 50 * len(sol.failed) <
                                best.n_over + 50 * len(best.failed)):
                best = sol
            if phase == "tighten":
                frozen.update(tried)
                restore(blocks, best_ext)
                tried = []
                log("  tightening step failed, reverted")
            else:
                hits, inner_pts = classify(bad, gw, info, blocks)
                grown = []
                for b, parts in hits.items():
                    blk = blocks[b]
                    for part, n in parts.items():
                        step = 1 if n < 6 else 2
                        if part == "inner":
                            step = 1
                            if hasattr(blk, "widen_inner"):
                                blk.widen_inner(inner_pts[b], info[4][b])
                            else:
                                blk.ext_int += 1
                        else:
                            blk.ext_side[part] += step
                        grown.append(f"{getattr(blk, 'label', blk.node.recipe_id)[:30]}:{part}+{step}")
                    blk.clear_cache()
                log(f"  widening: {', '.join(grown)}")
        info = placer.evaluate(state)[1]
        if info[6] > 0:
            log(f"  (spacing short by {info[6]:.0f} tiles after repack - re-annealing briefly)")
            state, _, info = placer.anneal(state, 5.0, t_scale=0.02, t_end_frac=1e-3)
    if best is None:
        raise RuntimeError("no layout produced")
    log(f"Done in {time.time() - t_start:.0f}s")
    return best, blocks
