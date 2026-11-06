"""SVG / JSON / text output for a finished layout."""
from __future__ import annotations

import colorsys
import hashlib
import json
from collections import defaultdict
from html import escape

S = 12  # px per tile

PORT_COLORS = {("input", "Item"): "#f2b705", ("output", "Item"): "#e8590c",
               ("input", "Fluid"): "#1c7ed6", ("output", "Fluid"): "#9c36b5"}


def _hue(key: str, sat=0.65, light=0.45):
    h = int(hashlib.md5(key.encode()).hexdigest()[:6], 16) / 0xFFFFFF
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _fill(key: str):
    return _hue(key, 0.35, 0.86)


def render_svg(problem, layout, path, title="Factory layout", mixed_crossing=False, analysis=None):
    x0, y0, x1, y1 = layout.bbox
    pad = 2
    vx0, vy0 = x0 - pad, y0 - pad
    W = (x1 - x0 + 2 * pad) * S
    H = (y1 - y0 + 2 * pad) * S
    header = 150
    legend_w = 420
    total_w, total_h = W + legend_w, max(H + header, 900)
    out = []
    a = out.append
    a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" '
      f'viewBox="0 0 {total_w} {total_h}" font-family="Segoe UI, Helvetica, Arial, sans-serif">')
    a('<defs>'
      f'<pattern id="g1" width="{S}" height="{S}" patternUnits="userSpaceOnUse">'
      f'<path d="M {S} 0 L 0 0 0 {S}" fill="none" stroke="#e3e6ea" stroke-width="0.6"/></pattern>'
      f'<pattern id="g10" width="{S * 10}" height="{S * 10}" patternUnits="userSpaceOnUse">'
      f'<rect width="{S * 10}" height="{S * 10}" fill="url(#g1)"/>'
      f'<path d="M {S * 10} 0 L 0 0 0 {S * 10}" fill="none" stroke="#c5cad1" stroke-width="1"/></pattern>'
      '</defs>')
    a(f'<rect width="{total_w}" height="{total_h}" fill="#ffffff"/>')

    # ---- header
    sol = layout
    overfull = set(sol.overfull(mixed_crossing))
    all_cells = set().union(*sol.cells) if sol.cells else set()
    n_pipe_tiles = len(all_cells)
    machine_tiles = sum(sum(r.w * r.h for r in m["shape"].rects) for m in layout.machines)
    shared = sum(1 for c in all_cells if sol.occ_s.get(c, 0) + sol.occ_l.get(c, 0) >= 2)
    status = "fully routed, all pipe rules satisfied" if layout.ok else \
        f"NOT fully routed - {len(overfull)} overfull tiles (red), {len(sol.failed)} unrouted nets"
    a(f'<text x="16" y="34" font-size="24" font-weight="600" fill="#1f2328">{escape(title)}</text>')
    a(f'<text x="16" y="62" font-size="15" fill="#1f2328">Footprint {x1 - x0} x {y1 - y0} = '
      f'<tspan font-weight="600">{(x1 - x0) * (y1 - y0):,} tiles</tspan> · {len(layout.machines)} machines '
      f'({machine_tiles:,} tiles, {100 * machine_tiles / max(1, (x1 - x0) * (y1 - y0)):.1f}% of area) · '
      f'{len([n for n in problem.nets if not n.stub])} pipe networks, {n_pipe_tiles:,} pipe tiles, '
      f'{shared:,} tiles with 2 pipes</text>')
    a(f'<text x="16" y="86" font-size="15" fill="{"#2b8a3e" if layout.ok else "#c92a2a"}">Status: {status}</text>')
    st = problem.plan.stats if problem.plan else {}
    if st:
        a(f'<text x="16" y="110" font-size="14" fill="#1f2328">Power use {fmt_power(st["mv_use"] + st["hv_use"])} '
          f'(HV {fmt_power(st["hv_use"])}) · output {fmt_power(st["mv_output"] + st["hv_output"])} · '
          f'net pollution {st["net_pollution"]:.2f} · machine cost ${st["machine_cost"]:,.0f} · '
          f'machine space {st["machine_space"]:,.0f} tiles · {len(problem.valves)} valve(s)</text>')
    a('<text x="16" y="132" font-size="13" fill="#57606a">1 grid square = 1 tile; thick lines every 10 tiles. '
      'Arrows show flow direction; hover machines, pipes and markers for values. Open the .json in viewer.py '
      'for the interactive view.</text>')

    a(f'<g transform="translate(0,{header})">')
    a(f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#g10)"/>')
    a(f'<rect x="{pad * S}" y="{pad * S}" width="{(x1 - x0) * S}" height="{(y1 - y0) * S}" fill="none" '
      f'stroke="#495057" stroke-width="2" stroke-dasharray="8 4"/>')

    def X(x):
        return (x - vx0) * S

    def Y(y):
        return (y - vy0) * S

    # ---- machines
    used_ports = defaultdict(set)
    for net in problem.nets:
        for t in net.terminals:
            for p in t.ports:
                used_ports[t.inst].add(p)
    a('<g id="machines">')
    for m in layout.machines:
        node = problem.nodes[m["node"]]
        shape = m["shape"]
        fill = "#ffe066" if node.shape.id.startswith("valve_") else _fill(node.recipe_id)
        tip = machine_tooltip(problem, m, analysis, (x0, y0))
        a(f'<g><title>{escape(tip)}</title>')
        for r in shape.rects:
            a(f'<rect x="{X(m["x"] + r.x):.1f}" y="{Y(m["y"] + r.y):.1f}" width="{r.w * S}" height="{r.h * S}" '
              f'fill="{fill}" stroke="#343a40" stroke-width="1.2" rx="2"/>')
        # labels
        valve = valve_of(problem, m["inst"])
        if valve:
            r = shape.rects[0]
            _label(a, X(m["x"] + r.x), Y(m["y"] + r.y), r.w * S, r.h * S, f"{valve['side_pct']:.0f}%", None)
        elif len(shape.rects) == 1:
            r = shape.rects[0]
            label = node.shape.name if not node.name.startswith(node.shape.name) else node.shape.name
            _label(a, X(m["x"] + r.x), Y(m["y"] + r.y), r.w * S, r.h * S, label, f"#{m['local'] + 1}  {node.recipe_id}")
        else:
            for r in shape.rects:
                if r.w >= 6 and r.h >= 6 and r.machine_id not in ("m_tree",):
                    _label(a, X(m["x"] + r.x), Y(m["y"] + r.y), r.w * S, r.h * S, r.label, None)
            bx, by = X(m["x"]), Y(m["y"])
            a(f'<text x="{bx + 4:.1f}" y="{by + 14:.1f}" font-size="12" font-weight="600" fill="#1f2328">'
              f'{escape(shape.name)} #{m["local"] + 1}</text>')
        # ports
        for pid, p in shape.ports.items():
            col = PORT_COLORS.get((p.direction, p.kind), "#868e96")
            used = pid in used_ports[m["inst"]]
            for (cx, cy) in p.cells:
                a(f'<rect x="{X(m["x"] + cx) + 1.5:.1f}" y="{Y(m["y"] + cy) + 1.5:.1f}" width="{S - 3}" '
                  f'height="{S - 3}" fill="{col}" fill-opacity="{1 if used else 0.3}" '
                  f'stroke="{"#000" if used else "none"}" stroke-width="0.8"><title>{escape(pid)} '
                  f'({p.direction} {p.kind}{", large" if p.width > 1 else ""}{", connected" if used else ", unused"})'
                  f'</title></rect>')
        a('</g>')
    a('</g>')

    # ---- pipes
    a('<g id="pipes" stroke-linecap="round" stroke-linejoin="round" fill="none">')
    order = sorted(range(len(problem.nets)), key=lambda i: not problem.nets[i].large)
    for ni in order:
        net = problem.nets[ni]
        col = _hue(net.product or net.label)
        tip = pipe_tooltip(problem, ni, sol, analysis)
        off = 1.0 if net.large else 0.5
        width = 1.7 * S if net.large else 0.42 * S
        unit = [e for e in sol.net_edges[ni] if abs(e[0][0] - e[1][0]) + abs(e[0][1] - e[1][1]) == 1]
        hops = [e for e in sol.net_edges[ni] if abs(e[0][0] - e[1][0]) + abs(e[0][1] - e[1][1]) > 1]
        segs = _merge_segments(unit)
        d = " ".join(f"M{X(ax + off):.1f} {Y(ay + off):.1f}L{X(bx + off):.1f} {Y(by + off):.1f}"
                     for (ax, ay), (bx, by) in segs)
        a(f'<g><title>{escape(tip)}</title>')
        if d:
            if net.large:
                a(f'<path d="{d}" stroke="#212529" stroke-width="{width + 2.5:.1f}"/>')
            a(f'<path d="{d}" stroke="{col}" stroke-width="{width:.1f}" stroke-opacity="0.92"/>')
        for (ax, ay), (bx, by) in hops:
            # quantum-piping hop: the two bores connect without a pipe in between
            a(f'<path d="M{X(ax + off):.1f} {Y(ay + off):.1f}L{X(bx + off):.1f} {Y(by + off):.1f}" '
              f'stroke="{col}" stroke-width="{max(2.0, width * 0.35):.1f}" stroke-dasharray="3 3">'
              f'<title>quantum-piping hop over other pipes</title></path>')
            for (qx, qy) in ((ax, ay), (bx, by)):
                a(f'<circle cx="{X(qx + off):.1f}" cy="{Y(qy + off):.1f}" r="{S * (0.5 if net.large else 0.32):.1f}" '
                  f'fill="#fff" stroke="{col}" stroke-width="2"/>')
        if analysis is not None:
            nf = analysis.nets[ni]
            for (sa, sb) in segs:
                _arrows(a, nf, sa, sb, X, Y, off, net.large)
            for ti in nf.terms:
                _terminal_marker(a, problem, ti, X, Y, off, net, col)
            for n, j in nf.junctions.items():
                if j.kind in ("split", "merge", "mix") and not _at_terminal(nf, n):
                    _junction_marker(a, n, j, X, Y, off, net, col)
        for (cx, cy) in sol.net_nodes[ni]:
            if net.stub or not sol.net_edges[ni]:
                sz = 2 if net.large else 1
                a(f'<rect x="{X(cx) + 2:.1f}" y="{Y(cy) + 2:.1f}" width="{sz * S - 4}" height="{sz * S - 4}" '
                  f'fill="{col}" stroke="#212529" stroke-width="1"/>')
        a('</g>')
    a('</g>')

    # ---- valves that still have to be placed by hand
    if analysis is not None:
        a('<g id="valve-todo">')
        for v in analysis.unplaced:
            vx, vy = v["node"]
            pct = ", ".join(f"{lbl} {p_:.0f}%" for lbl, p_ in v["split"])
            a(f'<circle cx="{X(vx + 0.5):.1f}" cy="{Y(vy + 0.5):.1f}" r="{S * 1.1:.1f}" fill="none" stroke="#e03131" '
              f'stroke-width="2.5"><title>{escape("Valve needed here (not placed): " + v["why"] + chr(10) + pct)}'
              f'</title></circle>')
        a('</g>')

    # ---- shared / overfull tile markers
    a('<g id="markers">')
    for c in all_cells:
        cx, cy = c
        if c in overfull:
            a(f'<rect x="{X(cx)}" y="{Y(cy)}" width="{S}" height="{S}" fill="#fa5252" fill-opacity="0.55" '
              f'stroke="#c92a2a"><title>overfull tile: {sol.occ_s.get(c, 0)} normal + {sol.occ_l.get(c, 0)} '
              f'large pipes</title></rect>')
        elif sol.occ_s.get(c, 0) + sol.occ_l.get(c, 0) >= 2:
            a(f'<rect x="{X(cx) + 2.5}" y="{Y(cy) + 2.5}" width="{S - 5}" height="{S - 5}" fill="none" '
              f'stroke="#212529" stroke-width="0.9" transform="rotate(45 {X(cx) + S / 2} {Y(cy) + S / 2})">'
              f'<title>2 pipes in this tile (intersection / dual pipe)</title></rect>')
    a('</g>')
    a('</g>')

    # ---- legend
    lx = W + 20
    ly = header
    a(f'<g transform="translate({lx},{ly})" font-size="13" fill="#1f2328">')
    a('<text y="0" font-size="16" font-weight="600">Legend</text>')
    yy = 24
    for (d, k), col in PORT_COLORS.items():
        a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="{col}" stroke="#000" stroke-width="0.8"/>'
          f'<text x="20" y="{yy}">{k} {d} port</text>')
        yy += 20
    a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="#adb5bd" fill-opacity="0.3"/>'
      f'<text x="20" y="{yy}">unused port (faded)</text>')
    yy += 22
    a(f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#495057" stroke-width="{0.42 * S}" '
      f'stroke-linecap="round"/><text x="50" y="{yy}">normal pipe / conveyor (1 tile)</text>')
    yy += 24
    a(f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#212529" stroke-width="{1.7 * S + 2.5}"/>'
      f'<line x1="0" y1="{yy - 4}" x2="40" y2="{yy - 4}" stroke="#868e96" stroke-width="{1.7 * S}"/>'
      f'<text x="50" y="{yy}">large fluid pipe (2x2 tiles)</text>')
    yy += 26
    a(f'<rect x="3" y="{yy - 10}" width="8" height="8" fill="none" stroke="#212529" '
      f'transform="rotate(45 7 {yy - 6})"/><text x="20" y="{yy}">tile holding 2 pipes</text>')
    yy += 20
    a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="#fa5252" fill-opacity="0.55"/>'
      f'<text x="20" y="{yy}">overfull tile (rule broken)</text>')
    yy += 22
    a(f'<polygon points="0,{yy - 10} 12,{yy - 5} 0,{yy}" fill="#212529"/><text x="20" y="{yy}">flow direction</text>')
    yy += 20
    a(f'<circle cx="6" cy="{yy - 5}" r="5" fill="#fff" stroke="#212529" stroke-width="2"/>'
      f'<text x="20" y="{yy}">split (pipe divides evenly)</text>')
    yy += 20
    a(f'<rect x="1" y="{yy - 10}" width="10" height="10" fill="#212529"/><text x="20" y="{yy}">merge (pipes join)</text>')
    yy += 20
    a(f'<polygon points="0,{yy - 10} 10,{yy - 5} 0,{yy}" fill="#2b8a3e" stroke="#fff"/>'
      f'<text x="20" y="{yy}">pipe feeds a machine input</text>')
    yy += 20
    a(f'<polygon points="10,{yy - 10} 0,{yy - 5} 10,{yy}" fill="#e8590c" stroke="#fff"/>'
      f'<text x="20" y="{yy}">machine output feeds the pipe</text>')
    yy += 20
    a(f'<rect x="0" y="{yy - 8}" width="24" height="8" fill="#ffe066" stroke="#343a40"/>'
      f'<text x="32" y="{yy}">valve control (label = side outlet %)</text>')
    yy += 20
    a(f'<circle cx="6" cy="{yy - 5}" r="6" fill="none" stroke="#e03131" stroke-width="2.5"/>'
      f'<text x="20" y="{yy}">valve still needed (place by hand)</text>')
    yy += 30
    a('<text font-size="15" font-weight="600" y="%d">Products</text>' % yy)
    yy += 20
    seen = {}
    for net in problem.nets:
        key = net.product or net.label
        if key in seen:
            continue
        seen[key] = 1
        name = net.label.split(" [")[0].replace(" (self-feed stub)", "")
        recips = sorted({problem.nodes[problem.instances[t.inst][0]].recipe_id for t in net.terminals})
        a(f'<rect x="0" y="{yy - 10}" width="24" height="10" fill="{_hue(key)}"/>'
          f'<text x="32" y="{yy}">{escape(name)}{" (large)" if net.large else ""}'
          f'<title>{escape(", ".join(recips))}</title></text>')
        yy += 17
    yy += 16
    a('<text font-size="15" font-weight="600" y="%d">Machines</text>' % yy)
    yy += 20
    for node in problem.nodes:
        a(f'<rect x="0" y="{yy - 10}" width="12" height="12" fill="{_fill(node.recipe_id)}" stroke="#343a40"/>'
          f'<text x="20" y="{yy}">{node.count} x {escape(node.shape.name)} '
          f'<tspan fill="#57606a">({node.recipe_id}{", inferred" if not node.known else ""})</tspan></text>')
        yy += 17
    a('</g>')
    a('</svg>')
    if yy + header + 20 > total_h:
        out[0] = out[0].replace(f'height="{total_h}"', f'height="{yy + header + 20}"').replace(
            f'viewBox="0 0 {total_w} {total_h}"', f'viewBox="0 0 {total_w} {yy + header + 20}"')
        out[2] = out[2].replace(f'height="{total_h}"', f'height="{yy + header + 20}"')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


def fmt_power(v):
    for unit, f in (("GMF/s", 1e9), ("MMF/s", 1e6), ("kMF/s", 1e3)):
        if abs(v) >= f:
            return f"{v / f:,.2f} {unit}"
    return f"{v:,.0f} MF/s"


def fmt_rate(v):
    if v is None:
        return "?"
    if abs(v) >= 100:
        return f"{v:,.0f}/s"
    if abs(v) >= 1:
        return f"{v:.2f}/s"
    return f"{v:.4g}/s"


def valve_of(problem, inst):
    for v in problem.valves:
        if v["inst"] == inst:
            return v
    return None


def machine_tooltip(problem, m, analysis, origin):
    node = problem.nodes[m["node"]]
    shape = m["shape"]
    lines = [node.name, f"machine {m['local'] + 1} of {node.count} (planner count {node.machine_count:.3f})",
             f"size {shape.w}x{shape.h}, rotation {m['rot'] * 90}°, position ({m['x'] - origin[0]}, "
             f"{m['y'] - origin[1]})"]
    v = valve_of(problem, m["inst"])
    if v:
        lines.append(f"valve {v['index']}/{v['of']} on {v['product']}: side outlet {v['side_pct']:.1f}%, straight "
                     f"{v['straight_pct']:.1f}% of {fmt_rate(v['flow'])}")
    r = node.recipe
    if r:
        u = node.util
        for key, title in (("inputs", "in"), ("outputs", "out")):
            for i, io in enumerate(r[key]):
                rate = io["quantity"] / (r.get("cycle_time") or 1)
                pname = problem.products.get(io["product_id"], {}).get("name", io["product_id"])
                t = io.get("temperature")
                lines.append(f"  {title}: {pname} {fmt_rate(rate * u)} (max {fmt_rate(rate)})"
                             + (f" @ {t:.0f}°C" if isinstance(t, (int, float)) and title == "out" else ""))
    if analysis is not None:
        g = m["inst"]
        lines.append(f"runs at {100 * analysis.planned_run.get(g, 0):.0f}% planned, "
                     f"{100 * analysis.run_valve.get(g, 0):.0f}% in this layout (even-split check)")
    return "\n".join(lines)


def pipe_tooltip(problem, ni, sol, analysis):
    net = problem.nets[ni]
    kind = "Large fluid pipe (2x2)" if net.large else ("Fluid pipe" if net.kind == "Fluid" else "Conveyor")
    lines = [net.label, f"{kind}" + (f" @ {net.temperature:.0f}°C" if net.temperature is not None else ""),
             f"flow {fmt_rate(net.flow)} · capacity {net.capacity:g}/s",
             f"{len(net.terminals)} connections, {len(sol.cells[ni])} tiles"]
    if analysis is not None:
        nf = analysis.nets[ni]
        for ti in nf.terms:
            node = problem.nodes[problem.instances[ti.t.inst][0]]
            arrow = "->" if ti.t.direction == "input" else "<-"
            lines.append(f"  {arrow} {node.shape.name} #{problem.instances[ti.t.inst][1] + 1}: {fmt_rate(ti.t.rate)}")
        if nf.balanced_note:
            lines.append(nf.balanced_note)
    return "\n".join(lines[:40])


def _at_terminal(nf, n):
    return any(ti.node == n for ti in nf.terms)


def _arrows(a, nf, sa, sb, X, Y, off, large):
    """Arrowheads along a straight run, every ~8 tiles, pointing with the planned flow."""
    dx = (sb[0] > sa[0]) - (sb[0] < sa[0])
    dy = (sb[1] > sa[1]) - (sb[1] < sa[1])
    n1 = (sa[0] + dx, sa[1] + dy)
    if nf.edge_flow.get((sa, n1), 0) > 0:
        pass
    elif nf.edge_flow.get((n1, sa), 0) > 0:
        dx, dy = -dx, -dy
    else:
        return
    length = abs(sb[0] - sa[0]) + abs(sb[1] - sa[1])
    steps = max(1, length // 8)
    size = (0.9 if large else 0.42) * S
    for k in range(steps):
        t = (k + 0.5) * length / steps
        cx = X(sa[0] + off + (sb[0] - sa[0]) * t / max(length, 1))
        cy = Y(sa[1] + off + (sb[1] - sa[1]) * t / max(length, 1))
        px, py = -dy, dx
        pts = [(cx + dx * size, cy + dy * size), (cx - dx * size + px * size * 0.8, cy - dy * size + py * size * 0.8),
               (cx - dx * size - px * size * 0.8, cy - dy * size - py * size * 0.8)]
        a('<polygon points="%s" fill="#212529" fill-opacity="0.85" stroke="none"/>'
          % " ".join(f"{x:.1f},{y:.1f}" for x, y in pts))


def _terminal_marker(a, problem, ti, X, Y, off, net, col):
    if ti.node is None or not ti.port_cells:
        return
    px = sum(c[0] for c in ti.port_cells) / len(ti.port_cells) + 0.5
    py = sum(c[1] for c in ti.port_cells) / len(ti.port_cells) + 0.5
    nx, ny = ti.node[0] + off, ti.node[1] + off
    # stub from the pipe into the port
    a(f'<path d="M{X(nx):.1f} {Y(ny):.1f}L{X(px):.1f} {Y(py):.1f}" stroke="{col}" '
      f'stroke-width="{(1.2 if net.large else 0.42) * S:.1f}"/>')
    dx, dy = px - nx, py - ny
    norm = max(1e-9, (dx * dx + dy * dy) ** 0.5)
    dx, dy = dx / norm, dy / norm
    if ti.t.direction == "output":
        dx, dy = -dx, -dy
    size = 0.38 * S
    cx, cy = X((nx + px) / 2), Y((ny + py) / 2)
    pts = [(cx + dx * size, cy + dy * size), (cx - dx * size - dy * size, cy - dy * size + dx * size),
           (cx - dx * size + dy * size, cy - dy * size - dx * size)]
    fill = "#2b8a3e" if ti.t.direction == "input" else "#e8590c"
    node = problem.nodes[problem.instances[ti.t.inst][0]]
    tip = (f"{'pipe -> ' if ti.t.direction == 'input' else ''}{node.shape.name} "
           f"#{problem.instances[ti.t.inst][1] + 1}{' -> pipe' if ti.t.direction == 'output' else ''}: "
           f"{fmt_rate(ti.t.rate)} {net.product_name}")
    a('<polygon points="%s" fill="%s" stroke="#fff" stroke-width="0.8"><title>%s</title></polygon>'
      % (" ".join(f"{x:.1f},{y:.1f}" for x, y in pts), fill, escape(tip)))


def _junction_marker(a, n, j, X, Y, off, net, col):
    cx, cy = X(n[0] + off), Y(n[1] + off)
    r = (0.75 if net.large else 0.36) * S
    tip = (f"{j.kind} on {net.label}\nin: " + ", ".join(f"{fmt_rate(f)}" for _, f in j.ins)
           + "\nout: " + ", ".join(f"{fmt_rate(f)}" for _, f in j.outs))
    if j.kind == "split" or j.kind == "mix":
        stroke = "#e03131" if not j.even_ok and (j.valve is None or not j.valve.get("ok")) else "#212529"
        a(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#fff" stroke="{stroke}" stroke-width="2">'
          f'<title>{escape(tip)}</title></circle>')
    else:
        a(f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" fill="#212529">'
          f'<title>{escape(tip)}</title></rect>')


def _label(a, x, y, w, h, text, sub):
    fs = max(5.0, min(h * 0.28, w / max(4, len(text)) * 1.7, 22))
    cx, cy = x + w / 2, y + h / 2
    if sub and h > fs * 2.6:
        a(f'<text x="{cx:.1f}" y="{cy - fs * 0.15:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
          f'font-weight="600" fill="#1f2328">{escape(text)}</text>')
        fs2 = max(4.0, min(fs * 0.62, w / max(4, len(sub)) * 1.7))
        a(f'<text x="{cx:.1f}" y="{cy + fs2 * 1.2:.1f}" font-size="{fs2:.1f}" text-anchor="middle" '
          f'fill="#495057">{escape(sub)}</text>')
    else:
        a(f'<text x="{cx:.1f}" y="{cy + fs * 0.35:.1f}" font-size="{fs:.1f}" text-anchor="middle" '
          f'font-weight="600" fill="#1f2328">{escape(text)}</text>')


def _merge_segments(edges):
    """Merge unit edges into straight runs to keep the SVG small."""
    adj = defaultdict(set)
    for a_, b_ in edges:
        adj[a_].add(b_)
        adj[b_].add(a_)
    done = set()
    segs = []
    for a_, b_ in edges:
        if (a_, b_) in done or (b_, a_) in done:
            continue
        dx, dy = b_[0] - a_[0], b_[1] - a_[1]
        start, end = a_, b_
        done.add((a_, b_))
        while True:  # extend forward
            n = (end[0] + dx, end[1] + dy)
            if n in adj[end] and (end, n) not in done and (n, end) not in done:
                done.add((end, n))
                end = n
            else:
                break
        while True:  # extend backward
            p = (start[0] - dx, start[1] - dy)
            if p in adj[start] and (p, start) not in done and (start, p) not in done:
                done.add((p, start))
                start = p
            else:
                break
        segs.append((start, end))
    return segs


def export_json(problem, layout, path, analysis=None, title=""):
    """Everything the desktop viewer needs, in layout coordinates (top-left of the footprint = 0, 0)."""
    x0, y0, x1, y1 = layout.bbox

    def P(c):
        return [c[0] - x0, c[1] - y0]

    prod = problem.products
    plan = problem.plan

    def pname(pid):
        return prod.get(pid, {}).get("name") or (pid or "?")

    groups = {ni: (pl, ev, vv) for ni, pl, ev, vv in (analysis.groups if analysis else [])}
    data = {
        "version": 2, "title": title,
        "footprint": {"width": x1 - x0, "height": y1 - y0, "area": (x1 - x0) * (y1 - y0)},
        "fully_routed": layout.ok,
        "stats": dict(plan.stats) if plan else {},
        "layout_stats": {
            "machines": len(layout.machines),
            "machine_tiles": sum(sum(r.w * r.h for r in m["shape"].rects) for m in layout.machines),
            "pipe_networks": len(problem.nets),
            "pipe_tiles": len(set().union(*layout.cells)) if layout.cells else 0,
            "overfull_tiles": len(layout.overfull()),
            "unrouted": len(layout.failed),
            "valves": len(problem.valves),
            "valves_needed_unplaced": len(analysis.unplaced) if analysis else 0,
        },
        "deficiencies": [{"product": pname(pid), "rate": t,
                          "nodes": [{"node": n, "name": nm, "rate": r} for n, nm, r in vs]}
                         for pid, t, vs in (plan.deficiencies if plan else [])],
        "excesses": [{"product": pname(pid), "rate": t,
                      "nodes": [{"node": n, "name": nm, "rate": r, "voidable": vd} for n, nm, r, vd in vs]}
                     for pid, t, vs in (plan.excesses if plan else [])],
        "groups": [], "machines": [], "pipes": [],
        "warnings": problem.warnings, "notes": problem.notes,
        "self_feeds": [{"node": problem.nodes[ni].id, "name": problem.nodes[ni].name,
                        "output": o, "input": i, "flow": f} for ni, o, i, f in problem.self_feeds],
    }
    for ni, node in enumerate(problem.nodes):
        pl, ev, vv = groups.get(ni, (node.machine_count, None, None))
        r = node.recipe or {}
        data["groups"].append({
            "index": ni, "id": node.id, "name": node.name, "recipe": node.recipe_id, "machine": node.shape.name,
            "count": node.count, "planned": node.machine_count, "even_split": ev, "with_valves": vv,
            "power": r.get("power_use"), "power_type": r.get("power_type"), "pollution": r.get("pollution"),
            "settings": node.settings, "special": node.special, "known": node.known,
        })
    port_use = {}
    for ni, net in enumerate(problem.nets):
        for t in net.terminals:
            for pid in t.ports:
                port_use[(t.inst, pid)] = (ni, t)
    for m in layout.machines:
        node = problem.nodes[m["node"]]
        g = m["inst"]
        r = node.recipe
        ios = {"inputs": [], "outputs": []}
        if r:
            for key in ("inputs", "outputs"):
                flows = node.result.inputs if (node.result and key == "inputs") else \
                    (node.result.outputs if node.result else [])
                for i, io in enumerate(r[key]):
                    rate = io["quantity"] / (r.get("cycle_time") or 1)
                    sl = node.slots.get((key[:-1], i))
                    ios[key].append({
                        "product": pname(io["product_id"]), "max_rate": rate, "planned_rate": rate * node.util,
                        "temperature": (flows[i].temperature if i < len(flows) else None) or io.get("temperature"),
                        "self_feed": (sl.self_feed / node.count) if sl else 0.0,
                        "voidable": bool(io.get("voidable")),
                    })
        ports = []
        for pid, pt in m["shape"].ports.items():
            use = port_use.get((g, pid))
            ports.append({"id": pid, "cells": [P((m["x"] + cx, m["y"] + cy)) for cx, cy in pt.cells],
                          "side": pt.side, "kind": pt.kind, "direction": pt.direction, "width": pt.width,
                          "net": use[0] if use else None, "rate": use[1].rate if use else None})
        v = valve_of(problem, g)
        data["machines"].append({
            "inst": g, "group": m["node"], "name": node.name, "machine": node.shape.name, "recipe": node.recipe_id,
            "index": m["local"] + 1, "count": node.count, "x": m["x"] - x0, "y": m["y"] - y0,
            "w": m["shape"].w, "h": m["shape"].h, "rotation": m["rot"] * 90,
            "rects": [[r_.x + m["x"] - x0, r_.y + m["y"] - y0, r_.w, r_.h, r_.label] for r_ in m["shape"].rects],
            "ports": ports, "io": ios, "valve": v,
            "run": {"planned": analysis.planned_run.get(g) if analysis else node.util,
                    "even_split": analysis.run_even.get(g) if analysis else None,
                    "built": analysis.run_valve.get(g) if analysis else None},
        })
    for ni, net in enumerate(problem.nets):
        entry = {"index": ni, "label": net.label, "product": net.product_name, "kind": net.kind, "large": net.large,
                 "flow": net.flow, "capacity": net.capacity, "temperature": net.temperature,
                 "routed": ni not in layout.failed, "segments": [], "nodes": [], "junctions": [], "terminals": []}
        nf = analysis.nets[ni] if analysis else None
        for a_, b_ in layout.net_edges[ni]:
            if nf and nf.edge_flow.get((b_, a_), 0) > nf.edge_flow.get((a_, b_), 0):
                a_, b_ = b_, a_
            seg = P(a_) + P(b_)
            if nf:
                seg += [nf.edge_flow.get((a_, b_), 0.0), nf.sim_flow.get((a_, b_)), nf.valve_flow.get((a_, b_))]
            entry["segments"].append(seg)
        entry["nodes"] = [P(c) for c in sorted(layout.net_nodes[ni])]
        if nf:
            for n, j in nf.junctions.items():
                if j.kind == "pass":
                    continue
                entry["junctions"].append({
                    "at": P(n), "kind": j.kind, "ins": [[lbl_fix(lbl, x0, y0), f] for lbl, f in j.ins],
                    "outs": [[lbl_fix(lbl, x0, y0), f] for lbl, f in j.outs], "even_ok": j.even_ok,
                    "valve": _valve_json(j.valve, P)})
            for ti in nf.terms:
                nd = problem.nodes[problem.instances[ti.t.inst][0]]
                entry["terminals"].append({
                    "inst": ti.t.inst, "machine": f"{nd.shape.name} #{problem.instances[ti.t.inst][1] + 1}",
                    "direction": ti.t.direction, "rate": ti.t.rate, "max_rate": ti.t.capacity,
                    "at": P(ti.node) if ti.node else None,
                    "port": [P(c) for c in ti.port_cells]})
            entry["note"] = nf.balanced_note
        data["pipes"].append(entry)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=None, separators=(",", ":"), default=_json_default)


def lbl_fix(lbl, x0, y0):
    """Junction labels name neighbour tiles in absolute coordinates; shift them into layout coordinates."""
    if lbl.startswith("pipe ("):
        try:
            x, y = lbl[6:-1].split(",")
            return f"pipe ({int(x) - x0}, {int(y) - y0})"
        except ValueError:
            return lbl
    return lbl


def _valve_json(v, P):
    if not v:
        return None
    out = {k: v.get(k) for k in ("ok", "why", "straight_pct", "side_pct", "rebuilt")}
    out["tiles"] = [P(c) for c in v.get("tiles", [])]
    out["split"] = [[lbl, pct] for lbl, pct in v.get("split", [])]
    return out


def _json_default(o):
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


def write_report(problem, layout, path, log_lines, analysis=None):
    x0, y0, x1, y1 = layout.bbox
    st = problem.plan.stats if problem.plan else {}
    lines = ["# Layout report", "",
             f"Footprint: {x1 - x0} x {y1 - y0} = {(x1 - x0) * (y1 - y0):,} tiles",
             f"Fully routed: {'yes' if layout.ok else 'NO'}", ""]
    if st:
        lines += ["## Planner numbers (Python port of the web app's solver)",
                  f"- Power use: {fmt_power(st['mv_use'])} MV, {fmt_power(st['hv_use'])} HV",
                  f"- Power output: {fmt_power(st['mv_output'])} MV, {fmt_power(st['hv_output'])} HV",
                  f"- Net pollution: {st['net_pollution']:.3f}",
                  f"- Machine cost: ${st['machine_cost']:,.0f} · machine space {st['machine_space']:,.0f} tiles · "
                  f"model count {st['model_count']:,.0f}", ""]
    if analysis is not None:
        lines.append("## Even-split check (pipes split evenly between open directions)")
        bad = [(problem.nodes[ni].name, pl, ev, vv) for ni, pl, ev, vv in analysis.groups
               if ev < pl * 0.995 or vv < pl * 0.995]
        if not bad:
            lines.append("- every machine group reaches its planned rate")
        for name, pl, ev, vv in bad:
            lines.append(f"- {name}: planned {pl:.3f}, plain even splits {ev:.3f} ({100 * ev / max(pl, 1e-9):.0f}%), "
                         f"as built {vv:.3f} ({100 * vv / max(pl, 1e-9):.0f}%)")
        lines.append("")
        lines.append(f"## Valve controls ({len(problem.valves)} in the layout)")
        for v in problem.valves:
            m = next((m for m in layout.machines if m["inst"] == v["inst"]), None)
            pos = f"at ({m['x'] - x0}, {m['y'] - y0}), rotation {m['rot'] * 90}°" if m else ""
            lines.append(f"- {v['product']} valve {v['index']}/{v['of']} {pos}: side outlet {v['side_pct']:.1f}%, "
                         f"straight {v['straight_pct']:.1f}% (of {v['flow']:.4g}/s)")
        if analysis.placed:
            lines.append(f"- plus {len(analysis.placed)} valve(s) fitted onto routed pipes:")
            for v in analysis.placed:
                t = v["tiles"][1]
                lines.append(f"  - {v['label']} at ({t[0] - x0}, {t[1] - y0})")
        if analysis.unplaced:
            lines.append(f"- {len(analysis.unplaced)} split(s) still need a valve placed by hand:")
            for v in analysis.unplaced:
                t = v["node"]
                lines.append(f"  - {v['label']} at ({t[0] - x0}, {t[1] - y0}): {v['why']}; set "
                             + ", ".join(f"{lbl_fix(lbl, x0, y0)} {pct:.1f}%" for lbl, pct in v["split"]))
        lines.append("")
    lines.append("## Machines")
    for n in problem.nodes:
        lines.append(f"- {n.count} x {n.shape.name} ({n.recipe_id}, planner {n.machine_count:.4f}, "
                     f"{n.shape.w}x{n.shape.h}){'' if n.known else '  <- rates unknown, ports inferred'}")
    lines += ["", "## Warnings"] + ([f"- {w}" for w in problem.warnings] or ["- none"])
    lines += ["", "## Notes / assumptions (check these!)"] + [f"- {n}" if not n.startswith("  ") else
                                                             f"    - {n.strip()}" for n in problem.notes]
    lines += ["", "## Optimizer log", "```"] + log_lines + ["```"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
